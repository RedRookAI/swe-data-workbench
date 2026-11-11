#!/usr/bin/env python3
"""Measure one fresh synthetic stratum and one approved real-task stratum.

Linux resource counters describe this profiler/controller and its waited children.
No review decisions, model calls, services, installations or repeated load runs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from swe_workbench.core import Workbench
from swe_workbench.exporter import export_batch, verify_export

SCHEMA = "swe-workbench-pilot-v1"
MEASURED_SOURCES = ("swe_workbench/worker.py", "swe_workbench/runner.py", "swe_workbench/core.py",
                    "swe_workbench/intake.py", "swe_workbench/exporter.py", "tools/profile_pilot.py")
MEMORY_SCOPE = (
    "Linux ru_maxrss in KiB, cumulative before/after counters: self is this profiler/controller's "
    "lifetime high-water RSS; waited_children is the largest individual waited child's high-water RSS. "
    "Neither is a per-stage peak, a sum, nor a simultaneous process-group peak."
)
CPU_SCOPE = (
    "RUSAGE_SELF covers all profiler/controller threads; RUSAGE_CHILDREN covers terminated children "
    "waited for by this process, including further descendants only when intervening processes waited "
    "for them. Deltas cover this stage; they exclude unrelated host processes."
)


class PilotError(ValueError):
    pass


class StageFailure(PilotError):
    def __init__(self, cause, measurement):
        super().__init__(str(cause))
        self.measurement = measurement


def resource_sample():
    sampled = {}
    for name, who in (("self", resource.RUSAGE_SELF), ("waited_children", resource.RUSAGE_CHILDREN)):
        usage = resource.getrusage(who)
        sampled[name] = {"user_seconds": usage.ru_utime, "system_seconds": usage.ru_stime,
                         "maxrss_kib_cumulative": usage.ru_maxrss}
    return sampled


def measure_stage(action, *, sampler=resource_sample, clock=time.perf_counter_ns):
    """Return result and observations, preserving an incomplete measurement on error."""
    before = sampler()
    started = clock()
    try:
        result = action()
    except Exception as exc:
        measurement = _measurement(before, sampler(), clock() - started, complete=False)
        measurement["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise StageFailure(exc, measurement) from exc
    return result, _measurement(before, sampler(), clock() - started, complete=True)


def _measurement(before, after, elapsed_ns, *, complete):
    cpu = {}
    for scope in ("self", "waited_children"):
        user = after[scope]["user_seconds"] - before[scope]["user_seconds"]
        system = after[scope]["system_seconds"] - before[scope]["system_seconds"]
        cpu[scope] = {"user_seconds": user, "system_seconds": system, "total_seconds": user + system}
    return {"complete": complete, "wall_seconds": elapsed_ns / 1_000_000_000,
            "cpu_seconds": cpu,
            "memory_high_water_counters": {
                scope: {"before_kib": before[scope]["maxrss_kib_cumulative"],
                        "after_kib": after[scope]["maxrss_kib_cumulative"]}
                for scope in ("self", "waited_children")}}


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def capacity_snapshot():
    """Read current visible capacity; never reserve resources or alter limits."""
    if sys.platform != "linux":
        raise PilotError("This pilot's resource/memory accounting requires Linux.")
    affinity = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1
    memory = {}
    for line in (_read('/proc/meminfo') or '').splitlines():
        if line.startswith(('MemAvailable:', 'MemTotal:')):
            key, value, *_ = line.split()
            memory[key.rstrip(':')] = int(value) * 1024
    effective_cpu = float(affinity)
    available = memory.get('MemAvailable')
    cgroups = []
    cgroup_path = next((line.split(':', 2)[2] for line in (_read('/proc/self/cgroup') or '').splitlines()
                        if line.startswith('0::')), None)
    if cgroup_path is not None:
        boundary = Path('/sys/fs/cgroup')
        directory = boundary / cgroup_path.lstrip('/')
        if not directory.exists():
            directory = boundary
        for depth, directory in enumerate([directory, *directory.parents]):
            if directory != boundary and boundary not in directory.parents:
                break
            raw_cpu = _read(directory / 'cpu.max')
            raw_max = _read(directory / 'memory.max')
            raw_current = _read(directory / 'memory.current')
            if raw_cpu or raw_max or raw_current:
                cgroups.append({'visible_ancestor_depth': depth, 'cpu_max': raw_cpu,
                                'memory_max_bytes': raw_max, 'memory_current_bytes': raw_current})
            if raw_cpu:
                quota, period = raw_cpu.split()
                if quota != 'max':
                    effective_cpu = min(effective_cpu, int(quota) / int(period))
            if raw_max and raw_max != 'max' and raw_current:
                headroom = max(0, int(raw_max) - int(raw_current))
                available = min(available, headroom) if available is not None else headroom
            if directory == boundary:
                break
    return {'observed_at': datetime.now(timezone.utc).isoformat(), 'logical_cpus': os.cpu_count(),
            'affinity_cpus': affinity, 'effective_cpu_capacity': effective_cpu,
            'host_memory_bytes': memory, 'effective_available_memory_bytes': available,
            'visible_cgroup_constraints': cgroups, 'load_average_1_5_15': list(os.getloadavg()),
            'proc_loadavg': _read('/proc/loadavg'),
            'scope': 'Read-only instantaneous visible host/cgroup observations; no reservation or fleet-wide isolation.'}


def require_capacity(snapshot, workers):
    if type(workers) is not int or workers not in (1, 2):
        raise PilotError('Pilot supports exactly one or two workers.')
    if snapshot['effective_cpu_capacity'] < workers:
        raise PilotError('Observed affinity/cgroup CPU capacity is below requested workers; choose a permitted setting explicitly.')
    available = snapshot.get('effective_available_memory_bytes')
    if available is None or available < 256 * 1024 * 1024:
        raise PilotError('Observed available memory does not satisfy the existing runner 256 MiB preflight.')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _reconcile(metrics):
    counts = metrics['counts']
    if counts['raw_lines'] != counts['invalid_lines'] + counts['duplicate_lines'] + counts['unique_items']:
        raise PilotError('Frozen intake counts do not reconcile.')


def profile_stratum(name, work_dir, bundle, input_path, input_format, workers, *,
                    workbench_factory=Workbench, exporter=export_batch, verifier=verify_export):
    def intake():
        workbench = workbench_factory(work_dir, fixture_dir=bundle)
        workbench.initialize()
        batch = workbench.import_jsonl(input_path, 'pilot-intake-' + name, input_format=input_format)
        return workbench, batch

    stages = {}
    result = {'name': name, 'input_format': input_format, 'input_sha256': _sha(input_path),
              'catalog_sha256': _sha(Path(bundle) / 'catalog.json'),
              'repetitions': 1, 'workers': workers, 'cache_condition': 'Fresh independent state; no result replay or recovery requested.',
              'stages': stages}
    try:
        (workbench, batch), stages['intake'] = measure_stage(intake)
        processing, stages['process'] = measure_stage(lambda: workbench.process(batch['id'], workers=workers))
        def export_and_verify():
            exported = exporter(workbench, batch['id'], Path(work_dir) / 'exports', 'pilot-export-' + name)
            verified = verifier(exported['path'])
            if not verified['ok']:
                raise PilotError('Frozen export verification failed: ' + '; '.join(verified['errors']))
            return exported, verified
        (exported, verified), stages['export'] = measure_stage(export_and_verify)
        _reconcile(exported['metrics'])
        integrity = workbench.verify()
        if not integrity['ok']:
            raise PilotError('Core integrity check failed.')
        items = workbench.submissions(batch['id'])
        result.update({'status': 'complete', 'batch_id': batch['id'], 'metrics': exported['metrics'],
                       'processing': processing, 'origin_counts': exported['metrics']['origin_counts'],
                       'export_id': exported['export_id'], 'manifest_digest': exported['manifest_digest'],
                       'export_verification': verified, 'core_verification': integrity,
                       'source_preservation': {'measured_result_count': sum(bool(item.get('result')) for item in items),
                                               'all_measured_source_unchanged': all(item['result'].get('source_unchanged') is True
                                                                                  for item in items if item.get('result'))},
                       'review': {'decisions_recorded_by_profiler': 0, 'active_seconds': None,
                                  'unavailable_reason': 'No review performed or active review duration measured.'}})
    except StageFailure as exc:
        for name in ('intake', 'process', 'export'):
            if name not in stages:
                stages[name] = exc.measurement
                break
        result.update({'status': 'failed', 'error': str(exc)})
    except Exception as exc:
        result.update({'status': 'failed', 'error': str(exc)})
    return result


def run_pilot(root, bundle=REPO / 'bundles/unicode-hyphen', workers=2, *, preflight=None,
              workbench_factory=Workbench, exporter=export_batch, verifier=verify_export):
    root, bundle = Path(root).resolve(), Path(bundle).resolve()
    if root.exists():
        raise PilotError('Pilot base root already exists; preserve prior evidence and select a fresh root.')
    observed = capacity_snapshot() if preflight is None else preflight
    require_capacity(observed, workers)
    strata = [('synthetic', REPO / 'fixtures', REPO / 'fixtures/sample.jsonl', 'native'),
              ('real-configured', bundle, bundle / 'predictions.jsonl', 'swebench')]
    for _, catalog_dir, source, _ in strata:
        if not source.is_file() or not (catalog_dir / 'catalog.json').is_file():
            raise PilotError('Declared pilot source or catalog is missing.')
    root.mkdir(parents=True, exist_ok=False)
    report = {'schema': SCHEMA, 'started_at': datetime.now(timezone.utc).isoformat(),
              'runtime': {'python': platform.python_version(), 'platform': sys.platform,
                          'wall_clock': time.get_clock_info('perf_counter').implementation},
              'implementation': {'source_sha256': {name: _sha(REPO / name) for name in MEASURED_SOURCES},
                                 'revision_scope': 'Exact source bytes at pilot start; no assertion that working files are committed.'},
              'capacity_before': observed, 'measurement_scope': {'cpu': CPU_SCOPE, 'memory': MEMORY_SCOPE,
              'stages': 'Intake includes initialization/import; process includes controller and waited workers; export includes freeze/publication/offline verification. Workload hashing and final integrity/readback occur outside these stages.'},
              'workload': {'strata': 2, 'repetitions_per_stratum': 1, 'workers': workers,
                           'model_calls': 0, 'review_decisions': 0,
                           'representativeness': 'One authored synthetic fixture batch and one configured historical upstream issue with authored controls; no production representativeness or speedup claim.'},
              'strata': []}
    for name, catalog_dir, source, input_format in strata:
        result = profile_stratum(name, root / name, catalog_dir, source, input_format, workers,
                                 workbench_factory=workbench_factory, exporter=exporter, verifier=verifier)
        report['strata'].append(result)
        if result['status'] != 'complete':
            break
    report['status'] = 'complete' if len(report['strata']) == 2 and all(s['status'] == 'complete' for s in report['strata']) else 'failed'
    if report['status'] == 'complete':
        keys = ('raw_lines', 'invalid_lines', 'duplicate_lines', 'unique_items', 'completed_measurements')
        report['combined_accounting'] = {key: sum(s['metrics']['counts'][key] for s in report['strata']) for key in keys}
        report['combined_accounting']['scope'] = 'Sum of separately rooted strata; task/submission uniqueness is scoped to each batch, not an assertion of global uniqueness.'
        totals = {stage: sum(s['stages'][stage]['wall_seconds'] for s in report['strata']) for stage in ('intake', 'process', 'export')}
        report['observed_stage_wall_seconds'] = totals
        report['limiting_stage_observation'] = {'largest_measured_stage': max(totals, key=totals.get),
            'interpretation': 'Largest elapsed stage in this single bounded workload only. No causal bottleneck, production limit, speedup, or optimization benefit established.'}
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='Fresh base directory; prior state is never reset')
    parser.add_argument('--output', type=Path, help='New JSON report path; default ROOT/pilot.json')
    parser.add_argument('--bundle', type=Path, default=REPO / 'bundles/unicode-hyphen')
    parser.add_argument('--workers', type=int, default=2, choices=(1, 2))
    args = parser.parse_args()
    output = args.output or args.root / 'pilot.json'
    if output.exists():
        parser.error('Output already exists; select a new report path.')
    try:
        report = run_pilot(args.root, args.bundle, args.workers)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n')
    except PilotError as exc:
        parser.exit(2, str(exc) + '\n')
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
