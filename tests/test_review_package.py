import json,unittest
from unittest.mock import patch
from tests.test_handoff_context import ContextTests
from swe_workbench.junit_report import import_report
from swe_workbench.project_context import configure,collect
from swe_workbench.review_package import assemble
from swe_workbench import handoff
from swe_workbench.errors import WorkbenchError

class PackageTests(unittest.TestCase):
    setUp=ContextTests.setUp;git=ContextTests.git;write_proof=ContextTests.write_proof
    def inputs(self):
        xml=self.p/'report.xml';xml.write_text('<testsuite tests="1"><testcase name="Authored fixture" time="0.95000000000000001"/></testsuite>');run=self.p/'run.json';run.write_text(json.dumps({'source_revision':self.candidate,'source_state':'clean'}));import_report(xml,self.p/'imported',run)
        context=self.p/'context.json';configure(context,repo=str(self.repo),profile=str(self.p/'imported/profile.json'),evidence_directory=str(self.p/'imported'),state=str(self.root),base_ref=self.base,candidate_ref=self.candidate)
        return context,dict(change_id='actual',title='Selected authored fixture',goal='Inspect existing report',report=xml,run_context=run)
    def test_package_resume_and_no_new_review(self):
        context,args=self.inputs();output=self.p/'package'
        with patch('swe_workbench.review_package.build',side_effect=WorkbenchError('injected','Owned view failure')):
            with self.assertRaisesRegex(WorkbenchError,'incomplete at captured'):assemble(context,output,**args)
        receipt=json.loads((output/'receipt.json').read_text());self.assertTrue(receipt['error']['durable_capture']);state=handoff.read(self.root,'actual')['state'];self.assertEqual(state['decision'],'unreviewed')
        result=assemble(context,output,resume=True);self.assertEqual(result['stage'],'complete');self.assertEqual(handoff.read(self.root,'actual')['state'],state);self.assertEqual(assemble(context,output,resume=True),result)
        second=assemble(context,self.p/'second',**(args|{'change_id':'second'}));self.assertEqual(second['stage'],'complete');self.assertEqual(result['context_sha256'],second['context_sha256'])
    def test_preflight_and_stale_resume(self):
        context,args=self.inputs()
        with self.assertRaises(WorkbenchError):assemble(context,self.repo/'inside',**args)
        self.assertFalse(self.root.exists())
        output=self.p/'failed'
        with patch('swe_workbench.review_package.build',side_effect=WorkbenchError('injected','Owned view failure')):
            with self.assertRaises(WorkbenchError):assemble(context,output,**args)
        self.data['check']=True;self.write_proof()
        # An explicit later change at the same ID makes the saved package selection stale.
        profile=json.loads((self.p/'imported/profile.json').read_text());profile['observations'][0]['scope']='Changed scope';(self.p/'imported/profile.json').write_text(json.dumps(profile));collect(context,change_id='actual',title='Later',goal='Later')
        with self.assertRaisesRegex(WorkbenchError,'incomplete'):assemble(context,output,resume=True)
        self.assertEqual(json.loads((output/'receipt.json').read_text())['selection']['revision'],0)
del ContextTests
