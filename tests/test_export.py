"""Export-only fixtures exercise the frozen core interface, never a second store."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from swe_workbench.exporter import (CRITERIA, ExportError, canonical_bytes, digest,
                                    export_batch, metrics_for_snapshot, verify_export)


def fixture():
    patch_text = "exact patch\n"
    machine = {"overall": "passed", "source_unchanged": True, "baseline": {"overall": "failed", "checks": [{"name": "actual-check", "outcome": "failed"}]},
               "candidate": {"overall": "passed", "checks": [{"name": "actual-check", "outcome": "passed"}]}, "checks": [{"name": "actual-check", "outcome": "passed"}]}
    machine.update({"submission_id": "item-1", "source_digest": "1" * 64,
                    "patch_digest": digest(patch_text.encode()), "check_digest": "2" * 64, "rubric_digest": "3" * 64})
    artifact = canonical_bytes(machine)[:-1]
    key = digest(artifact)
    item = {"id": "item-1", "batch_id": "batch-1", "task_id": "task-1", "title": "Synthetic task",
            "task_text": "Preserve code whitespace.", "patch": patch_text, "revision": 2,
            "source_digest": "1" * 64, "patch_digest": digest(patch_text.encode()),
            "check_digest": "2" * 64, "rubric_digest": "3" * 64, "origin": "synthetic_fixture",
            "execution_status": "completed", "disposition": "accepted", "result": {**machine, "evidence_digest": key},
            "review": {"submission_revision": 1, "evidence_digest": key, "rubric_digest": "3" * 64,
                       "decision": "accepted", "actor": "operator", "origin": "developer_adjudication",
                       "criteria": {name: "pass" for name in CRITERIA}, "reason": "Inspected actual behavior."},
            "seeded_reviews": []}
    event = {"seq": 1, "kind": "submission-reviewed", "actor": "operator",
             "payload": {"submission_id": item["id"], "revision": item["revision"], **item["review"]},
             "prev_hash": "0" * 64, "created_at": "2026-11-11T00:00:00Z"}
    event["hash"] = digest(canonical_bytes(event)[:-1])
    snap = {"batch": {"id": "batch-1", "raw_lines": 3, "invalid_lines": 1, "duplicate_lines": 1,
                      "unique_items": 1, "counts": {"accepted": 1}, "created_at": "2026-11-11T00:00:00Z"},
            "items": [item], "audit": [event], "cut": {"seq": 1, "hash": event["hash"]},
            "runtime": {"python": "3.12"},
            "timing_segments": [{"complete": True, "elapsed_seconds": 2.0, "completed_ids": [item["id"]]}]}
    return snap, {key: artifact}


class FrozenCore:
    def __init__(self):
        self.snapshot, self.artifacts = fixture()
        self.status = "pending"
        self.fail_completion = False
        self.prepared = None
        self.completions = []

    def prepare_export(self, batch_id, operation_key):
        # Fixture models the documented durable snapshot, without database implementation.
        if self.prepared is None:
            self.prepared = copy.deepcopy(self.snapshot)
        return {"export_id": digest(canonical_bytes(self.prepared)), "snapshot": copy.deepcopy(self.prepared), "status": self.status}

    def artifact_bytes(self, key):
        return self.artifacts[key]

    def complete_export(self, export_id, manifest_digest, location):
        if self.fail_completion:
            raise RuntimeError("deliberate interruption after filesystem publish")
        self.status = "ready"
        self.completions.append((export_id, manifest_digest, location))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.core = FrozenCore()

    def export(self, key="export-a"):
        return export_batch(self.core, "batch-1", self.root / "exports", key)

    def test_same_cut_byte_stable_and_fresh_process_verifies(self):
        first = self.export()
        files = {p.name: p.read_bytes() for p in Path(first["path"]).iterdir()}
        second = self.export("export-b")
        self.assertEqual(first["manifest_digest"], second["manifest_digest"])
        self.assertEqual(files, {p.name: p.read_bytes() for p in Path(second["path"]).iterdir()})
        result = subprocess.run([sys.executable, "-c", "import sys; from swe_workbench.exporter import verify_export; assert verify_export(sys.argv[1])['ok']", first["path"]], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(first["metrics"]["counts"]["duplicate_lines"], 1)

    def test_publish_then_interruption_recovers_same_snapshot(self):
        self.core.fail_completion = True
        with self.assertRaises(RuntimeError):
            self.export()
        self.assertEqual(self.core.status, "pending")
        published = list((self.root / "exports").iterdir())
        self.assertEqual(len(published), 1)
        self.assertTrue(verify_export(published[0])["ok"])
        self.core.fail_completion = False
        recovered = self.export()
        self.assertEqual(Path(recovered["path"]), published[0])
        self.assertEqual(self.core.status, "ready")

    def test_failure_before_publish_stays_pending(self):
        with patch("swe_workbench.exporter._fsync_directory", side_effect=OSError("deliberate fsync failure")):
            with self.assertRaises(OSError):
                self.export()
        self.assertEqual(self.core.status, "pending")
        self.assertEqual(list((self.root / "exports").iterdir()), [])
        self.assertTrue(verify_export(self.export()["path"])["ok"])

    def test_missing_and_altered_evidence_fail(self):
        result = self.export()
        evidence = Path(result["path"]) / "evidence.json"
        original = evidence.read_bytes()
        evidence.unlink()
        self.assertFalse(verify_export(result["path"])["ok"])
        evidence.write_bytes(original.replace(b"Inspected actual behavior.", b"Changed review."))
        self.assertFalse(verify_export(result["path"])["ok"])

    def test_stale_review_rubric_or_synthetic_authority_is_ineligible(self):
        for field, value in (("submission_revision", 9), ("rubric_digest", "9" * 64),
                             ("evidence_digest", "8" * 64), ("origin", "synthetic_fixture")):
            snap, _ = fixture()
            snap["items"][0]["review"][field] = value
            with self.subTest(field=field), self.assertRaises(ExportError):
                metrics_for_snapshot(snap)

    def test_artifact_tamper_and_audit_tamper_fail_before_ready(self):
        key = next(iter(self.core.artifacts))
        self.core.artifacts[key] = b'{}'
        with self.assertRaises(ExportError):
            self.export()
        self.assertFalse(self.core.completions)
        snap, _ = fixture()
        snap["audit"][0]["payload"]["submission_id"] = "tampered"
        with self.assertRaises(ExportError):
            metrics_for_snapshot(snap)

    def test_later_review_changes_snapshot(self):
        first = self.export()
        core2 = FrozenCore()
        core2.snapshot["items"][0]["disposition"] = "needs-work"
        core2.snapshot["items"][0]["review"]["decision"] = "needs-work"
        second = export_batch(core2, "batch-1", self.root / "exports", "later-review")
        self.assertNotEqual(first["manifest_digest"], second["manifest_digest"])
        self.assertEqual((Path(second["path"]) / "accepted.jsonl").read_bytes(), b"")
        self.assertEqual(second["metrics"]["send_back_rate"]["value"], 1)

    def test_review_must_be_backed_by_audit_event(self):
        snap, _ = fixture()
        snap["items"][0]["review"]["reason"] = "Unlogged replacement review"
        with self.assertRaises(ExportError):
            metrics_for_snapshot(snap)

    def test_agreement_requires_bound_labels_and_reports_synthetic_pairs(self):
        snap, _ = fixture()
        label = dict(snap["items"][0]["review"], actor="seeded-reviewer", origin="synthetic_seed")
        snap["items"][0]["seeded_reviews"] = [label, {"decision": "accepted", "actor": "unbound"}]
        metric = metrics_for_snapshot(snap)["agreement"]
        self.assertEqual(metric["denominator"], 1)
        self.assertEqual(metric["synthetic_pairs"], 1)
        self.assertEqual(metric["value"], 1)

    def test_crashed_timing_and_empty_population_unavailable(self):
        snap, _ = fixture()
        snap["timing_segments"].insert(0, {"complete": False, "elapsed_seconds": None, "completed_ids": []})
        self.assertIsNone(metrics_for_snapshot(snap)["machine_throughput"]["value"])
        snap["items"] = []
        snap["batch"].update(raw_lines=0, invalid_lines=0, duplicate_lines=0, unique_items=0)
        metrics = metrics_for_snapshot(snap)
        self.assertIsNone(metrics["accepted_yield"]["value"])
        self.assertIsNone(metrics["agreement"]["value"])
        self.assertIsNone(metrics["review_throughput"]["value"])

    def test_builder_excludes_private_files_and_symlinks(self):
        spec = importlib.util.spec_from_file_location("build_public", Path(__file__).parents[1] / "tools" / "build_public.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        web = self.root / "web"
        web.mkdir()
        (web / "index.html").write_text('<!doctype html><p>Recorded evidence</p>')
        (web / "app.js").write_text('console.log("public");')
        (web / "owner-token.txt").write_text("PRIVATE")
        (web / "coordination").mkdir()
        (web / "coordination" / "secret.json").write_text('{"secret":"PRIVATE"}')
        exported = self.export()["path"]
        built = builder.build_public(web, exported, self.root / "dist")
        self.assertNotIn("owner-token.txt", built["files"])
        self.assertNotIn("coordination/secret.json", built["files"])
        self.assertIn("data/evidence.json", built["files"])
        (web / "assets").mkdir()
        (web / "assets" / "leak.js").symlink_to(web / "owner-token.txt")
        with self.assertRaises(ExportError):
            builder.build_public(web, exported, self.root / "dist")


if __name__ == "__main__":
    unittest.main()
