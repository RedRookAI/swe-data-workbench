"""Ordinary report import, without project execution or custom producer facts."""
import json,tempfile,unittest
from pathlib import Path
from swe_workbench.junit_report import project,import_report
from swe_workbench.errors import WorkbenchError

class JUnitAdapterTests(unittest.TestCase):
    def test_cases_and_missing_execution_context(self):
        raw=b'<testsuites><testsuite tests="9"><testcase name="same" time="0.95"/><testcase name="same"><failure message="broken">detail</failure></testcase><testcase name="skip"><skipped/></testcase><testcase name="error"><error/></testcase></testsuite></testsuites>'
        report=project(raw);self.assertEqual(report['counts'],{'passed':1,'failed':1,'error':1,'skipped':1});self.assertEqual(report['executed'],3);self.assertIsNone(report['execution_revision']);self.assertIsNone(report['definition_sha256']);self.assertEqual(len({c['id'] for c in report['cases']}),4);self.assertTrue(report['aggregate_warnings']);self.assertEqual(report['cases'][0]['duration_text'],'0.95')
    def test_import_preserves_bytes_and_supplied_context(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);raw=b'<testsuite tests="1"><testcase name="value" time="0.001"/></testsuite>';(root/'source.xml').write_bytes(raw)
            context={'source_revision':'a'*40,'source_state':'clean'};(root/'context.json').write_text(json.dumps(context))
            result=import_report(root/'source.xml',root/'imported',root/'context.json');self.assertEqual(result['execution_revision'],'a'*40);self.assertEqual((root/'imported/original.xml').read_bytes(),raw)
            with self.assertRaises(WorkbenchError):import_report(root/'source.xml',root/'imported')
    def test_entities_and_empty_work(self):
        self.assertEqual(project(b'<testsuite tests="0"/>')['executed'],0)
        with self.assertRaises(WorkbenchError):project(b'<!DOCTYPE a [<!ENTITY x "boom">]><testsuite/>')
