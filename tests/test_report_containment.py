import json,unittest
from tests.test_daily_workflow import DailyTests
from swe_workbench import project_context as project,handoff
from swe_workbench.reported_checks import extract
from swe_workbench.attention import list_changes,summary
from swe_workbench.handoff_view import build_project
from swe_workbench.store import digest,Store
from swe_workbench.errors import WorkbenchError

class ContainmentTests(unittest.TestCase):
    setUp=DailyTests.setUp;git=DailyTests.git;write_proof=DailyTests.write_proof;context=DailyTests.context
    def test_invalid_context_stays_invalid(self):
        raw='<testsuite><testcase name="a"/></testsuite>'
        for context in (17,[],{}):
            data={'schema':'swe-workbench-junit-report/v1','context_text':context,'report_sha256':digest(raw.encode())}
            report=extract({'candidate_revision':self.candidate,'attachments':[{'name':'report','text':json.dumps(data),'sha256':digest(json.dumps(data).encode())},{'name':'xml','text':raw,'sha256':digest(raw.encode())}]})
            self.assertEqual(report[0]['status'],'invalid-supported-report');self.assertIn('context_text',report[0]['error'])
    def test_missing_sibling_visible_global_failure_loud(self):
        c=self.context()
        for key in ('good','broken'):project.collect(c,change_id=key,title=key,goal='Use2')
        broken=handoff.read(self.root,'broken')['state']['material_digest'];(self.root/'artifacts'/broken).unlink()
        rows=list_changes(c)['changes'];self.assertEqual([x['change_id'] for x in rows],['broken','good']);self.assertEqual(rows[0]['decision'],'unavailable');self.assertTrue(rows[0]['needs_attention']);self.assertNotIn('problem',rows[1]);self.assertIn('Unavailable',summary(c,'broken')['summary'])
        result=build_project(c,self.p/'view');self.assertEqual(result['changes'],2);self.assertIsNone(json.loads((self.p/'view/attention.json').read_text())['changes'][0]['view'])
        with Store(self.root).transaction() as con:con.execute("UPDATE audit SET hash=? WHERE seq=1",('0'*64,))
        with self.assertRaisesRegex(WorkbenchError,'Audit chain'):list_changes(c)
del DailyTests
