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
from . import handoff_validation as shape

SCHEMA='swe-workbench-handoff/v1'
V2='swe-workbench-handoff/v2'
V3='swe-workbench-handoff/v3'
V4='swe-workbench-handoff/v4'
COMPACT_SCHEMAS=(V3,V4)
ROLE_SCHEMAS=(V2,V3,V4)
VERSIONS=(SCHEMA,V2,V3,V4)
UNSET=object()
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
    try:
        if isinstance(raw, bytes): raw = raw.decode("utf-8")
        shape.check(isinstance(raw, str), "json", "expected UTF-8 JSON text")
        result=json.loads(raw,object_pairs_hook=pairs,parse_constant=reject_constant)
        canonical(result)  # Validate Unicode and overflowed/nonfinite numbers without replacing bytes.
        return result
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise WorkbenchError('handoff-json','Expected unambiguous UTF-8 JSON.') from exc


def field(value, path):
    require(isinstance(path,list) and all(isinstance(p,str) for p in path),'Evidence field paths must be arrays of keys.')
    for key in path:
        if not isinstance(value,dict) or key not in value:return None
        value=value[key]
    return value


def observations(material):
    shape.observation_requests(material["observation_requests"], material["schema"])
    attachments={a['name']:a for a in material['attachments']}
    output=[]
    for request in material['observation_requests']:
        allowed={'label','attachment','field_path','context_path','required','scope'} | ({'subject'} if material['schema'] in ROLE_SCHEMAS else set())
        require(isinstance(request,dict) and set(request)<=allowed,'Unsupported observation fields.')
        require(all(isinstance(request.get(k),str) and request[k].strip() for k in ('label','attachment','scope')) and type(request.get('required')) is bool,'Observation needs label, attachment, scope and required flag.')
        require(request['attachment'] in attachments,'Observation attachment is missing.')
        attachment=attachments[request['attachment']]
        if material['schema']==V4:
            from .exact_json import decode
            value=decode(attachment['text'])
        else:value=parse(attachment['text'])
        observed=field(value,request.get('field_path'))
        if material['schema']==V4:
            from .exact_json import decode,encode
            exact=field(decode(attachment['text']),request.get('field_path'))
            observed=None if exact is None else encode(exact)
        revision=field(value,request['context_path']) if 'context_path' in request else None
        if material['schema']==V4:
            from .exact_json import Token
            if isinstance(revision,Token):revision=None
        binding='declared-same-source' if revision==material['candidate_revision'] else ('declared-other-source' if revision is not None else 'unbound')
        item={**request,'value':observed,'declared_revision':revision,'binding':binding,'origin':'externally-reported',
              'attachment_sha256':attachment['sha256'],'execution_by_workbench':False}
        if material['schema']==V4:
            from .exact_json import FORMAT
            item['value_format']=FORMAT
        if material['schema'] in ROLE_SCHEMAS:
            from .handoff_context import observation_binding
            item.update(observation_binding(material,request,revision))
        output.append(item)
    if material['schema'] in ROLE_SCHEMAS:
        require(len({o['label'] for o in output})==len(output),'Observation labels must be unique.')
    return output


def validate_material(material,read_blob=None):
    shape.material(material)
    require(material.get('schema') in VERSIONS and digest(material['patch'].encode())==material['patch_sha256'],'Patch identity mismatch.','handoff-integrity',409)
    if material['schema']==SCHEMA:
        require(not ({'subjects','subject_requests','relationships','relationship_requests','profile'} & set(material)), 'Role/profile fields require a v2 material version.','handoff-integrity',409)
    if material['schema'] in COMPACT_SCHEMAS:
        from .handoff_compact import validate
        validate(material,read_blob)
    else:
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
    if material['schema'] in ROLE_SCHEMAS:
        from .handoff_context import subjects,relationships
        require(canonical(material['subjects'])==canonical(subjects(material)) and canonical(material['relationships'])==canonical(relationships(material)), 'Revision roles differ from retained evidence.','handoff-integrity',409)
        if material.get('profile'):
            from .handoff_profile import expand
            profile=material['profile'];definition=profile['definition']
            require(digest(canonical(definition))==profile['sha256'],'Profile identity mismatch.','handoff-integrity',409)
            effective=expand(definition,change_id='validation',title=material['title'],goal=material['goal'])
            require(effective['repository']==material['repository'] and canonical(effective['observations'])==canonical(material['observation_requests']) and canonical(effective['subjects'])==canonical(material['subject_requests']) and canonical(effective['relationships'])==canonical(material['relationship_requests']), 'Effective profile differs from captured material.','handoff-integrity',409)
            require(set(definition.get('attachments',[]))<={a['name'] for a in material['attachments']},'Required profile attachment missing.')
    if material['schema'] in COMPACT_SCHEMAS and 'reported_checks' in material:
        from .reported_checks import extract
        require(canonical(material['reported_checks'])==canonical(extract(material)),'Reported checks differ from original retained report/context.','handoff-integrity',409)
    require(canonical(material['observations'])==canonical(observations(material)),'Observation differs from retained evidence.','handoff-integrity',409)


def _load(store,con,change_id,selected_events=None):
    row=con.execute('SELECT value FROM meta WHERE key=?',('handoff:'+change_id,)).fetchone()
    if not row:raise WorkbenchError('handoff-not-found','Change handoff does not exist.',404)
    state=parse(store.artifact_bytes(row['value']));shape.state(state);material=parse(store.artifact_bytes(state['material_digest']))
    validate_material(material,store.artifact_bytes)
    events=selected_events if selected_events is not None else [e for e in store.events(con) if e['kind'].startswith('handoff-') and e['payload'].get('change_id')==change_id]
    require(events and events[-1]['payload']['state_digest']==row['value'],'Handoff state/audit mismatch.','handoff-integrity',409)
    return state,material,events


def _save(store,con,state,kind,actor):
    key=store.artifact_write(canonical(state))
    con.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('handoff:'+state['change_id'],key))
    store.event(con,kind,{'change_id':state['change_id'],'revision':state['revision'],'material_digest':state['material_digest'],'state_digest':key},actor=actor)
    return state


def inspect(root,*,repo,base,candidate,request,evidence,source_blobs=None):
    """Resolve/validate exact selected material without creating runtime state."""
    required={'change_id','title','goal','repository','observations'}
    version=request.get('schema',SCHEMA) if isinstance(request,dict) else None
    allowed=required if version==SCHEMA else required|{'schema','profile','subjects','relationships'}
    shape.obj(request,'capture',required,allowed-required)
    require(version in VERSIONS,'capture.schema: unsupported version')
    require(isinstance(request['change_id'],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}',request['change_id']),'Invalid change ID.')
    require(all(isinstance(request[k],str) and request[k].strip() for k in ('title','goal','repository')),'Title, goal and repository are required.')
    require(isinstance(request['observations'],list) and len(request['observations'])<=MAX_RECORDS,'Invalid observations.')
    shape.observation_requests(request['observations'],version)
    shape.check(isinstance(evidence,dict),'evidence','expected named file bindings')
    repo=Path(repo).resolve()
    state_root=Path(root).resolve()
    require(not state_root.is_relative_to(repo) and not repo.is_relative_to(state_root),'Source repository and handoff state must be separate.')
    for revision in (base,candidate):require(isinstance(revision,str) and re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',revision),'Use explicit full commit IDs.')
    base=_git(repo,'rev-parse','--verify',base+'^{commit}').decode().strip();candidate=_git(repo,'rev-parse','--verify',candidate+'^{commit}').decode().strip()
    paths=[_text(p,'Source path') for p in _git(repo,'diff','--no-ext-diff','--no-textconv','--no-renames','--name-only','-z',base,candidate).split(b'\0') if p]
    require(paths and len(paths)<=MAX_RECORDS,'Select a nonempty supported committed change.')
    if source_blobs is None:source_blobs={}
    if version in COMPACT_SCHEMAS:
        from .handoff_compact import collect
        files,patch,total,coverage=collect(repo,base,candidate,paths,source_blobs)
    else:
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
        require(total+len(patch)<=MAX_FILE_BYTES,'Source and patch exceed the existing input byte limit.')
    attachments=[]
    for name,path in evidence.items():
        require(isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_.-]+',name),'Evidence names must be simple labels.')
        raw=_read(path);total+=len(raw);require(total+len(patch)<=MAX_FILE_BYTES,'Handoff exceeds the existing input byte limit.')
        attachments.append({'name':name,'sha256':digest(raw),'text':_text(raw,'Evidence attachment')})
    material={'schema':version,'title':request['title'],'goal':request['goal'],'repository':request['repository'],'base_revision':base,'candidate_revision':candidate,
              'files':files,'patch':_text(patch,'Patch'),'patch_sha256':digest(patch),'attachments':attachments,'observation_requests':request['observations'],
              'assurance':'Captured Git/evidence content consistency; unsigned external reports, no independent execution or delivery authority.'}
    if version in COMPACT_SCHEMAS:material['coverage']=coverage
    if version in ROLE_SCHEMAS:
        from .handoff_context import subjects,relationships
        material.update(profile=request.get('profile'),subject_requests=request.get('subjects',[{'id':'product','role':'product_source','selector':{'source':'candidate'}}]),relationship_requests=request.get('relationships',[]))
        material['subjects']=subjects(material);material['relationships']=relationships(material)
    material['observations']=observations(material)
    if version in COMPACT_SCHEMAS:
        from .reported_checks import extract
        reports=extract(material)
        if reports:material['reported_checks']=reports
    validate_material(material,lambda key:source_blobs[key])
    require(len(canonical(material))<=MAX_FILE_BYTES,'Canonical handoff exceeds the existing input byte limit.')
    return material


def capture(root,*,repo,base,candidate,request,evidence,operation_key=None,project=False,expected_state=UNSET):
    blobs={}
    material=inspect(root,repo=repo,base=base,candidate=candidate,request=request,evidence=evidence,source_blobs=blobs)
    version=material["schema"]
    store=Store(root);store.initialize()
    with store.transaction() as con:
        from .project_scope import enforce
        enforce(store,con,repo,material['repository'],claim=project)
        current=con.execute('SELECT value FROM meta WHERE key=?',('handoff:'+request['change_id'],)).fetchone()
        state=_load(store,con,request['change_id'])[0] if current else None
        if expected_state is not UNSET:
            actual=None if state is None else {k:state[k] for k in ('revision','material_digest')}
            require(actual==expected_state,'Capture selection advanced; no newer material was selected.','handoff-conflict',409)
        for raw in blobs.values():store.artifact_write(raw)
        material_digest=store.artifact_write(canonical(material))
        payload={'change_id':request['change_id'],'material_digest':material_digest}
        prior=store.operation(con,'capture-handoff',operation_key,payload) if operation_key is not None else None
        if prior is not None:return prior
        if state is None or state['material_digest']!=material_digest:
            state={'schema':version,'change_id':request['change_id'],'revision':0 if state is None else state['revision']+1,'material_digest':material_digest,
                   'decision':'unreviewed','reason':'','findings':[],'next_action':'Inspect the exact change and evidence scope.','reviewer_mode':None,'actor':None}
            if version in ROLE_SCHEMAS:state['responsible_party']=None
            _save(store,con,state,'handoff-captured','operator')
        if operation_key is not None:store.remember(con,'capture-handoff',operation_key,payload,state)
        return state


def _envelope(store,events):
    schemas={parse(store.artifact_bytes(e['payload']['state_digest']))['schema'] for e in events}
    return V4 if V4 in schemas else (V3 if V3 in schemas else (V2 if V2 in schemas else SCHEMA))


def read(root,change_id,baseline_revision=None):
    store=Store(root);store.initialize()
    with store.transaction(write=False) as con:
        state,material,events=_load(store,con,change_id)
        result={'schema':_envelope(store,events),'state':state,'material':material,'events':events}
        if result['schema'] in ROLE_SCHEMAS:
            from .handoff_context import compare
            artifacts={e['payload'][k]:store.artifact_bytes(e['payload'][k]) for e in events for k in ('state_digest','material_digest')}
            result['comparison']=compare(state,material,events,artifacts,baseline_revision)
        return result


def review(root,change_id,*,expected_revision,material_digest,decision,reason,findings,next_action,operation_key,reviewer_mode='ai_assisted_adjudication',responsible_party=None):
    require(decision in ('handoff-ready','needs-work') and reviewer_mode in ('owner_adjudication','ai_assisted_adjudication','scripted_adjudication'),'Invalid handoff review mode/decision.')
    require(all(isinstance(v,str) and v.strip() for v in (reason,next_action)) and isinstance(findings,list) and all(isinstance(v,str) and v.strip() for v in findings),'Reason, findings and next action must be explicit.')
    require(responsible_party is None or isinstance(responsible_party,str) and bool(responsible_party.strip()),'Responsible party must be a supplied label or unassigned.')
    store=Store(root);store.initialize();payload={k:v for k,v in locals().copy().items() if k not in ('store','root','operation_key')}
    if responsible_party is None:payload.pop('responsible_party')
    with store.transaction() as con:
        prior=store.operation(con,'review-handoff',operation_key,payload)
        if prior is not None:return prior
        state,material,_=_load(store,con,change_id)
        require(type(expected_revision) is int and expected_revision==state['revision'] and material_digest==state['material_digest'],'Handoff context changed; review the current material.','stale-handoff',409)
        if decision=='handoff-ready':
            from .handoff_context import eligible
            require(eligible(material),'Required external evidence is missing or its candidate relationship is unresolved.','handoff-unresolved',422)
        require(state['schema'] in ROLE_SCHEMAS or responsible_party is None,'Responsible-party labels require a v2 capture; old review semantics remain unchanged.')
        state=state|{'revision':state['revision']+1,'decision':decision,'reason':reason,'findings':findings,'next_action':next_action,'reviewer_mode':reviewer_mode,'actor':'operator'}
        if state['schema'] in ROLE_SCHEMAS:state['responsible_party']=responsible_party
        _save(store,con,state,'handoff-reviewed','operator');store.remember(con,'review-handoff',operation_key,payload,state);return state


def _validate_package(handoff,encoded):
    shape.check(isinstance(handoff,dict),'handoff','expected an object')
    require(handoff.get('schema') in VERSIONS,'handoff.schema: Unknown handoff schema.')
    allowed={'schema','state','material','events','audit_scope','workbench_executions','keep_mutations'}|({'comparison'} if handoff['schema'] in ROLE_SCHEMAS else set())
    require(set(handoff)==allowed
            and all(type(handoff[k]) is int and handoff[k]==0 for k in ('workbench_executions','keep_mutations')),
            'A read-only external-evidence handoff cannot claim execution or source mutation.','handoff-integrity',409)
    shape.state(handoff['state'])
    shape.check(isinstance(encoded,dict),'artifacts','expected a digest-to-base64 object')
    shape.array(handoff['events'],'events')
    if handoff['schema'] in ROLE_SCHEMAS:shape.check(isinstance(handoff['comparison'],dict),'comparison','expected an object')
    artifacts={}
    for key,value in encoded.items():
        shape.sha(key,'artifacts.key');shape.text(value,'artifacts.'+key,empty=True)
        raw=base64.b64decode(value,validate=True);require(digest(raw)==key,'Historical artifact mismatch.','handoff-integrity',409);artifacts[key]=raw
    events=handoff['events'];require(bool(events),'Missing handoff history.')
    expected=set();previous=-1
    for i,e in enumerate(events):
        path=f'events[{i}]'
        shape.obj(e,path,('seq','kind','actor','payload','prev_hash','hash','created_at'))
        for k in ('kind','actor','created_at'):shape.text(e[k],path+'.'+k)
        shape.integer(e['seq'],path+'.seq')
        for k in ('hash','prev_hash'):shape.sha(e[k],path+'.'+k)
        shape.obj(e['payload'],path+'.payload',('change_id','revision','material_digest','state_digest'))
        shape.text(e['payload']['change_id'],path+'.payload.change_id')
        shape.integer(e['payload']['revision'],path+'.payload.revision')
        for k in ('material_digest','state_digest'):
            shape.sha(e['payload'][k],path+'.payload.'+k)
            require(e['payload'][k] in artifacts,path+'.payload.'+k+': missing artifact')
        item=dict(e);actual=item.pop('hash');require(digest(canonical(item))==actual,'Handoff event mismatch.','handoff-integrity',409)
        p=e['payload'];s=parse(artifacts[p['state_digest']]);shape.state(s,path+'.state');m=parse(artifacts[p['material_digest']]);validate_material(m,lambda key:artifacts[key])
        require(s['schema'] in VERSIONS and s['schema']==m['schema'] and s['decision'] in ('unreviewed','handoff-ready','needs-work'), 'Invalid historical handoff decision.','handoff-integrity',409)
        require(s['schema'] in ROLE_SCHEMAS or 'responsible_party' not in s,'Responsible-party metadata requires a v2 state.','handoff-integrity',409)
        require(s['schema']==SCHEMA or handoff['schema'] in ROLE_SCHEMAS,'A role-bearing history requires a v2 envelope.','handoff-integrity',409)
        if s['schema'] in ROLE_SCHEMAS:
            require(s.get('responsible_party') is None or isinstance(s['responsible_party'],str) and bool(s['responsible_party'].strip()),'Invalid responsible-party label.')
        require(e['kind'] in ('handoff-captured','handoff-reviewed') and p['change_id']==s['change_id']==handoff['state']['change_id'] and p['revision']==s['revision']==previous+1 and s['material_digest']==p['material_digest'],'Handoff history mismatch.','handoff-integrity',409)
        previous=s['revision'];expected.update((p['state_digest'],p['material_digest']))
        from .handoff_compact import refs
        expected.update(refs(m))
        require(m['schema'] not in COMPACT_SCHEMAS or handoff['schema'] in COMPACT_SCHEMAS,'Compact history needs a compact envelope')
        require(m['schema']!=V4 or handoff['schema']==V4,'v4 history needs a v4 envelope')
    require(set(artifacts)==expected,'Missing or extra handoff artifacts.','handoff-integrity',409)
    last=events[-1]['payload'];require(canonical(handoff['state'])==artifacts[last['state_digest']] and canonical(handoff['material'])==artifacts[last['material_digest']],'Current handoff differs from history.','handoff-integrity',409)
    if handoff['state']['decision']=='handoff-ready':
        from .handoff_context import eligible
        require(eligible(handoff['material']),'Unresolved handoff claims.','handoff-integrity',409)
    if handoff['schema'] in ROLE_SCHEMAS:
        from .handoff_context import compare
        expected_comparison=compare(handoff['state'],handoff['material'],events,artifacts,handoff['comparison'].get('baseline_revision'))
        require(canonical(expected_comparison)==canonical(handoff['comparison']),'Comparison differs from retained old/new material.','handoff-integrity',409)


def export(root,change_id,output,baseline_revision=None):
    store=Store(root);store.initialize()
    with store.transaction(write=False) as con:
        state,material,events=_load(store,con,change_id)
        keys={e['payload'][k] for e in events for k in ('state_digest','material_digest')}
        from .handoff_compact import refs
        for event in events:keys.update(refs(parse(store.artifact_bytes(event['payload']['material_digest']))))
        encoded={key:base64.b64encode(store.artifact_bytes(key)).decode() for key in sorted(keys)}
        version=_envelope(store,events)
        handoff={'schema':version,'state':state,'material':material,'events':events,
                 'audit_scope':'Selected change events with original audit hashes; not a complete global audit chain.','workbench_executions':0,'keep_mutations':0}
        if version in ROLE_SCHEMAS:
            from .handoff_context import compare
            handoff['comparison']=compare(state,material,events,{k:base64.b64decode(v) for k,v in encoded.items()},baseline_revision)
    _validate_package(handoff,encoded)
    data={'handoff.json':canonical(handoff)+b'\n','artifacts.json':canonical(encoded)+b'\n'}
    manifest={'schema':version,'change_id':change_id,'revision':state['revision'],'files':{n:{'sha256':digest(raw),'bytes':len(raw)} for n,raw in data.items()}}
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
        raw={name:_read(folder/name) for name in FILES};manifest=parse(raw['manifest.json']);shape.manifest(manifest,FILES)
        require(manifest['schema'] in VERSIONS and set(manifest['files'])==set(FILES)-{'manifest.json'},'Invalid manifest.')
        for name,expected in manifest['files'].items():require(expected=={'sha256':digest(raw[name]),'bytes':len(raw[name])},'Manifest content mismatch.','handoff-integrity',409)
        handoff=parse(raw['handoff.json']);_validate_package(handoff,parse(raw['artifacts.json']))
        require(manifest['schema']==handoff['schema'] and manifest['change_id']==handoff['state']['change_id'] and manifest['revision']==handoff['state']['revision'],'Manifest state mismatch.')
        return {'ok':True,'errors':[],'manifest_digest':digest(raw['manifest.json']),'change_id':manifest['change_id'],'revision':manifest['revision']}
    except (WorkbenchError,OSError,ValueError,KeyError,TypeError) as exc:return {'ok':False,'errors':[str(exc)]}
