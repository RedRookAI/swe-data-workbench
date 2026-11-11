"""Protected-role controls, without an OS isolation claim or original-task scores."""
import copy
import difflib
import json
from pathlib import Path
import tempfile
import unittest

from swe_workbench.core import Workbench
from swe_workbench.store import canonical, digest
from swe_workbench.worker import evaluate

BASE = 'def value():\n    return 0\n'
CHECK = """import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('candidate_solution', Path.cwd() / 'solution.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.value() in (1, 2)
print('external behavioral check passed')
"""


def patch_for(text):
    return ''.join(difflib.unified_diff(BASE.splitlines(True), text.splitlines(True), fromfile='a/solution.py', tofile='b/solution.py'))


class WorkerVerifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reference = patch_for('def value():\n    return 1\n')
        self.alternate = patch_for('def value():\n    return 2\n')
        self.task = {'title': 'Verifier role test', 'task_text': 'Return one or two.',
                     'source_files': {'solution.py': BASE}, 'verifier_files': {'check.py': CHECK},
                     'checks': [{'name': 'behavior', 'argv': ['{python}', '{verifier}/check.py'], 'timeout': 3}],
                     'patches': [self.reference, self.alternate]}

    def measure(self, patch, name='attempt'):
        self.task['patches'].append(patch)
        return evaluate(self.task, patch, self.root / name)

    def assert_protected(self, result, name='attempt'):
        integrity = result['verifier_integrity']
        self.assertTrue(integrity['unchanged'])
        self.assertEqual(integrity['verifier_digest'], digest(canonical(self.task['verifier_files'])))
        self.assertEqual([o['stage'] for o in integrity['observations']], ['before_baseline', 'after_baseline', 'before_candidate', 'after_candidate'])
        self.assertTrue(all(o['unchanged'] for o in integrity['observations']))
        self.assertEqual((self.root / name / 'verifier/check.py').read_text(), CHECK)
        self.assertFalse((self.root / name / 'candidate/verifier').exists())

    def test_reference_and_alternate_use_same_external_behavioral_verifier(self):
        for name, patch in [('reference', self.reference), ('alternate', self.alternate)]:
            with self.subTest(name=name):
                result = self.measure(patch, name)
                self.assertEqual(result['baseline']['overall'], 'failed')
                self.assertEqual(result['candidate']['overall'], 'passed')
                self.assertEqual(result['overall'], 'passed')
                self.assertEqual(result['runner'], 'trusted-task-worker-v4')
                self.assertEqual(result['candidate']['checks'][0]['argv'], self.task['checks'][0]['argv'])
                self.assertNotIn(str(self.root), json.dumps(result))
                self.assertTrue(result['source_unchanged'])
                self.assert_protected(result, name)

    def test_candidate_local_fake_checker_cannot_replace_external_entrypoint(self):
        fake = 'diff --git a/check.py b/check.py\nnew file mode 100644\n--- /dev/null\n+++ b/check.py\n@@ -0,0 +1 @@\n+raise SystemExit(0)\n'
        result = self.measure(fake)
        self.assertEqual(result['patch_application']['outcome'], 'passed')
        self.assertEqual(result['candidate']['overall'], 'failed')
        self.assertEqual(result['overall'], 'failed')
        self.assertTrue((self.root / 'attempt/candidate/check.py').is_file())
        self.assert_protected(result)

    def test_traversal_patch_cannot_target_sibling_verifier(self):
        evil = ''.join(difflib.unified_diff(CHECK.splitlines(True), ['raise SystemExit(0)\n'],
                     fromfile='a/../verifier/check.py', tofile='b/../verifier/check.py'))
        result = self.measure(evil)
        self.assertEqual(result['patch_application']['outcome'], 'failed')
        self.assertEqual(result['overall'], 'error')
        self.assertTrue(all(c['outcome'] == 'not-run' for c in result['candidate']['checks']))
        self.assert_protected(result)

    def test_symlink_patch_is_refused_before_grading(self):
        evil = 'diff --git a/link b/link\nnew file mode 120000\n--- /dev/null\n+++ b/link\n@@ -0,0 +1 @@\n+../verifier/check.py\n'
        result = self.measure(evil)
        self.assertEqual(result['patch_application']['outcome'], 'passed')
        self.assertEqual(result['candidate']['overall'], 'error')
        self.assertTrue(all(c['outcome'] == 'not-run' for c in result['candidate']['checks']))
        self.assert_protected(result)

    def test_runtime_verifier_mutation_invalidates_even_passing_measurement(self):
        text = "from pathlib import Path\ndef value():\n    (Path.cwd().parent / 'verifier/check.py').write_text('raise SystemExit(0)\\n')\n    return 1\n"
        result = self.measure(patch_for(text))
        self.assertEqual(result['candidate']['overall'], 'passed')
        self.assertEqual(result['overall'], 'error')
        self.assertFalse(result['verifier_integrity']['unchanged'])
        self.assertFalse(result['verifier_integrity']['observations'][-1]['unchanged'])
        # The observed mutation is retained as evidence, not silently repaired.
        self.assertEqual((self.root / 'attempt/verifier/check.py').read_text(), 'raise SystemExit(0)\n')

    def test_verifier_contents_change_context_while_legacy_digest_is_unchanged(self):
        folder = self.root / 'bundle'; folder.mkdir()
        catalog = {'rubric': {'version': 1}, 'tasks': {'role-test': self.task}}
        (folder / 'catalog.json').write_bytes(canonical(catalog))
        record = {'task_id': 'role-test', 'patch': self.reference}
        first = Workbench(self.root / 'unused', folder)._record(record)
        self.assertEqual(first['check_digest'], digest(canonical({'checks': self.task['checks'], 'verifier_files': self.task['verifier_files']})))
        changed = copy.deepcopy(catalog)
        changed['tasks']['role-test']['verifier_files']['check.py'] += '# versioned repair\n'
        (folder / 'catalog.json').write_bytes(canonical(changed))
        second = Workbench(self.root / 'unused', folder)._record(record)
        self.assertNotEqual(first['id'], second['id'])
        del changed['tasks']['role-test']['verifier_files']
        (folder / 'catalog.json').write_bytes(canonical(changed))
        legacy = Workbench(self.root / 'unused', folder)._record(record)
        self.assertEqual(legacy['check_digest'], digest(canonical(self.task['checks'])))

    def test_invalid_protected_paths_refused_before_execution(self):
        for index, relative in enumerate(('../check.py', '/check.py', '.git/config', './check.py')):
            with self.subTest(relative=relative):
                self.task['verifier_files'] = {relative: CHECK}
                with self.assertRaises(ValueError):
                    self.measure(self.reference, name='invalid-' + str(index))
