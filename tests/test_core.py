from pathlib import Path
import tempfile
import unittest
from swe_workbench.core import Workbench, CRITERIA
from swe_workbench.errors import WorkbenchError
from swe_workbench.store import canonical,digest


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]);self.addCleanup(self.tmp.cleanup)
        self.w=Workbench(Path(self.tmp.name)/'state');self.w.initialize()
        self.batch=self.w.import_sample('sample')
        self.w.process(self.batch['id'])
        self.items={i['fixture_label']:i for i in self.w.submissions(self.batch['id'])}

    def request(self,item,decision='accepted',**changes):
        return {'expected_revision':item['revision'],'evidence_digest':item['result']['evidence_digest'] if item['result'] else None,
                'rubric_digest':item['rubric_digest'],'decision':decision,'reason':'Checked task and exact evidence.',
                'criteria':dict.fromkeys(CRITERIA,'pass'),'operation_key':'review-'+item['id'],**changes}

    def test_exact_review_bindings_and_payload_idempotency(self):
        item=self.items['good'];request=self.request(item)
        accepted=self.w.review(item['id'],**request)
        self.assertEqual(accepted['disposition'],'accepted')
        self.assertEqual(accepted['revision'],item['revision']+1)
        self.assertEqual(self.w.review(item['id'],**request),accepted)
        for changes,code in [({'operation_key':'new'},'stale-review'),({'reason':'changed'},'operation-conflict')]:
            with self.assertRaises(WorkbenchError) as caught:
                self.w.review(item['id'],**(request|changes))
            self.assertEqual(caught.exception.code,code)
        other=self.items['same-patch-different-context']
        for changes,code in [({'evidence_digest':'f'*64},'stale-evidence'),({'rubric_digest':'f'*64},'stale-rubric')]:
            with self.assertRaises(WorkbenchError) as caught:
                self.w.review(other['id'],**(self.request(other)|changes))
            self.assertEqual(caught.exception.code,code)

    def test_failed_missing_or_uncertain_criteria_cannot_be_accepted(self):
        for label in ('failing','missing-evidence'):
            item=self.items[label]
            with self.assertRaises(WorkbenchError):self.w.review(item['id'],**self.request(item))
        good=self.items['good']
        with self.assertRaises(WorkbenchError) as caught:
            self.w.review(good['id'],**self.request(good,criteria=dict.fromkeys(CRITERIA,'uncertain')))
        self.assertEqual(caught.exception.code,'ineligible-acceptance')
        wrong=self.items['weak-check-wrong']
        changed=self.w.review(wrong['id'],**self.request(wrong,'needs-work',reason='Sorting changes first-seen order for b,a,b.',criteria=dict.fromkeys(CRITERIA,'pass')|{'requested_behavior':'fail'}))
        self.assertEqual(changed['disposition'],'needs-work')
        self.assertEqual(changed['result']['overall'],'passed')
        self.assertEqual(changed['review']['origin'],'developer_adjudication')
        self.assertEqual(changed['seeded_reviews'][0]['origin'],'synthetic_seed')

    def test_changed_check_context_and_invalid_criteria_refuse_review(self):
        good=self.items['good']
        with self.assertRaises(WorkbenchError) as caught:
            self.w.review(good['id'],**self.request(good,criteria=dict.fromkeys(CRITERIA,[])))
        self.assertEqual(caught.exception.code,'invalid-criteria')
        self.w.catalog['tasks'][good['task_id']]['checks'][0]['timeout']=6
        with self.assertRaises(WorkbenchError) as caught:
            self.w.review(good['id'],**self.request(good))
        self.assertEqual(caught.exception.code,'stale-context')
        self.assertEqual(self.w.submission(good['id'])['disposition'],'pending')

    def test_export_freeze_same_cut_and_changed_decision(self):
        item=self.items['good'];self.w.review(item['id'],**self.request(item))
        first=self.w.prepare_export(self.batch['id'],'export1')
        self.w.complete_export(first['export_id'],'f'*64,'private-export-location')
        second=self.w.prepare_export(self.batch['id'],'export2')
        self.assertEqual(first['export_id'],second['export_id'])
        self.assertEqual(first['snapshot'],second['snapshot'])
        self.assertEqual(second['status'],'ready')
        self.assertEqual(self.w.prepare_export(self.batch['id'],'export1')['export_id'],first['export_id'])
        with self.assertRaises(WorkbenchError):self.w.complete_export(first['export_id'],'a'*64,'other')
        current=self.w.submission(item['id'])
        self.w.review(item['id'],**self.request(current,'rejected',operation_key='changed-review'))
        third=self.w.prepare_export(self.batch['id'],'export3')
        self.assertNotEqual(first['export_id'],third['export_id'])
        self.assertEqual(first['snapshot']['items'],self.w.exports(self.batch['id'])[0]['snapshot']['items'] if self.w.exports(self.batch['id'])[0]['export_id']==first['export_id'] else self.w.exports(self.batch['id'])[1]['snapshot']['items'])
        self.assertNotIn(str(self.w.root),canonical(first['snapshot']).decode())

    def test_missing_artifact_and_audit_tampering_are_integrity_failures(self):
        item=self.items['good'];name=item['result']['evidence_digest']
        self.assertEqual(digest(self.w.artifact_bytes(name)),name)
        (self.w.store.artifacts/name).write_bytes(b'changed')
        with self.assertRaises(WorkbenchError) as caught:self.w.snapshot(self.batch['id'])
        self.assertEqual(caught.exception.code,'artifact-integrity')
        with self.w.store.transaction() as con:con.execute("UPDATE audit SET actor='tampered' WHERE seq=1")
        with self.assertRaises(WorkbenchError) as caught:Workbench(self.w.root).initialize()
        self.assertEqual(caught.exception.code,'audit-integrity')


if __name__ == '__main__':unittest.main()
