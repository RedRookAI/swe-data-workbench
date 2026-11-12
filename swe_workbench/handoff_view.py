"""Build a selected read-only view. Opens no listener and publishes nothing."""
import shutil,tempfile,os
from pathlib import Path
from .assets import bundled_directory
from .bundle import _publish,_fsync_directory
from .handoff import verify,require,FILES


def build(source,output):
    source=Path(source).resolve();target=Path(output).absolute()
    result=verify(source);require(result['ok'],'Selected handoff failed verification: '+str(result['errors']))
    require(target.parent.is_dir() and not target.exists() and not target.is_symlink(),'Choose a fresh view directory under an existing parent.')
    require(not target.resolve().is_relative_to(source) and not source.is_relative_to(target.resolve()),'View and input cannot overlap.')
    stage=Path(tempfile.mkdtemp(prefix='.handoff-view-',dir=target.parent));web=bundled_directory('web')
    try:
        for name in ('index.html','app.js','handoff-verify.js','style.css'):shutil.copyfile(web/name,stage/name)
        index=stage/'index.html';index.write_text(index.read_text().replace('<body>','<body data-handoff-only="true">').replace('SWE Data Workbench · Evidence to dataset','SWE Data Workbench · Change review'))
        (stage/'handoff').mkdir(mode=0o700)
        for name in FILES:shutil.copyfile(source/name,stage/'handoff'/name)
        require(verify(stage/'handoff')['ok'],'Copied handoff failed verification.')
        for f in stage.rglob('*'):
            if f.is_file():
                with f.open('rb') as stream:os.fsync(stream.fileno())
        _fsync_directory(stage/'handoff');_fsync_directory(stage);_publish(stage,target);_fsync_directory(target.parent)
        return {'output':str(target),'read_only':True,'runtime_database_created':False,'manifest_digest':result['manifest_digest'],'notice':'Selected evidence copied locally. No listener or upload; serve privately through your trusted connection, or publish only authorized inputs.'}
    finally:
        if stage.exists():shutil.rmtree(stage)


def build_project(context_path,output):
    from .attention import list_changes,detail
    from .project_context import load
    from .handoff import export,parse
    from .store import digest,canonical
    context=load(context_path);rows=list_changes(context_path)['changes'];target=Path(output).absolute()
    require(target.parent.is_dir() and not target.exists() and not target.is_symlink(),'project.view: choose a fresh directory')
    source=Path(context['state']).resolve();require(not target.resolve().is_relative_to(source) and not source.is_relative_to(target.resolve()),'project.view: input/output overlap')
    stage=Path(tempfile.mkdtemp(prefix='.project-view-',dir=target.parent));web=bundled_directory('web')
    try:
        selected=[]
        for row in rows:
            key='change-'+digest(row['change_id'].encode())[:20];raw=stage/('.raw-'+key)
            export(source,row['change_id'],raw);frozen=parse((raw/'handoff.json').read_bytes())
            current=detail(source,row['change_id']);require(current['revision']==frozen['state']['revision'] and current['material_digest']==frozen['state']['material_digest'],'project.view: change updated while selecting; retry fresh output')
            build(raw,stage/key);shutil.rmtree(raw)
            selected.append({k:current[k] for k in ('change_id','title','decision','needs_attention','responsible_party','next_action','revision','material_digest') }|{'view':key+'/'})
        for name in ('attention.html','attention.js','style.css'):shutil.copyfile(web/name,stage/('index.html' if name=='attention.html' else name))
        (stage/'attention.json').write_bytes(canonical({'schema':'swe-workbench-attention/v1','changes':selected,'scope':'Each selected change is frozen independently; not a global atomic batch.'})+b'\n')
        _fsync_directory(stage);_publish(stage,target);_fsync_directory(target.parent)
        return {'output':str(target),'changes':len(selected),'read_only':True,'notice':'Local selected snapshot; no listener or publication. Private evidence keeps its intended audience.'}
    finally:
        if stage.exists():shutil.rmtree(stage)
