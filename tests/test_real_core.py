"""Controlled review attribution shares exact core acceptance authority."""
from pathlib import Path
import tempfile
import unittest
from swe_workbench.core import Workbench, CRITERIA, REVIEWER_MODES
from swe_workbench.errors import WorkbenchError


class ReviewerModeTests(unittest.TestCase):
    def test_modes_are_audited_idempotent_and_cannot_bypass_failed_evidence(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as root:
            w=Workbench(Path(root)/'state');batch=w.import_sample('sample')
            # Affected default fixture behavior: actual results and origin remain
            # unchanged while the review-origin vocabulary becomes explicit.
            w.process(batch['id'])
            items={i['fixture_label']:i for i in w.submissions(batch['id'])}
            self.assertTrue(all(i['origin']=='synthetic_fixture' for i in items.values() if i['trusted_tuple']))
            self.assertEqual(w.snapshot(batch['id'])['runtime']['intake_version'],'raw-occurrence-v2')
            good=items['good'];failed=items['failing']
            for mode in sorted(REVIEWER_MODES):
                request={'expected_revision':good['revision'],'evidence_digest':good['result']['evidence_digest'],
                         'rubric_digest':good['rubric_digest'],'decision':'accepted','reason':'Focused exact-evidence test.',
                         'criteria':dict.fromkeys(CRITERIA,'pass'),'operation_key':mode,'reviewer_mode':mode}
                current=w.review(good['id'],**request)
                self.assertEqual(current['review']['origin'],mode)
                self.assertEqual(current['review']['reviewer_mode'],mode)
                self.assertEqual(current['review']['actor'],'operator')
                self.assertEqual(w.review(good['id'],**request),current)
                other=next(value for value in REVIEWER_MODES if value!=mode)
                with self.assertRaises(WorkbenchError) as caught:w.review(good['id'],**(request|{'reviewer_mode':other}))
                self.assertEqual(caught.exception.code,'operation-conflict')
                with self.assertRaises(WorkbenchError) as caught:
                    w.review(failed['id'],**(request|{'expected_revision':failed['revision'],'evidence_digest':failed['result']['evidence_digest'],
                                                    'operation_key':'failed-'+mode}))
                self.assertEqual(caught.exception.code,'ineligible-acceptance')
                good=current
            events=[e for e in w.audit_events() if e['kind']=='submission-reviewed']
            self.assertEqual({e['payload']['reviewer_mode'] for e in events},REVIEWER_MODES)
            self.assertTrue(all(e['actor']=='operator' and e['payload']['origin']==e['payload']['reviewer_mode'] for e in events))
            with self.assertRaises(WorkbenchError) as caught:
                w.review(good['id'],expected_revision=good['revision'],evidence_digest=good['result']['evidence_digest'],rubric_digest=good['rubric_digest'],
                         decision='accepted',reason='invalid',criteria=dict.fromkeys(CRITERIA,'pass'),operation_key='invalid',reviewer_mode='independent-human-proof')
            self.assertEqual(caught.exception.code,'invalid-reviewer-mode')
            self.assertTrue(w.verify()['ok'])


if __name__=='__main__':unittest.main()
