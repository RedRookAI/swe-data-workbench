"""v3 source artifacts and explicit text/metadata coverage. No source execution."""
import hashlib
from .bundle import _git,_text,_source_path
from .intake import MAX_FILE_BYTES,MAX_RECORDS
from .store import digest
from .errors import WorkbenchError
from . import handoff_validation as v

V3='swe-workbench-handoff/v3'

def refs(material):
    return {phase['content_digest'] for f in material['files'] for phase in (f['before'],f['after']) if phase is not None and phase.get('coverage')=='text'} if material['schema']==V3 else set()

def collect(repo,base,candidate,paths,blobs):
    files=[];total=0;text_paths=[];metadata=[]
    for path in paths:
        _source_path(path);f={'path':path}
        for name,revision in [('before',base),('after',candidate)]:
            entry=_git(repo,'ls-tree','-z','--full-tree',revision,'--',path).split(b'\0')[0]
            if not entry:f[name]=None;continue
            header,actual=entry.split(b'\t',1);mode,kind,oid=header.decode().split()
            v.check(actual.decode()==path,'source.path','Git path differs')
            size=int(_git(repo,'cat-file','-s',oid)) if kind=='blob' else None
            phase={'mode':mode,'git_blob':oid,'bytes':size,'coverage':'metadata-only','reason':'Unsupported type; no target traversal or execution'}
            if mode in ('100644','100755') and kind=='blob' and total+size<=MAX_FILE_BYTES:
                raw=_git(repo,'cat-file','blob',oid)
                try:_text(raw,'Source blob')
                except WorkbenchError:phase['reason']='Binary or unsupported UTF8 text'
                else:
                    key=digest(raw);blobs[key]=raw;total+=len(raw)
                    phase={'mode':mode,'git_blob':oid,'bytes':size,'coverage':'text','content_digest':key}
            elif mode in ('100644','100755'):phase['reason']='Source text exceeds remaining admitted byte budget'
            f[name]=phase
        files.append(f)
        (text_paths if all(x is None or x['coverage']=='text' for x in (f['before'],f['after'])) else metadata).append(path)
    patch=_git(repo,'diff','--no-ext-diff','--no-textconv','--no-renames','--full-index',base,candidate,'--',*text_paths) if text_paths else b''
    v.check(total+len(patch)<=MAX_FILE_BYTES,'source.patch','Source and text patch exceed admitted bytes')
    return files,patch,total,{'text_paths':text_paths,'metadata_only_paths':metadata,'patch_scope':'fully-captured-text-paths-only'}

def validate(material,read_blob):
    v.obj(material['coverage'],'material.coverage',('text_paths','metadata_only_paths','patch_scope'))
    text_paths=[];metadata=[]
    for i,f in enumerate(material['files']):
        path=f'material.files[{i}]';v.obj(f,path,('path','before','after'));_source_path(f['path'])
        for name in ('before','after'):
            phase=f[name]
            if phase is None:continue
            v.obj(phase,path+'.'+name,('mode','git_blob','bytes','coverage'),('content_digest','reason'))
            v.text(phase['mode'],path+'.mode');v.sha(phase['git_blob'],path+'.git_blob',git=True)
            if phase['bytes'] is not None:v.integer(phase['bytes'],path+'.bytes')
            v.check(phase['coverage'] in ('text','metadata-only'),path+'.coverage','expected text or metadata-only')
            if phase['coverage']=='text':
                v.check(phase['mode'] in ('100644','100755') and 'content_digest' in phase and 'reason' not in phase,path,'invalid text source phase')
                v.sha(phase['content_digest'],path+'.content_digest');v.check(read_blob is not None,path,'source artifact reader missing')
                raw=read_blob(phase['content_digest']);_text(raw,'Source artifact')
                algorithm='sha1' if len(phase['git_blob'])==40 else 'sha256'
                oid=hashlib.new(algorithm,b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
                v.check(len(raw)==phase['bytes'] and digest(raw)==phase['content_digest'] and oid==phase['git_blob'],path,'source artifact identity mismatch')
            else:
                v.check('content_digest' not in phase and isinstance(phase.get('reason'),str),path,'metadata-only content must declare unavailable bytes/reason')
        (text_paths if all(x is None or x['coverage']=='text' for x in (f['before'],f['after'])) else metadata).append(f['path'])
    v.check(material['coverage']=={'text_paths':text_paths,'metadata_only_paths':metadata,'patch_scope':'fully-captured-text-paths-only'},'material.coverage','scope differs from retained paths')
