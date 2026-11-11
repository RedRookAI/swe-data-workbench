"""Execute only the exact trusted task tuples supplied by the controller.

The CLI is an owned child, never a database writer.  The controller must launch
it with ``start_new_session=True`` and record its identity before sending G over
the inherited control pipe.  EOF kills this worker's session process group.
This is bounded execution of owner-admitted tasks, not an arbitrary-code sandbox.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import selectors
import subprocess
import sys
import threading
import time
from typing import Any


OUTPUT_LIMIT = 65536
READ_CHUNK = 16384
REAP_TIMEOUT = 1.0


class _StreamCapture:
    """Retain only the fixed prefix; excess bytes are consumed and discarded."""

    def __init__(self):
        self.prefix = bytearray()
        self.truncated = False

    def append(self, data: bytes) -> None:
        remaining = OUTPUT_LIMIT - len(self.prefix)
        if len(data) > remaining:
            self.truncated = True
        self.prefix.extend(data[:remaining])


def _bounded_capture(child, deadline):
    captures = {"stdout": _StreamCapture(), "stderr": _StreamCapture()}
    timed_out = False
    try:
        with selectors.DefaultSelector() as selector:
            for name in captures:
                stream = getattr(child, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _ in selector.select(remaining):
                    # Readiness can remain continuous on a noisy pipe. Check
                    # time before every fixed read, including across both FDs.
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                    try:
                        chunk = os.read(key.fd, READ_CHUNK)
                    except BlockingIOError:
                        continue
                    if chunk:
                        captures[key.data].append(chunk)
                    else:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                if timed_out:
                    break
        if not timed_out:
            try:
                child.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        # Closing pipes is bounded even if another process inherited a writer.
        # Only this owned direct child is signaled; group reconciliation remains
        # the controller's job. A timeout never establishes descendant death.
        for name in captures:
            getattr(child, name).close()
        if child.poll() is None:
            child.kill()
            try:
                child.wait(timeout=REAP_TIMEOUT)
            except subprocess.TimeoutExpired:
                # Keep returncode=None: an uninterruptible/live child must not
                # be reported as reaped. Controller ownership checks still run.
                pass
    return captures, timed_out


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _start_ticks(pid: int) -> str | None:
    try:
        # /proc names may contain spaces or parentheses; split after the last ).
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _output(data: bytes, root: Path) -> tuple[str, bool]:
    truncated = len(data) > OUTPUT_LIMIT
    value = data[:OUTPUT_LIMIT].decode("utf-8", errors="replace")
    return value.replace(str(root), "<attempt>"), truncated


def _invoke(name: str, argv: list[str], cwd: Path, timeout: float, root: Path) -> dict[str, Any]:
    started = time.monotonic()
    actual_argv = [sys.executable if arg == "{python}" else arg for arg in argv]
    env = {
        "PATH": os.defpath,
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONHASHSEED": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        # Full Git diffs otherwise discover an enclosing repository and may
        # silently skip candidate-root paths as outside its worktree prefix.
        # Stop discovery before leaving this disposable command workspace.
        "GIT_CEILING_DIRECTORIES": str(cwd.resolve().parent),
    }
    identity: dict[str, Any] = {}
    try:
        child = subprocess.Popen(
            actual_argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
        )
        # Children inherit this group by construction. Reading getpgid(child)
        # can race a very short Git process exiting before the read.
        identity = {"pid": child.pid, "start_ticks": _start_ticks(child.pid), "pgid": os.getpgrp()}
        captures, timed_out = _bounded_capture(child, started + timeout)
        outcome = "timeout" if timed_out else ("passed" if child.returncode == 0 else "failed")
        out, _ = _output(captures["stdout"].prefix, root)
        err, _ = _output(captures["stderr"].prefix, root)
        return {
            "name": name, "outcome": outcome, "argv": argv,
            "stdout": out, "stderr": err, "exit_code": child.returncode,
            "duration_seconds": time.monotonic() - started,
            "output_truncated": any(capture.truncated for capture in captures.values()),
            "process": identity,
        }
    except OSError as exc:
        return {
            "name": name, "outcome": "error", "argv": argv,
            "stdout": "", "stderr": str(exc).replace(str(root), "<attempt>"),
            "exit_code": None, "duration_seconds": time.monotonic() - started,
            "process": identity,
        }


def _phase(checks: list[dict[str, Any]], directory: Path, root: Path) -> dict[str, Any]:
    measured = [
        _invoke(check["name"], check["argv"], directory, float(check.get("timeout", 5)), root)
        for check in checks
    ]
    outcomes = {check["outcome"] for check in measured}
    overall = next((kind for kind in ("error", "timeout", "failed") if kind in outcomes), "passed")
    if not measured:
        overall = "not-run"
    return {"overall": overall, "checks": measured}


def _write_sources(files: dict[str, str], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    for relative, content in files.items():
        path = Path(relative)
        if path.is_absolute() or not path.parts or ".." in path.parts or ".git" in path.parts:
            raise ValueError("Fixture source path must be relative and cannot escape its workspace")
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))


def evaluate(task: dict[str, Any], patch: str, work_dir: Path) -> dict[str, Any]:
    """Measure baseline and exact candidate in separate disposable directories.

    The parent supplies a manifest-pinned task. This function also refuses a
    patch not present byte-for-byte in that task's allowlist.
    """
    if not isinstance(patch, str) or patch not in task.get("patches", []):
        return {
            "overall": "not-run", "baseline": {"overall": "not-run", "checks": []},
            "candidate": {"overall": "not-run", "checks": []},
            "source_unchanged": True, "checks": [],
            "explanation": "Exact patch is absent from the trusted fixture manifest; no command ran.",
        }
    root = Path(work_dir).absolute()
    root.mkdir(parents=True, exist_ok=True)
    files = task["source_files"]
    source_digest = hashlib.sha256(_canonical(files)).hexdigest()
    baseline_dir, candidate_dir = root / "baseline", root / "candidate"
    _write_sources(files, baseline_dir)
    _write_sources(files, candidate_dir)
    started = time.monotonic()
    baseline = _phase(task["checks"], baseline_dir, root)
    patch_path = root / "candidate.patch"
    patch_path.write_bytes(patch.encode("utf-8"))
    # git apply works outside a repository. No init/config/hook or shell is used.
    application = _invoke("apply-exact-patch", ["git", "apply", "--", str(patch_path)], candidate_dir, 5, root)
    # Keep the internal patch path out of evidence; the exact bytes are already
    # bound by patch_digest in the controller's submission record.
    application["argv"] = ["git", "apply", "--", "<exact-patch>"]
    if application["outcome"] == "passed":
        candidate = _phase(task["checks"], candidate_dir, root)
    else:
        candidate = {
            "overall": "timeout" if application["outcome"] == "timeout" else "error",
            "checks": [{"name": check["name"], "outcome": "not-run", "explanation": "Exact patch application did not succeed."} for check in task["checks"]],
        }
    source_unchanged = source_digest == hashlib.sha256(_canonical(task["source_files"])).hexdigest()
    baseline_preserved = all((baseline_dir / key).read_bytes() == content.encode("utf-8") for key, content in files.items())
    source_unchanged = source_unchanged and baseline_preserved
    checks = [dict(check, phase="baseline") for check in baseline["checks"]]
    checks += [dict(application, phase="patch")]
    checks += [dict(check, phase="candidate") for check in candidate["checks"]]
    overall = candidate["overall"]
    if baseline["overall"] in {"error", "timeout", "not-run"}:
        overall = baseline["overall"]
    if not source_unchanged:
        overall = "error"
    return {
        "overall": overall, "baseline": baseline, "candidate": candidate,
        "patch_application": application, "source_unchanged": source_unchanged,
        "checks": checks, "duration_seconds": time.monotonic() - started,
        "runner": "trusted-task-worker-v3",
    }


def _watch_control(control_fd: int) -> None:
    try:
        while os.read(control_fd, 1):
            pass
    finally:
        # Never kill an inherited parent group if someone invoked this CLI
        # outside its required dedicated session.
        if os.getpgrp() == os.getpid():
            os.killpg(os.getpgrp(), signal.SIGKILL)
        os._exit(73)


def _durable_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("xb") as handle:
        handle.write(_canonical(result))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--control-fd", required=True, type=int)
    args = parser.parse_args()
    if os.getpid() != os.getpgrp():
        raise SystemExit("Owned worker requires start_new_session=True")
    # Waiting and reading the job cannot execute submitted code. The first G
    # comes only after the parent has committed PID/start/group registration.
    if os.read(args.control_fd, 1) != b"G":
        return 73
    threading.Thread(target=_watch_control, args=(args.control_fd,), daemon=True).start()
    try:
        job = json.loads(args.job.read_bytes())
        result = evaluate(job["task"], job["patch"], Path(job["work_dir"]))
    except Exception as exc:
        result = {
            "overall": "error", "baseline": {"overall": "not-run", "checks": []},
            "candidate": {"overall": "not-run", "checks": []}, "checks": [],
            "source_unchanged": False,
            "explanation": f"Worker error: {type(exc).__name__}",
        }
    _durable_result(args.result, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
