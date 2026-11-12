"""Fixture qualification of selected artifact staging and base policy."""
import importlib.util,json,unittest
from pathlib import Path
from tests.test_ci_evidence import CITests
from swe_workbench.store import canonical
from swe_workbench.ci_evidence import begin,finish
spec=importlib.util.spec_from_file_location('ci_recipe',Path(__file__).parents[1]/'tools/ci_recipe.py');recipe=importlib.util.module_from_spec(spec);spec.loader.exec_module(recipe)
class RecipeTests(unittest.TestCase):
    setUp=CITests.setUp;git=CITests.git;write_proof=CITests.write_proof
    def test_allowlist_failure_and_missing(self):
        for code,xml,name in [(1,'<testsuite><testcase name="Authored failure"><failure/></testcase></testsuite>','failed'),(3,None,'missing'),(5,'<testsuite/>','empty')]:
            root=self.p/name;root.mkdir();(root/'recipe.json').write_bytes(canonical({'case':'normal','source':str(self.repo),'workspace':str(self.repo),'product':'example/source','base':self.base}));out=root/'observed';begin(self.repo,out,'example/source',['pytest'],['value.py'],{})
            if xml:(out/'original.xml').write_text(xml)
            finish(out,code);result=recipe.package(root)
            self.assertEqual(result['status'],'complete' if xml else 'incomplete');self.assertEqual(result['exit_code'],code)
            share=root/'share';self.assertFalse(any(x.suffix in ('.sqlite','.db') or x.name in ('project.json','started.json','receipt.json','selection.json') for x in share.rglob('*')))
            self.assertEqual(set(x.name for x in share.iterdir()),{'ci-receipt.json','run-context.json','check-definition.json','package-status.json'}|({'original.xml','view','export','summary.json'} if xml else set()))
    def test_pr_push_manual_base(self):
        self.assertEqual(recipe.select_base({'GITHUB_EVENT_NAME':'pull_request','WB_PR_BASE':'base','GITHUB_SHA':'merge'}),'base')
        self.assertEqual(recipe.select_base({'GITHUB_EVENT_NAME':'push','WB_PUSH_BASE':'previous'}),'previous')
        self.assertEqual(recipe.select_base({'GITHUB_EVENT_NAME':'workflow_dispatch'}),recipe.MANUAL_BASE)
        root=self.p/'none';root.mkdir();result=recipe.package(root);self.assertEqual(result['status'],'incomplete');self.assertEqual(len(list((root/'share').iterdir())),1)
del CITests
