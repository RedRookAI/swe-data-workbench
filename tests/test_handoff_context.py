import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from swe_workbench import handoff
from swe_workbench.handoff_context import PROFILE, V2
from swe_workbench.handoff_profile import expand
from swe_workbench.errors import WorkbenchError

class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.p=Path(self.temp.name);self.repo=self.p/'source';self.repo.mkdir();self.root=self.p/'state'
        self.git('init','-q');self.git('config','user.email','example@invalid.local');self.git('config','user.name','Fixture')
        (self.repo/'value.py').write_text('value = 1\n');self.git('add','.');self.git('commit','-qm','base');self.base=self.git('rev-parse','HEAD').strip()
        (self.repo/'value.py').write_text('value = 2\n');self.git('commit','-qam','candidate');self.candidate=self.git('rev-parse','HEAD').strip()
        self.proof=self.p/'proof.json';self.data={'source':self.candidate,'fixture':'f'*40,'check':False};self.write_proof()
        self.profile={'schema':PROFILE,'id':'project','version':'1','repository':'example-project','attachments':['proof.json'],
            'observations':[{'label':'Check','attachment':'proof.json','field_path':['check'],'context_path':['source'],'required':True,'scope':'Reported scope'}]}
    def git(self,*args):return subprocess.check_output(['git','-c','core.hooksPath=/dev/null','-C',str(self.repo),*args],text=True,stderr=subprocess.PIPE)
    def write_proof(self):self.proof.write_text(json.dumps(self.data)+'\n')
    def request(self,profile=None,goal='Use value2'):
        return expand(profile or self.profile,change_id='change',title='Change value',goal=goal)
    def capture(self,request=None,key=None):
        return handoff.capture(self.root,repo=self.repo,base=self.base,candidate=self.candidate,request=request or self.request(),evidence={'proof.json':self.proof},operation_key=key)
    def review(self,state,key='review',**updates):
        fields={'expected_revision':state['revision'],'material_digest':state['material_digest'],'decision':'handoff-ready','reason':'Inspected reported scope','findings':[],'next_action':'Owner review','operation_key':key,'responsible_party':'Project owner'};fields.update(updates)
        return handoff.review(self.root,'change',**fields)
    def test_profile_reuse_effective_inputs_and_refusal(self):
        first=self.capture();same=self.capture(copy.deepcopy(self.request()));self.assertEqual(first,same)
        material=handoff.read(self.root,'change')['material'];self.assertEqual(material['profile']['definition'],self.profile)
        explicit={'schema':V2,'change_id':'explicit','title':'Change value','goal':'Use value2','repository':'example-project','observations':self.profile['observations']}
        e=self.capture(explicit);m=handoff.read(self.root,'explicit')['material']
        for k in ['files','patch','observations','subjects','relationships']:self.assertEqual(material[k],m[k])
        with self.assertRaises(WorkbenchError):expand(self.profile|{'command':'touch marker'},change_id='x',title='x',goal='x')
        with self.assertRaises(WorkbenchError):expand(self.profile|{'repository':'/private/host'},change_id='x',title='x',goal='x')
        with self.assertRaises(WorkbenchError):self.capture(self.request(self.profile|{'attachments':['missing.json']}))
        self.assertEqual(handoff.read(self.root,'change')['state'],first)
        reviewed=self.review(first,'profile-reviewed')
        self.assertEqual(self.capture(),reviewed,'Normal repeated capture returns the current review, not its old first-capture response.')
    def fixture_profile(self):
        p=copy.deepcopy(self.profile);p['subjects']=[{'id':'product','role':'product_source','selector':{'source':'candidate'}},{'id':'fixture','role':'consumer_fixture','selector':{'attachment':'proof.json','field_path':['fixture']}}]
        p['observations'][0].update(subject='fixture',context_path=['fixture'])
        p['relationships']=[{'id':'fixture-product','kind':'fixture_for','from':'fixture','to':'product','reason':'Reported test fixture association',
            'evidence':[{'attachment':'proof.json','field_path':['source'],'matches_subject':'product'},{'attachment':'proof.json','field_path':['fixture'],'matches_subject':'fixture'}]}]
        return p
    def test_fixture_role_does_not_become_product_and_missing_relation_holds(self):
        p=self.fixture_profile();s=self.capture(self.request(p));m=handoff.read(self.root,'change')['material'];o=m['observations'][0]
        self.assertEqual(o['binding'],'declared-same-subject');self.assertEqual(o['subject_role'],'consumer_fixture');self.assertEqual(o['candidate_applicability'],'declared');self.review(s)
        self.data['source']=self.base;self.write_proof();new=self.capture(self.request(p));m=handoff.read(self.root,'change')['material']
        self.assertEqual(m['relationships'][0]['status'],'unknown')
        with self.assertRaises(WorkbenchError):self.review(new,'stale-source')
        p['subjects'][1]['role']='product_source'
        with self.assertRaises(WorkbenchError):self.capture(self.request(p))
    def test_unknown_roles_remain_unknown(self):
        p=self.fixture_profile();self.data.pop('fixture');self.write_proof();s=self.capture(self.request(p));m=handoff.read(self.root,'change')['material']
        self.assertEqual(m['subjects'][1]['status'],'unknown');self.assertEqual(m['observations'][0]['candidate_applicability'],'unknown')
        with self.assertRaises(WorkbenchError):self.review(s)
    def test_v1_history_v2_comparison_and_review_only_update(self):
        legacy={k:v for k,v in self.request().items() if k in ('change_id','title','goal','repository','observations')}
        first=self.capture(legacy);first=handoff.review(self.root,'change',expected_revision=first['revision'],material_digest=first['material_digest'],decision='handoff-ready',reason='Original review',findings=[],next_action='Inspect',operation_key='legacy-review')
        old=handoff.export(self.root,'change',self.p/'v1');old_bytes=(self.p/'v1/handoff.json').read_bytes()
        current=self.capture();record=handoff.read(self.root,'change');self.assertEqual(record['comparison']['baseline_revision'],first['revision']);self.assertFalse(record['comparison']['source_context_changed'])
        current=self.review(current);current=self.review(current,'review-only',reason='Updated next-owner explanation')
        comp=handoff.read(self.root,'change')['comparison'];self.assertEqual(list(comp['review_changes']),['reason']);self.assertTrue(all(o['status']=='unchanged-reported-binding' for o in comp['applicability']))
        self.assertEqual(handoff.read(self.root,'change',first['revision'])['comparison']['baseline_revision'],first['revision'])
        with self.assertRaises(WorkbenchError):handoff.read(self.root,'change',999)
        exported=handoff.export(self.root,'change',self.p/'v2');self.assertTrue(exported['ok']);self.assertTrue(handoff.verify(self.p/'v1')['ok']);self.assertEqual(old_bytes,(self.p/'v1/handoff.json').read_bytes())
        raw=json.load(open(self.p/'v2/handoff.json'));encoded=json.load(open(self.p/'v2/artifacts.json'));raw['comparison']['source_context_changed']=True
        with self.assertRaises(WorkbenchError):handoff._validate_package(raw,encoded)
    def test_zero_false_missing_and_unrelated_head(self):
        first=self.capture();self.review(first);self.data['check']=0;self.write_proof();second=self.capture();comp=handoff.read(self.root,'change')['comparison'];self.assertEqual(comp['observations']['changed'],['Check']);self.review(second,'zero')
        self.data.pop('check');self.write_proof();third=self.capture();self.assertEqual(handoff.read(self.root,'change')['material']['observations'][0]['value'],None)
        with self.assertRaises(WorkbenchError):self.review(third,'missing')
        (self.repo/'unrelated.py').write_text('unrelated = True\n');self.git('add','.');self.git('commit','-qm','unrelated');self.assertEqual(third,self.capture())
    def test_cli_profile_capture_and_inline_review(self):
        p=self.p/'profile.json';p.write_text(json.dumps(self.profile));cmd=[sys.executable,'-m','swe_workbench.cli','--root',str(self.root)]
        s=json.loads(subprocess.check_output(cmd+['capture-handoff','--repo',str(self.repo),'--base',self.base,'--candidate',self.candidate,'--profile',str(p),'--change-id','change','--title','Change value','--goal','Use value2','--evidence-dir',str(self.p)],text=True))
        reviewed=json.loads(subprocess.check_output(cmd+['review-handoff','change','--expected-revision',str(s['revision']),'--material-digest',s['material_digest'],'--decision','handoff-ready','--reason','Scoped review','--next-action','Owner review','--operation-key','inline','--responsible-party','Owner'],text=True))
        self.assertEqual(reviewed['responsible_party'],'Owner');self.assertEqual(reviewed['decision'],'handoff-ready')

if __name__=='__main__':unittest.main()
