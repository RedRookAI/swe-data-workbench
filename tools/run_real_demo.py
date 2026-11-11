#!/usr/bin/env python3
"""Run the pinned upstream case with actual checks and labeled scripted reviews.

The shipped review plan records a code assessment prepared with Codex assistance.
It is replayed against matching source/patch/check/rubric identities and observed
outcomes; it is not an independent human assessment or a model-generated patch.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from swe_workbench.assets import resolve_bundle
from swe_workbench.core import Workbench
from swe_workbench.exporter import export_batch, verify_export


def review_requests(workbench, batch_id):
    """Bind the examined case plan to actual current evidence, never fixture labels."""
    plan = json.loads((resolve_bundle('unicode-hyphen') / 'review-plan.json').read_text())
    requests = []
    for item in workbench.submissions(batch_id):
        assessed = plan['assessments'].get(item['patch_digest'])
        if assessed is None:
            assert not item['trusted_tuple'] and item['result'] is None
            continue
        assert item['trusted_tuple'] and item['context_current']
        for key in ('source_digest', 'check_digest', 'rubric_digest', 'task_text'):
            assert item[key] == plan[key], 'Review plan no longer matches ' + key
        result = item['result']
        assert result and result['source_unchanged'] and item['execution_status'] == 'completed'
        baseline = [check['outcome'] for check in result['baseline']['checks']]
        candidate = [check['outcome'] for check in result['candidate']['checks']]
        assert baseline == ['failed', 'passed', 'passed']
        assert candidate == assessed['candidate_outcomes']
        requests.append((item, dict(expected_revision=item['revision'],
            evidence_digest=result['evidence_digest'], rubric_digest=item['rubric_digest'],
            decision=assessed['decision'], criteria=assessed['criteria'], reason=assessed['reason'],
            actor='reference case replay (Codex-assisted assessment)',
            reviewer_mode='scripted_adjudication', operation_key='real-case-review-' + item['id'])))
    assert len(requests) == 2
    return requests


def run_demo(root, workers=1):
    workbench = Workbench(root, fixture_dir='unicode-hyphen')
    workbench.initialize()
    batch = workbench.import_approved('documented-real-import-v1')
    assert (batch['raw_lines'], batch['unique_items'], batch['duplicate_lines'], batch['invalid_lines']) == (4, 3, 1, 0)
    command = [sys.executable, '-m', 'swe_workbench.cli', '--root', str(root), '--bundle', 'unicode-hyphen', 'process', batch['id']]
    paused = subprocess.run(command + ['--workers', '1', '--stop-after', '1'], cwd=REPO, capture_output=True, text=True, check=True)
    before = {i['id']: i['result']['evidence_digest'] for i in workbench.submissions(batch['id']) if i.get('result')}
    resumed = subprocess.run(command + ['--workers', str(workers)], cwd=REPO, capture_output=True, text=True, check=True)
    assert all(workbench.submission(key)['result']['evidence_digest'] == value for key, value in before.items())
    for item, request in review_requests(workbench, batch['id']):
        if not item.get('review'):
            workbench.review(item['id'], **request)
    exported = export_batch(workbench, batch['id'], Path(root) / 'exports', 'real-demo-export-v1')
    repeated = export_batch(workbench, batch['id'], Path(root) / 'exports', 'real-demo-export-repeat-v1')
    assert exported['manifest_digest'] == repeated['manifest_digest']
    check = verify_export(exported['path'])
    assert check['ok'] and check['accepted_count'] == 1
    counts = workbench.batch(batch['id'])['counts']
    assert counts['accepted'] == 1 and counts['rejected'] == 1 and counts['pending-evidence'] == 1
    return {'schema': 'swe-workbench-real-case-demo/v1',
        'case': workbench.bundle_info(), 'decision_origin': 'scripted replay of Codex-assisted code assessment',
        'model_calls': 0, 'keep_dependency': False, 'batch': workbench.batch(batch['id']),
        'cooperative_stop': json.loads(paused.stdout), 'fresh_process_resume': json.loads(resumed.stdout),
        'preserved_completed_evidence': before, 'export': exported | {'snapshot': None},
        'verification': check, 'integrity': workbench.verify()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.state/real-example'))
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    print(json.dumps(run_demo(args.root.resolve(), args.workers), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
