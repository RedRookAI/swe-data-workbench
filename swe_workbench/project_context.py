"""Explicit owner context. Resolves selected refs; never discovers or executes config."""
from pathlib import Path
from .handoff import parse,require,capture,inspect,read,review
from .handoff_profile import expand,bind_directory
from .bundle import _read,_git
from .store import canonical,digest
from . import handoff_validation as v

SCHEMA='swe-workbench-project-context/v1'
FIELDS=('schema','repo','profile','evidence_directory','state','base_ref','candidate_ref')

def load(path):
    context=parse(_read(path));v.obj(context,'context',FIELDS);require(context['schema']==SCHEMA,'context.schema: unsupported')
    for key in FIELDS:v.text(context[key],'context.'+key)
    for key in ('repo','profile','evidence_directory','state'):require(Path(context[key]).is_absolute(),'context.'+key+': expected an explicit absolute path')
    repo=Path(context['repo']).resolve();root=Path(context['state']).resolve();require(not root.is_relative_to(repo) and not repo.is_relative_to(root),'context.state: keep source/state separate')
    return context

def configure(output,**fields):
    data={'schema':SCHEMA,**fields}
    for key in ('repo','profile','evidence_directory','state'):data[key]=str(Path(data[key]).absolute())
    target=Path(output);require(target.parent.is_dir() and not target.exists() and not target.is_symlink(),'context.output: choose a fresh owned file')
    # Check without creating runtime state or touching the source.
    v.obj(data,'context',FIELDS)
    for key in FIELDS:v.text(data[key],'context.'+key)
    require(Path(data['repo']).is_dir() and Path(data['profile']).is_file() and Path(data['evidence_directory']).is_dir(),'context: selected source/profile/evidence must exist')
    root=Path(data['state']).resolve();repo=Path(data['repo']).resolve();require(not root.is_relative_to(repo) and not repo.is_relative_to(root),'context.state: source and state overlap')
    with target.open('xb') as f:f.write(canonical(data)+b'\n')
    return {'context':str(target),'runtime_writes':0,'notice':'Explicit owner-selected data; no source configuration discovery or execution.'}

def collect(path,*,change_id,title,goal,base=None,candidate=None,evidence_directory=None,preview=False,output=None,compact=False):
    context=load(path);repo=Path(context['repo'])
    if output:
        target=Path(output);require(target.parent.is_dir() and not target.exists() and not target.is_symlink(),'selection.output: choose a fresh file')
    refs={name:_git(repo,'rev-parse','--verify','--end-of-options',ref+'^{commit}').decode().strip() for name,ref in [('base',base or context['base_ref']),('candidate',candidate or context['candidate_ref'])]}
    profile=parse(_read(context['profile']));request=expand(profile,change_id=change_id,title=title,goal=goal)
    if compact:request['schema']='swe-workbench-handoff/v3'
    evidence=bind_directory(profile,evidence_directory or context['evidence_directory'],{})
    if preview:
        material=inspect(context['state'],repo=repo,**refs,request=request,evidence=evidence)
        return {'operation':'preview','runtime_writes':0,'material_digest':digest(canonical(material)),'resolved':refs,'material':material}
    state=capture(context['state'],repo=repo,**refs,request=request,evidence=evidence)
    selection={'schema':'swe-workbench-review-selection/v1','context_sha256':digest(canonical(context)),'change_id':change_id,'revision':state['revision'],'material_digest':state['material_digest']}
    if output:
        target=Path(output);require(target.parent.is_dir() and not target.exists() and not target.is_symlink(),'selection.output: choose a fresh file')
        with target.open('xb') as f:f.write(canonical(selection)+b'\n')
    return {'resolved':refs,'state':state,'selection':selection,'notice':'Capture reads committed bytes only. A decision remains explicit.'}

def review_selection(path,selection,**fields):
    context=load(path);chosen=parse(_read(selection));v.obj(chosen,'selection',('schema','context_sha256','change_id','revision','material_digest'))
    require(chosen['schema']=='swe-workbench-review-selection/v1' and chosen['context_sha256']==digest(canonical(context)),'selection: different project context')
    key=fields.pop('operation_key',None) or 'selected-review:'+digest(canonical({'selection':chosen,**fields}))
    return review(context['state'],chosen['change_id'],expected_revision=chosen['revision'],material_digest=chosen['material_digest'],operation_key=key,**fields)
