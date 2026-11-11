#!/usr/bin/env python3
"""Run the account-free ingestion audit/repair example with recorded assessment replay."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
if 'swe_workbench' not in sys.modules:
    sys.path.insert(0, str(REPO))
from swe_workbench.core import Workbench
from swe_workbench.evaluation import context, record_calibration, review_task, score_batch
from swe_workbench.evaluation_export import export_evaluation, verify_evaluation
from swe_workbench.exporter import export_batch, verify_export


def source_repository(inputs, destination):
    """Reconstruct the deliberately authored original commit; run no source code."""
    snapshot=json.loads((inputs/'source-snapshot.json').read_text())
    destination.mkdir(parents=True)
    for relative, expected in snapshot['files'].items():
        raw=(inputs/'visible'/relative).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:
            raise ValueError('Original source changed: '+relative)
        target=destination/relative; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(raw)
    shutil.copyfile(inputs/'license',destination/'license')
    env=os.environ.copy()
    for prefix, role in [('AUTHOR','author'),('COMMITTER','committer')]:
        for suffix,key in [('NAME','name'),('EMAIL','email'),('DATE','date')]:
            env['GIT_'+prefix+'_'+suffix]=snapshot[role+'_'+key]
    def git(*args):
        return subprocess.check_output(['git','-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false',*args],cwd=destination,env=env,text=True,stderr=subprocess.PIPE)
    git('init','-q'); git('add','--','eventflow','license'); git('commit','-q','-m',snapshot['message'])
    if git('rev-parse','HEAD').strip()!=snapshot['commit']:
        raise ValueError('Authored original commit identity differs.')
    return snapshot['commit']


def assert_measurements(score, inputs, version):
    by_patch={item['patch_digest']:item for item in score['items']}
    for name in ('reference.patch','alternate.patch','candidate-001.patch'):
        item=by_patch[hashlib.sha256((inputs/name).read_bytes()).hexdigest()]
        assert item['complete'] and item['score']==100 and item['critical_passed'] is True, (version,name,item["score"],[(c["id"],c["outcome"]) for c in item["criteria"]])
    control=by_patch[hashlib.sha256((inputs/'unchanged-control.patch').read_bytes()).hexdigest()]
    assert control['complete'] and control['score']==(100 if version=='weak-v1' else 50)
    assert control['critical_passed'] is (version=='weak-v1')
    assert len(score['items'])==5 and sum(not item['complete'] for item in score['items'])==1


def run_demo(root, inputs=REPO/'examples/ingest-recovery'):
    root,inputs=Path(root).resolve(),Path(inputs).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('Use a fresh owned root; existing evidence is preserved.')
    root.mkdir(parents=True,exist_ok=True)
    commit=source_repository(inputs,root/'source')
    assessment=json.loads((inputs/'assessment.json').read_text())
    records=[]
    for version in ('weak-v1','fixed-v3'):
        bundle=root/('bundle-'+version)
        command=[sys.executable,'-m','swe_workbench.cli','prepare-bundle','--repo',str(root/'source'),'--commit',commit,
            '--task-id','ingest-recovery','--task-text',str(inputs/'task.txt'),'--notice','license',
            '--checks',str(inputs/'checks.json'),'--candidates',str(inputs/'candidates.json'),
            '--provenance',str(inputs/'provenance.json'),'--predictions',str(inputs/'predictions.jsonl'),
            '--format','swebench','--name','ingest-recovery','--title','Durable event ingestion',
            '--verifier-files',str(inputs/(version+'-verifier.json')),'--evaluation',str(inputs/(version+'-evaluation.json')),
            '--output',str(bundle)]
        for name in json.loads((inputs/'source-snapshot.json').read_text())['files']: command.extend(['--source',name])
        prepared=json.loads(subprocess.check_output(command,text=True))
        w=Workbench(root/'workbench',fixture_dir=bundle);w.initialize()
        batch=w.import_approved('quality-demo-'+version)
        processed=w.process(batch['id'],workers=1)
        measured=score_batch(w,batch['id']);assert_measurements(measured,inputs,version)
        approved=assessment['versions'][version]
        calibrated=record_calibration(w,'ingest-recovery',reviews=approved['reviews'],reason=approved['calibration_reason'],
            author_feedback=approved['author_feedback'],guideline_update=approved['guideline_update'],operation_key='calibration-replay-'+version)
        decision=review_task(w,'ingest-recovery',decision=approved['decision'],reason='Scripted replay of recorded assessment: '+approved['reason'],
            findings=approved['findings'],expected_revision=calibrated['revision'],operation_key='task-review-replay-'+version,reviewer_mode='scripted_adjudication')
        exported=export_evaluation(w,batch['id'],root/'evaluation-exports','evaluation-'+version)
        repeat=export_evaluation(w,batch['id'],root/'evaluation-exports','evaluation-repeat-'+version)
        assert exported['manifest_digest']==repeat['manifest_digest']
        verified=verify_evaluation(exported['path']);assert verified['ok'],verified
        # The frozen score is the publication authority at this cut.
        frozen=json.loads((Path(exported['path'])/'evidence.json').read_text())['scores']
        records.append({'version':version,'bundle':str(bundle),'batch_id':batch['id'],'preparation':prepared,
            'processed':processed,'score':frozen,'evaluation_export':exported,'verification':verified})
        (root/'progress.json').write_text(json.dumps({'versions':records,'state':str(root/'workbench')},indent=2)+'\n')
    ordinary=export_batch(w,batch['id'],root/'accepted-code-exports','quality-queue-only')
    ordinary_verified=verify_export(ordinary['path']);assert ordinary_verified['ok'] and ordinary_verified['accepted_count']==0
    integrity=w.verify();assert integrity['ok']
    receipt={'schema':'swe-workbench-quality-example/v1','root':str(root),'state':str(root/'workbench'),
        'versions':records,'ordinary_export':ordinary,'ordinary_verification':ordinary_verified,'integrity':integrity,
        'decision_origin':'Explicit scripted replay of separately recorded AI-assisted review and author resolution, gated on actual unchanged candidate measurements.',
        'new_model_calls':0,'recorded_candidate_attempts':1,'assessment_sha256':hashlib.sha256((inputs/'assessment.json').read_bytes()).hexdigest()}
    (root/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=REPO/'.state/quality-example')
    parser.add_argument('--inputs',type=Path,default=REPO/'examples/ingest-recovery')
    args=parser.parse_args()
    result=run_demo(args.root,args.inputs)
    print(json.dumps({'receipt':str(Path(result['root'])/'receipt.json'),'quality':[r['score']['context']['quality']['decision'] for r in result['versions']],
        'candidate_scores':[[i['score'] for i in r['score']['items']] for r in result['versions']],'integrity':result['integrity'],'new_model_calls':0},indent=2))

if __name__=='__main__':main()
