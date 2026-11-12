"""One installed-wheel handoff rehearsal. No publishing or input-project execution."""
import argparse,importlib.metadata,json,os,subprocess,sys,tempfile,zipfile
from pathlib import Path
from . import __version__
from .store import digest,canonical
from .handoff import verify
from .receipt_example import produce
from .errors import WorkbenchError

def run(wheel,legacy,current,output):
    output=Path(output).absolute()
    try:output.mkdir(mode=0o700,exist_ok=False)
    except OSError as exc:return {'ok':False,'version':__version__,'error':'Choose a fresh qualification directory under an existing parent: '+str(exc)}
    receipt={'version':__version__,'wheel_sha256':digest(Path(wheel).read_bytes()),'checks':[],'application_model_calls':0,'input_project_execution':0}
    def record(name,**fields):receipt['checks'].append({'name':name,**fields});(output/'qualification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    try:
        package=Path(__file__).resolve().parent
        if not any(part in ('site-packages','dist-packages') for part in package.parts):raise WorkbenchError('release-import','Qualification must import an installed wheel, not the source checkout.')
        if importlib.metadata.version('swe-data-workbench')!=__version__:raise WorkbenchError('release-version','Installed package metadata/version differ.')
        with zipfile.ZipFile(wheel) as z:
            names=z.namelist();metadata=[n for n in names if n.endswith('.dist-info/METADATA')]
            if len(metadata)!=1 or ('Version: '+__version__+'\n').encode() not in z.read(metadata[0]):raise WorkbenchError('release-version','Selected wheel version differs from installed package.')
            checked=[]
            for name in names:
                if name.startswith('swe_workbench/'):
                    target=package.parent/name
                elif '.data/data/share/swe-data-workbench/' in name:
                    target=Path(sys.prefix)/name.split('.data/data/',1)[1]
                else:continue
                if not target.is_file() or target.read_bytes()!=z.read(name):raise WorkbenchError('release-bytes','Installed bytes differ from wheel: '+name)
                checked.append(name)
        record('installed-wheel-parity',files=len(checked))
        for name,path in [('frozen-v1',legacy),('frozen-v2',current)]:
            result=verify(path)
            if not result['ok']:raise WorkbenchError('release-legacy',name+': '+str(result['errors']))
            record(name,manifest_digest=result['manifest_digest'])
        inputs=produce(output/'example');state=output/'state'
        def cli(*args,ok=True):
            result=subprocess.run([sys.executable,'-I','-m','swe_workbench.cli','--root',str(state),*map(str,args)],cwd=output,capture_output=True,text=True)
            if (result.returncode==0)!=ok:raise WorkbenchError('release-cli','Stage '+str(args[0])+' failed: '+result.stdout+result.stderr)
            return json.loads(result.stdout)
        capture=['--repo',inputs['repo'],'--base',inputs['base'],'--candidate',inputs['candidate'],'--profile',inputs['profile'],'--evidence-dir',inputs['evidence_dir'],'--change-id',inputs['change_id'],'--title',inputs['title'],'--goal',inputs['goal']]
        preview=cli('preview-handoff',*capture)
        if state.exists():raise WorkbenchError('release-preview','Preview created runtime state.')
        captured=cli('capture-handoff',*capture)
        if preview['material_digest']!=captured['material_digest']:raise WorkbenchError('release-preview','Preview and capture differ on unchanged inputs.')
        review_args=['review-handoff',inputs['change_id'],'--expected-revision',captured['revision'],'--material-digest',captured['material_digest'],'--decision','handoff-ready','--reason','Scripted qualification inspected one fixed synthetic check.','--next-action','Owner can inspect the exported example.','--operation-key','qualification-review','--reviewer-mode','scripted_adjudication']
        reviewed=cli(*review_args)
        if cli(*review_args)!=reviewed or cli('capture-handoff',*capture)!=reviewed:raise WorkbenchError('release-retry','Review/capture retry changed current state.')
        cli('export-handoff',inputs['change_id'],'--output',output/'export');cli('verify-handoff',output/'export')
        cli('export-handoff',inputs['change_id'],'--output',output/'export',ok=False)
        cli('review-handoff',inputs['change_id'],'--expected-revision',captured['revision'],'--material-digest',captured['material_digest'],'--decision','needs-work','--reason','Stale synthetic input','--next-action','Read current state','--operation-key','stale',ok=False)
        record('preview-capture-review-export',revision=reviewed['revision'],retries_preserved=True,occupied_export_and_stale_review_refused=True)
        cli('backup-state','--output',output/'backup');cli('restore-state',output/'backup','--output',output/'restored')
        state=output/'restored';restored=cli('handoff',inputs['change_id'])['state']
        if restored!=reviewed:raise WorkbenchError('release-restore','Restored review differs.')
        cli('review-handoff',inputs['change_id'],'--expected-revision',reviewed['revision'],'--material-digest',reviewed['material_digest'],'--decision','needs-work','--reason','Scripted continuation after restore','--next-action','Owner review','--operation-key','restored-review','--reviewer-mode','scripted_adjudication')
        cli('export-handoff',inputs['change_id'],'--output',output/'restored-export');cli('verify-handoff',output/'restored-export')
        record('restore-and-continue',history_preserved=True)
        # Missing source binding is exercised without inventing another execution.
        proof=Path(inputs['evidence_dir'])/'receipt.json';facts=json.loads(proof.read_text());facts['source']['worktree']='unknown';facts['execution_revision']=None;proof.write_bytes(canonical(facts)+b'\n')
        unknown=cli('capture-handoff',*capture)
        cli('review-handoff',inputs['change_id'],'--expected-revision',unknown['revision'],'--material-digest',unknown['material_digest'],'--decision','handoff-ready','--reason','Must refuse unknown binding','--next-action','Obtain actual context','--operation-key','unknown',ok=False)
        if cli('preview-handoff',*capture)['required_bindings_complete']:raise WorkbenchError('release-unknown','Unknown binding was hidden.')
        record('unknown-source-remains-unresolved')
        receipt['ok']=True
    except (WorkbenchError,OSError,ValueError,zipfile.BadZipFile) as exc:
        receipt.update(ok=False,error=str(exc))
    (output/'qualification.json').write_text(json.dumps(receipt,indent=2)+'\n');return receipt

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('wheel','legacy-export','current-export','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=run(args.wheel,args.legacy_export,args.current_export,args.output);print(json.dumps(result,indent=2));return 0 if result['ok'] else 1
if __name__=='__main__':raise SystemExit(main())
