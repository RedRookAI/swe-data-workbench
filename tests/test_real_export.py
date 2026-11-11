"""Focused export contracts for occurrence attribution and explicit review modes."""
import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest

from swe_workbench.exporter import (
    CRITERIA, ExportError, canonical_bytes, digest, export_batch, verify_export,
)


MODES = ("developer_adjudication", "ai_assisted_adjudication", "owner_adjudication", "scripted_adjudication")


def snapshot_fixture(mode="ai_assisted_adjudication", legacy=False):
    """Use a frozen core double: no actual case execution or upstream validation."""
    patch = "--- a/file.js\n+++ b/file.js\n@@ -1 +1 @@\n-old\n+new\n"
    machine = {
        "submission_id": "item-public", "source_digest": "1" * 64,
        "patch_digest": digest(patch.encode()), "check_digest": "2" * 64, "rubric_digest": "3" * 64,
        "overall": "passed", "source_unchanged": True,
        "baseline": {"overall": "failed", "checks": [{"name": "actual-check", "outcome": "failed"}]},
        "candidate": {"overall": "passed", "checks": [{"name": "actual-check", "outcome": "passed"}]},
        "checks": [{"name": "actual-check", "outcome": "passed"}],
    }
    artifact = canonical_bytes(machine)[:-1]
    key = digest(artifact)
    review = {
        "submission_revision": 1, "evidence_digest": key, "rubric_digest": "3" * 64,
        "decision": "accepted", "actor": "authorized-operator", "origin": mode, "reviewer_mode": mode,
        "criteria": {criterion: "pass" for criterion in CRITERIA}, "reason": "Inspected exact-version evidence.",
    }
    if legacy:
        review.pop("reviewer_mode")
        review["origin"] = "developer_adjudication"
    item = {
        "id": machine["submission_id"], "batch_id": "batch-current", "task_id": "public-task",
        "title": "Public task export double", "task_text": "Retain publisher attribution.",
        "patch": patch, "revision": 2,
        **{name: machine[name] for name in ("source_digest", "patch_digest", "check_digest", "rubric_digest")},
        "origin": "public_upstream", "patch_provenance": {"origin": "public_upstream", "license": "MIT"},
        "execution_status": "completed", "disposition": "accepted",
        "result": {**machine, "evidence_digest": key}, "review": review, "seeded_reviews": [],
    }
    records = [
        ("batch-current", 1, None, "native", {
            "schema_version": 1, "task_id": "public-task", "patch": patch,
            "model": "publisher-a-reference", "origin": "publisher-a",
        }, b"\r\n"),
        ("batch-current", 2, 1, "swebench", {
            "instance_id": "public-task", "model_patch": patch,
            "model_name_or_path": "publisher-b-model", "source": "publisher-b",
        }, b"\n"),
        ("batch-other", 1, None, "native", {
            "schema_version": 1, "task_id": "public-task", "patch": patch,
            "model_name_or_path": "human-reference", "model": "ignored-fallback", "source": "publisher-c",
        }, b""),
    ]
    lineages = []
    for batch_id, line, duplicate, fmt, record, ending in records:
        raw = json.dumps(record, ensure_ascii=False, separators=(", ", ": ")).encode() + ending
        lineages.append({
            "batch_id": batch_id, "line": line, "duplicate_of": duplicate, "raw_digest": digest(raw),
            "input_format": fmt, "raw_record_base64": base64.b64encode(raw).decode(),
            "declared_model": record.get("model_name_or_path", record.get("model")),
            "declared_source": record.get("source", record.get("origin", "unspecified")),
        })
    if legacy:
        lineages = [{k: v for k, v in lineage.items() if k in ("batch_id", "line", "raw_digest", "duplicate_of")}
                    for lineage in lineages]
    item["lineage"] = lineages
    event = {
        "seq": 1, "kind": "submission-reviewed", "actor": review["actor"],
        "payload": {"submission_id": item["id"], "revision": item["revision"], **review},
        "prev_hash": "0" * 64, "created_at": "2026-11-11T00:00:00Z",
    }
    event["hash"] = digest(canonical_bytes(event)[:-1])
    occurrences = [{"line": value["line"], "submission_id": item["id"], "error": None,
                    "raw_digest": value["raw_digest"], "duplicate_of": value["duplicate_of"]}
                   for value in lineages if value["batch_id"] == "batch-current"]
    occurrences.append({"line": 3, "submission_id": None, "error": "invalid-json",
                        "raw_digest": digest(b"malformed\n"), "duplicate_of": None})
    snapshot = {
        "batch": {"id": "batch-current", "raw_lines": 3, "invalid_lines": 1, "duplicate_lines": 1,
                  "unique_items": 1, "created_at": "2026-11-11T00:00:00Z", "occurrences": occurrences},
        "items": [item], "audit": [event], "cut": {"seq": 1, "hash": event["hash"]},
        "runtime": {"intake_version": "raw-occurrence-v2"} if not legacy else {"python": "3.12"},
    }
    return snapshot, {key: artifact}


class FrozenCore:
    def __init__(self, mode="ai_assisted_adjudication", legacy=False):
        self.snapshot, self.artifacts = snapshot_fixture(mode, legacy)
        self.completions = []

    def prepare_export(self, batch_id, operation_key):
        return {"export_id": "export-double", "snapshot": copy.deepcopy(self.snapshot), "status": "pending"}

    def artifact_bytes(self, key):
        return self.artifacts[key]

    def complete_export(self, *args):
        self.completions.append(args)


class RealExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def export(self, core):
        return export_batch(core, "batch-current", self.root / "exports", "operation")

    def test_all_four_reviewer_modes_and_distinct_occurrences_survive(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                core = FrozenCore(mode)
                exported = self.export(core)
                self.assertTrue(verify_export(exported["path"])["ok"])
                accepted = json.loads((Path(exported["path"]) / "accepted.jsonl").read_bytes())
                self.assertEqual(accepted["review"]["reviewer_mode"], mode)
                self.assertEqual(accepted["lineage"], core.snapshot["items"][0]["lineage"])
                self.assertEqual([lineage["declared_source"] for lineage in accepted["lineage"]],
                                 ["publisher-a", "publisher-b", "publisher-c"])
                self.assertEqual(accepted["origin"], "public_upstream")
                self.assertEqual(accepted["patch_provenance"]["origin"], "public_upstream")
                self.assertEqual(exported["metrics"]["counts"]["accepted"], 1)
                self.assertEqual(exported["metrics"]["counts"]["duplicate_lines"], 1)

    def test_review_mode_requires_allowed_matching_origin(self):
        for origin, mode in (("ai_assisted_adjudication", "owner_adjudication"),
                             ("unknown", "unknown"), ("synthetic_fixture", "synthetic_fixture")):
            with self.subTest(origin=origin, mode=mode):
                core = FrozenCore()
                core.snapshot["items"][0]["review"].update(origin=origin, reviewer_mode=mode)
                with self.assertRaises(ExportError):
                    self.export(core)
                self.assertFalse(core.completions)
        core = FrozenCore("owner_adjudication")
        core.snapshot["items"][0]["review"].pop("reviewer_mode")
        with self.assertRaises(ExportError):
            self.export(core)

    def test_legacy_v1_export_needs_no_new_mode_or_raw_fields(self):
        core = FrozenCore(legacy=True)
        exported = self.export(core)
        self.assertTrue(verify_export(exported["path"])["ok"])
        accepted = json.loads((Path(exported["path"]) / "accepted.jsonl").read_bytes())
        self.assertNotIn("reviewer_mode", accepted["review"])
        self.assertNotIn("raw_record_base64", accepted["lineage"][0])
        self.assertEqual(accepted, core.snapshot["items"][0])
        self.assertEqual(exported["manifest"]["schema"], "swe-workbench-export-v1")

    def test_attribution_and_input_format_tampering_fail_before_ready(self):
        for field, value in (("declared_model", "invented-model"), ("declared_source", "invented-source"),
                             ("input_format", "swebench"), ("input_format", "unknown"),
                             ("raw_record_base64", "not valid base64!"), ("raw_digest", "9" * 64)):
            with self.subTest(field=field, value=value):
                core = FrozenCore()
                core.snapshot["items"][0]["lineage"][0][field] = value
                with self.assertRaises(ExportError):
                    self.export(core)
                self.assertFalse(core.completions)

    def test_raw_bytes_and_mapped_identity_tampering_fail(self):
        for transform, update_digest in ((lambda raw: raw.rstrip(b"\r\n"), False),
                                         (lambda raw: raw.replace(b"public-task", b"wrong-task"), True),
                                         (lambda raw: raw.replace(b"+new", b"+different"), True)):
            with self.subTest(update_digest=update_digest):
                core = FrozenCore()
                lineage = core.snapshot["items"][0]["lineage"][0]
                changed = transform(base64.b64decode(lineage["raw_record_base64"]))
                lineage["raw_record_base64"] = base64.b64encode(changed).decode()
                if update_digest:
                    lineage["raw_digest"] = digest(changed)
                with self.assertRaises(ExportError):
                    self.export(core)

    def test_v2_requires_each_field_and_every_selected_batch_occurrence(self):
        for field in ("input_format", "raw_record_base64", "declared_model", "declared_source"):
            with self.subTest(field=field):
                core = FrozenCore()
                core.snapshot["items"][0]["lineage"][0].pop(field)
                with self.assertRaises(ExportError):
                    self.export(core)
        for action in ("all-new-fields", "repeated-occurrence", "all-lineage", "batch-occurrences"):
            with self.subTest(action=action):
                core = FrozenCore()
                item = core.snapshot["items"][0]
                if action == "all-new-fields":
                    item["lineage"][0] = {key: value for key, value in item["lineage"][0].items()
                                          if key in ("batch_id", "line", "raw_digest", "duplicate_of")}
                elif action == "repeated-occurrence":
                    item["lineage"].pop(1)
                elif action == "all-lineage":
                    item.pop("lineage")
                else:
                    core.snapshot["batch"].pop("occurrences")
                with self.assertRaises(ExportError):
                    self.export(core)

    def test_new_lineage_on_unmarked_snapshot_is_still_validated(self):
        core = FrozenCore()
        core.snapshot["runtime"].pop("intake_version")
        core.snapshot["items"][0]["lineage"][0]["declared_source"] = "forged"
        with self.assertRaises(ExportError):
            self.export(core)

    def test_offline_verifier_checks_claims_after_outer_hashes_are_rebuilt(self):
        exported = self.export(FrozenCore())
        root = Path(exported["path"])
        evidence = json.loads((root / "evidence.json").read_bytes())
        evidence["items"][0]["lineage"][0]["declared_model"] = "forged-model"
        accepted = canonical_bytes(evidence["items"][0])
        evidence_bytes = canonical_bytes(evidence)
        manifest = json.loads((root / "manifest.json").read_bytes())
        manifest["files"]["accepted.jsonl"] = {"bytes": len(accepted), "sha256": digest(accepted)}
        manifest["files"]["evidence.json"] = {"bytes": len(evidence_bytes), "sha256": digest(evidence_bytes)}
        (root / "accepted.jsonl").write_bytes(accepted)
        (root / "evidence.json").write_bytes(evidence_bytes)
        (root / "manifest.json").write_bytes(canonical_bytes(manifest))
        verified = verify_export(root)
        self.assertFalse(verified["ok"])
        self.assertIn("attribution", verified["errors"][0])


if __name__ == "__main__":
    unittest.main()
