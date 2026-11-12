import json,subprocess,sys,unittest
from tests.test_handoff_context import ContextTests
from swe_workbench import handoff
from swe_workbench.check_receipt import make,validate,write
from swe_workbench.errors import WorkbenchError

class ReuseTests(unittest.TestCase):
    setUp=ContextTests.setUp;git=ContextTests.git;write_proof=ContextTests.write_proof
    request=ContextTests.request;capture=ContextTests.capture;review=ContextTests.review
    def test_preview_no_state_same_material_and_changed_inputs(self):
        profile=self.p/'profile.json';profile.write_text(json.dumps(self.profile))
        args=[sys.executable,'-m','swe_workbench.cli','--root',str(self.root),'preview-handoff','--repo',str(self.repo),'--base',self.base,'--candidate',self.candidate,'--profile',str(profile),'--change-id','change','--title','Change value','--goal','Use value2','--evidence-dir',str(self.p)]
        before={p.relative_to(self.repo):p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        preview=json.loads(subprocess.check_output(args,text=True));self.assertFalse(self.root.exists());self.assertEqual(preview['runtime_writes'],0)
        self.assertEqual(before,{p.relative_to(self.repo):p.read_bytes() for p in self.repo.rglob('*') if p.is_file()})
        first=self.capture();self.assertEqual(first['material_digest'],preview['material_digest'])
        self.data.pop('source');self.write_proof();unknown=json.loads(subprocess.check_output(args,text=True));self.assertFalse(unknown['required_bindings_complete']);self.assertNotEqual(first['material_digest'],unknown['material_digest'])
        self.assertEqual(handoff.read(self.root,'change')['state'],first)
    def facts(self,outcome='passed',code=0):
        return {'source':{'revision':self.candidate,'worktree':'clean'},'checks':{'value':{'definition_sha256':'a'*64,'inputs':{'source':'b'*64},'outcome':outcome,'exit_code':code,'outputs':{}}}}
    def test_receipt_outcomes_binding_and_exact_capture(self):
        for outcome,code in [('passed',0),('failed',1),('skipped',None),('unavailable',None)]:
            facts=self.facts(outcome,code);receipt=make(facts);self.assertEqual(receipt['checks']['value']['outcome'],outcome);validate(receipt)
        facts=self.facts();facts['source']['worktree']='dirty';self.assertIsNone(make(facts)['execution_revision'])
        facts['source']['revision']=None;self.assertIsNone(make(facts)['execution_revision'])
        with self.assertRaisesRegex(WorkbenchError,'exit_code'):make(self.facts('passed',None))
        report=self.p/'receipt.json';write(self.facts(),report);original=report.read_bytes()
        p=self.profile|{'attachments':['receipt.json'],'observations':[{'label':'Value result','attachment':'receipt.json','field_path':['checks','value','outcome'],'context_path':['execution_revision'],'scope':'One external check','required':True}]}
        from swe_workbench.handoff_profile import expand
        request=expand(p,change_id='change',title='Change value',goal='Use value2')
        state=handoff.capture(self.root,repo=self.repo,base=self.base,candidate=self.candidate,request=request,evidence={'receipt.json':report});self.review(state);handoff.export(self.root,'change',self.p/'out')
        self.assertEqual(handoff.read(self.root,'change')['material']['attachments'][0]['text'].encode(),original)
        with self.assertRaises(WorkbenchError):write(self.facts(),report)
        self.assertEqual(report.read_bytes(),original)
del ContextTests
