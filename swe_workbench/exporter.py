"""Deterministic exports from the core's durable frozen snapshot API."""
from __future__ import annotations

import base64
from collections import Counter
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile

from .errors import WorkbenchError

SCHEMA = "swe-workbench-export-v1"
FILES = ("accepted.jsonl", "evidence.json", "manifest.json")
CRITERIA = ("task_clarity", "evidence_adequacy", "requested_behavior", "preserved_behavior", "unsupported_claims")
REVIEWER_MODES = frozenset(("developer_adjudication", "ai_assisted_adjudication", "owner_adjudication", "scripted_adjudication"))
OCCURRENCE_VERSION = "raw-occurrence-v2"
OCCURRENCE_FIELDS = frozenset(("input_format", "raw_record_base64", "declared_model", "declared_source"))
HEX = re.compile(r"[0-9a-f]{64}\Z")


class ExportError(WorkbenchError, ValueError):
    """A prepared snapshot or published artifact failed its contract."""

    def __init__(self, message):
        super().__init__("export-integrity", message, 409)


def canonical_bytes(value):
    """Project-specific UTF-8 JSON, deliberately not an RFC 8785 claim."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _require(condition, message):
    if not condition:
        raise ExportError(message)


def _ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None,
            "unavailable_reason": None if denominator else "No eligible population."}


def _reviewer_mode_valid(review):
    origin = review.get("origin")
    if not isinstance(origin, str) or origin not in REVIEWER_MODES:
        return False
    # Historical v1 reviews used this one origin without a separate mode.
    if "reviewer_mode" not in review:
        return origin == "developer_adjudication"
    return review["reviewer_mode"] == origin


def _invalid_json_constant(value):
    raise ValueError(f"Unsupported non-finite JSON number: {value}")


def _verify_lineage(item, required):
    """Bind each delivered attribution to its exact raw occurrence bytes.

    Declarations are input claims. Matching them does not authenticate their
    publisher/model identity or authorize execution of the patch.
    """
    lineages = item.get("lineage", [])
    _require(isinstance(lineages, list), "Occurrence lineage must be a list.")
    if required:
        _require(bool(lineages), "Raw-occurrence-v2 item is missing its occurrence lineage.")
    identities = set()
    for lineage in lineages:
        _require(isinstance(lineage, dict), "Invalid occurrence lineage.")
        if not required and not OCCURRENCE_FIELDS.intersection(lineage):
            # Legacy exports retain their original reduced lineage contract.
            continue
        _require(OCCURRENCE_FIELDS.issubset(lineage), "Raw occurrence fields are missing.")
        _require(isinstance(lineage.get("batch_id"), str) and bool(lineage["batch_id"])
                 and type(lineage.get("line")) is int and lineage["line"] > 0,
                 "Occurrence batch/line identity is invalid.")
        identity = (lineage["batch_id"], lineage["line"])
        _require(identity not in identities, "Duplicate occurrence identity in item lineage.")
        identities.add(identity)
        _require("duplicate_of" in lineage and (lineage["duplicate_of"] is None
                 or (type(lineage["duplicate_of"]) is int and 0 < lineage["duplicate_of"] < lineage["line"])),
                 "Invalid duplicate occurrence relation.")
        fmt = lineage["input_format"]
        _require(fmt in ("native", "swebench"), "Unsupported occurrence input format.")
        raw_digest = lineage.get("raw_digest")
        _require(isinstance(raw_digest, str) and HEX.fullmatch(raw_digest), "Invalid raw occurrence digest.")
        try:
            encoded = lineage["raw_record_base64"]
            _require(isinstance(encoded, str), "Invalid raw occurrence encoding.")
            raw = base64.b64decode(encoded, validate=True)
            record = json.loads(raw.decode("utf-8"), parse_constant=_invalid_json_constant)
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise ExportError("Invalid raw occurrence encoding or JSON.") from exc
        _require(digest(raw) == raw_digest, "Raw occurrence digest mismatch.")
        _require(isinstance(record, dict), "Raw occurrence must be a JSON object.")
        if fmt == "swebench":
            task_id, patch = record.get("instance_id"), record.get("model_patch")
            model = record.get("model_name_or_path")
        else:
            _require(type(record.get("schema_version")) is int and record["schema_version"] == 1,
                     "Raw native occurrence has an unsupported schema.")
            task_id, patch = record.get("task_id"), record.get("patch")
            model = record.get("model_name_or_path", record.get("model"))
        _require(isinstance(task_id, str) and task_id == item.get("task_id")
                 and (isinstance(patch, str) or patch is None)
                 and type(patch) is type(item.get("patch")) and patch == item.get("patch"),
                 "Raw occurrence task/patch differs from its submission.")
        source = record.get("source", record.get("origin", "unspecified"))
        _require(canonical_bytes(model) == canonical_bytes(lineage["declared_model"])
                 and canonical_bytes(source) == canonical_bytes(lineage["declared_source"]),
                 "Occurrence attribution differs from its raw source/model declaration.")


def _verify_batch_occurrences(snap):
    """Require every valid occurrence of the selected v2 batch to survive export."""
    batch = snap["batch"]
    occurrences = batch.get("occurrences")
    _require(isinstance(occurrences, list) and len(occurrences) == batch["raw_lines"],
             "Raw-occurrence-v2 batch is missing its occurrence accounting.")
    expected, invalid = {}, 0
    for occurrence in occurrences:
        _require(isinstance(occurrence, dict) and type(occurrence.get("line")) is int
                 and 0 < occurrence["line"] <= batch["raw_lines"], "Invalid batch occurrence identity.")
        line = occurrence["line"]
        _require(line not in expected, "Duplicate batch occurrence identity.")
        expected[line] = occurrence
        invalid += occurrence.get("error") is not None
    _require(invalid == batch["invalid_lines"], "Invalid occurrence count differs from the batch.")
    actual = {}
    for item in snap["items"]:
        for lineage in item.get("lineage", []):
            if lineage["batch_id"] != batch["id"]:
                continue
            line = lineage["line"]
            _require(line not in actual, "Batch occurrence is attributed to multiple items.")
            actual[line] = {"submission_id": item["id"], "duplicate_of": lineage["duplicate_of"],
                            "raw_digest": lineage["raw_digest"]}
    valid = {line: occurrence for line, occurrence in expected.items() if occurrence.get("error") is None}
    _require(set(actual) == set(valid), "Valid batch occurrence lineage is missing or extra.")
    for line, occurrence in valid.items():
        _require(all(occurrence.get(key) == value for key, value in actual[line].items()),
                 "Batch occurrence does not match its item lineage.")
        duplicate = occurrence.get("duplicate_of")
        if duplicate is not None:
            _require(duplicate in valid and valid[duplicate].get("submission_id") == occurrence.get("submission_id"),
                     "Duplicate occurrence does not refer to the same submission.")
    _require(sum(occurrence.get("duplicate_of") is not None for occurrence in valid.values()) == batch["duplicate_lines"],
             "Duplicate occurrence count differs from the batch.")


def _eligible(item):
    result, review = item.get("result") or {}, item.get("review") or {}
    return (item.get("disposition") == "accepted" and item.get("execution_status") == "completed"
            and result.get("overall") == "passed" and result.get("source_unchanged") is True
            and bool(result.get("checks"))
            and result.get("baseline", {}).get("overall") in ("passed", "failed")
            and result.get("candidate", {}).get("overall") == "passed"
            and bool(result.get("candidate", {}).get("checks"))
            and all(check.get("outcome") == "passed" for check in result["candidate"]["checks"])
            and review.get("decision") == "accepted"
            and type(item.get("revision")) is int and item["revision"] > 1
            and review.get("submission_revision") == item["revision"] - 1
            and review.get("evidence_digest") == result.get("evidence_digest")
            and review.get("rubric_digest") == item.get("rubric_digest")
            and all(review.get("criteria", {}).get(key) == "pass" for key in CRITERIA)
            and bool(review.get("actor")) and _reviewer_mode_valid(review)
            and all(isinstance(item.get(key), str) and HEX.fullmatch(item[key])
                    for key in ("source_digest", "patch_digest", "check_digest", "rubric_digest")))


def _snapshot(snapshot):
    snap = json.loads(canonical_bytes(snapshot))
    snap["items"] = sorted(snap["items"], key=lambda item: item["id"])
    snap["audit"] = sorted(snap["audit"], key=lambda event: event["seq"])
    ids = [item["id"] for item in snap["items"]]
    _require(len(ids) == len(set(ids)), "Duplicate unique item in frozen snapshot.")
    previous = "0" * 64
    for seq, event in enumerate(snap["audit"], 1):
        bound = {key: value for key, value in event.items() if key != "hash"}
        _require(event["seq"] == seq and event["prev_hash"] == previous
                 and digest(canonical_bytes(bound)[:-1]) == event["hash"], "Audit chain verification failed.")
        previous = event["hash"]
    _require(snap["cut"] == {"seq": len(snap["audit"]), "hash": previous}, "Audit cut does not bind frozen chain.")
    batch = snap["batch"]
    for key in ("raw_lines", "invalid_lines", "duplicate_lines", "unique_items"):
        _require(type(batch.get(key)) is int and batch[key] >= 0, f"Invalid intake count: {key}.")
    _require(batch["raw_lines"] == batch["invalid_lines"] + batch["duplicate_lines"] + batch["unique_items"], "Intake accounting does not reconcile.")
    _require(batch["unique_items"] == len(ids), "Unique membership count does not reconcile.")
    raw_occurrences_required = snap.get("runtime", {}).get("intake_version") == OCCURRENCE_VERSION
    for item in snap["items"]:
        _verify_lineage(item, raw_occurrences_required)
        if item.get("review"):
            _require(_reviewer_mode_valid(item["review"]), "Current review has an unsupported or inconsistent reviewer mode.")
        if item.get("disposition") == "accepted":
            _require(_eligible(item), f"Accepted item lacks exact-version eligibility: {item['id']}.")
            review = item["review"]
            _require(any(event["kind"] == "submission-reviewed"
                         and event["actor"] == review["actor"]
                         and event["payload"].get("submission_id") == item["id"]
                         and event["payload"].get("revision") == item["revision"]
                         and all(event["payload"].get(key) == value for key, value in review.items())
                         for event in snap["audit"]), "Accepted review is not bound by the frozen audit chain.")
    if raw_occurrences_required:
        _verify_batch_occurrences(snap)
    return snap


def metrics_for_snapshot(snapshot):
    snap = _snapshot(snapshot)
    items, batch = snap["items"], snap["batch"]
    dispositions = Counter(item.get("disposition", "pending") for item in items)
    executions = Counter(item.get("execution_status", "pending-evidence") for item in items)
    accepted = sum(_eligible(item) for item in items)
    adjudicated = sum(dispositions[key] for key in ("accepted", "rejected", "needs-work"))
    completed_ids = {item["id"] for item in items if item.get("execution_status") == "completed"
                     and (item.get("result") or {}).get("overall") in ("passed", "failed")}
    segments = snap.get("timing_segments", [])
    measured_ids, seconds = [], 0.0
    timing_ok = bool(segments)
    for segment in segments:
        elapsed = segment.get("elapsed_seconds")
        ids = segment.get("completed_ids")
        if (segment.get("complete") is not True or type(elapsed) not in (int, float)
                or not math.isfinite(elapsed) or elapsed <= 0 or not isinstance(ids, list)):
            timing_ok = False
            continue
        seconds += elapsed
        measured_ids.extend(ids)
    timing_ok = timing_ok and bool(completed_ids) and len(measured_ids) == len(set(measured_ids)) and set(measured_ids) == completed_ids
    throughput = {"value": len(completed_ids) / seconds if timing_ok else None,
                  "unit": "unique completed required measurements per second",
                  "numerator": len(completed_ids), "elapsed_seconds": seconds if timing_ok else None,
                  "segments": len(segments),
                  "unavailable_reason": None if timing_ok else "Missing, incomplete, overlapping, or workload-mismatched measured segments; resumed-tail timing cannot represent the batch."}
    pairs = matched = synthetic_pairs = 0
    for item in items:
        reviews = item.get("seeded_reviews", [])
        current = item.get("review")
        if current:
            reviews = [*reviews, current]
        for left, right in itertools.combinations(reviews, 2):
            # Compare only two explicit labels on the same exact evidence/rubric/revision.
            keys = ("rubric_digest", "evidence_digest", "submission_revision")
            if (left.get("actor") and right.get("actor") and left["actor"] != right["actor"]
                    and all(left.get(k) is not None and left.get(k) == right.get(k) for k in keys)
                    and left.get("decision") in ("accepted", "rejected", "needs-work")
                    and right.get("decision") in ("accepted", "rejected", "needs-work")):
                pairs += 1
                matched += left["decision"] == right["decision"]
                synthetic_pairs += any(str(r.get("origin", "")).startswith("synthetic") for r in (left, right))
    return {"counts": {"raw_lines": batch["raw_lines"], "invalid_lines": batch["invalid_lines"],
                       "duplicate_lines": batch["duplicate_lines"], "unique_items": len(items),
                       "accepted": accepted, "rejected": dispositions["rejected"],
                       "needs-work": dispositions["needs-work"], "pending_review": dispositions["pending"],
                       "execution": dict(sorted(executions.items())), "completed_measurements": len(completed_ids)},
            "denominators": {"accepted_yield": "all valid unique batch memberships, including pending and incomplete",
                             "send_back_rate": "unique memberships with current accepted/rejected/needs-work adjudication"},
            "accepted_yield": _ratio(accepted, len(items)),
            "send_back_rate": _ratio(dispositions["needs-work"], adjudicated),
            "send_back_reasons": dict(sorted(Counter((item.get("review") or {}).get("reason", "Unspecified")
                                           for item in items if item.get("disposition") == "needs-work").items())),
            "machine_throughput": throughput,
            "review_throughput": {"value": None, "unavailable_reason": "Active review duration is not measured; timestamps do not measure reviewer work."},
            "agreement": {**_ratio(matched, pairs), "synthetic_pairs": synthetic_pairs,
                          "interpretation": "Comparable paired labels under one rubric; agreement does not establish correctness."},
            "origin_counts": dict(sorted(Counter(item.get("origin", "unspecified") for item in items).items())),
            "cached_results": sum(bool((item.get("result") or {}).get("cached")) for item in items),
            "recovered_results": sum(bool((item.get("result") or {}).get("recovered")) for item in items)}


def _accepted(snap):
    return b"".join(canonical_bytes(item) for item in snap["items"] if _eligible(item))


def _verify_artifacts(snap, artifacts):
    referenced = {(item.get("result") or {}).get("evidence_digest") for item in snap["items"] if item.get("result")}
    _require(set(artifacts) == referenced, "Evidence artifacts do not match frozen result references.")
    for item in snap["items"]:
        patch = item.get("patch")
        if isinstance(patch, str) and item.get("patch_digest"):
            _require(digest(patch.encode("utf-8")) == item["patch_digest"], "Patch digest mismatch.")
        result = item.get("result")
        if not result:
            continue
        _require(result.get("submission_id") == item["id"] and all(
            result.get(binding) == item.get(binding) and item.get(binding) is not None
            for binding in ("source_digest", "patch_digest", "check_digest", "rubric_digest")),
            "Machine evidence does not bind the exact submission/source/patch/check/rubric identities.")
        key = result.get("evidence_digest", "")
        _require(isinstance(key, str) and HEX.fullmatch(key), "Invalid evidence digest.")
        try:
            data = base64.b64decode(artifacts[key], validate=True)
            stored = json.loads(data)
        except (ValueError, TypeError, KeyError) as exc:
            raise ExportError("Invalid evidence artifact encoding.") from exc
        _require(digest(data) == key, "Evidence artifact digest mismatch.")
        bound_result = {k: v for k, v in result.items() if k != "evidence_digest"}
        _require(stored == bound_result, "Evidence artifact does not bind the frozen machine result.")


def _files(export_id, snapshot, artifacts):
    snap = _snapshot(snapshot)
    _verify_artifacts(snap, artifacts)
    metrics = metrics_for_snapshot(snap)
    accepted, evidence = _accepted(snap), canonical_bytes({**snap, "export_schema": SCHEMA, "artifacts": artifacts})
    manifest = {"schema": SCHEMA, "export_id": export_id, "batch_id": snap["batch"]["id"],
                "cut": snap["cut"], "serialization": "utf8-sorted-compact-json-lf-v1",
                "files": {"accepted.jsonl": {"sha256": digest(accepted), "bytes": len(accepted)},
                          "evidence.json": {"sha256": digest(evidence), "bytes": len(evidence)}},
                "accepted_ids": [item["id"] for item in snap["items"] if _eligible(item)], "metrics": metrics}
    return {"accepted.jsonl": accepted, "evidence.json": evidence, "manifest.json": canonical_bytes(manifest)}, manifest


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def export_batch(workbench, batch_id, output_dir, operation_key):
    prepared = workbench.prepare_export(batch_id, operation_key)
    snapshot = prepared["snapshot"]
    artifacts = {}
    for item in snapshot["items"]:
        result = item.get("result")
        if result:
            key = result["evidence_digest"]
            artifacts[key] = base64.b64encode(workbench.artifact_bytes(key)).decode("ascii")
    files, manifest = _files(prepared["export_id"], snapshot, artifacts)
    manifest_digest = digest(files["manifest.json"])
    parent = Path(output_dir)
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / manifest_digest
    if not destination.exists():
        temporary = Path(tempfile.mkdtemp(prefix=f".pending-{manifest_digest}-", dir=parent))
        try:
            for name, data in files.items():
                with (temporary / name).open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            _fsync_directory(temporary)
            # One exporter owner; concurrent identical publication is harmless only after verification.
            try:
                temporary.rename(destination)
            except OSError:
                if not destination.is_dir():
                    raise
            _fsync_directory(parent)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    verified = verify_export(destination)
    _require(verified["ok"], "; ".join(verified["errors"]))
    _require(verified["manifest_digest"] == manifest_digest, "Existing export differs from prepared snapshot.")
    # Re-fsync even a recovered directory before recording ready.
    for name in FILES:
        with (destination / name).open("rb") as stream:
            os.fsync(stream.fileno())
    _fsync_directory(destination)
    _fsync_directory(parent)
    workbench.complete_export(prepared["export_id"], manifest_digest, str(destination.resolve()))
    return {"export_id": prepared["export_id"], "path": str(destination), "manifest": manifest,
            "manifest_digest": manifest_digest, "metrics": manifest["metrics"]}


def verify_export(path):
    """Offline hash/eligibility/lineage verification; no trust in filenames alone."""
    errors = []
    try:
        root = Path(path)
        _require(not root.is_symlink(), "Export directory cannot be a symlink.")
        _require(set(p.name for p in root.iterdir()) == set(FILES), "Unexpected or missing export files.")
        _require(all((root / name).is_file() and not (root / name).is_symlink() for name in FILES), "Export files must be regular files.")
        raw = {name: (root / name).read_bytes() for name in FILES}
        manifest = json.loads(raw["manifest.json"])
        evidence = json.loads(raw["evidence.json"])
        _require(manifest["schema"] == SCHEMA and evidence["export_schema"] == SCHEMA, "Unsupported export schema.")
        artifacts = evidence.pop("artifacts")
        evidence.pop("export_schema")
        expected, rebuilt = _files(manifest["export_id"], evidence, artifacts)
        _require(all(raw[name] == expected[name] for name in FILES), "Export bytes, manifest, counts, or accepted membership differ from frozen evidence.")
        return {"ok": True, "errors": [], "manifest_digest": digest(raw["manifest.json"]),
                "export_id": rebuilt["export_id"], "accepted_count": len(rebuilt["accepted_ids"])}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append(str(exc))
    return {"ok": False, "errors": errors}
