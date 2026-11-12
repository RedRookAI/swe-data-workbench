import json,shutil,unittest
from tests.test_handoff_context import ContextTests
from swe_workbench import project_context as project,handoff
from swe_workbench.project_scope import associate
from swe_workbench.attention import list_changes,summary
from swe_workbench.handoff_view import build_project
from swe_workbench.errors import WorkbenchError

class ScopeTests(unittest.TestCase):
    setUp=ContextTests.setUp;git=ContextTests.git;write_proof=ContextTests.write_proof
    request=ContextTests.request;capture=ContextTests.capture;review=ContextTests.review
    def context(self,name='a',repo=None):
        profile=self.p/(name+'-profile.json');profile.write_text(json.dumps(self.profile))
        path=self.p/(name+'.json');project.configure(path,repo=str(repo or self.repo),profile=str(profile),evidence_directory=str(self.p),state=str(self.root),base_ref=self.base,candidate_ref=self.candidate)
        return path
    def test_project_boundary_retry_and_restore(self):
        context=self.context();selection=self.p/'selection.json';state=project.collect(context,change_id='change',title='Change',goal='Use2',output=selection)['state']
        fields=dict(decision='needs-work',reason='Inspect',findings=['Scope'],next_action='Inspect',responsible_party=None)
        reviewed=project.review_selection(context,selection,**fields);self.assertEqual(project.review_selection(context,selection,**fields),reviewed)
        before=(self.root/'workbench.sqlite3').read_bytes();files=set((self.root/'artifacts').iterdir())
        other=self.p/'other';shutil.copytree(self.repo,other)
        with self.assertRaisesRegex(WorkbenchError,'different project'):self.context('b',other)
        mutated=json.loads(context.read_text());mutated['repo']=str(other);bad=self.p/'bad.json';bad.write_text(json.dumps(mutated))
        for action in [lambda:project.collect(bad,change_id='change',title='Other',goal='Other'),lambda:list_changes(bad),lambda:summary(bad,'change'),lambda:build_project(bad,self.p/'bad-view'),lambda:project.review_selection(bad,selection,**fields),lambda:handoff.capture(self.root,repo=other,base=self.base,candidate=self.candidate,request=self.request(),evidence={'proof.json':self.proof})]:
            with self.assertRaisesRegex(WorkbenchError,'different project'):action()
        self.assertEqual((self.root/'workbench.sqlite3').read_bytes(),before);self.assertEqual(set((self.root/'artifacts').iterdir()),files)
        from swe_workbench.state_backup import backup,restore
        backup(self.root,self.p/'backup');restore(self.p/'backup',self.p/'restored');self.assertTrue(handoff.export(self.p/'restored','change',self.p/'export')['ok'])
        associate(bad,relocate=True);self.assertEqual(len(list_changes(bad)['changes']),1);self.assertEqual(handoff.read(self.root,'change')['state'],reviewed)
    def test_legacy_explicit_association_and_mixed_refusal(self):
        state=self.capture();context=self.context()
        with self.assertRaisesRegex(WorkbenchError,'unassociated'):list_changes(context)
        original=handoff.export(self.root,'change',self.p/'old');raw=(self.p/'old/handoff.json').read_bytes()
        self.assertEqual(associate(context)['legacy_changes'],1);self.assertTrue(associate(context)['existing']);self.assertEqual(len(list_changes(context)['changes']),1)
        self.assertEqual(handoff.read(self.root,'change')['state'],state);self.assertEqual((self.p/'old/handoff.json').read_bytes(),raw)
        # A separate legacy fixture with two labels must not be silently adopted.
        mixed=self.p/'mixed';req=self.request();handoff.capture(mixed,repo=self.repo,base=self.base,candidate=self.candidate,request=req,evidence={'proof.json':self.proof})
        req=self.request(self.profile|{'repository':'other-project'});req['change_id']='other';handoff.capture(mixed,repo=self.repo,base=self.base,candidate=self.candidate,request=req,evidence={'proof.json':self.proof})
        data=json.loads(context.read_text());data['state']=str(mixed);bad=self.p/'mixed.json';bad.write_text(json.dumps(data));before=(mixed/'workbench.sqlite3').read_bytes()
        with self.assertRaisesRegex(WorkbenchError,'Mixed/unknown'):associate(bad)
        self.assertEqual((mixed/'workbench.sqlite3').read_bytes(),before)
del ContextTests
