"""Profiler accounting with explicit transport doubles; no workload executes here."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('profile_pilot', REPO / 'tools/profile_pilot.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def sample(user, system, rss, child_user, child_system, child_rss):
    return {'self': {'user_seconds': user, 'system_seconds': system, 'maxrss_kib_cumulative': rss},
            'waited_children': {'user_seconds': child_user, 'system_seconds': child_system,
                                'maxrss_kib_cumulative': child_rss}}


class MeasurementTests(unittest.TestCase):
    def test_stage_cpu_deltas_and_memory_counters_are_distinct(self):
        observations = iter([sample(1, 2, 100, 3, 4, 300), sample(2, 4, 120, 5, 9, 500)])
        ticks = iter([1_000_000_000, 3_500_000_000])
        result, measured = profile.measure_stage(lambda: 'actual-result', sampler=lambda: next(observations), clock=lambda: next(ticks))
        self.assertEqual(result, 'actual-result')
        self.assertTrue(measured['complete'])
        self.assertEqual(measured['wall_seconds'], 2.5)
        self.assertEqual(measured['cpu_seconds']['self']['total_seconds'], 3)
        self.assertEqual(measured['cpu_seconds']['waited_children']['total_seconds'], 7)
        self.assertEqual(measured['memory_high_water_counters']['self'], {'before_kib': 100, 'after_kib': 120})
        self.assertEqual(measured['memory_high_water_counters']['waited_children'], {'before_kib': 300, 'after_kib': 500})
        self.assertNotIn('memory_peak', measured)
        self.assertIn('Neither is a per-stage peak', profile.MEMORY_SCOPE)

    def test_exception_retains_incomplete_stage_without_success_result(self):
        observations = iter([sample(1, 2, 100, 3, 4, 300), sample(1, 3, 100, 3, 5, 300)])
        ticks = iter([0, 1_000_000_000])
        def fail():
            raise RuntimeError('deliberate stopped measurement')
        with self.assertRaises(profile.StageFailure) as caught:
            profile.measure_stage(fail, sampler=lambda: next(observations), clock=lambda: next(ticks))
        measured = caught.exception.measurement
        self.assertFalse(measured['complete'])
        self.assertEqual(measured['wall_seconds'], 1)
        self.assertEqual(measured['error']['type'], 'RuntimeError')


class FakeWorkbench:
    """Declared interface double: tests orchestration, never real task outcomes."""
    calls = []
    def __init__(self, root, fixture_dir):
        self.root = Path(root)
        self.name = self.root.name
        self.fixture_dir = Path(fixture_dir)
    def initialize(self):
        self.root.mkdir(parents=True)
        self.calls.append((self.name, 'initialize'))
    def import_jsonl(self, path, operation_key, *, input_format):
        self.calls.append((self.name, 'import', Path(path).name, input_format))
        return {'id': self.name + '-batch'}
    def process(self, batch_id, workers):
        self.calls.append((self.name, 'process', workers))
        return {'processed': 4 if self.name == 'synthetic' else 2, 'workers': workers}
    def verify(self):
        return {'ok': True}
    def submissions(self, batch_id):
        return [{'result': {'source_unchanged': True}}]


def fake_export(workbench, batch_id, output_dir, operation_key):
    synthetic = workbench.name == 'synthetic'
    counts = {'raw_lines': 8 if synthetic else 4, 'invalid_lines': 1 if synthetic else 0,
              'duplicate_lines': 1, 'unique_items': 6 if synthetic else 3,
              'completed_measurements': 4 if synthetic else 2}
    return {'path': str(output_dir), 'export_id': 'fake-' + workbench.name, 'manifest_digest': 'f' * 64,
            'metrics': {'counts': counts, 'origin_counts': {'explicit-test-double': counts['unique_items']}}}


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=REPO)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'fresh'
        self.preflight = {'effective_cpu_capacity': 2, 'effective_available_memory_bytes': 1024 ** 3}
        FakeWorkbench.calls = []
    def run_double(self, **kwargs):
        return profile.run_pilot(self.root, workers=2, preflight=self.preflight, workbench_factory=FakeWorkbench,
                                 exporter=kwargs.get('exporter', fake_export), verifier=lambda path: {'ok': True})
    def test_two_strata_once_fresh_and_accounting_reconciles(self):
        report = self.run_double()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(set(report['implementation']['source_sha256']), set(profile.MEASURED_SOURCES))
        self.assertTrue(all(len(value) == 64 for value in report['implementation']['source_sha256'].values()))
        self.assertEqual(report['combined_accounting']['raw_lines'], 12)
        self.assertEqual(report['combined_accounting']['unique_items'], 9)
        self.assertEqual(report['combined_accounting']['duplicate_lines'], 2)
        self.assertEqual(report['combined_accounting']['invalid_lines'], 1)
        self.assertEqual(report['combined_accounting']['completed_measurements'], 6)
        self.assertEqual([call for call in FakeWorkbench.calls if call[1] == 'import'],
                         [('synthetic', 'import', 'sample.jsonl', 'native'),
                          ('real-configured', 'import', 'predictions.jsonl', 'swebench')])
        self.assertEqual(len([call for call in FakeWorkbench.calls if call[1] == 'process']), 2)
        for stratum in report['strata']:
            self.assertEqual(stratum['repetitions'], 1)
            self.assertEqual(stratum['review']['decisions_recorded_by_profiler'], 0)
            self.assertIsNone(stratum['review']['active_seconds'])
            self.assertEqual(set(stratum['stages']), {'intake', 'process', 'export'})
            self.assertTrue(all(stage['complete'] for stage in stratum['stages'].values()))
        with self.assertRaisesRegex(profile.PilotError, 'already exists'):
            self.run_double()
        self.assertEqual(len([call for call in FakeWorkbench.calls if call[1] == 'process']), 2)
    def test_insufficient_cpu_or_memory_refuses_before_creating_state(self):
        for preflight in ({'effective_cpu_capacity': 1, 'effective_available_memory_bytes': 1024 ** 3},
                          {'effective_cpu_capacity': 2, 'effective_available_memory_bytes': 1024}):
            self.preflight = preflight
            with self.assertRaises(profile.PilotError):
                self.run_double()
            self.assertFalse(self.root.exists())
        self.assertEqual(FakeWorkbench.calls, [])
    def test_export_failure_stops_after_first_stratum_and_preserves_measurement(self):
        def fail(*args):
            raise RuntimeError('deliberate publication failure')
        report = self.run_double(exporter=fail)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(len(report['strata']), 1)
        self.assertFalse(report['strata'][0]['stages']['export']['complete'])
        self.assertNotIn('combined_accounting', report)
        self.assertTrue((self.root / 'synthetic').exists())
    def test_mismatched_frozen_accounting_is_not_reported_complete(self):
        def mismatched(*args):
            result = fake_export(*args)
            result['metrics']['counts']['raw_lines'] += 1
            return result
        report = self.run_double(exporter=mismatched)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('do not reconcile', report['strata'][0]['error'])
        self.assertNotIn('combined_accounting', report)


if __name__ == '__main__':
    unittest.main()
