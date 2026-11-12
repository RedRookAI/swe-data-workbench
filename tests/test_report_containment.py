import json,unittest
from tests.test_daily_workflow import DailyTests
from swe_workbench import project_context as project,handoff
from swe_workbench.reported_checks import extract
from swe_workbench.attention import list_changes,summary
from swe_workbench.handoff_view import build_project
from swe_workbench.store import canonical,digest,Store
from swe_workbench.junit_report import project as junit_project
from swe_workbench.handoff_profile import expand
from swe_workbench.errors import WorkbenchError

class ContainmentTests(unittest.TestCase):
    setUp=DailyTests.setUp;git=DailyTests.git;write_proof=DailyTests.write_proof;context=DailyTests.context
    def test_invalid_context_stays_invalid(self):
        raw='<testsuite><testcase name="a"/></testsuite>'
        for context in (17,[],{}):
            data={'schema':'swe-workbench-junit-report/v1','context_text':context,'report_sha256':digest(raw.encode())}
            report=extract({'candidate_revision':self.candidate,'attachments':[{'name':'report','text':json.dumps(data),'sha256':digest(json.dumps(data).encode())},{'name':'xml','text':raw,'sha256':digest(raw.encode())}]})
            self.assertEqual(report[0]['status'],'invalid-supported-report');self.assertIn('context_text',report[0]['error'])
    def ci_missing_context(self):
        xml=b'<testsuite><testcase name="Authored ordinary case"/></testsuite>'
        definition=canonical({});receipt=canonical({'definition_sha256':digest(definition)})
        projection=junit_project(xml);projection['ci_receipt_sha256']=digest(receipt)
        return {'original.xml':xml,'report.json':canonical(projection),'ci-receipt.json':receipt,'check-definition.json':definition}
    def test_ci_requires_context_but_report_only_does_not(self):
        items=self.ci_missing_context()
        material={'candidate_revision':self.candidate,'attachments':[{'name':name,'text':raw.decode(),'sha256':digest(raw)} for name,raw in items.items()]}
        result=extract(material);self.assertEqual(result[0]['status'],'invalid-supported-report');self.assertIn('context_text',result[0]['error'])
        projection=json.loads(items['report.json']);projection.pop('ci_receipt_sha256');material['attachments'][1]['text']=json.dumps(projection)
        result=extract(material);self.assertEqual(result[0]['status'],'reported');self.assertEqual(result[0]['binding'],'unbound')
    def test_invalid_legacy_ci_keeps_healthy_sibling_visible(self):
        c=self.context();project.collect(c,change_id='healthy',title='Healthy fixture',goal='Inspect value2')
        items=self.ci_missing_context();evidence={}
        for name,raw in items.items():
            path=self.p/name;path.write_bytes(raw);evidence[name]=path
        profile=self.profile|{'attachments':list(items),'observations':[]}
        request=expand(profile,change_id='invalid-ci',title='Malformed authored legacy CI',goal='Contain missing context');request['schema']=handoff.V2
        handoff.capture(self.root,repo=self.repo,base=self.base,candidate=self.candidate,request=request,evidence=evidence,project=True)
        rows=list_changes(c)['changes'];self.assertEqual([r['change_id'] for r in rows],['healthy','invalid-ci']);self.assertEqual(rows[1]['reports'][0]['status'],'invalid-supported-report');self.assertTrue(rows[1]['needs_attention']);self.assertNotIn('problem',rows[0])
        self.assertIn('Invalid supported report',summary(c,'invalid-ci')['summary'])
        build_project(c,self.p/'view');selected=json.loads((self.p/'view/attention.json').read_text())['changes'];self.assertIsNotNone(selected[0]['view']);self.assertIsNone(selected[1]['view']);self.assertIn('context_text',selected[1]['problem']['message'])
        # Current capture also retains the inert invalid result predictably.
        request['schema']=handoff.V4;request['change_id']='invalid-current'
        state=handoff.capture(self.root,repo=self.repo,base=self.base,candidate=self.candidate,request=request,evidence=evidence,project=True)
        self.assertEqual(state['decision'],'unreviewed');self.assertEqual(handoff.read(self.root,'invalid-current')['material']['reported_checks'][0]['status'],'invalid-supported-report')
    def test_missing_sibling_visible_global_failure_loud(self):
        c=self.context()
        for key in ('good','broken'):project.collect(c,change_id=key,title=key,goal='Use2')
        broken=handoff.read(self.root,'broken')['state']['material_digest'];(self.root/'artifacts'/broken).unlink()
        rows=list_changes(c)['changes'];self.assertEqual([x['change_id'] for x in rows],['broken','good']);self.assertEqual(rows[0]['decision'],'unavailable');self.assertTrue(rows[0]['needs_attention']);self.assertNotIn('problem',rows[1]);self.assertIn('Unavailable',summary(c,'broken')['summary'])
        result=build_project(c,self.p/'view');self.assertEqual(result['changes'],2);self.assertIsNone(json.loads((self.p/'view/attention.json').read_text())['changes'][0]['view'])
        with Store(self.root).transaction() as con:con.execute("UPDATE audit SET hash=? WHERE seq=1",('0'*64,))
        with self.assertRaisesRegex(WorkbenchError,'Audit chain'):list_changes(c)
del DailyTests
