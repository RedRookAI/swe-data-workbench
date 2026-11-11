#!/usr/bin/env python3
"""Prepare a real local repository and run checks; leave decisions to review.

Obtain the public pinned source explicitly first, as described in
examples/escape-goat/README.md. This driver performs no fetch or model call.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from swe_workbench.core import Workbench


def run_demo(repo, root, bundle, workers=1):
    inputs = REPO / 'examples/escape-goat'
    root, bundle = root.resolve(), bundle.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('Use a fresh owned root; existing evidence is preserved.')
    command = [sys.executable, '-m', 'swe_workbench.cli']
    preparation = subprocess.check_output(command + ['prepare-bundle', '--repo', str(repo.resolve()),
        '--commit', '235683eb791e13336cf4bd9705ea9df97e0d8e51',
        '--task-id', 'sindresorhus__escape-goat-pr13', '--task-text', str(inputs / 'task.txt'),
        '--source', 'index.js', '--source', 'test.js', '--source', 'index.d.ts', '--notice', 'license',
        '--checks', str(inputs / 'checks.json'), '--candidates', str(inputs / 'candidates.json'),
        '--provenance', str(inputs / 'provenance.json'), '--predictions', str(inputs / 'predictions.jsonl'),
        '--format', 'swebench', '--name', 'escape-goat', '--title', 'Prepared repository: escape-goat PR13',
        '--output', str(bundle)], cwd=REPO, text=True)
    owner = command + ['--root', str(root), '--bundle', str(bundle)]
    batch = json.loads(subprocess.check_output(owner + ['import-approved', '--operation-key', 'prepared-demo-import'], cwd=REPO, text=True))
    stopped = json.loads(subprocess.check_output(owner + ['process', batch['id'], '--workers', '1', '--stop-after', '1'], cwd=REPO, text=True))
    workbench = Workbench(root, fixture_dir=bundle); workbench.initialize()
    before = {i['id']: i['result']['evidence_digest'] for i in workbench.submissions(batch['id']) if i['result']}
    resumed = json.loads(subprocess.check_output(owner + ['process', batch['id'], '--workers', str(workers)], cwd=REPO, text=True))
    assert all(workbench.submission(key)['result']['evidence_digest'] == value for key, value in before.items())
    return {'schema': 'swe-workbench-prepared-example/v1', 'preparation': json.loads(preparation),
        'bundle': str(bundle), 'state': str(root), 'batch': workbench.batch(batch['id']),
        'cooperative_stop': stopped, 'fresh_process_resume': resumed,
        'preserved_completed_evidence': before, 'review_state': 'No decisions made by this driver; inspect actual evidence before review.',
        'model_calls': 0, 'keep_dependency': False, 'integrity': workbench.verify()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=REPO / '.state/prepared-example')
    parser.add_argument('--bundle-output', type=Path, default=REPO / '.state/prepared-example-bundle')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    print(json.dumps(run_demo(args.repo, args.root, args.bundle_output, args.workers), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
