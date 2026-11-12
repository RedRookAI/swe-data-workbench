"""One explicit local assembly command. Receipt stages expose partial completion."""
import os,json,tempfile,shutil
from pathlib import Path
from .bundle import _read,_publish,_fsync_directory
from .store import canonical,digest,Store
from .handoff import parse,require,read,export
from .project_context import load,collect
from .project_scope import check
from .junit_report import import_report
from .handoff_view import build
from .attention import summary
from .errors import WorkbenchError

SCHEMA='swe-workbench-review-package/v1'

def save(path,data):
    temporary=path.with_name('.'+path.name+'.tmp')
    try:
        with temporary.open('xb') as stream:stream.write(canonical(data)+b'\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path);_fsync_directory(path.parent)
    finally:temporary.unlink(missing_ok=True)

def current(root,key):
    if not Store(root).db.exists():return None
    try:s=read(root,key)['state'];return {k:s[k] for k in ('revision','material_digest')}
    except WorkbenchError as error:
        if error.code=='handoff-not-found':return None
        raise

def assemble(context_path,output,*,resume=False,change_id=None,title=None,goal=None,report=None,run_context=None,base=None,candidate=None,ci_receipt=None,check_definition=None):
    context=load(context_path);check(context);target=Path(output).absolute();receipt_path=target/'receipt.json';context_sha=digest(canonical(context))
    require(target.parent.is_dir() and not target.is_symlink(),'review.output: choose an owned directory under an existing parent')
    for value in (context['repo'],context['state']):
        source=Path(value).resolve();require(not target.resolve().is_relative_to(source) and not source.is_relative_to(target.resolve()),'review.output: source/state/output overlap')
    if not resume:
        require(not target.exists(),'review.output: choose a fresh output, or explicitly resume it')
        require(all(isinstance(x,str) and x.strip() for x in (change_id,title,goal)) and report is not None,'review.inputs: supply change ID, title, goal and existing report')
        stage=Path(tempfile.mkdtemp(prefix='.review-package-',dir=target.parent))
        try:
            import_report(report,stage/'imported',run_context,ci_receipt,check_definition)
            generated=parse(_read(stage/'imported/profile.json'));profile=parse(_read(context['profile']))
            require(profile.get('observations')==generated['observations'] and profile.get('attachments')==generated['attachments'],'review.profile: this command supports the pytest import profile; use the explicit commands for custom mappings')
            preview=collect(context_path,change_id=change_id,title=title,goal=goal,base=base,candidate=candidate,evidence_directory=stage/'imported',preview=True)
            before=current(context['state'],change_id)
            receipt={'schema':SCHEMA,'context_sha256':context_sha,'change_id':change_id,'title':title,'goal':goal,'resolved':preview['resolved'],'material_digest':preview['material_digest'],'before':before,'stage':'prepared','notice':'Local assembly only. View is the shareable selection; receipt/imports/review-selection retain their intended private audience.'}
            save(stage/'receipt.json',receipt);_publish(stage,target);_fsync_directory(target.parent)
        finally:
            if stage.exists():shutil.rmtree(stage)
    else:
        require(target.is_dir() and not receipt_path.is_symlink(),'review.resume: expected an existing owned package receipt')
        receipt=parse(_read(receipt_path))
        require(isinstance(receipt,dict) and receipt.get('schema')==SCHEMA and receipt.get('context_sha256')==context_sha,'review.resume: different context or unsupported receipt')
        from . import handoff_validation as validation
        validation.obj(receipt,'review.receipt',('schema','context_sha256','change_id','title','goal','resolved','material_digest','before','stage','notice'),('selection','error'))
        require(receipt['stage'] in ('prepared','capture-failed','captured','complete'),'review.receipt: unsupported stage')
        if receipt['stage']=='complete':
            from .handoff import verify
            frozen=verify(target/'export');view=verify(target/'view/handoff')
            require(frozen['ok'] and view['ok'] and frozen['manifest_digest']==view['manifest_digest'],'review.complete: retained package is missing or changed')
            return receipt
    try:
        preview=collect(context_path,change_id=receipt['change_id'],title=receipt['title'],goal=receipt['goal'],base=receipt['resolved']['base'],candidate=receipt['resolved']['candidate'],evidence_directory=target/'imported',preview=True)
        require(preview['material_digest']==receipt['material_digest'],'review.resume: selected input/profile content changed; no newer material was selected')
        if receipt['stage'] in ('prepared','capture-failed'):
            now=current(context['state'],receipt['change_id']);before=receipt['before'];revision=0 if before is None else before['revision']+(before['material_digest']!=receipt['material_digest'])
            expected={'revision':revision,'material_digest':receipt['material_digest']}
            require(now==before or now==expected,'review.resume: review/source state advanced; inspect the exact recorded selection')
            result=collect(context_path,change_id=receipt['change_id'],title=receipt['title'],goal=receipt['goal'],base=receipt['resolved']['base'],candidate=receipt['resolved']['candidate'],evidence_directory=target/'imported',expected_state=now)
            require({k:result['state'][k] for k in expected}==expected,'review.capture: selected revision changed')
            receipt['selection']=result['selection'];receipt['stage']='captured';receipt.pop('error',None);save(receipt_path,receipt);save(target/'selection.json',result['selection'])
        chosen=receipt['selection'];require(current(context['state'],receipt['change_id'])=={k:chosen[k] for k in ('revision','material_digest')},'review.resume: saved selection is stale; no review token was refreshed')
        if not (target/'export').exists():export(context['state'],receipt['change_id'],target/'export')
        from .handoff import verify
        verified=verify(target/'export');require(verified['ok'],'review.export: frozen package failed verification')
        frozen=parse(_read(target/'export/handoff.json'))['state'];require(all(frozen[k]==chosen[k] for k in ('revision','material_digest')),'review.export: different selected revision')
        if not (target/'view').exists():build(target/'export',target/'view')
        view=verify(target/'view/handoff');require(view['ok'] and view['manifest_digest']==verified['manifest_digest'],'review.view: selected view does not match the frozen export')
        readable=summary(context_path,receipt['change_id']);require(all(readable[k]==chosen[k] for k in ('revision','material_digest')),'review.summary: selection advanced; no newer summary was selected')
        save(target/'summary.json',readable);receipt['stage']='complete';receipt.pop('error',None);save(receipt_path,receipt)
        return receipt
    except (WorkbenchError,OSError) as error:
        if receipt['stage']=='prepared':receipt['stage']='capture-failed'
        receipt['error']={'code':getattr(error,'code','review-output'),'message':str(error),'durable_capture':receipt['stage']=='captured'};save(receipt_path,receipt)
        raise WorkbenchError('review-incomplete','Review package is incomplete at '+receipt['stage']+'. Exact stage/error are retained in receipt.json; use explicit --resume after inspection. '+str(error)) from error
