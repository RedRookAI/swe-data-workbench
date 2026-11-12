import copy,json,subprocess,sys,unittest
from pathlib import Path
from tests.test_handoff_context import ContextTests
from swe_workbench import handoff
from swe_workbench.errors import WorkbenchError

class BoundaryTests(unittest.TestCase):
    setUp=ContextTests.setUp;git=ContextTests.git;write_proof=ContextTests.write_proof
    request=ContextTests.request;capture=ContextTests.capture;review=ContextTests.review;fixture_profile=ContextTests.fixture_profile
    # Only the new boundary cases belong to this class; reuse fixture helpers.
    def test_invalid_shapes(self):
        for value,field in [([], 'material'),({}, 'material'),({'schema':None},'material')]:
            with self.subTest(value=value),self.assertRaisesRegex(WorkbenchError,field):handoff.validate_material(value)
        p=self.fixture_profile();p['subjects'][1]['selector']=None
        with self.assertRaisesRegex(WorkbenchError,r'subjects\[1\].selector'):self.capture(self.request(p))
        self.assertFalse(self.root.exists())
    def test_cli_error_preserves_review(self):
        reviewed=self.review(self.capture());before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        f=self.p/'invalid.json';f.write_text(json.dumps(self.profile|{'observations':[{'label':None}]}))
        r=subprocess.run([sys.executable,'-m','swe_workbench.cli','--root',str(self.root),'capture-handoff','--repo',str(self.repo),'--base',self.base,'--candidate',self.candidate,'--profile',str(f),'--change-id','change','--title','x','--goal','x'],capture_output=True,text=True)
        self.assertEqual(r.returncode,1);self.assertEqual(json.loads(r.stdout)['error']['code'],'handoff-field');self.assertNotIn('Traceback',r.stderr)
        self.assertEqual(before,{p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()});self.assertEqual(handoff.read(self.root,'change')['state'],reviewed)
    def test_bad_export_reports_field(self):
        self.capture();out=self.p/'out';handoff.export(self.root,'change',out);(out/'manifest.json').write_text('[]')
        result=handoff.verify(out);self.assertFalse(result['ok']);self.assertIn('manifest',result['errors'][0])
    def test_unknown_false_zero_preserved(self):
        for value in [False,0,None]:
            self.data['check']=value;self.write_proof();s=self.capture();self.assertIs(handoff.read(self.root,'change')['material']['observations'][0]['value'],value)
            if value is None:
                with self.assertRaises(WorkbenchError):self.review(s,'missing')
                self.review(s,'unresolved',decision='needs-work')
    def test_unsupported_source_path_has_specific_error(self):
        import os
        fd=os.open(os.fsencode(self.repo)+b'/bad-\xff',os.O_CREAT|os.O_WRONLY,0o644);os.write(fd,b'value = 3\n');os.close(fd)
        self.git('add','--all');self.git('commit','-qm','Unsupported path');self.candidate=self.git('rev-parse','HEAD').strip()
        with self.assertRaisesRegex(WorkbenchError,'Source path'):self.capture()
        self.assertFalse(self.root.exists())
    def test_legacy_exports(self):
        for folder in ['keep-handoff','everyday-handoff']:
            self.assertTrue(handoff.verify(Path(__file__).resolve().parents[1]/'docs/examples'/folder/'export')['ok'])

del ContextTests
