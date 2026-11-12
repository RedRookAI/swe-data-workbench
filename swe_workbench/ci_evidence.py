"""Observe a caller's existing test command. Never execute a supplied command."""

import argparse
import importlib.metadata
import os
import platform
import re
from pathlib import Path
from .bundle import _git, _read
from .handoff import parse, require
from .store import canonical, digest
from .review_package import save
from .errors import WorkbenchError

SCHEMA = "swe-workbench-ci-receipt/v1"
DEFINITION = "swe-workbench-check-definition/v1"
ASSURANCE = (
    "Unsigned pre/post observations, not continuous monitoring or hermetic execution."
)
EXIT = {
    0: "passed",
    1: "tests-failed",
    2: "interrupted",
    3: "internal-error",
    4: "usage-error",
    5: "no-tests",
    6: "warning-limit",
}


def repository(value):
    require(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value)
        and all(x not in (".", "..") for x in value.split("/")),
        "ci.repository: expected owner/name",
    )
    return value


def sha(value, label):
    require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value),
        "ci." + label + ": expected Git identity",
    )
    return value


def provider(env):
    if env.get("GITHUB_ACTIONS") != "true":
        return None
    p = {
        "provider": "github",
        "repository": repository(env.get("GITHUB_REPOSITORY")),
        "workflow_revision": sha(env.get("GITHUB_WORKFLOW_SHA"), "workflow_revision"),
        "workflow_ref": env.get("GITHUB_WORKFLOW_REF"),
        "run_id": env.get("GITHUB_RUN_ID"),
        "attempt": env.get("GITHUB_RUN_ATTEMPT"),
        "job": env.get("GITHUB_JOB"),
        "event": env.get("GITHUB_EVENT_NAME"),
        "proposed_head": None,
        "proposed_base": None,
    }
    # PR values are selected by workflow expressions, not arbitrary event JSON ingestion.
    for key, variable in [
        ("proposed_head", "WB_PR_HEAD"),
        ("proposed_base", "WB_PR_BASE"),
    ]:
        if env.get(variable):
            p[key] = sha(env[variable], key)
    validate_provider(p)
    return p


def validate_provider(p):
    if p is None:
        return
    require(
        isinstance(p, dict)
        and set(p)
        == {
            "provider",
            "repository",
            "workflow_revision",
            "workflow_ref",
            "run_id",
            "attempt",
            "job",
            "event",
            "proposed_head",
            "proposed_base",
        },
        "ci.provider: unsupported fields",
    )
    require(p["provider"] == "github", "ci.provider: unsupported")
    repository(p["repository"])
    sha(p["workflow_revision"], "workflow_revision")
    for k in ("run_id", "attempt"):
        require(
            isinstance(p[k], str) and re.fullmatch(r"[1-9][0-9]*", p[k]),
            "ci.provider." + k + ": expected positive ID",
        )
    for k in ("job", "event"):
        require(
            isinstance(p[k], str) and re.fullmatch(r"[A-Za-z0-9_-]+", p[k]),
            "ci.provider." + k + ": invalid",
        )
    require(
        isinstance(p["workflow_ref"], str)
        and p["workflow_ref"].startswith(p["repository"] + "/.github/workflows/")
        and not any(ord(c) < 32 for c in p["workflow_ref"]),
        "ci.workflow_ref: invalid",
    )
    for k in ("proposed_head", "proposed_base"):
        if p[k] is not None:
            sha(p[k], k)


def run_url(p):
    validate_provider(p)
    return (
        None
        if p is None
        else "https://github.com/"
        + p["repository"]
        + "/actions/runs/"
        + p["run_id"]
        + "/attempts/"
        + p["attempt"]
    )


def observation(repo, names):
    try:
        head = _git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        inputs = {}
        for name in names:
            path = Path(repo) / name
            require(
                not path.is_symlink()
                and path.resolve().is_relative_to(Path(repo).resolve()),
                "ci.input: expected contained regular source",
            )
            inputs[name] = digest(_read(path)) if path.is_file() else None
        return {
            "head": head,
            "clean": not bool(status),
            "status_sha256": digest(status),
            "inputs": inputs,
            "error": None,
        }
    except (WorkbenchError, ValueError, OSError) as exc:
        return {
            "head": None,
            "clean": False,
            "status_sha256": None,
            "inputs": {},
            "error": str(exc),
        }


def begin(repo, output, product, argv, inputs, env=None, import_path=None):
    repo = Path(repo).resolve()
    output = Path(output).absolute()
    repository(product)
    require(
        not output.resolve().is_relative_to(repo)
        and not repo.is_relative_to(output.resolve()),
        "ci.output: keep output outside source",
    )
    require(
        repo.is_dir() and not output.exists() and output.parent.is_dir(),
        "ci.output: choose a fresh directory",
    )
    require(
        Path(_git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        == repo,
        "ci.source: select the actual checkout root",
    )
    require(
        argv and all(isinstance(a, str) and a for a in argv),
        "ci.argv: expected declared nonempty arguments",
    )
    require(len(set(inputs)) == len(inputs), "ci.inputs: duplicate path")
    for name in inputs:
        require(
            isinstance(name, str)
            and name
            and not Path(name).is_absolute()
            and str(Path(name)) == name
            and not any(p in (".", "..", ".git") for p in Path(name).parts),
            "ci.input: expected relative source path",
        )
    before = observation(repo, inputs)
    definition = {
        "schema": DEFINITION,
        "argv": argv,
        "inputs": before["inputs"],
        "runtime": {
            "python": platform.python_version(),
            "pytest": importlib.metadata.version("pytest"),
            "git": _git(repo, "--version").decode().strip(),
            "verified_import_path": import_path,
        },
        "scope": "Caller-declared pytest invocation and selected input bytes; dependencies/environment beyond these identities are not attested.",
    }
    p = provider(os.environ if env is None else env)
    output.mkdir()
    save(output / "check-definition.json", definition)
    save(
        output / "started.json",
        {
            "schema": "swe-workbench-ci-start/v1",
            "repo": str(repo),
            "product": product,
            "before": before,
            "provider": p,
        },
    )
    return definition


def finish(output, exit_code):
    output = Path(output)
    require(
        type(exit_code) is int and -255 <= exit_code <= 255,
        "ci.exit: expected observed process code",
    )
    require(
        not (output / "ci-receipt.json").exists(),
        "ci.finish: attempt already finalized",
    )
    started = parse(_read(output / "started.json"))
    definition_raw = _read(output / "check-definition.json")
    definition = parse(definition_raw)
    before = started["before"]
    after = observation(started["repo"], list(definition["inputs"]))
    stable = (
        before == after
        and before["clean"]
        and bool(before["head"])
        and all(x is not None for x in before["inputs"].values())
    )
    context = {
        "schema": "swe-workbench-run-context/v1",
        "source_revision": before["head"],
        "source_state": (
            "clean"
            if stable
            else ("dirty" if before["head"] and after["head"] else "unknown")
        ),
        "definition_sha256": digest(definition_raw),
        "inputs": {k: v for k, v in before["inputs"].items() if v is not None},
        "assurance": ASSURANCE,
    }
    save(output / "run-context.json", context)
    context_raw = _read(output / "run-context.json")
    report = output / "original.xml"
    raw = _read(report) if report.is_file() else None
    diagnostic = None
    if raw is None:
        report_status = "missing"
        diagnostic = "Test command did not leave a JUnit report."
    else:
        try:
            from .junit_report import project

            project(raw, context_raw)
            report_status = "parsed"
        except (WorkbenchError, ValueError) as exc:
            report_status = "invalid"
            diagnostic = str(exc)
    receipt = {
        "schema": SCHEMA,
        "product_repository": started["product"],
        "tested_revision": before["head"],
        "before": before,
        "after": after,
        "source_state": context["source_state"],
        "provider": started["provider"],
        "exit_code": exit_code,
        "process_outcome": EXIT.get(
            exit_code,
            "terminated" if exit_code < 0 or exit_code >= 128 else "other-error",
        ),
        "report_status": report_status,
        "diagnostic": diagnostic,
        "report_sha256": None if raw is None else digest(raw),
        "context_sha256": digest(context_raw),
        "definition_sha256": digest(definition_raw),
        "assurance": ASSURANCE,
    }
    save(output / "ci-receipt.json", receipt)
    return receipt


def validate(raw, xml, context_raw, definition_raw):
    from . import handoff_validation as v

    r = parse(raw)
    v.obj(
        r,
        "ci.receipt",
        (
            "schema",
            "product_repository",
            "tested_revision",
            "before",
            "after",
            "source_state",
            "provider",
            "exit_code",
            "process_outcome",
            "report_status",
            "diagnostic",
            "report_sha256",
            "context_sha256",
            "definition_sha256",
            "assurance",
        ),
    )
    require(r["schema"] == SCHEMA, "ci.receipt: unsupported schema")
    repository(r["product_repository"])
    validate_provider(r["provider"])
    for k, content in [
        ("report", xml),
        ("context", context_raw),
        ("definition", definition_raw),
    ]:
        require(r[k + "_sha256"] == digest(content), "ci." + k + ": hash mismatch")
    c = parse(context_raw)
    d = parse(definition_raw)
    v.obj(d, "ci.definition", ("schema", "argv", "inputs", "runtime", "scope"))
    require(d["schema"] == DEFINITION, "ci.definition: unsupported schema")
    v.obj(
        d["runtime"], "ci.runtime", ("python", "pytest", "git", "verified_import_path")
    )
    for k in ("python", "pytest", "git"):
        v.text(d["runtime"][k], "ci.runtime." + k)
    require(
        d["runtime"]["verified_import_path"] is None
        or isinstance(d["runtime"]["verified_import_path"], str),
        "ci.import: expected text or null",
    )
    v.text(d["scope"], "ci.scope")
    require(
        isinstance(d["argv"], list)
        and d["argv"]
        and all(isinstance(a, str) and a for a in d["argv"]),
        "ci.argv: invalid",
    )
    require(
        type(r["exit_code"]) is int
        and -255 <= r["exit_code"] <= 255
        and r["process_outcome"]
        == EXIT.get(
            r["exit_code"],
            (
                "terminated"
                if r["exit_code"] < 0 or r["exit_code"] >= 128
                else "other-error"
            ),
        ),
        "ci.exit: inconsistent outcome",
    )
    for o in (r["before"], r["after"]):
        v.obj(
            o, "ci.observation", ("head", "clean", "status_sha256", "inputs", "error")
        )
        require(
            type(o["clean"]) is bool and isinstance(o["inputs"], dict),
            "ci.observation: invalid",
        )
        if o["head"] is not None:
            sha(o["head"], "head")
        if o["status_sha256"] is not None:
            v.sha(o["status_sha256"], "ci.status")
        if o["clean"]:
            require(
                o["head"] is not None
                and o["error"] is None
                and o["status_sha256"] == digest(b""),
                "ci.observation: clean conflicts with status/error",
            )
        require(
            o["error"] is None or isinstance(o["error"], str),
            "ci.observation.error: expected text or null",
        )
        for key, value in o["inputs"].items():
            v.text(key, "ci.input")
            if value is not None:
                v.sha(value, "ci.input.digest")
    require(r["assurance"] == ASSURANCE, "ci.assurance: unsupported")
    before = r["before"]
    stable = (
        before == r["after"]
        and before["clean"]
        and bool(before["head"])
        and all(x is not None for x in before["inputs"].values())
    )
    state = (
        "clean"
        if stable
        else ("dirty" if before["head"] and r["after"]["head"] else "unknown")
    )
    require(
        r["tested_revision"] == before["head"] == c.get("source_revision")
        and r["source_state"] == state == c.get("source_state"),
        "ci.source: conflicting observed source",
    )
    require(
        d["inputs"] == before["inputs"]
        and c.get("inputs")
        == {k: v for k, v in before["inputs"].items() if v is not None}
        and c.get("definition_sha256") == r["definition_sha256"],
        "ci.definition: conflicting input identities",
    )
    require(
        r["report_status"] == "parsed" and r["diagnostic"] is None,
        "ci.report: incomplete report",
    )
    from .junit_report import project

    report = project(xml, context_raw)
    problems = []
    if r["exit_code"] != 0:
        problems.append(
            "Process exited " + str(r["exit_code"]) + " (" + r["process_outcome"] + ")."
        )
    if r["exit_code"] == 0 and (
        report["counts"]["failed"]
        or report["counts"]["error"]
        or report["executed"] == 0
    ):
        problems.append(
            "Process success conflicts with failed/error/empty report evidence."
        )
    if state != "clean":
        problems.append(
            "Source/input pre/post observations do not establish clean stable execution."
        )
    return r | {"run_url": run_url(r["provider"]), "problems": problems}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    start = sub.add_parser("begin")
    start.add_argument("--repo", required=True, type=Path)
    start.add_argument("--output", required=True, type=Path)
    start.add_argument("--product", required=True)
    start.add_argument("--input", action="append", default=[])
    start.add_argument("argv", nargs=argparse.REMAINDER)
    end = sub.add_parser("finish")
    end.add_argument("--output", required=True, type=Path)
    end.add_argument("--exit-code", required=True, type=int)
    args = parser.parse_args()
    if args.action == "begin":
        begin(
            args.repo,
            args.output,
            args.product,
            args.argv[1:] if args.argv[:1] == ["--"] else args.argv,
            args.input,
        )
    else:
        finish(args.output, args.exit_code)


if __name__ == "__main__":
    main()
