#!/usr/bin/env python3
"""Create only a fresh owned synthetic example; run one public, fixed check."""
import argparse,hashlib,json,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from swe_workbench.check_receipt import write

def produce(output):
    output=Path(output).absolute();output.mkdir(mode=0o700,parents=False,exist_ok=False)
    repo=output/'source';repo.mkdir()
    def git(*args):return subprocess.check_output(['git','-c','core.hooksPath=/dev/null','-C',str(repo),*args],text=True,stderr=subprocess.PIPE).strip()
    git('init','-q');git('config','user.name','Synthetic example');git('config','user.email','example@invalid.local')
    source=repo/'value.py';source.write_text('value = 1\n');git('add','value.py');git('commit','-qm','Synthetic base');base=git('rev-parse','HEAD')
    source.write_text('value = 2\n');git('commit','-qam','Synthetic candidate');candidate=git('rev-parse','HEAD')
    check='import runpy; assert runpy.run_path("value.py")["value"] == 2'
    started=datetime.now(timezone.utc).isoformat();actual_revision=git('rev-parse','HEAD');clean=not git('status','--porcelain')
    result=subprocess.run([sys.executable,'-c',check],cwd=repo,capture_output=True)
    evidence=output/'evidence';evidence.mkdir()
    facts={'source':{'revision':actual_revision,'worktree':'clean' if clean else 'dirty'},'producer':{'label':'Synthetic public example script','version':sys.version.split()[0]},'run':{'started':started,'finished':datetime.now(timezone.utc).isoformat()},'checks':{'value':{'definition_sha256':hashlib.sha256(check.encode()).hexdigest(),'inputs':{'value.py':hashlib.sha256(source.read_bytes()).hexdigest()},'outcome':'passed' if result.returncode==0 else 'failed','exit_code':result.returncode,'outputs':{}}}}
    write(facts,evidence/'receipt.json')
    profile={'schema':'swe-workbench-handoff-profile/v1','id':'simple-check','version':'1','repository':'synthetic-public-example','attachments':['receipt.json'],'observations':[{'label':'Value check outcome','attachment':'receipt.json','field_path':['checks','value','outcome'],'context_path':['execution_revision'],'required':True,'scope':'One fixed check of synthetic value.py; not general correctness.'}]}
    (output/'profile.json').write_text(json.dumps(profile,indent=2)+'\n')
    inputs={'repo':str(repo),'base':base,'candidate':candidate,'profile':str(output/'profile.json'),'evidence_dir':str(evidence),'change_id':'synthetic-value-change','title':'Set the synthetic value to 2','goal':'Change the public example constant from 1 to 2.'}
    (output/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
    return inputs
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();print(json.dumps(produce(args.output),indent=2))

if __name__=="__main__":main()
