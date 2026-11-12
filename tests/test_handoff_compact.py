import copy,json,os,unittest
from pathlib import Path
from tests.test_handoff_context import ContextTests
from swe_workbench import handoff
from swe_workbench.handoff_compact import V3,refs
from swe_workbench.state_backup import backup,restore
from swe_workbench.errors import WorkbenchError

class CompactTests(unittest.TestCase):
    setUp=ContextTests.setUp;git=ContextTests.git;write_proof=ContextTests.write_proof
    request=ContextTests.request;capture=ContextTests.capture;review=ContextTests.review
    def test_mixed_modes_source_reuse_restore_and_corruption(self):
        (self.repo/'tool.sh').write_text('echo inert\n');os.chmod(self.repo/'tool.sh',0o755)
        (self.repo/'image.bin').write_bytes(b'\x00\xff');(self.repo/'link').symlink_to('/never/read/this')
        (self.repo/'empty.txt').write_bytes(b'')
        self.git('add','.');self.git('update-index','--add','--cacheinfo','160000,'+self.candidate+',component');self.git('commit','-qm','Mixed source data');self.candidate=self.git('rev-parse','HEAD').strip();self.data['source']=self.candidate;self.write_proof()
        req=self.request();req['schema']=V3
        preview=handoff.inspect(self.root,repo=self.repo,base=self.base,candidate=self.candidate,request=req,evidence={'proof.json':self.proof});self.assertFalse(self.root.exists())
        first=self.capture(req);record=handoff.read(self.root,'change');m=record['material'];keys=refs(m)
        self.assertEqual(m['coverage']['metadata_only_paths'],['component','image.bin','link']);self.assertIn('tool.sh',m['coverage']['text_paths']);self.assertEqual(preview,m)
        self.review(first);self.data['check']=True;self.write_proof();second=self.capture(req);self.assertEqual(refs(handoff.read(self.root,'change')['material']),keys)
        self.review(second,'second');result=handoff.export(self.root,'change',self.p/'export');self.assertTrue(result['ok'])
        backup(self.root,self.p/'backup');restore(self.p/'backup',self.p/'restored');self.assertTrue(handoff.export(self.p/'restored','change',self.p/'restored-export')['ok'])
        key=next(iter(keys));(self.root/'artifacts'/key).write_bytes(b'corrupt')
        with self.assertRaises(WorkbenchError):handoff.read(self.root,'change')
        self.assertEqual((self.repo/'tool.sh').read_text(),'echo inert\n');self.assertTrue((self.repo/'link').is_symlink())
    def test_mixed_legacy_history_and_mode_only(self):
        old=self.capture();self.review(old);self.base=self.candidate;os.chmod(self.repo/'value.py',0o755);self.git('add','.');self.git('commit','-qm','Mode only');self.candidate=self.git('rev-parse','HEAD').strip();self.data['source']=self.candidate;self.write_proof()
        req=self.request();req['schema']=V3;s=self.capture(req);self.review(s,'mode')
        r=handoff.read(self.root,'change');self.assertEqual(r['schema'],V3);self.assertIn('new mode 100755',r['material']['patch']);self.assertTrue(handoff.export(self.root,'change',self.p/'out')['ok'])
del ContextTests
