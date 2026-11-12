"""Local project association. Private state metadata; never publisher identity."""
import json
from pathlib import Path
from .bundle import _git,_read
from .store import Store,canonical
from .errors import WorkbenchError

KEY='project-association/v1'

def require(ok,message):
    if not ok:raise WorkbenchError('project-scope',message,409)

def identity(repo):
    path=Path(repo).resolve()
    common=Path(_git(path,'rev-parse','--git-common-dir').decode().strip())
    if not common.is_absolute():common=path/common
    stat=common.resolve().stat()
    return {'device':stat.st_dev,'inode':stat.st_ino}

def binding(store,con):
    row=con.execute('SELECT value FROM meta WHERE key=?',(KEY,)).fetchone()
    if row is None:return None
    from .handoff import parse
    value=parse(row[0])
    require(isinstance(value,dict) and set(value)=={'schema','repository','git_directory'} and value['schema']==KEY,'Invalid project association.')
    last=con.execute("SELECT payload FROM audit WHERE kind='project-associated' ORDER BY seq DESC LIMIT 1").fetchone()
    require(last is not None and json.loads(last[0])==value,'Project association differs from its recorded audit event.')
    return value

def enforce(store,con,repo,repository,*,claim=False):
    current=binding(store,con);expected={'schema':KEY,'repository':repository,'git_directory':identity(repo)}
    if current is not None:
        require(current==expected,'This state belongs to a different project/repository. Select its original context or a separate state directory.')
    elif claim:
        require(not con.execute("SELECT 1 FROM meta WHERE key LIKE 'handoff:%' LIMIT 1").fetchone(),'Legacy state is unassociated. Run associate-project with its explicit original context after inspection; mixed state is refused.')
        con.execute('INSERT INTO meta VALUES(?,?)',(KEY,canonical(expected).decode()))
        store.event(con,'project-associated',expected,'operator')
    return current

def check(context,*,con=None,store=None):
    from .handoff import parse
    profile=parse(_read(context['profile']))
    require(isinstance(profile,dict) and isinstance(profile.get('repository'),str) and bool(profile['repository'].strip()),'Selected profile needs an explicit repository label.')
    repository=profile['repository'];store=store or Store(context['state'])
    if not store.db.exists():return
    if con is None:
        store.initialize()
        with store.transaction(write=False) as connection:return check(context,con=connection,store=store)
    current=enforce(store,con,context['repo'],repository)
    require(current is not None or not con.execute("SELECT 1 FROM meta WHERE key LIKE 'handoff:%' LIMIT 1").fetchone(),'Legacy state is unassociated. Run associate-project with its original context; no project view has been exported.')

def associate(context_path,relocate=False):
    from .project_context import load
    from .handoff import _load,parse
    context=load(context_path);profile=parse(_read(context['profile']));store=Store(context['state'])
    require(store.db.exists(),'Associate only existing legacy state; new captures establish their association automatically.')
    store.initialize()
    with store.transaction() as con:
        existing=binding(store,con)
        if existing and not relocate:
            enforce(store,con,context['repo'],profile['repository']);return {'associated':True,'existing':True}
        if existing:require(existing['repository']==profile['repository'],'Relocation cannot rename or mix the associated project.')
        ids=[r[0][len('handoff:'):] for r in con.execute("SELECT key FROM meta WHERE key LIKE 'handoff:%'")]
        for change_id in ids:
            _,material,_=_load(store,con,change_id)
            require(material['repository']==profile['repository'],'Mixed/unknown legacy project labels; select separate original state. No history was relabeled.')
            for key in ('base_revision','candidate_revision'):
                require(_git(context['repo'],'rev-parse','--verify','--end-of-options',material[key]+'^{commit}').decode().strip()==material[key],'Selected repository lacks original committed source.')
        value={'schema':KEY,'repository':profile['repository'],'git_directory':identity(context['repo'])}
        con.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(KEY,canonical(value).decode()));store.event(con,'project-associated',value,'operator')
    return {'associated':True,'legacy_changes':len(ids),'notice':'Explicit local association; historical source/material/review bytes unchanged. Directory moves on the same filesystem retain identity; deliberate clone/filesystem relocation requires explicit --relocate and matching retained project/source.'}
