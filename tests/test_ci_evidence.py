"""Owned source/status fixtures; XML/status fixtures are explicitly authored."""
import copy,json,sys,unittest
from pathlib import Path
from tests.test_handoff_context import ContextTests
from swe_workbench import ci_evidence as ci, handoff
from swe_workbench.junit_report import import_report
from swe_workbench.project_context import configure
from swe_workbench.review_package import assemble
from swe_workbench.reported_checks import extract
from swe_workbench.errors import WorkbenchError
from swe_workbench.store import canonical,digest

class CITests(unittest.TestCase):
    setUp=ContextTests.setUp;git=ContextTests.git;write_proof=ContextTests.write_proof
    def create(self,code=0,xml='<testsuite tests="1"><testcase name="Authored case"/></testsuite>',env=None):
        out=self.p/('run-'+str(len(list(self.p.glob('run-*')))))
        ci.begin(self.repo,out,'example/source',[sys.executable,'-m','pytest','test.py','--junitxml=../result.xml'],['value.py'],env or {})
        if xml is not None:(out/'original.xml').write_text(xml)
        r=ci.finish(out,code);return out,r
    def test_source_changes_and_provider_separation(self):
        env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'example/workflow','GITHUB_WORKFLOW_SHA':'a'*40,'GITHUB_WORKFLOW_REF':'example/workflow/.github/workflows/check.yml@refs/heads/main','GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'2','GITHUB_JOB':'check','GITHUB_EVENT_NAME':'pull_request','GITHUB_SHA':'b'*40,'WB_PR_HEAD':'c'*40,'WB_PR_BASE':'d'*40}
        out,r=self.create(env=env);self.assertEqual(r['tested_revision'],self.candidate);self.assertEqual(r['provider']['workflow_revision'],'a'*40);self.assertEqual(r['provider']['proposed_head'],'c'*40);self.assertEqual(r['source_state'],'clean')
        changed=self.p/'changed';ci.begin(self.repo,changed,'example/source',['pytest'],['value.py'],{})
        (self.repo/'ignored.txt').write_text('untracked input');r=ci.finish(changed,3);self.assertEqual(r['source_state'],'dirty');self.assertEqual(r['report_status'],'missing')
        (self.repo/'ignored.txt').unlink()
        head=self.p/'head';ci.begin(self.repo,head,'example/source',['pytest'],['value.py'],{});self.git('checkout','-q',self.base);self.assertEqual(ci.finish(head,2)['source_state'],'dirty')
    def test_input_changes_and_incomplete_reports(self):
        out=self.p/'inputs';ci.begin(self.repo,out,'example/source',['pytest'],['value.py'],{});(self.repo/'value.py').write_text('mutated');self.assertEqual(ci.finish(out,4)['source_state'],'dirty')
        for code,outcome,xml,status in [(5,'no-tests','<testsuite/>','parsed'),(2,'interrupted','<testsuite>','invalid'),(3,'internal-error',None,'missing'),(4,'usage-error',None,'missing'),(137,'terminated',None,'missing')]:
            o,r=self.create(code,xml);self.assertEqual(r['process_outcome'],outcome);self.assertEqual(r['report_status'],status)
    def test_crosslinks_and_package_resume(self):
        out,r=self.create(1,'<testsuite tests="1" failures="1"><testcase name="Authored failure"><failure message="Expected probe"/></testcase></testsuite>')
        params=dict(context=out/'run-context.json',ci_receipt=out/'ci-receipt.json',check_definition=out/'check-definition.json')
        imported=self.p/'imported';import_report(out/'original.xml',imported,**params)
        profile=json.loads((imported/'profile.json').read_text());profile['repository']='example/source';(imported/'profile.json').write_bytes(canonical(profile)+b'\n')
        context=self.p/'context.json';configure(context,repo=str(self.repo),profile=str(imported/'profile.json'),evidence_directory=str(imported),state=str(self.root),base_ref=self.base,candidate_ref=self.candidate)
        package=self.p/'package';result=assemble(context,package,change_id='ci',title='Authored failure case',goal='Inspect failure',report=out/'original.xml',run_context=params['context'],ci_receipt=params['ci_receipt'],check_definition=params['check_definition'])
        self.assertEqual(result['stage'],'complete');self.assertEqual(assemble(context,package,resume=True),result);self.assertTrue(handoff.verify(package/'export')['ok'])
        record=handoff.read(self.root,'ci');report=record['material']['reported_checks'][0];self.assertEqual(report['ci']['exit_code'],1);self.assertTrue(report['ci']['problems']);self.assertIsNone(report['ci']['provider']);self.assertEqual(record['state']['decision'],'unreviewed')
        self.assertIn('Process: 1',json.loads((package/'summary.json').read_text())['summary'])
        material=copy.deepcopy(record['material']);ci_attachment=next(a for a in material['attachments'] if a['name']=='ci-receipt.json');bad=json.loads(ci_attachment['text']);bad['report_sha256']='0'*64;ci_attachment['text']=json.dumps(bad);ci_attachment['sha256']=digest(ci_attachment['text'].encode());projection=next(a for a in material['attachments'] if a['name']=='report.json');data=json.loads(projection['text']);data['ci_receipt_sha256']=ci_attachment['sha256'];projection['text']=json.dumps(data)
        self.assertEqual(extract(material)[0]['status'],'invalid-supported-report')
        for key in ('report_sha256','context_sha256','definition_sha256'):
            bad=r|{key:'0'*64}
            with self.assertRaisesRegex(WorkbenchError,'hash mismatch'):ci.validate(canonical(bad),(out/'original.xml').read_bytes(),(out/'run-context.json').read_bytes(),(out/'check-definition.json').read_bytes())
    def test_conflicts_safe_links_and_no_overwrite(self):
        out,r=self.create(0,'<testsuite><testcase name="Authored failure"><failure/></testcase></testsuite>');validated=ci.validate((out/'ci-receipt.json').read_bytes(),(out/'original.xml').read_bytes(),(out/'run-context.json').read_bytes(),(out/'check-definition.json').read_bytes());self.assertIn('conflicts',validated['problems'][0])
        with self.assertRaisesRegex(WorkbenchError,'already finalized'):ci.finish(out,0)
        with self.assertRaises(WorkbenchError):ci.begin(self.repo,self.repo/'output','example/source',['pytest'],[],{})
        with self.assertRaises(WorkbenchError):ci.repository('evil.example/../x')
        bad=r|{'tested_revision':self.base}
        with self.assertRaisesRegex(WorkbenchError,'conflicting observed source'):ci.validate(canonical(bad),(out/'original.xml').read_bytes(),(out/'run-context.json').read_bytes(),(out/'check-definition.json').read_bytes())

del ContextTests
