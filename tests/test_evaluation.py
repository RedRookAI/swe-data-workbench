"""Focused task quality/scoring and all-outcome export acceptance."""
import base64
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from swe_workbench.core import Workbench
from swe_workbench.errors import WorkbenchError
from swe_workbench.evaluation import context,review_task,record_calibration,score_batch,score_item
from swe_workbench.evaluation_export import export_evaluation,verify_evaluation
from swe_workbench.exporter import export_batch,verify_export
from swe_workbench.store import canonical,digest


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]);self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.fixtures=self.root/'fixtures';self.fixtures.mkdir()
        base='def flags():\n    return 0\n'
        def diff(code):return '--- a/solution.py\n+++ b/solution.py\n@@ -1,2 +1,2 @@\n def flags():\n-    return 0\n+    '+code+'\n'
        patches=[diff('return 7'),diff('return 1 | 2 | 4'),diff('return 3'),diff('return 0  # unchanged control')]
        verifier='import sys\nsys.path.insert(0,".")\nfrom solution import flags\nmask={"ordinary":1,"identity":2,"recovery":4}[sys.argv[1]]\nassert flags() & mask, sys.argv[1]\nprint("measured",sys.argv[1])\n'
        evaluation={'family':'authored-test-fixture','version':1,'kind':'clean',
                    'requirements':[{'id':'bits','text':'Preserve all three flags.'}],
                    'rubric':[{'id':name,'points':points,'checks':[name],'critical':name=='recovery'} for name,points in [('ordinary',25),('identity',25),('recovery',50)]],
                    'reference_patch_digest':digest(patches[0].encode()),'alternate_patch_digest':digest(patches[1].encode())}
        task={'title':'Quality test fixture','task_text':'Return all three flags.', 'source_files':{'solution.py':base},
              'verifier_files':{'check.py':verifier},'checks':[{'name':n,'argv':['{python}','{verifier}/check.py',n],'timeout':3} for n in ['ordinary','identity','recovery']],
              'patches':patches,'evaluation':evaluation,'provenance':{'origin':'synthetic_fixture','license':'MIT'}}
        self.catalog={'version':1,'origin':'synthetic_fixture','rubric':{'version':1},'tasks':{'flags':task}}
        self.write_catalog(self.fixtures,self.catalog)
        rows=[{'schema_version':1,'task_id':'flags','patch':p,'model_name_or_path':label} for p,label in zip(patches,['reference','alternate','partial','unchanged'])]
        rows.append({'schema_version':1,'task_id':'flags','patch':patches[0]+'\n','model_name_or_path':'unapproved'})
        rows.append(dict(rows[2],model_name_or_path='duplicate-delivery'))
        (self.fixtures/'sample.jsonl').write_bytes(b''.join(canonical(row)+b'\n' for row in rows))
        self.w=Workbench(self.root/'state',fixture_dir=self.fixtures);self.batch=self.w.import_sample('fixture')

    def write_catalog(self,path,catalog):
        path.mkdir(exist_ok=True);(path/'catalog.json').write_bytes(canonical(catalog))

    def run_checks(self):self.w.process(self.batch['id'])

    def review(self,decision='approved',findings=None,**changes):
        state=context(self.w,'flags')
        return review_task(self.w,'flags',decision=decision,reason='Explicit fixture adjudication.',findings=findings or [],expected_revision=state['revision'],operation_key='review-'+str(state['revision']),**changes)

    def test_integer_credit_critical_gate_and_missing_error_distinction(self):
        before=score_batch(self.w,self.batch['id'])
        self.assertTrue(all(i['score'] is None and not i['complete'] for i in before['items']))
        self.run_checks();view=score_batch(self.w,self.batch['id'])
        by_role={i['role']:i for i in view['items'] if i['role']!='candidate'}
        self.assertEqual(by_role['reference']['score'],100);self.assertEqual(by_role['alternate']['score'],100)
        partial=next(i for i in view['items'] if i['score']==50)
        self.assertEqual([c['earned'] for c in partial['criteria']],[25,25,0]);self.assertFalse(partial['critical_passed'])
        self.assertTrue(any(i['score']==0 and i['complete'] for i in view['items']))
        self.assertTrue(any(i['score'] is None and i['overall']=='not-run' for i in view['items']))
        raw=next(i for i in self.w.submissions(self.batch['id']) if i['id']==by_role['reference']['submission_id'])
        for mutation in ('error','integrity','missing-check'):
            item=copy.deepcopy(raw)
            if mutation=='error':item['execution_status']='execution-error';item['result']['overall']='error'
            elif mutation=='integrity':item['result']['verifier_integrity']['unchanged']=False
            else:item['result']['candidate']['checks'].pop()
            scored=score_item(view['context'],item)
            self.assertIsNone(scored['score']);self.assertFalse(scored['complete'])
        self.assertEqual(view['summary']['unique_submissions'],5)
        self.assertEqual(view['summary']['complete_scores'],4)
        self.assertTrue(self.w.verify()['ok'])

    def test_task_review_gates_findings_idempotency_and_atomic_rollback(self):
        with self.assertRaises(WorkbenchError) as caught:self.review()
        self.assertEqual(caught.exception.code,'task-ineligible')
        self.run_checks()
        finding={'id':'coverage','kind':'verifier-gap','severity':'high','status':'open','reason':'Fixture diagnostic.',
                 'assignee':'task-author','requested_correction':'Add the missing assertion.'}
        repair=self.review('needs-repair',[finding])
        for findings,code in [([],'invalid-findings'),([finding],'task-ineligible')]:
            with self.assertRaises(WorkbenchError) as caught:self.review(findings=findings)
            self.assertEqual(caught.exception.code,code)
        fixed=finding|{'status':'resolved','resolution':'fixture:revision-two'}
        request=dict(decision='approved',reason='Explicit passing reference/alternate evidence.',findings=[fixed],expected_revision=repair['revision'],operation_key='final')
        approved=review_task(self.w,'flags',**request)
        self.assertEqual(set(approved['quality']['qualification']),{'reference','alternate'})
        self.assertEqual(review_task(self.w,'flags',**request),approved)
        with self.assertRaises(WorkbenchError) as caught:review_task(self.w,'flags',**(request|{'operation_key':'stale'}))
        self.assertEqual(caught.exception.code,'stale-task-review')
        self.assertTrue(all(i['disposition']=='pending' for i in self.w.submissions(self.batch['id'])))
        original=self.w.store.event
        def fail_after_event(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('Injected transactional failure')
        with patch.object(self.w.store,'event',side_effect=fail_after_event):
            with self.assertRaises(RuntimeError):self.review('quarantined',[fixed])
        self.assertEqual(context(self.w,'flags'),approved)
        reloaded=Workbench(self.w.root,fixture_dir=self.fixtures);reloaded.initialize()
        self.assertEqual(context(reloaded,'flags'),approved)
        summary=score_batch(self.w,self.batch['id'])['summary']
        self.assertEqual(summary['task_reviews'],2);self.assertEqual(summary['repair_requests'],1)

    def test_separately_recorded_calibration_conflict_and_revision(self):
        state=context(self.w,'flags')
        reviews=[{'review_id':str(n),'actor':'fixture-ai-pass-'+str(n),'reviewer_mode':'ai_assisted_adjudication',
                  'decision':decision,'reason':'Synthetic unit-test review data.', 'input_digest':digest(b'fixture-input'),
                  'output_digest':digest(str(n).encode())} for n,decision in enumerate(['needs-repair','quarantined'])]
        args=dict(reviews=reviews,reason='Compare declared fixture decisions.',author_feedback='Author should add coverage.',guideline_update='Require explicit recovery assertions.',operation_key='calibration')
        result=record_calibration(self.w,'flags',**args)
        self.assertEqual(result['revision'],state['revision']+1)
        self.assertEqual(result['calibration'][0]['agreement']['matching_pairs'],0)
        self.assertEqual(result['calibration'][0]['agreement']['pairs'],1)
        self.assertEqual(record_calibration(self.w,'flags',**args),result)
        with self.assertRaises(WorkbenchError) as caught:record_calibration(self.w,'flags',**(args|{'reason':'changed'}))
        self.assertEqual(caught.exception.code,'operation-conflict')
        with self.assertRaises(WorkbenchError):record_calibration(self.w,'flags',**(args|{'reviews':[reviews[0],reviews[0]],'operation_key':'duplicate'}))

    def test_export_all_outcomes_samecut_challenge_and_historical_context(self):
        self.run_checks();approved=self.review()
        first=export_evaluation(self.w,self.batch['id'],self.root/'exports','first')
        path=Path(first['path']);original={p.name:p.read_bytes() for p in path.iterdir()}
        verified=verify_evaluation(path);self.assertTrue(verified['ok'],verified)
        self.assertEqual(verified['candidate_count'],5);self.assertEqual(verified['clean_task_count'],1)
        evaluation=json.loads((path/'evaluation.json').read_bytes())
        outcomes=evaluation['clean_tasks'][0]['items']
        self.assertTrue(any(i['score']==0 for i in outcomes));self.assertTrue(any(i['score'] is None for i in outcomes))
        again=export_evaluation(self.w,self.batch['id'],self.root/'exports','second')
        self.assertEqual(first['manifest_digest'],again['manifest_digest']);self.assertEqual(first['export_id'],again['export_id'])
        # Legacy accepted-code output remains empty until submission review.
        legacy=export_batch(self.w,self.batch['id'],self.root/'accepted','legacy')
        self.assertTrue(verify_export(legacy['path'])['ok']);self.assertEqual(legacy['metrics']['counts']['accepted'],0)
        changed=copy.deepcopy(self.catalog);changed['tasks']['flags']['evaluation']['kind']='audit_challenge';changed['tasks']['flags']['evaluation']['version']=2
        changed_path=self.root/'challenge';self.write_catalog(changed_path,changed)
        challenge=Workbench(self.w.root,fixture_dir=changed_path)
        initial=context(challenge,'flags');self.assertNotEqual(initial['id'],approved['id']);self.assertEqual(initial['quality']['decision'],'draft')
        self.assertGreater(initial['revision'],approved['revision'])
        with self.assertRaises(WorkbenchError) as caught:review_task(challenge,'flags',decision='quarantined',reason='Stale old-context request.',findings=[],expected_revision=approved['revision'],operation_key='stale-context')
        self.assertEqual(caught.exception.code,'stale-task-review')
        with self.assertRaises(WorkbenchError):review_task(challenge,'flags',decision='approved',reason='Forbidden challenge approval.',findings=[],expected_revision=initial['revision'],operation_key='challenge-accept')
        review_task(challenge,'flags',decision='quarantined',reason='Labeled fixture challenge.',findings=[],expected_revision=initial['revision'],operation_key='challenge-quarantine')
        archived=export_evaluation(challenge,self.batch['id'],self.root/'exports','challenge')
        self.assertEqual(archived['manifest']['clean_task_count'],0);self.assertEqual(archived['manifest']['audit_task_count'],1)
        self.assertTrue(verify_evaluation(archived['path'])['ok'])
        self.assertEqual({p.name:p.read_bytes() for p in path.iterdir()},original)
        self.assertTrue(verify_evaluation(path)['ok'])
        # A verifier change invalidates old machine scores, preserving artifacts.
        changed['tasks']['flags']['verifier_files']['check.py']+='\n# changed verifier context\n'
        self.write_catalog(changed_path,changed);new=Workbench(self.w.root,fixture_dir=changed_path)
        self.assertTrue(all(i['score'] is None for i in score_batch(new,self.batch['id'])['items']))

    def test_export_tampering_and_missing_artifact_refused(self):
        self.run_checks();self.review()
        published=export_evaluation(self.w,self.batch['id'],self.root/'exports','export')
        source=Path(published['path'])
        for mode in ('approval','rubric','score','raw','machine'):
            target=self.root/('tamper-'+mode);shutil.copytree(source,target)
            evidence=json.loads((target/'evidence.json').read_bytes())
            if mode=='approval':evidence['context']['quality']['decision']='quarantined'
            elif mode=='rubric':evidence['context']['rubric'][0]['points']=999
            elif mode=='score':evidence['scores']['items'][0]['score']=999
            elif mode=='raw':evidence['snapshot']['items'][0]['lineage'][0]['declared_source']='forged publisher'
            else:
                key=next(i['result']['evidence_digest'] for i in evidence['snapshot']['items'] if i['result'])
                evidence['artifacts'][key]=base64.b64encode(b'{}').decode()
            (target/'evidence.json').write_bytes(canonical(evidence)+b'\n')
            self.assertFalse(verify_evaluation(target)['ok'],mode)
        state=context(self.w,'flags');(self.w.store.artifacts/state['material_digest']).unlink()
        with self.assertRaises(WorkbenchError):export_evaluation(self.w,self.batch['id'],self.root/'exports','missing')

    def test_invalid_rubric_does_not_create_quality_state(self):
        for field,value in [('points',-1),('points',2.5),('points',True),('checks',['unknown'])]:
            with self.subTest(field=field,value=value):
                altered=copy.deepcopy(self.catalog);altered['tasks']['flags']['evaluation']['rubric'][0][field]=value
                self.write_catalog(self.fixtures,altered);w=Workbench(self.w.root,fixture_dir=self.fixtures)
                with self.assertRaises(WorkbenchError):context(w,'flags')
        with self.w.store.transaction(write=False) as con:self.assertEqual(con.execute('SELECT count(*) FROM meta').fetchone()[0],0)


if __name__=='__main__':unittest.main()
