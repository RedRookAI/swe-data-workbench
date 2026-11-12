import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from swe_workbench import handoff
from swe_workbench.errors import WorkbenchError
from swe_workbench.store import Store

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.p=Path(self.temp.name)
        self.repo=self.p/'source';self.repo.mkdir();self.root=self.p/'state'
        self.git('init','-q');self.git('config','user.email','example@invalid.local');self.git('config','user.name','Fixture')
        (self.repo/'value.py').write_text('value = 1\n');self.git('add','.');self.git('commit','-qm','base');self.base=self.git('rev-parse','HEAD').strip()
        (self.repo/'value.py').write_text('value = 2\n');self.git('commit','-qam','fix');self.candidate=self.git('rev-parse','HEAD').strip()
        self.proof=self.p/'proof.json';self.proof.write_bytes((json.dumps({'source':self.candidate,'check':{'passed':True,'command':'touch DO_NOT_RUN'}})+'\r\n').encode())
        self.request={'change_id':'real-fix','title':'Fix value','goal':'Use value2','repository':'public-example','observations':[{'label':'Existing CI','attachment':'proof.json','field_path':['check'],'context_path':['source'],'scope':'Reported one check','required':True}]}
    def git(self,*args):return subprocess.check_output(['git','-c','core.hooksPath=/dev/null','-C',str(self.repo),*args],text=True,stderr=subprocess.PIPE)
    def capture(self,key='capture',request=None):return handoff.capture(self.root,repo=self.repo,base=self.base,candidate=self.candidate,request=request or self.request,evidence={'proof.json':self.proof},operation_key=key)
    def review(self,state,**updates):
        return handoff.review(self.root,'real-fix',expected_revision=state['revision'],material_digest=state['material_digest'],decision='handoff-ready',reason='Reviewed external scope',findings=['External assertions remain unsigned'],next_action='Owner reviews delivery',operation_key='review-'+str(state['revision']),**updates)
    def test_capture_is_read_only_exact_and_idempotent(self):
        (self.repo/'value.py').write_text('uncommitted work stays\n');before=self.git('status','--porcelain');s=self.capture();r=handoff.read(self.root,'real-fix')
        self.assertEqual(r['material']['files'][0]['after']['text'],'value = 2\n');self.assertEqual(r['material']['attachments'][0]['text'].encode(),self.proof.read_bytes())
        self.assertFalse((self.repo/'DO_NOT_RUN').exists());self.assertEqual(before,self.git('status','--porcelain'))
        self.assertEqual(s,self.capture());self.assertEqual(s,self.capture('new-capture'));self.assertEqual(len(r['events']),1)
        self.assertEqual(r['material']['observations'][0]['origin'],'externally-reported')
        con=Store(self.root).connect();self.addCleanup(con.close);self.assertEqual(con.execute('SELECT count(*) FROM submissions').fetchone()[0],0)
    def test_review_binds_revision_and_material_then_preserves_history(self):
        first=self.capture();approved=self.review(first)
        changed=copy.deepcopy(self.request);changed['goal']='A revised requirement';new=self.capture('capture-v2',changed)
        self.assertEqual(new['decision'],'unreviewed');self.assertGreater(new['revision'],approved['revision'])
        self.assertEqual(self.review(first), approved, 'Identical operation retry retains its original response')
        self.assertEqual(handoff.read(self.root,'real-fix')['state'], new)
        result=handoff.export(self.root,'real-fix',self.p/'history')
        self.assertTrue(result['ok'])
        self.assertEqual(len(handoff.read(self.root,'real-fix')['events']),3)
    def test_stale_context_and_unbound_claim_are_refused(self):
        first=self.capture();old=copy.deepcopy(self.request);old['goal']='changed';self.capture('new',old)
        with self.assertRaises(WorkbenchError) as cm:
            handoff.review(self.root,'real-fix',expected_revision=first['revision'],material_digest=first['material_digest'],decision='handoff-ready',reason='old',findings=[],next_action='old',operation_key='distinct-stale')
        self.assertEqual(cm.exception.code,'stale-handoff')
        self.proof.write_text(json.dumps({'source':self.base,'check':{'passed':True}}));current=self.capture('different-evidence')
        with self.assertRaises(WorkbenchError) as cm:self.review(current)
        self.assertEqual(cm.exception.code,'handoff-unresolved')
    def test_export_fresh_process_roundtrip_tamper_and_no_private_neighbors(self):
        s=self.capture();self.review(s);store=Store(self.root)
        with store.transaction() as con:store.event(con,'unrelated-private',{'secret':'MUST_NOT_EXPORT'})
        a=handoff.export(self.root,'real-fix',self.p/'export');b=handoff.export(self.root,'real-fix',self.p/'export2')
        self.assertTrue(a['ok']);self.assertEqual(a['manifest_digest'],b['manifest_digest']);self.assertNotIn('MUST_NOT_EXPORT',(self.p/'export/handoff.json').read_text())
        r=subprocess.check_output([os.sys.executable,'-m','swe_workbench.cli','verify-handoff',str(self.p/'export')],text=True);self.assertTrue(json.loads(r)['ok'])
        with (self.p/'export/handoff.json').open('ab') as f:f.write(b' ')
        self.assertFalse(handoff.verify(self.p/'export')['ok'])
        self.assertEqual(handoff.read(self.root,'real-fix')['state']['decision'],'handoff-ready')
    def test_overlap_duplicate_json_unsupported_mode_and_missing_field(self):
        with self.assertRaises(WorkbenchError):handoff.capture(self.repo/'state',repo=self.repo,base=self.base,candidate=self.candidate,request=self.request,evidence={},operation_key='bad')
        with self.assertRaises(WorkbenchError):handoff.parse('{"source":1,"source":2}')
        self.proof.write_text(json.dumps({'source':self.candidate}));s=self.capture()
        with self.assertRaises(WorkbenchError):self.review(s)
        self.git('update-index','--chmod=+x','value.py');self.git('commit','-qm','executable');self.candidate=self.git('rev-parse','HEAD').strip()
        with self.assertRaises(WorkbenchError):self.capture('executable')
    def test_external_handoff_cannot_relabel_itself_as_native_execution(self):
        self.capture();handoff.export(self.root,'real-fix',self.p/'export')
        record=json.loads((self.p/'export/handoff.json').read_text());encoded=json.loads((self.p/'export/artifacts.json').read_text())
        for key in ('workbench_executions','keep_mutations'):
            changed=copy.deepcopy(record);changed[key]=1
            with self.assertRaises(WorkbenchError):handoff._validate_package(changed,encoded)

if __name__=='__main__':unittest.main()
