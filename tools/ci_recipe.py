#!/usr/bin/env python3
"""Fixed public qualification recipes; no arbitrary repository or command input."""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
from swe_workbench import ci_evidence as ci
from swe_workbench.bundle import _git
from swe_workbench.handoff import parse,verify
from swe_workbench.junit_report import import_report
from swe_workbench.project_context import configure
from swe_workbench.review_package import assemble,save
from swe_workbench.errors import WorkbenchError

BASE='93ae366874bbd4f69d90495c45b2cd336387496c'
CANDIDATE='7f4dcf83a07bb3d53f4e0e65ef1b43327b4cca90'
MANUAL_BASE='4ed531cae30a8cd7c8a18ca2da5d675b0511cc7f'
TESTS=['tests/test_ci_evidence.py','tests/test_ci_recipe.py','tests/test_project_scope.py','tests/test_report_containment.py','tests/test_exact_observations.py','tests/test_attention_cut.py','tests/test_review_package.py','tests/test_handoff_browser.py','tests/test_review_overview.py','tests/test_private_assets.py',
       'tests/test_core.py','tests/test_runner.py','tests/test_recovery.py',
       'tests/test_worker_capture.py','tests/test_worker_verifier.py',
       'tests/test_evaluation.py','tests/test_quality_demo.py']

def select_base(env):
    if env.get('GITHUB_EVENT_NAME')=='pull_request':return env.get('WB_PR_BASE')
    if env.get('GITHUB_EVENT_NAME')=='push':return env.get('WB_PUSH_BASE')
    return MANUAL_BASE

def setup(workspace,root,case):
    root.mkdir();source=workspace;product='RedRookAI/swe-data-workbench';base=select_base(os.environ)
    if case=='itsdangerous':
        source=root/'source';source.mkdir()
        for args in [('init','-q'),('remote','add','origin','https://github.com/pallets/itsdangerous.git'),('fetch','--depth=2','origin',CANDIDATE),('checkout','--detach','--quiet',CANDIDATE)]:
            subprocess.run(['git','-c','core.hooksPath=/dev/null','-C',str(source),*args],check=True,stdout=subprocess.DEVNULL)
        if _git(source,'rev-parse','HEAD^').decode().strip()!=BASE:raise ValueError('Pinned external parent differs')
        product='pallets/itsdangerous';base=BASE
    save(root/'recipe.json',{'case':case,'source':str(source),'workspace':str(workspace),'product':product,'base':base})

def check(root):
    recipe=parse((root/'recipe.json').read_bytes());source=Path(recipe['source']);case=recipe['case'];out=root/'observed'
    selected=['tests/test_itsdangerous/test_signer.py'] if case=='itsdangerous' else (['tools/ci_failure_probe.py'] if case=='intentional-failure' else TESTS)
    argv=[sys.executable,'-m','pytest',*selected,'-q','-p','no:cacheprovider','--junitxml='+str(out/'original.xml')]
    # All tracked product bytes are selected inputs, including ignored tracked files.
    names=_git(source,'ls-files','-z').decode().rstrip('\0').split('\0')
    probe=None
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    if case=='itsdangerous':
        env['PYTHONPATH']=str(source/'src')
        probe=subprocess.run([sys.executable,'-c','import itsdangerous; print(itsdangerous.__file__)'],env=env,cwd=source,check=True,capture_output=True,text=True).stdout.strip()
        if Path(probe).resolve()!=source/'src/itsdangerous/__init__.py':raise ValueError('External import did not resolve to pinned src')
        save(root/'import-path.json',{'actual_import':probe,'expected_candidate':CANDIDATE,'scope':'Selected ordinary signer module; not a FIPS compliance test.'})
    ci.begin(source,out,recipe['product'],argv,names,import_path=probe)
    result=subprocess.run(argv,cwd=source,env=env)
    ci.finish(out,result.returncode)
    return result.returncode

def package(root):
    share=root/'share';share.mkdir();recipe_path=root/'recipe.json';out=root/'observed'
    diagnostic={'schema':'swe-workbench-ci-package-status/v1','status':'incomplete','case':None,'detail':'Check did not start or prerequisites failed; no report was fabricated.'}
    if recipe_path.is_file():
        recipe=parse(recipe_path.read_bytes());diagnostic['case']=recipe['case']
        if (out/'ci-receipt.json').is_file():
            receipt=parse((out/'ci-receipt.json').read_bytes());diagnostic['process_outcome']=receipt['process_outcome'];diagnostic['exit_code']=receipt['exit_code'];diagnostic['detail']=receipt['diagnostic']
            # Diagnostics retain allowlisted public provenance, never started.json/private paths.
            for name in ('ci-receipt.json','run-context.json','check-definition.json'):
                shutil.copyfile(out/name,share/name)
            if (out/'original.xml').is_file():shutil.copyfile(out/'original.xml',share/'original.xml')
            if receipt['report_status']=='parsed':
                source=Path(recipe['source']);base=recipe['base'];candidate=receipt['tested_revision']
                if not base or set(base)=={'0'}:diagnostic.update(status='unavailable-base',detail='No previous source revision was supplied; report retained without an invented diff.')
                else:
                    try:
                        try:base=_git(source,'rev-parse','--verify','--end-of-options',base+'^{commit}').decode().strip()
                        except WorkbenchError:
                            diagnostic.update(status='unavailable-base',detail='Declared base object is unavailable; original report retained without an invented diff.')
                            save(share/'package-status.json',diagnostic)
                            return diagnostic
                        if base==candidate:diagnostic.update(status='no-comparable-change',detail='Base equals candidate; original report retained without an invented change.')
                        else:
                            imported=root/'profile-import';import_report(out/'original.xml',imported,out/'run-context.json',out/'ci-receipt.json',out/'check-definition.json')
                            context=root/'project.json';configure(context,repo=str(source),profile=str(imported/'profile.json'),evidence_directory=str(imported),state=str(root/'state'),base_ref=base,candidate_ref=candidate)
                            title='Historical itsdangerous lazy SHA-1 lookup' if recipe['case']=='itsdangerous' else ('Intentional failing-check qualification' if recipe['case']=='intentional-failure' else 'Actual workbench CI checks')
                            assembled=root/'assembled';assemble(context,assembled,change_id='ci-selected',title=title,goal='Review the selected committed change with its observed pytest run. Package creation leaves review unreviewed.',report=out/'original.xml',run_context=out/'run-context.json',ci_receipt=out/'ci-receipt.json',check_definition=out/'check-definition.json')
                            if not verify(assembled/'export')['ok']:raise ValueError('Selected export failed verification')
                            for name in ('view','export'):shutil.copytree(assembled/name,share/name)
                            shutil.copyfile(assembled/'summary.json',share/'summary.json')
                            if recipe['case']=='itsdangerous':
                                shutil.copyfile(source/'LICENSE.txt',share/'UPSTREAM-LICENSE.txt')
                                save(share/'UPSTREAM.json',{'repository':'https://github.com/pallets/itsdangerous','base':BASE,'candidate':CANDIDATE,'original_date':'2024-04-16','attribution':'Historical upstream change; not authored by this workbench. Actual current selected signer tests; no model-generated patch or FIPS-compliance claim.'})
                            diagnostic.update(status='complete',detail='Selected view/export/summary; explicit review remains unreviewed.')
                    except (WorkbenchError,ValueError,OSError) as exc:
                        diagnostic.update(status='packaging-error',detail=str(exc));save(share/'package-status.json',diagnostic);raise
    save(share/'package-status.json',diagnostic)
    summary=os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a') as f:f.write('## Selected review artifact\n\n'+json.dumps(diagnostic,indent=2)+'\n\nDownload requires GitHub sign-in and is subject to repository retention. Serve the extracted view over HTTP. Unsigned observations; package status is separate from test outcome and explicit review.\n')
    return diagnostic

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['setup','check','package']);p.add_argument('--root',type=Path,required=True);p.add_argument('--workspace',type=Path,default=Path.cwd());p.add_argument('--case',choices=['normal','intentional-failure','itsdangerous'],default='normal');a=p.parse_args()
    if a.action=='setup':setup(a.workspace.resolve(),a.root,a.case)
    elif a.action=='check':return check(a.root)
    else:package(a.root)
    return 0
if __name__=='__main__':sys.exit(main())
