import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from swe_workbench.core import Workbench
from swe_workbench.errors import WorkbenchError
from swe_workbench.runner import controller_lock, _claim, _execute, commit_result
from swe_workbench.store import canonical


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]);self.addCleanup(self.tmp.cleanup)
        self.w=Workbench(Path(self.tmp.name)/'state');self.w.initialize();self.batch=self.w.import_sample('sample')

    def test_real_baseline_candidate_concurrency_and_exact_allowlist(self):
        original=(self.w.fixture_dir/'catalog.json').read_bytes()
        report=self.w.process(self.batch['id'],workers=2)
        self.assertEqual(report['processed'],4)
        self.assertEqual(report['observed_max_workers'],2)
        items={i['fixture_label']:i for i in self.w.submissions(self.batch['id'])}
        for label in ('good','weak-check-wrong','same-patch-different-context'):
            result=items[label]['result']
            self.assertEqual(result['baseline']['overall'],'failed')
            self.assertEqual(result['candidate']['overall'],'passed')
            self.assertEqual(result['overall'],'passed')
            self.assertTrue(result['source_unchanged'])
            self.assertEqual(result['submission_id'],items[label]['id'])
            self.assertEqual(json.loads(self.w.artifact_bytes(result['evidence_digest'])),{k:v for k,v in result.items() if k!='evidence_digest'})
        self.assertEqual(items['failing']['result']['overall'],'failed')
        for label in ('missing-evidence','unsupported-tuple'):
            self.assertIsNone(items[label]['result'])
            self.assertEqual(items[label]['execution_status'],'pending-evidence')
        self.assertEqual((self.w.fixture_dir/'catalog.json').read_bytes(),original)
        self.assertEqual(len(list((self.w.root/'attempts').iterdir())),4)
        with self.w.store.transaction(write=False) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM attempts').fetchone()[0],4)
        self.assertTrue(self.w.verify()['ok'])

    def test_controller_lock_refuses_live_owner(self):
        with controller_lock(self.w.root):
            with self.assertRaises(WorkbenchError) as caught:self.w.process(self.batch['id'])
        self.assertEqual(caught.exception.code,'controller-owned')
        self.assertEqual(self.w.batch(self.batch['id'])['counts']['queued'],4)

    def test_worker_error_is_distinct_from_failed_checks(self):
        with patch('swe_workbench.runner._execute',return_value={'error':'Deliberate unavailable worker','identity':None}):
            result=self.w.process(self.batch['id'],stop_after=1)
        self.assertEqual(result['processed'],0)
        self.assertEqual(result['counts']['execution-error'],1)
        self.assertEqual(result['counts']['completed'],0)
        self.assertEqual(len([e for e in self.w.audit_events() if e['kind']=='execution-error']),1)
        errored=[i for i in self.w.submissions(self.batch['id']) if i['execution_status']=='execution-error'][0]
        self.assertIsNone(errored['result'])

    def test_deliberate_interruption_retains_results_and_same_run(self):
        first=self.w.process(self.batch['id'],stop_after=1)
        self.assertTrue(first['interrupted'])
        prior={i['id']:i['result'] for i in self.w.submissions(self.batch['id']) if i['result']}
        restarted=Workbench(self.w.root);restarted.initialize();second=restarted.process(self.batch['id'])
        self.assertEqual(first['run_id'],second['run_id'])
        self.assertEqual(second['processed'],3)
        self.assertFalse(second['interrupted'])
        for sid,result in prior.items():self.assertEqual(restarted.submission(sid)['result'],result)
        self.assertEqual(len(restarted.snapshot(self.batch['id'])['timing_segments']),2)


if __name__=='__main__':unittest.main()
