import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from swe_workbench.core import Workbench
from swe_workbench.errors import WorkbenchError
from swe_workbench.runner import _claim, _execute, commit_result, recover, owned_state
from swe_workbench.store import canonical,now


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]);self.addCleanup(self.tmp.cleanup)
        self.w=Workbench(Path(self.tmp.name)/'state');self.w.initialize();self.batch=self.w.import_sample('sample')

    def claim(self):
        with self.w.store.transaction() as con:
            if not con.execute("SELECT 1 FROM runs WHERE id='test-run'").fetchone():
                con.execute('INSERT INTO runs VALUES(?,?,?,?,?,?)',('test-run',self.batch['id'],'running','{}',1,now()))
            return _claim(self.w,con,self.batch['id'],'test-run')

    def test_real_controller_kill_recovery_and_retained_result(self):
        code='from swe_workbench.core import Workbench; import sys; w=Workbench(sys.argv[1]);w.initialize();w.process(sys.argv[2])'
        child=subprocess.Popen([sys.executable,'-c',code,str(self.w.root),self.batch['id']],cwd=Path(__file__).resolve().parents[1],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        deadline=time.monotonic()+10
        previous={};active=None
        while time.monotonic()<deadline:
            with self.w.store.transaction(write=False) as con:
                previous={r['id']:json.loads(r['result']) for r in con.execute('SELECT id,result FROM submissions WHERE result IS NOT NULL')}
                active=con.execute("SELECT * FROM attempts WHERE state='registered' ORDER BY created_at DESC LIMIT 1").fetchone()
            if previous and active:
                break
            if child.poll() is not None:
                self.fail('Controller finished before kill boundary: '+child.stderr.read().decode())
            time.sleep(.002)
        self.assertTrue(previous)
        self.assertIsNotNone(active)
        # SIGKILL the actual separate controller, not a simulated exception.
        child.kill();child.wait(timeout=3);child.stderr.close()
        identity=json.loads(active['identity'])
        deadline=time.monotonic()+3
        while owned_state(identity)!='stopped' and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(owned_state(identity),'stopped')
        restarted=Workbench(self.w.root);restarted.initialize();report=restarted.process(self.batch['id'])
        self.assertEqual(report['processed'],4-len(previous))
        self.assertEqual(report['run_id'],active['run_id'])
        for sid,result in previous.items():self.assertEqual(restarted.submission(sid)['result'],result)
        events=restarted.audit_events()
        commits=[e['payload']['submission_id'] for e in events if e['kind']=='result-committed']
        self.assertEqual(len(commits),4)
        self.assertEqual(len(set(commits)),4)
        self.assertTrue(any(e['kind']=='attempt-recovered' for e in events))
        segments=restarted.snapshot(self.batch['id'])['timing_segments']
        self.assertEqual(sum(not s['complete'] for s in segments),1)
        self.assertTrue(restarted.verify()['ok'])

    def test_unregistered_launch_crash_does_not_dispatch(self):
        # Inject registration transaction failure after worker launch. G is never
        # sent; channel EOF makes the real child exit without workspace checks.
        claim=self.claim()
        with patch('swe_workbench.runner.process_identity',side_effect=WorkbenchError('test-registration','Injected registration failure',409)):
            with self.assertRaises(WorkbenchError):_execute(self.w,claim)
        attempt_dir=self.w.root/'attempts'/claim['attempt_id']
        self.assertFalse((attempt_dir/'result.json').exists())
        self.assertFalse((attempt_dir/'workspace').exists())
        recover(self.w)
        self.assertEqual(self.w.submission(claim['submission_id'])['execution_status'],'queued')

    def test_generation_fence_and_lost_acknowledgement(self):
        old=self.claim();recover(self.w);new=self.claim()
        self.assertEqual(new['submission_id'],old['submission_id'])
        self.assertGreater(new['generation'],old['generation'])
        outcome=_execute(self.w,new)
        with self.assertRaises(WorkbenchError) as caught:commit_result(self.w,old,outcome)
        self.assertEqual(caught.exception.code,'stale-result')
        forged=json.loads(canonical(outcome))
        forged['result']['generation']=old['generation']
        with self.assertRaises(WorkbenchError) as caught:commit_result(self.w,new,forged)
        self.assertEqual(caught.exception.code,'stale-result')
        self.assertTrue(commit_result(self.w,new,outcome))
        before=self.w.submission(new['submission_id'])
        events=len(self.w.audit_events())
        self.assertFalse(commit_result(self.w,new,outcome))
        self.assertEqual(self.w.submission(new['submission_id']),before)
        self.assertEqual(len(self.w.audit_events()),events)
        with self.assertRaises(WorkbenchError):commit_result(self.w,old,outcome)
        self.assertEqual(self.w.submission(new['submission_id']),before)

    def test_unknown_child_remains_uncertain_and_unrelated_process_survives(self):
        unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'],start_new_session=True)
        self.addCleanup(lambda:(unrelated.terminate(),unrelated.wait(timeout=3)) if unrelated.poll() is None else None)
        claim=self.claim()
        with self.w.store.transaction() as con:
            con.execute("UPDATE attempts SET state='registered',identity=? WHERE id=?",(canonical({'pid':-1,'pgid':-1,'start_ticks':'unknown'}).decode(),claim['attempt_id']))
        with self.assertRaises(WorkbenchError) as caught:self.w.process(self.batch['id'])
        self.assertEqual(caught.exception.code,'unresolved-execution')
        self.assertEqual(self.w.submission(claim['submission_id'])['execution_status'],'uncertain')
        self.assertIsNone(unrelated.poll())
        self.assertEqual(self.w.batch(self.batch['id'])['counts']['completed'],0)


if __name__=='__main__':unittest.main()
