import copy,json,unittest
from tests.test_handoff_context import ContextTests
from swe_workbench import handoff
from swe_workbench.exact_json import decode,encode,meaning
from swe_workbench.state_backup import backup,restore
from swe_workbench.errors import WorkbenchError

class ExactTests(unittest.TestCase):
    setUp=ContextTests.setUp;git=ContextTests.git;write_proof=ContextTests.write_proof
    request=ContextTests.request;capture=ContextTests.capture;review=ContextTests.review
    def test_source_precision_history_restore_and_tamper(self):
        old=self.capture();self.review(old);handoff.export(self.root,'change',self.p/'old')
        raw='{"source":"'+self.candidate+'","check":{"near":0.95000000000000001,"tiny":1e-400,"large":9007199254740993,"text":"0.95","bool":false,"zero":0,"signed":-0.0}}'
        self.proof.write_text(raw);request=self.request();request['schema']=handoff.V4;s=self.capture(request);m=handoff.read(self.root,'change')['material'];tree=m['observations'][0]['value'];members=tree['members']
        self.assertEqual(members['near'],{'type':'number','token':'0.95000000000000001'});self.assertEqual(members['tiny']['token'],'1e-400');self.assertEqual(members['text']['type'],'string');self.assertEqual(members['bool']['type'],'boolean')
        self.review(s,'exact');self.assertTrue(handoff.export(self.root,'change',self.p/'new')['ok']);backup(self.root,self.p/'backup');restore(self.p/'backup',self.p/'restored');self.assertTrue(handoff.export(self.p/'restored','change',self.p/'restored-export')['ok']);self.assertTrue(handoff.verify(self.p/'old')['ok'])
        forged=copy.deepcopy(m);forged['observations'][0]['value']['members']['near']['token']='0.95'
        from swe_workbench.store import Store
        with self.assertRaises(WorkbenchError):handoff.validate_material(forged,Store(self.root).artifact_bytes)
    def test_exact_semantics_and_limits(self):
        self.assertEqual(meaning('1e-7'),meaning('0.0000001'));self.assertNotEqual(meaning('1e-400'),meaning('0.0'));self.assertNotEqual(meaning('-0.0'),meaning('0.0'));self.assertNotEqual(meaning('9007199254740992'),meaning('9007199254740993'))
        self.assertEqual(encode(decode('{"type":"number","token":"0.95"}'))['type'],'object')
        for raw in ('NaN','{"x":1,"x":2}','1' * 4301):
            with self.assertRaises(WorkbenchError):decode(raw)
del ContextTests
