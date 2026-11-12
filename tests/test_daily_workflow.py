import json,unittest
from pathlib import Path
from tests.test_handoff_context import ContextTests
from swe_workbench import project_context as project
from swe_workbench import handoff
from swe_workbench.junit_report import project as parse_junit,import_report
from swe_workbench.attention import list_changes,summary
from swe_workbench.reported_checks import extract
from swe_workbench.errors import WorkbenchError

class DailyTests(unittest.TestCase):
    setUp=ContextTests.setUp;git=ContextTests.git;write_proof=ContextTests.write_proof
    def context(self):
        profile=self.p/'profile.json';profile.write_text(json.dumps(self.profile));context=self.p/'context.json'
        project.configure(context,repo=str(self.repo),profile=str(profile),evidence_directory=str(self.p),state=str(self.root),base_ref='HEAD^',candidate_ref='HEAD')
        return context
    def test_context_selection_and_attention(self):
        context=self.context();args=dict(change_id='first',title='Actual fixture change',goal='Use value2')
        preview=project.collect(context,preview=True,**args);self.assertFalse(self.root.exists())
        captured=project.collect(context,output=self.p/'selection.json',**args);self.assertEqual(preview['material_digest'],captured['state']['material_digest'])
        review=dict(decision='needs-work',reason='Inspect the check',findings=['Check scope remains narrow'],next_action='Expand scope',responsible_party=None)
        reviewed=project.review_selection(context,self.p/'selection.json',**review);self.assertEqual(project.review_selection(context,self.p/'selection.json',**review),reviewed)
        self.assertTrue(list_changes(context,True)['changes'][0]['needs_attention']);self.assertIn('Unassigned',summary(context,'first')['summary'])
        self.data.pop('source');self.write_proof();project.collect(context,**args)
        with self.assertRaisesRegex(WorkbenchError,'changed'):project.review_selection(context,self.p/'selection.json',**(review|{'reason':'A different stale decision'}))
        row=list_changes(context)['changes'][0];self.assertEqual(row['prior_findings_for_reassessment'],review['findings'])
        before=handoff.read(self.root,'first')['state']
        with self.assertRaises(WorkbenchError):project.collect(context,output=self.p/'selection.json',**args)
        self.assertEqual(handoff.read(self.root,'first')['state'],before)
    def test_junit_outcomes_context_and_raw_projection(self):
        raw=b'<testsuites><testsuite tests="9"><testcase name="same" time="0.95"/><testcase name="same"><failure message="broken">details</failure></testcase><testcase name="skip"><skipped/></testcase><testcase name="err"><error/></testcase></testsuite></testsuites>'
        report=parse_junit(raw);self.assertEqual(report['counts'],{'passed':1,'failed':1,'error':1,'skipped':1});self.assertEqual(report['executed'],3);self.assertIsNone(report['execution_revision']);self.assertIsNone(report['definition_sha256']);self.assertEqual(len({c['id'] for c in report['cases']}),4);self.assertTrue(report['aggregate_warnings'])
        original=self.p/'original.xml';original.write_bytes(raw);import_report(original,self.p/'imported')
        self.assertEqual((self.p/'imported/original.xml').read_bytes(),raw)
        self.assertEqual(parse_junit(b'<testsuite tests="0"/>')['executed'],0)
        with self.assertRaises(WorkbenchError):parse_junit(b'<!DOCTYPE a [<!ENTITY x "boom">]><testsuite/>')
    def test_report_projection_cannot_hide_original(self):
        raw=b'<testsuite tests="1"><testcase name="broken"><failure/></testcase></testsuite>'
        context=json.dumps({'source_revision':self.candidate,'source_state':'clean'}).encode();r=parse_junit(raw,context)
        from swe_workbench.store import digest
        material={'candidate_revision':self.candidate,'attachments':[{'name':'report.json','text':json.dumps(r),'sha256':digest(json.dumps(r).encode())},{'name':'original.xml','text':raw.decode(),'sha256':digest(raw)}]}
        observed=extract(material);self.assertEqual(observed[0]['counts']['failed'],1);self.assertEqual(observed[0]['binding'],'declared-same-source')
        r['counts']['failed']=0;material['attachments'][0]['text']=json.dumps(r)
        self.assertEqual(extract(material)[0]['status'],'invalid-supported-report')
del ContextTests
