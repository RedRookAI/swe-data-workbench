"""Portable caller-supplied check facts; never runs a command or attests identity."""
import os,tempfile
from pathlib import Path
from . import handoff_validation as v
from .store import canonical
from .bundle import _publish,_fsync_directory

SCHEMA='swe-workbench-check-receipt/v1'
ASSURANCE='Caller-supplied external report; no execution witnessing or producer authentication.'

def make(facts):
    v.obj(facts,'receipt',('source','checks'),('producer','run'))
    source=facts['source'];v.obj(source,'receipt.source',('revision','worktree'))
    if source['revision'] is not None:v.sha(source['revision'],'receipt.source.revision',git=True)
    v.check(isinstance(source['worktree'],str) and source['worktree'] in ('clean','dirty','unknown'),'receipt.source.worktree','expected clean, dirty or unknown')
    v.check(isinstance(facts['checks'],dict) and bool(facts['checks']),'receipt.checks','expected named check results')
    for name,check in facts['checks'].items():
        path='receipt.checks.'+name;v.text(name,'receipt.checks.key')
        v.obj(check,path,('definition_sha256','inputs','outcome','exit_code','outputs'))
        v.sha(check['definition_sha256'],path+'.definition_sha256')
        for key in ('inputs','outputs'):
            v.check(isinstance(check[key],dict),path+'.'+key,'expected named SHA256 identities')
            for label,sha in check[key].items():v.text(label,path+'.'+key+'.key');v.sha(sha,path+'.'+key+'.'+label)
        v.check(isinstance(check['outcome'],str) and check['outcome'] in ('passed','failed','skipped','unavailable'),path+'.outcome','expected passed, failed, skipped or unavailable')
        code=check['exit_code'];v.check(code is None or type(code) is int,path+'.exit_code','expected an integer exit code or null')
        v.check(check['outcome']!='passed' or code==0,path+'.exit_code','a passed check must report exit0')
        v.check(check['outcome']!='failed' or type(code) is int and code!=0,path+'.exit_code','a failed check must report a nonzero exit')
        v.check(check['outcome'] not in ('skipped','unavailable') or code is None,path+'.exit_code','unexecuted checks have null exit code')
    for key in ('producer','run'):
        if key in facts:
            v.obj(facts[key],'receipt.'+key,(),('label','version') if key=='producer' else ('id','started','finished'))
            for name,value in facts[key].items():v.text(value,'receipt.'+key+'.'+name,nullable=True)
    exact=source['revision'] if source['worktree']=='clean' else None
    return {'schema':SCHEMA,**facts,'execution_revision':exact,'assurance':ASSURANCE}

def validate(receipt):
    v.obj(receipt,'receipt',('schema','source','checks','execution_revision','assurance'),('producer','run'))
    v.check(receipt['schema']==SCHEMA,'receipt.schema','unsupported check receipt version')
    expected=make({k:receipt[k] for k in ('source','checks','producer','run') if k in receipt})
    v.check(canonical(receipt)==canonical(expected),'receipt','derived execution binding or assurance differs from supplied source context')
    return receipt

def write(facts,output):
    receipt=make(facts);target=Path(output).absolute()
    v.check(target.parent.is_dir() and not target.exists() and not target.is_symlink(),'receipt.output','choose a fresh file under an existing parent')
    descriptor,name=tempfile.mkstemp(prefix='.receipt-',dir=target.parent);temporary=Path(name)
    try:
        with os.fdopen(descriptor,'wb') as f:f.write(canonical(receipt)+b'\n');f.flush();os.fsync(f.fileno())
        _publish(temporary,target);_fsync_directory(target.parent)
    finally:temporary.unlink(missing_ok=True)
    return {'output':str(target),'schema':SCHEMA,'execution_revision':receipt['execution_revision'],'assurance':ASSURANCE}
