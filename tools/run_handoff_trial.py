#!/usr/bin/env python3
"""Capture/review one real change using retained reports, without running that project."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import time

REPO=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True,help='Local complete Git objects; working files are never changed')
    parser.add_argument('--root',type=Path,default=REPO/'.state/keep-handoff')
    args=parser.parse_args();root=args.root.resolve();inputs=REPO/'examples/keep-handoff'
    if root.exists() and any(root.iterdir()):parser.error('Choose a fresh root; prior evidence is preserved.')
    root.mkdir(parents=True,exist_ok=True);source=json.loads((inputs/'source.json').read_text());steps=[]
    def run(name,command):
        started=time.monotonic();raw=subprocess.check_output([sys.executable,'-m','swe_workbench.cli','--root',str(root/'state'),*command],text=True)
        result=json.loads(raw);steps.append({'operation':name,'elapsed_seconds':time.monotonic()-started});return result
    state=run('capture', ['capture-handoff','--repo',str(args.repo.resolve()),'--base',source['base'],'--candidate',source['candidate'],
        '--request',str(inputs/'capture-request.json'),'--evidence','reported-evidence.json='+str(inputs/'reported-evidence.json'),'--evidence','KEEP-LICENSE='+str(inputs/'KEEP-LICENSE'),'--evidence','source-preparation.mjs='+str(inputs/'source-preparation.mjs'),'--evidence','preparation-workflow.yml='+str(inputs/'preparation-workflow.yml'),'--evidence','revision-roles.json='+str(inputs/'source.json'),'--operation-key','real-keep-capture'])
    assessment=json.loads((inputs/'assessment.json').read_text())
    assert assessment['binding']['candidate']==source['candidate']
    assert hashlib.sha256((inputs/'reported-evidence.json').read_bytes()).hexdigest()==assessment['binding']['report_sha256']
    review={k:v for k,v in assessment.items() if k!='binding'}
    review.update(expected_revision=state['revision'],material_digest=state['material_digest'],operation_key='real-keep-review',reviewer_mode='scripted_adjudication')
    review['reason']='Scripted replay of the recorded AI-assisted assessment: '+review['reason']
    request=root/'review-request.json';request.write_text(json.dumps(review,indent=2)+'\n')
    state=run('review',['review-handoff','keep-sandbox-preflight','--request',str(request)])
    exported=run('export',['export-handoff','keep-sandbox-preflight','--output',str(root/'export')])
    verified=run('fresh-process-verify',['verify-handoff',str(root/'export')]);assert verified['ok']
    recovered=run('fresh-process-read',['handoff','keep-sandbox-preflight']);assert recovered['state']==state
    result={'schema':'swe-workbench-handoff-trial/v1','state':str(root/'state'),'export':exported,'fresh_process_verification':verified,
        'source':source,'review':state,'steps':steps,'application_model_calls':0,'keep_application_commands_executed':0,'keep_mutations':0,
        'scope':'Git object reads and reported evidence only. Step elapsed times measure tool execution, not human review speed or development effort. The assisted review examines actual code/report; this driver replays its recorded reasons.'}
    (root/'receipt.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
