"""Read-only Git change capture and version-bound review of reported evidence.

This record never executes checks, grants code acceptance or changes the source.
It reuses schema1 artifacts/audit; native task execution remains separate.
"""
from __future__ import annotations
import base64
import json
from pathlib import Path
import re
import tempfile
import shutil
from .bundle import _git, _read, _source_path, _text, _publish, _fsync_directory
from .errors import WorkbenchError
from .intake import MAX_FILE_BYTES, MAX_RECORDS, reject_constant
from .store import Store, canonical, digest

SCHEMA='swe-workbench-handoff/v1'
FILES=('handoff.json','artifacts.json','manifest.json')


def require(value, message, code='invalid-handoff', status=400):
    if not value: raise WorkbenchError(code,message,status)


def parse(raw):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result: raise ValueError('duplicate key')
            result[key]=value
        return result
    try: return json.loads(raw,object_pairs_hook=pairs,parse_constant=reject_constant)
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise WorkbenchError('handoff-json','Expected unambiguous UTF-8 JSON.') from exc


def field(value, path):
    require(isinstance(path,list) and all(isinstance(p,str) for p in path),'Evidence field paths must be arrays of keys.')
    for key in path:
        if not isinstance(value,dict) or key not in value:return None
        value=value[key]
    return value


def observations(material):
    attachments={a['name']:a for a in material['attachments']}
    output=[]
    for request in material['observation_requests']:
        require(isinstance(request,dict) and set(request)<= {'label','attachment','field_path','context_path','required','scope'},'Unsupported observation fields.')
        require(all(isinstance(request.get(k),str) and request[k].strip() for k in ('label','attachment','scope')) and type(request.get('required')) is bool,'Observation needs label, attachment, scope and required flag.')
        require(request['attachment'] in attachments,'Observation attachment is missing.')
        attachment=attachments[request['attachment']]
        value=parse(attachment['text'])
        observed=field(value,request.get('field_path'))
        revision=field(value,request['context_path']) if 'context_path' in request else None
        binding='declared-same-source' if revision==material['candidate_revision'] else ('declared-other-source' if revision is not None else 'unbound')
        output.append({**request,'value':observed,'declared_revision':revision,'binding':binding,'origin':'externally-reported',
                       'attachment_sha256':attachment['sha256'],'execution_by_workbench':False})
    return output


def validate_material(material):
    require(material.get('schema')==SCHEMA and digest(material['patch'].encode())==material['patch_sha256'],'Patch identity mismatch.','handoff-integrity',409)
    for f in material['files']:
        _source_path(f['path'])
        for phase in ('before','after'):
            value=f[phase]
            if value is not None:
                raw=value['text'].encode('utf-8');algorithm='sha1' if len(value['git_blob'])==40 else 'sha256'
                import hashlib
                oid=hashlib.new(algorithm,b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
                require(digest(raw)==value['sha256'] and oid==value['git_blob'],'Captured source blob mismatch.','handoff-integrity',409)
    require(len({f['path'] for f in material['files']})==len(material['files']),'Duplicate source paths.','handoff-integrity',409)
    require(len({a['name'] for a in material['attachments']})==len(material['attachments']),'Duplicate evidence names.','handoff-integrity',409)
    for a in material['attachments']:
        require(digest(a['text'].encode())==a['sha256'],'Attached evidence identity mismatch.','handoff-integrity',409)
    require(material['observations']==observations(material),'Observation differs from retained evidence.','handoff-integrity',409)


def _load(store,con,change_id):
    row=con.execute('SELECT value FROM meta WHERE key=?',('handoff:'+change_id,)).fetchone()
    if not row:raise WorkbenchError('handoff-not-found','Change handoff does not exist.',404)
    state=parse(store.artifact_bytes(row['value']));material=parse(store.artifact_bytes(state['material_digest']))
    validate_material(material)
    events=[e for e in store.events(con) if e['kind'].startswith('handoff-') and e['payload'].get('change_id')==change_id]
    require(events and events[-1]['payload']['state_digest']==row['value'],'Handoff state/audit mismatch.','handoff-integrity',409)
    return state,material,events


def _save(store,con,state,kind,actor):
    key=store.artifact_write(canonical(state))
    con.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('handoff:'+state['change_id'],key))
    store.event(con,kind,{'change_id':state['change_id'],'revision':state['revision'],'material_digest':state['material_digest'],'state_digest':key},actor=actor)
    return state


def capture(root,*,repo,base,candidate,request,evidence,operation_key):
    """Capture explicit committed Git objects and local evidence files; execute nothing."""
    require(isinstance(request,dict) and set(request)=={'change_id','title','goal','repository','observations'},'Capture needs exactly change_id,title,goal,repository,observations.')
    require(isinstance(request['change_id'],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}',request['change_id']),'Invalid change ID.')
    require(all(isinstance(request[k],str) and request[k].strip() for k in ('title','goal','repository')),'Title, goal and repository are required.')
    require(isinstance(request['observations'],list) and len(request['observations'])<=MAX_RECORDS,'Invalid observations.')
    repo=Path(repo).resolve()
    state_root=Path(root).resolve()
    require(not state_root.is_relative_to(repo) and not repo.is_relative_to(state_root),'Keep source and handoff state must be separate.')
    for revision in (base,candidate):require(isinstance(revision,str) and re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',revision),'Use explicit full commit IDs.')
    base=_git(repo,'rev-parse','--verify',base+'^{commit}').decode().strip();candidate=_git(repo,'rev-parse','--verify',candidate+'^{commit}').decode().strip()
    paths=[p.decode('utf-8') for p in _git(repo,'diff','--no-ext-diff','--no-textconv','--no-renames','--name-only','-z',base,candidate).split(b'\0') if p]
    require(paths and len(paths)<=MAX_RECORDS,'Select a nonempty supported committed change.')
    files=[];total=0
    for path in paths:
        _source_path(path);values={'path':path}
        for phase,revision in [('before',base),('after',candidate)]:
            entry=_git(repo,'ls-tree','-z','--full-tree',revision,'--',path).split(b'\0')[0]
            if not entry:values[phase]=None;continue
            header,actual=entry.split(b'\t',1);mode,kind,oid=header.decode().split()
            require(mode=='100644' and kind=='blob' and actual.decode()==path,'Handoff supports regular nonexecutable UTF-8 files only.')
            size=int(_git(repo,'cat-file','-s',oid));total+=size;require(total<=MAX_FILE_BYTES,'Captured source exceeds the existing input byte limit.')
            raw=_git(repo,'cat-file','blob',oid)
            values[phase]={'git_blob':oid,'sha256':digest(raw),'text':_text(raw,'Source blob')}
        files.append(values)
    patch=_git(repo,'diff','--no-ext-diff','--no-textconv','--no-renames','--full-index',base,candidate)
    attachments=[]
    for name,path in evidence.items():
        require(isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_.-]+',name),'Evidence names must be simple labels.')
        raw=_read(path);total+=len(raw);require(total+len(patch)<=MAX_FILE_BYTES,'Handoff exceeds the existing input byte limit.')
        attachments.append({'name':name,'sha256':digest(raw),'text':_text(raw,'Evidence attachment')})
    material={'schema':SCHEMA,'title':request['title'],'goal':request['goal'],'repository':request['repository'],'base_revision':base,'candidate_revision':candidate,
              'files':files,'patch':_text(patch,'Patch'),'patch_sha256':digest(patch),'attachments':attachments,'observation_requests':request['observations'],
              'assurance':'Captured Git/evidence content consistency; unsigned external reports, no independent execution or delivery authority.'}
    material['observations']=observations(material);validate_material(material)
    require(len(canonical(material))<=MAX_FILE_BYTES,'Canonical handoff exceeds the existing input byte limit.')
    store=Store(root);store.initialize();material_digest=store.artifact_write(canonical(material))
    payload={'change_id':request['change_id'],'material_digest':material_digest}
    with store.transaction() as con:
        prior=store.operation(con,'capture-handoff',operation_key,payload)
        if prior is not None:return prior
        current=con.execute('SELECT value FROM meta WHERE key=?',('handoff:'+request['change_id'],)).fetchone()
        state=_load(store,con,request['change_id'])[0] if current else None
        if state is None or state['material_digest']!=material_digest:
            state={'schema':SCHEMA,'change_id':request['change_id'],'revision':0 if state is None else state['revision']+1,'material_digest':material_digest,
                   'decision':'unreviewed','reason':'','findings':[],'next_action':'Inspect the exact change and evidence scope.','reviewer_mode':None,'actor':None}
            _save(store,con,state,'handoff-captured','operator')
        store.remember(con,'capture-handoff',operation_key,payload,state)
        return state


def read(root,change_id):
    store=Store(root);store.initialize()
    with store.transaction(write=False) as con:
        state,material,events=_load(store,con,change_id)
        return {'schema':SCHEMA,'state':state,'material':material,'events':events}


def review(root,change_id,*,expected_revision,material_digest,decision,reason,findings,next_action,operation_key,reviewer_mode='ai_assisted_adjudication'):
    require(decision in ('handoff-ready','needs-work') and reviewer_mode in ('owner_adjudication','ai_assisted_adjudication','scripted_adjudication'),'Invalid handoff review mode/decision.')
    require(all(isinstance(v,str) and v.strip() for v in (reason,next_action)) and isinstance(findings,list) and all(isinstance(v,str) and v.strip() for v in findings),'Reason, findings and next action must be explicit.')
    store=Store(root);store.initialize();payload={k:v for k,v in locals().copy().items() if k not in ('store','root','operation_key')}
    with store.transaction() as con:
        prior=store.operation(con,'review-handoff',operation_key,payload)
        if prior is not None:return prior
        state,material,_=_load(store,con,change_id)
        require(type(expected_revision) is int and expected_revision==state['revision'] and material_digest==state['material_digest'],'Handoff context changed; review the current material.','stale-handoff',409)
        if decision=='handoff-ready':
            require(all(not o['required'] or (o['value'] is not None and o['binding']=='declared-same-source') for o in material['observations']),'Required external evidence is missing or declares a different source.','handoff-unresolved',422)
        state=state|{'revision':state['revision']+1,'decision':decision,'reason':reason,'findings':findings,'next_action':next_action,'reviewer_mode':reviewer_mode,'actor':'operator'}
        _save(store,con,state,'handoff-reviewed','operator');store.remember(con,'review-handoff',operation_key,payload,state);return state


def _validate_package(handoff,encoded):
    require(handoff.get('schema')==SCHEMA,'Unknown handoff schema.')
    require(set(handoff)=={'schema','state','material','events','audit_scope','workbench_executions','keep_mutations'}
            and all(type(handoff[k]) is int and handoff[k]==0 for k in ('workbench_executions','keep_mutations')),
            'A read-only external-evidence handoff cannot claim execution or source mutation.','handoff-integrity',409)
    artifacts={}
    for key,value in encoded.items():
        raw=base64.b64decode(value,validate=True);require(digest(raw)==key,'Historical artifact mismatch.','handoff-integrity',409);artifacts[key]=raw
    events=handoff['events'];require(bool(events),'Missing handoff history.')
    expected=set();previous=-1
    for e in events:
        item=dict(e);actual=item.pop('hash');require(digest(canonical(item))==actual,'Handoff event mismatch.','handoff-integrity',409)
        p=e['payload'];s=parse(artifacts[p['state_digest']]);m=parse(artifacts[p['material_digest']]);validate_material(m)
        require(s['schema']==SCHEMA and s['decision'] in ('unreviewed','handoff-ready','needs-work'), 'Invalid historical handoff decision.','handoff-integrity',409)
        require(e['kind'] in ('handoff-captured','handoff-reviewed') and p['change_id']==s['change_id']==handoff['state']['change_id'] and p['revision']==s['revision']==previous+1 and s['material_digest']==p['material_digest'],'Handoff history mismatch.','handoff-integrity',409)
        previous=s['revision'];expected.update((p['state_digest'],p['material_digest']))
    require(set(artifacts)==expected,'Missing or extra handoff artifacts.','handoff-integrity',409)
    last=events[-1]['payload'];require(canonical(handoff['state'])==artifacts[last['state_digest']] and canonical(handoff['material'])==artifacts[last['material_digest']],'Current handoff differs from history.','handoff-integrity',409)
    if handoff['state']['decision']=='handoff-ready':require(all(not o['required'] or (o['value'] is not None and o['binding']=='declared-same-source') for o in handoff['material']['observations']),'Unresolved handoff claims.','handoff-integrity',409)


def export(root,change_id,output):
    store=Store(root);store.initialize()
    with store.transaction(write=False) as con:
        state,material,events=_load(store,con,change_id)
        keys={e['payload'][k] for e in events for k in ('state_digest','material_digest')}
        encoded={key:base64.b64encode(store.artifact_bytes(key)).decode() for key in sorted(keys)}
        handoff={'schema':SCHEMA,'state':state,'material':material,'events':events,
                 'audit_scope':'Selected change events with original audit hashes; not a complete global audit chain.','workbench_executions':0,'keep_mutations':0}
    _validate_package(handoff,encoded)
    data={'handoff.json':canonical(handoff)+b'\n','artifacts.json':canonical(encoded)+b'\n'}
    manifest={'schema':SCHEMA,'change_id':change_id,'revision':state['revision'],'files':{n:{'sha256':digest(raw),'bytes':len(raw)} for n,raw in data.items()}}
    data['manifest.json']=canonical(manifest)+b'\n';destination=Path(output).absolute()
    require(all(len(raw)<=MAX_FILE_BYTES for raw in data.values()),'Handoff history exceeds the existing file byte limit; preserve it privately and select a smaller change.')
    require(destination.parent.is_dir() and not destination.exists() and not destination.is_symlink(),'Choose a fresh output under an existing owned parent.')
    temporary=Path(tempfile.mkdtemp(prefix='.handoff-',dir=destination.parent))
    try:
        for name,raw in data.items():
            with (temporary/name).open('xb') as stream:
                stream.write(raw);stream.flush();__import__('os').fsync(stream.fileno())
        _fsync_directory(temporary);_publish(temporary,destination);_fsync_directory(destination.parent)
    finally:
        if temporary.exists():shutil.rmtree(temporary)
    verified=verify(destination);require(verified['ok'],'Export verification failed.','handoff-integrity',409)
    return {'path':str(destination),'manifest_digest':digest(data['manifest.json']),**verified}


def verify(path):
    try:
        folder=Path(path);require(not folder.is_symlink() and folder.is_dir() and {p.name for p in folder.iterdir()}==set(FILES),'Exact handoff file set required.')
        for name in FILES:require((folder/name).is_file() and not(folder/name).is_symlink(),'Regular handoff files required.')
        raw={name:_read(folder/name) for name in FILES};manifest=parse(raw['manifest.json'])
        require(manifest['schema']==SCHEMA and set(manifest['files'])==set(FILES)-{'manifest.json'},'Invalid manifest.')
        for name,expected in manifest['files'].items():require(expected=={'sha256':digest(raw[name]),'bytes':len(raw[name])},'Manifest content mismatch.','handoff-integrity',409)
        handoff=parse(raw['handoff.json']);_validate_package(handoff,parse(raw['artifacts.json']))
        require(manifest['change_id']==handoff['state']['change_id'] and manifest['revision']==handoff['state']['revision'],'Manifest state mismatch.')
        return {'ok':True,'errors':[],'manifest_digest':digest(raw['manifest.json']),'change_id':manifest['change_id'],'revision':manifest['revision']}
    except (WorkbenchError,OSError,ValueError,KeyError,TypeError) as exc:return {'ok':False,'errors':[str(exc)]}
