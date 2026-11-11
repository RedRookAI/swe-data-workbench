#!/usr/bin/env python3
"""Run the account-free synthetic example through real processing and review APIs.

Adjudications are scripted fixture decisions, not independent human review.
No model request or Keep installation is used.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from swe_workbench.core import Workbench, CRITERIA
from swe_workbench.exporter import export_batch, verify_export

def run_demo(root: Path, workers: int = 1) -> dict:
    root = root.resolve()
    workbench = Workbench(root)
    workbench.initialize()
    batch = workbench.import_sample("documented-synthetic-import-v1")
    again = workbench.import_sample("documented-synthetic-import-v1")
    assert batch["id"] == again["id"]
    assert (batch["raw_lines"], batch["unique_items"], batch["duplicate_lines"], batch["invalid_lines"]) == (8, 6, 1, 1)

    # A real controller process commits one result and stops cooperatively.
    # A fresh process resumes from its SQLite state. Crash/kill behavior is
    # exercised separately by the focused recovery tests.
    command = [sys.executable, "-m", "swe_workbench.cli", "--root", str(root), "process", batch["id"]]
    paused = subprocess.run(command + ["--workers", "1", "--stop-after", "1"], cwd=REPO, capture_output=True, text=True, check=True)
    before = {item["id"]: item["result"]["evidence_digest"] for item in workbench.submissions(batch["id"]) if item.get("result")}
    resumed = subprocess.run(command + ["--workers", str(workers)], cwd=REPO, capture_output=True, text=True, check=True)
    items = workbench.submissions(batch["id"])
    assert all(next(i for i in items if i["id"] == key)["result"]["evidence_digest"] == value for key, value in before.items())

    for item in items:
        label = item.get("fixture_label")
        if not item.get("result") or item.get("review"):
            continue
        criteria = dict.fromkeys(CRITERIA, "pass")
        if label in {"good", "same-patch-different-context"}:
            decision, reason = "accepted", "Scripted fixture adjudication: the order-preserving fix matches the requested behavior and the recorded checks pass."
            assert item["result"]["overall"] == "passed"
        elif label == "weak-check-wrong":
            decision = "rejected"
            reason = 'Scripted fixture adjudication: visible ascending-input checks pass, but sorted(set(items)) returns ["a","b"] for ["b","a","b"]; the task requires first-seen order ["b","a"].'
            criteria.update({"requested_behavior":"fail", "preserved_behavior":"fail", "evidence_adequacy":"fail"})
            assert item["result"]["overall"] == "passed"
        else:
            decision, reason = "rejected", "Scripted fixture adjudication: the candidate fails the actual required check and drops distinct values."
            criteria.update({"requested_behavior":"fail", "preserved_behavior":"fail"})
            assert item["result"]["overall"] == "failed"
        workbench.review(item["id"], expected_revision=item["revision"],
            evidence_digest=item["result"]["evidence_digest"], rubric_digest=item["rubric_digest"],
            decision=decision, reason=reason, criteria=criteria, operation_key="documented-review-"+item["id"],
            actor="demo-driver (scripted developer adjudication)")

    exported = export_batch(workbench, batch["id"], root/"exports", "documented-export-v1")
    repeated = export_batch(workbench, batch["id"], root/"exports", "documented-export-repeat-v1")
    assert exported["manifest_digest"] == repeated["manifest_digest"]
    verification = verify_export(exported["path"])
    assert verification["ok"], verification
    summary = workbench.batch(batch["id"])
    assert summary["counts"]["accepted"] == 2
    assert summary["counts"]["rejected"] == 2
    assert summary["counts"]["pending-evidence"] == 2
    integrity = workbench.verify()
    assert integrity["ok"], integrity
    return {
        "schema":"swe-workbench-documented-demo/v1",
        "fixture_origin":"synthetic authored sample",
        "decision_origin":"scripted developer adjudication through actual core API",
        "model_calls":0,
        "keep_dependency":False,
        "batch":summary,
        "cooperative_stop":json.loads(paused.stdout),
        "fresh_process_resume":json.loads(resumed.stdout),
        "preserved_completed_evidence":before,
        "export":{"export_id":exported["export_id"],"path":str(exported["path"]),"manifest_digest":exported["manifest_digest"]},
        "verification":verification,
        "integrity":integrity,
    }

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path(".state/documented-demo"))
    parser.add_argument("--workers",type=int,choices=[1,2],default=1)
    args=parser.parse_args()
    print(json.dumps(run_demo(args.root,args.workers),ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()

