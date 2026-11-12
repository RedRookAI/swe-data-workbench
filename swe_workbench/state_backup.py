"""Private quiescent state snapshots. Never restore workers or source workspaces."""
import contextlib,hashlib,os,re,shutil,sqlite3,tempfile
from pathlib import Path
from .store import Store,canonical
from .handoff import parse,require
from .bundle import _read,_publish,_fsync_directory
from . import handoff_validation as v
from .errors import WorkbenchError

SCHEMA='swe-workbench-state-backup/v1'
COVERAGE='SQLite records and immutable artifacts; external bundles, source repositories, published exports, credentials and attempt directories are excluded. Historical process identities confer no execution authority.'

def _hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(65536),b''):h.update(block)
    return h.hexdigest()

def _files(root):
    require(not root.is_symlink() and root.is_dir(),'backup.root: expected a regular state directory')
    require((root/'workbench.sqlite3').is_file() and not (root/'workbench.sqlite3').is_symlink(),'backup.database: expected an existing regular SQLite database')
    artifacts=root/'artifacts';require(artifacts.is_dir() and not artifacts.is_symlink(),'backup.artifacts: expected a regular artifact directory')
    files={'workbench.sqlite3':root/'workbench.sqlite3'}
    for f in artifacts.iterdir():
        require(f.is_file() and not f.is_symlink() and re.fullmatch('[a-f0-9]{64}',f.name),'backup.artifacts: unexpected non-artifact entry')
        require(_hash(f)==f.name,'backup.artifacts: content digest mismatch')
        files['artifacts/'+f.name]=f
    return files

def _verify_state(root):
    files=_files(root);store=Store(root)
    with contextlib.closing(sqlite3.connect((root/'workbench.sqlite3').as_uri()+'?mode=ro',uri=True)) as con:
        con.row_factory=sqlite3.Row
        require(con.execute('PRAGMA user_version').fetchone()[0]==1,'backup.schema: only existing schema1 state is supported')
        require(con.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not con.execute('PRAGMA foreign_key_check').fetchall(),'backup.database: integrity check failed')
        require(con.execute('PRAGMA journal_mode').fetchone()[0]=='delete','backup.database: unsupported journal mode')
        require(not con.execute("SELECT 1 FROM attempts WHERE state IN ('intent','registered','uncertain') LIMIT 1").fetchone() and not con.execute("SELECT 1 FROM runs WHERE status='running' LIMIT 1").fetchone() and not con.execute('SELECT 1 FROM submissions WHERE active_attempt IS NOT NULL LIMIT 1').fetchone(),'backup.execution: active or uncertain execution is unsupported; original state preserved')
        try:
            audit_root=store.verify_audit(con);events=store.events(con)
        except (ValueError,TypeError,KeyError) as exc:
            raise WorkbenchError('backup-audit','backup.audit: malformed stored event') from exc
        refs=set()
        for event in events:
            v.check(isinstance(event['payload'],dict),'backup.audit.payload','expected an object')
            for key in ('state_digest','material_digest','evidence_digest'):
                if key in event['payload']:refs.add(event['payload'][key])
        for row in con.execute('SELECT key,value FROM meta'):
            if row['key'].startswith(('handoff:','quality-context:')):refs.add(row['value'])
        for row in con.execute('SELECT result FROM submissions WHERE result IS NOT NULL'):
            result=parse(row[0]);v.check(isinstance(result,dict) and 'evidence_digest' in result,'backup.result','expected an evidence-bound result object');key=result['evidence_digest'];v.sha(key,'backup.result.evidence_digest');refs.add(key)
            require(store.artifact_bytes(key)==canonical({k:x for k,x in result.items() if k!='evidence_digest'}),'backup.results: stored evidence mismatch')
        refs.update(row[0] for row in con.execute('SELECT result_digest FROM attempts WHERE result_digest IS NOT NULL'))
        for key in refs:
            v.sha(key,'backup.reference');store.artifact_bytes(key)
        for row in con.execute('SELECT key FROM meta WHERE key LIKE ?',('handoff:%',)):
            from .handoff import _load
            _load(store,con,row['key'][len('handoff:'):])
        return files,audit_root

def _destination(source,output):
    target=Path(output).absolute();actual=target.resolve()
    require(target.parent.is_dir() and not target.exists() and not target.is_symlink(),'backup.output: choose a fresh destination under an existing parent')
    require(not actual.is_relative_to(source) and not source.is_relative_to(actual),'backup.output: source and destination cannot overlap')
    return target

def _sync(root):
    for f in _files(root).values():
        with f.open('rb') as stream:os.fsync(stream.fileno())
    _fsync_directory(root/'artifacts');_fsync_directory(root)

def backup(root,output):
    source=Path(root).absolute();_files(source);target=_destination(source.resolve(),output)
    stage=Path(tempfile.mkdtemp(prefix='.state-backup-',dir=target.parent))
    try:
        # SQLite supplies the database cut. Artifacts are immutable and no GC runs.
        with contextlib.closing(sqlite3.connect((source/'workbench.sqlite3').as_uri()+'?mode=ro',uri=True)) as src,contextlib.closing(sqlite3.connect(stage/'workbench.sqlite3')) as dst:src.backup(dst)
        (stage/'artifacts').mkdir(mode=0o700)
        for f in (source/'artifacts').iterdir():
            require(f.is_file() and not f.is_symlink() and re.fullmatch('[a-f0-9]{64}',f.name),'backup.artifacts: unexpected entry')
            shutil.copyfile(f,stage/'artifacts'/f.name)
        files,audit_root=_verify_state(stage)
        manifest={'schema':SCHEMA,'sqlite_schema':1,'quiescent':True,'audit_root':audit_root,'coverage':COVERAGE,'files':{name:{'sha256':_hash(f),'bytes':f.stat().st_size} for name,f in files.items()}}
        with (stage/'backup.json').open('xb') as f:f.write(canonical(manifest)+b'\n');f.flush();os.fsync(f.fileno())
        _sync(stage);_publish(stage,target);_fsync_directory(target.parent)
        return {'output':str(target),'schema':SCHEMA,'audit_root':audit_root,'artifacts':len(files)-1,'coverage':COVERAGE}
    except (OSError,sqlite3.DatabaseError) as exc:raise WorkbenchError('backup-state','Backup could not complete; original state preserved: '+str(exc)) from exc
    finally:
        if stage.exists():shutil.rmtree(stage)

def restore(source,output):
    source=Path(source).absolute();target=_destination(source.resolve(),output)
    require(source.is_dir() and not source.is_symlink() and {f.name for f in source.iterdir()}=={'workbench.sqlite3','artifacts','backup.json'},'backup.files: exact backup file set required')
    require(not (source/'backup.json').is_symlink(),'backup.manifest: regular file required')
    manifest=parse(_read(source/'backup.json'))
    v.obj(manifest,'backup.manifest',('schema','sqlite_schema','quiescent','audit_root','coverage','files'))
    require(manifest['schema']==SCHEMA and manifest['sqlite_schema']==1 and manifest['quiescent'] is True and manifest['coverage']==COVERAGE,'backup.manifest: unsupported format/scope')
    files=_files(source);v.obj(manifest['files'],'backup.manifest.files',files.keys())
    for name,f in files.items():require(manifest['files'][name]=={'sha256':_hash(f),'bytes':f.stat().st_size},'backup.files: manifest content mismatch: '+name)
    stage=Path(tempfile.mkdtemp(prefix='.state-restore-',dir=target.parent))
    try:
        (stage/'artifacts').mkdir(mode=0o700)
        for name,f in files.items():shutil.copyfile(f,stage/name)
        _,audit_root=_verify_state(stage);require(audit_root==manifest['audit_root'],'backup.audit: root mismatch')
        _sync(stage);_publish(stage,target);_fsync_directory(target.parent)
        return {'output':str(target),'schema':SCHEMA,'audit_root':audit_root,'coverage':COVERAGE}
    except (OSError,sqlite3.DatabaseError) as exc:raise WorkbenchError('backup-state','Restore could not complete; original state preserved: '+str(exc)) from exc
    finally:
        if stage.exists():shutil.rmtree(stage)
