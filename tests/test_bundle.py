"""Temporary repositories qualify preparation without running supplied checks."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from swe_workbench.bundle import prepare_bundle, _publish
from swe_workbench.cli import main
from swe_workbench.core import Workbench
from swe_workbench.errors import WorkbenchError
from swe_workbench.intake import MAX_LINE_BYTES
from swe_workbench.store import canonical, digest


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        self.git('init', '--initial-branch=main')
        self.git('config', 'user.name', 'Preparation fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.committed = b'def value():\r\n    return 0\r\n'
        (self.repo/'solution.py').write_bytes(self.committed)
        (self.repo/'license').write_bytes(b'Example MIT notice\r\n')
        (self.repo/'binary.dat').write_bytes(b'\x00binary')
        (self.repo/'link.py').symlink_to('solution.py')
        (self.repo/'executable.py').write_bytes(b'print(1)\n');(self.repo/'executable.py').chmod(0o755)
        (self.repo/'directory').mkdir();(self.repo/'directory/file').write_text('tracked')
        (self.repo/'.gitattributes').write_text('*.py filter=marker\n')
        self.git('add', '.');self.git('commit', '-m', 'Pinned input fixture')
        parent = self.git('rev-parse', 'HEAD').strip().decode()
        self.git('update-index', '--add', '--cacheinfo', '160000,'+parent+',submodule')
        self.git('commit', '-m', 'Add unsupported gitlink fixture')
        self.commit = self.git('rev-parse', 'HEAD').strip().decode()
        # The selected worktree is dirty. Prep must use pinned blobs, never it.
        (self.repo/'solution.py').write_text('dirty working content\n')
        (self.repo/'untracked.py').write_text('untracked secret\n')
        self.marker = self.root/'MUST-NOT-RUN'
        self.git('config', 'filter.marker.clean', 'touch '+str(self.marker))
        self.git('config', 'filter.marker.smudge', 'touch '+str(self.marker))
        self.patch_bytes = b'--- a/solution.py\n+++ b/solution.py\n@@ -1,2 +1,2 @@\n def value():\n-    return 0\n+    return 1\n'
        (self.root/'fix.patch').write_bytes(self.patch_bytes)
        self.task = self.root/'task.txt';self.task.write_text('Make value return one.\n')
        self.checks = self.root/'checks.json'
        self.check_data = [{'name':'marker','argv':[sys.executable,'-c',f'from pathlib import Path; Path({str(self.marker)!r}).write_text("executed")'],'timeout':5}]
        self.checks.write_bytes(canonical(self.check_data))
        self.candidates = self.root/'candidates.json'
        self.candidate_data = [{'patch_file':'fix.patch','model_name_or_path':'selected-reference','provenance':{'origin':'public_upstream','license':'MIT'}}]
        self.candidates.write_bytes(canonical(self.candidate_data))
        self.provenance = self.root/'provenance.json'
        self.provenance.write_bytes(canonical({'origin':'public_upstream','license':'MIT','repository':'local-fixture'}))
        self.arguments = dict(repo=self.repo,commit=self.commit,task_id='example-task',task_text=self.task,sources=['solution.py'],
                              checks=self.checks,candidates=self.candidates,provenance=self.provenance,notices=['license'],output=self.root/'bundle')

    def git(self,*args):
        return subprocess.run(['git','-C',str(self.repo),*args],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout

    def prepare(self,**changes):
        return prepare_bundle(**(self.arguments|changes))

    def test_committed_bytes_not_dirty_or_untracked_inputs_and_stable_identity(self):
        index = (self.repo/'.git/index').read_bytes()
        files = [self.task,self.checks,self.candidates,self.provenance,self.root/'fix.patch',self.repo/'solution.py']
        before = {str(p):p.read_bytes() for p in files}
        first = self.prepare()
        output = self.arguments['output'];catalog = json.loads((output/'catalog.json').read_bytes())
        task = catalog['tasks']['example-task']
        self.assertEqual(task['source_files']['solution.py'].encode(),self.committed)
        self.assertNotIn('untracked.py',task['source_files'])
        self.assertEqual(task['source_files']['license'].encode(),b'Example MIT notice\r\n')
        self.assertEqual((output/'notices/license').read_bytes(),b'Example MIT notice\r\n')
        self.assertEqual((output/'patches'/ (digest(self.patch_bytes)+'.patch')).read_bytes(),self.patch_bytes)
        self.assertEqual(task['checks'],self.check_data)
        self.assertFalse(first['checks_executed'])
        self.assertFalse(self.marker.exists())
        self.assertEqual({str(p):p.read_bytes() for p in files},before)
        self.assertEqual((self.repo/'.git/index').read_bytes(),index)
        second = self.prepare(output=self.root/'second-bundle')
        for key in ('source_digest','check_digest','rubric_digest','catalog_digest','prediction_digest'):
            self.assertEqual(first[key],second[key])
        self.assertEqual((output/'catalog.json').read_bytes(),(self.root/'second-bundle/catalog.json').read_bytes())
        w=Workbench(self.root/'runtime',fixture_dir=output)
        batch=w.import_approved('prepared')
        item=w.submissions(batch['id'])[0]
        self.assertTrue(item['trusted_tuple']);self.assertEqual(item['origin'],'public_upstream')
        self.assertEqual(item['execution_status'],'queued');self.assertIsNone(item['result'])
        self.assertFalse((w.root/'attempts').exists())

    def test_supplied_swe_predictions_preserved_and_extra_patch_not_admitted(self):
        records=[{'instance_id':'example-task','model_name_or_path':model,'model_patch':value}
                 for model,value in [('publisher-one',self.patch_bytes.decode()),('publisher-two',self.patch_bytes.decode()),
                                     ('unapproved',self.patch_bytes.decode()+'\n')]]
        raw=b'\n'.join(canonical(record) for record in records)  # no final newline
        path=self.root/'predictions.jsonl';path.write_bytes(raw)
        summary=self.prepare(predictions=path,input_format='swebench')
        self.assertEqual(summary['unapproved_prediction_records'],1)
        self.assertEqual((self.arguments['output']/'predictions.jsonl').read_bytes(),raw)
        w=Workbench(self.root/'runtime',fixture_dir=self.arguments['output']);batch=w.import_approved('prepared')
        self.assertEqual([batch[k] for k in ('raw_lines','duplicate_lines','unique_items')],[3,1,2])
        approved=next(i for i in w.submissions(batch['id']) if i['trusted_tuple'])
        self.assertEqual([line['declared_model'] for line in approved['lineage']],['publisher-one','publisher-two'])
        pending=next(i for i in w.submissions(batch['id']) if not i['trusted_tuple'])
        self.assertEqual(pending['execution_status'],'pending-evidence')
        self.assertFalse(self.marker.exists())

    def test_unsupported_paths_types_and_missing_objects_leave_no_bundle(self):
        for source in ('../solution.py','.git/config','/absolute','./solution.py','directory','link.py','binary.dat','executable.py','submodule','untracked.py','missing'):
            with self.subTest(source=source):
                with self.assertRaises(WorkbenchError):self.prepare(sources=[source])
                self.assertFalse(self.arguments['output'].exists())
        with self.assertRaises(WorkbenchError):self.prepare(commit='missing-ref')
        self.assertFalse(self.marker.exists())
        self.assertEqual(list(self.root.glob('.bundle-pending-*')),[])

    def test_bad_checks_encoding_and_prediction_limits_are_explicit_and_atomic(self):
        for check in ([{'name':'x','argv':'shell text','timeout':1}], [{'name':'x','argv':['echo'],'timeout':0}], []):
            with self.subTest(check=check):
                self.checks.write_bytes(canonical(check))
                with self.assertRaises(WorkbenchError) as caught:self.prepare()
                self.assertEqual(caught.exception.code,'bundle-checks')
                self.assertFalse(self.arguments['output'].exists())
        self.checks.write_bytes(canonical(self.check_data))
        (self.root/'fix.patch').write_bytes(b'\xff')
        with self.assertRaises(WorkbenchError) as caught:self.prepare()
        self.assertEqual(caught.exception.code,'bundle-encoding')
        (self.root/'fix.patch').write_bytes(b'a'*(MAX_LINE_BYTES+1))
        with self.assertRaises(WorkbenchError) as caught:self.prepare()
        self.assertEqual(caught.exception.code,'bundle-predictions')
        self.assertIn('line-too-large',caught.exception.message)
        self.assertFalse(self.arguments['output'].exists())
        self.assertEqual(list(self.root.glob('.bundle-pending-*')),[])
        (self.root/'fix.patch').write_bytes(self.patch_bytes)
        predictions=self.root/'bad.jsonl';predictions.write_bytes(b'{}\n')
        with self.assertRaises(WorkbenchError):self.prepare(predictions=predictions)
        with self.assertRaises(WorkbenchError) as caught:self.prepare(input_format='swebench')
        self.assertEqual(caught.exception.code,'bundle-format')

    def test_output_overlap_existing_state_and_dangling_symlink_refused(self):
        populated=self.root/'state';populated.mkdir();(populated/'workbench.sqlite3').write_bytes(b'preserved')
        empty=self.root/'empty';empty.mkdir()
        dangling=self.root/'link';dangling.symlink_to(self.root/'new-target')
        for output in (self.repo/'new-bundle',self.root,self.task,self.root/'fix.patch',populated,empty,dangling):
            with self.subTest(output=output):
                with self.assertRaises(WorkbenchError):self.prepare(output=output)
        self.assertEqual((populated/'workbench.sqlite3').read_bytes(),b'preserved')
        self.assertFalse((self.repo/'new-bundle').exists())
        self.assertFalse((self.root/'new-target').exists())

    def test_publication_race_never_overwrites_and_staging_is_removed(self):
        def race(temporary,output):
            output.mkdir();(output/'existing').write_bytes(b'preserved')
            _publish(temporary,output)
        with patch('swe_workbench.bundle._publish',side_effect=race):
            with self.assertRaises(WorkbenchError):self.prepare()
        self.assertEqual((self.arguments['output']/'existing').read_bytes(),b'preserved')
        self.assertFalse((self.arguments['output']/'catalog.json').exists())
        self.assertEqual(list(self.root.glob('.bundle-pending-*')),[])

    def test_cli_dispatch_does_not_initialize_workbench_or_database(self):
        output=io.StringIO();runtime=self.root/'unused-runtime'
        argv=['--root',str(runtime),'--bundle','missing-default','prepare-bundle','--repo',str(self.repo),'--commit',self.commit,
              '--task-id','example-task','--task-text',str(self.task),'--source','solution.py','--checks',str(self.checks),
              '--candidates',str(self.candidates),'--provenance',str(self.provenance),'--notice','license','--output',str(self.arguments['output'])]
        with patch('swe_workbench.cli.Workbench',side_effect=AssertionError('Preparation must not initialize runtime')),redirect_stdout(output):
            self.assertEqual(main(argv),0)
        self.assertFalse(runtime.exists())
        self.assertEqual(json.loads(output.getvalue())['base_commit'],self.commit)
        self.assertFalse(self.marker.exists())

    def test_partial_clone_config_refused_without_creating_output(self):
        self.git('config','remote.origin.promisor','true')
        with self.assertRaises(WorkbenchError) as caught:self.prepare()
        self.assertEqual(caught.exception.code,'bundle-repository')
        self.assertFalse(self.arguments['output'].exists())


if __name__=='__main__':unittest.main()
