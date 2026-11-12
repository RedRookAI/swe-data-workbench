import json,shutil,unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_handoff_context import ContextTests
from swe_workbench import handoff
from swe_workbench.state_backup import backup,restore
from swe_workbench.store import Store
from swe_workbench.errors import WorkbenchError

class BackupTests(unittest.TestCase):
    setUp=ContextTests.setUp;git=ContextTests.git;write_proof=ContextTests.write_proof
    request=ContextTests.request;capture=ContextTests.capture;review=ContextTests.review
    def test_restore_continue_and_retry(self):
        state=self.capture(key='capture-original');reviewed=self.review(state)
        saved=backup(self.root,self.p/'saved');restore(self.p/'saved',self.p/'restored')
        self.assertEqual(handoff.read(self.p/'restored','change')['state'],reviewed)
        retry=handoff.capture(self.p/'restored',repo=self.repo,base=self.base,candidate=self.candidate,request=self.request(),evidence={'proof.json':self.proof},operation_key='capture-original');self.assertEqual(retry,state)
        updated=handoff.review(self.p/'restored','change',expected_revision=reviewed['revision'],material_digest=reviewed['material_digest'],decision='needs-work',reason='Continue after restore',findings=[],next_action='Owner checks',operation_key='after-restore')
        self.assertEqual(updated['revision'],reviewed['revision']+1);self.assertTrue(handoff.export(self.p/'restored','change',self.p/'export')['ok'])
        self.assertEqual(saved['audit_root'],backup(self.root,self.p/'again')['audit_root'])
    def test_bad_destination_corruption_and_active_refusal(self):
        self.capture();backup(self.root,self.p/'saved')
        for target in [self.root,self.root/'inside',self.p/'saved']:
            with self.assertRaises(WorkbenchError):backup(self.root,target)
        (self.p/'link').symlink_to(self.p/'saved',target_is_directory=True)
        with self.assertRaises(WorkbenchError):restore(self.p/'saved',self.p/'link')
        artifact=next((self.p/'saved/artifacts').iterdir());artifact.write_bytes(b'broken')
        with self.assertRaises(WorkbenchError):restore(self.p/'saved',self.p/'failed')
        self.assertFalse((self.p/'failed').exists())
        store=Store(self.root)
        with store.transaction() as con:
            con.execute("INSERT INTO batches VALUES('b','x','now')");con.execute("INSERT INTO runs VALUES('r','b','running','{}',1,'now')")
        with self.assertRaisesRegex(WorkbenchError,'active or uncertain'):backup(self.root,self.p/'active')
        self.assertFalse((self.p/'active').exists())
    def test_consistent_cut_with_later_metadata_write(self):
        self.capture();store=Store(self.root);real_copy=shutil.copyfile;written=[]
        def copy(*args,**kwargs):
            if not written:
                with store.transaction() as con:
                    con.execute("INSERT INTO meta VALUES('later','new')");store.event(con,'later-test',{'note':'After SQLite snapshot'})
                written.append(True)
            return real_copy(*args,**kwargs)
        with patch('swe_workbench.state_backup.shutil.copyfile',side_effect=copy):backup(self.root,self.p/'saved')
        restore(self.p/'saved',self.p/'restored')
        with Store(self.p/'restored').transaction(write=False) as con:self.assertIsNone(con.execute("SELECT value FROM meta WHERE key='later'").fetchone())
        with store.transaction(write=False) as con:self.assertEqual(con.execute("SELECT value FROM meta WHERE key='later'").fetchone()[0],'new')
    def test_malformed_audit_payload_refuses(self):
        from swe_workbench.store import canonical,digest
        self.capture();store=Store(self.root)
        with store.transaction() as con:store.event(con,'malformed-test',None)
        with self.assertRaisesRegex(WorkbenchError,'backup.audit.payload'):backup(self.root,self.p/'invalid-audit')
        self.assertFalse((self.p/'invalid-audit').exists())
    def test_completed_native_history_preserved(self):
        source=Path(__file__).resolve().parents[1]/'.state/recorded-demo'
        if not source.exists():self.skipTest('Existing private native recording unavailable; covered by release qualification when present')
        result=backup(source,self.p/'native');restore(self.p/'native',self.p/'native-restored')
        with Store(self.p/'native-restored').transaction(write=False) as con:
            self.assertGreater(con.execute('SELECT count(*) FROM submissions WHERE result IS NOT NULL').fetchone()[0],0)
            self.assertEqual(Store(self.p/'native-restored').verify_audit(con),result['audit_root'])
del ContextTests
