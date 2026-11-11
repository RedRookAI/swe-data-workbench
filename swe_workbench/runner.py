"""Owned local controller: intent, launch gate, generation fencing and recovery.

Linux process identity uses boot ID and /proc start ticks. Recovery never signals
an unknown process. Control-channel EOF makes a registered worker kill only its
own dedicated group; a surviving/indeterminate group stays explicitly uncertain.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from .errors import WorkbenchError
from .store import canonical, digest, now


def _proc(pid):
    try:
        parts = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': int(pid), 'state': parts[0], 'pgid': int(parts[2]), 'start_ticks': parts[19]}
    except FileNotFoundError:
        return None
    except (OSError, ValueError, IndexError):
        return {'unknown': True}


def process_identity(pid):
    identity = _proc(pid)
    if not identity or identity.get('unknown'):
        raise WorkbenchError('worker-identity', 'Cannot establish worker process-start identity.', 409)
    identity.pop('state')
    identity['boot_id'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    return identity


def owned_state(identity):
    """stopped/live/uncertain; scan group even if its original leader exited."""
    if not identity or not all(k in identity for k in ('pid', 'pgid', 'start_ticks', 'boot_id')):
        return 'uncertain'
    try:
        if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != identity['boot_id']:
            return 'stopped'
        leader = _proc(identity['pid'])
        if leader and leader.get('unknown'):
            return 'uncertain'
        if leader and leader['start_ticks'] != identity['start_ticks']:
            # PID reused: original leader is gone but group identity cannot be
            # reestablished without inspecting its remaining members.
            leader = None
        live = False
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            child = _proc(entry.name)
            if child and child.get('unknown'):
                return 'uncertain'
            if child and child['pgid'] == identity['pgid'] and child['state'] not in ('Z', 'X'):
                live = True
        if not live:
            return 'stopped'
        return 'live' if leader else 'uncertain'
    except OSError:
        return 'uncertain'


@contextmanager
def controller_lock(root):
    with (Path(root) / 'controller.lock').open('a+b') as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkbenchError('controller-owned', 'A live controller already owns processing; no timer can steal it.', 409) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def recover(workbench):
    store = workbench.store
    with store.transaction() as con:
        rows = con.execute("SELECT a.*,r.batch_id FROM attempts a JOIN runs r ON a.run_id=r.id WHERE a.state IN ('intent','registered','uncertain') ORDER BY a.created_at").fetchall()
        blocked = []
        for attempt in rows:
            # Intent has never been granted permission; channel EOF stops any
            # spawned but unregistered child before it can execute.
            state = 'stopped' if attempt['state'] == 'intent' else owned_state(json.loads(attempt['identity']) if attempt['identity'] else None)
            if state != 'stopped':
                con.execute("UPDATE attempts SET state='uncertain' WHERE id=?", (attempt['id'],))
                changed = con.execute("UPDATE submissions SET execution_status='uncertain',revision=revision+1 WHERE id=? AND active_attempt=? AND execution_status!='uncertain'", (attempt['submission_id'], attempt['id'])).rowcount
                if changed:
                    store.event(con, 'attempt-uncertain', {'batch_id': attempt['batch_id'], 'submission_id': attempt['submission_id'], 'attempt_id': attempt['id'], 'observed_state': state})
                blocked.append(attempt['id'])
                continue
            con.execute("UPDATE attempts SET state='interrupted' WHERE id=?", (attempt['id'],))
            con.execute("UPDATE submissions SET execution_status='queued',active_attempt=NULL,revision=revision+1 WHERE id=? AND active_attempt=?", (attempt['submission_id'], attempt['id']))
            store.event(con, 'attempt-recovered', {'batch_id': attempt['batch_id'], 'submission_id': attempt['submission_id'], 'attempt_id': attempt['id'], 'generation': attempt['generation'], 'observation': 'owned group stopped or permission never granted'})
        con.execute("UPDATE runs SET status='interrupted' WHERE status='running'")
        return blocked


def _claim(workbench, con, batch_id, run_id):
    row = con.execute("SELECT s.* FROM submissions s WHERE s.id IN (SELECT submission_id FROM memberships WHERE batch_id=?) AND s.execution_status='queued' AND s.active_attempt IS NULL ORDER BY s.id LIMIT 1", (batch_id,)).fetchone()
    if not row:
        return None
    item = json.loads(row['data'])
    task = workbench.catalog['tasks'].get(item['task_id'])
    current = workbench._record({'task_id': item['task_id'], 'patch': item['patch'], 'task_text': item['task_text'], 'schema_version': 1})
    if not task or not current['trusted_tuple'] or any(item.get(k) != current.get(k) for k in ('source_digest','patch_digest','check_digest','rubric_digest','task_text')):
        con.execute("UPDATE submissions SET execution_status='pending-evidence',revision=revision+1 WHERE id=?", (item['id'],))
        workbench.store.event(con, 'tuple-refused', {'batch_id': batch_id, 'submission_id': item['id'], 'reason': 'Current manifest does not match pinned source/patch/check/rubric tuple.'})
        return {'refused': True}
    attempt_id = 'attempt-' + uuid.uuid4().hex
    generation = row['generation'] + 1
    revision = row['revision'] + 1
    con.execute('INSERT INTO attempts(id,run_id,submission_id,generation,expected_revision,state,created_at) VALUES(?,?,?,?,?,?,?)',
                (attempt_id, run_id, item['id'], generation, revision, 'intent', now()))
    changed = con.execute("UPDATE submissions SET execution_status='running',generation=?,active_attempt=?,revision=? WHERE id=? AND revision=? AND active_attempt IS NULL",
                          (generation, attempt_id, revision, item['id'], row['revision'])).rowcount
    if not changed:
        raise WorkbenchError('claim-conflict', 'Submission claim lost its current revision.', 409)
    workbench.store.event(con, 'attempt-intent', {'batch_id': batch_id, 'run_id': run_id, 'submission_id': item['id'], 'attempt_id': attempt_id, 'generation': generation, 'revision': revision})
    return {'attempt_id': attempt_id, 'run_id': run_id, 'batch_id': batch_id, 'submission_id': item['id'], 'generation': generation,
            'revision': revision, 'task': task, 'patch': item['patch'], 'bindings': {k:item[k] for k in ('source_digest','patch_digest','check_digest','rubric_digest')}}


def _execute(workbench, claim):
    store = workbench.store
    attempt_dir = workbench.root / 'attempts' / claim['attempt_id']
    attempt_dir.mkdir(parents=True, mode=0o700)
    job_path, result_path = attempt_dir / 'job.json', attempt_dir / 'result.json'
    job_path.write_bytes(canonical({'task': claim['task'], 'patch': claim['patch'], 'work_dir': str(attempt_dir / 'workspace')}))
    catalog_before = digest((workbench.fixture_dir / 'catalog.json').read_bytes())
    read_fd, write_fd = os.pipe()
    child = None
    identity = None
    try:
        # Preserve importability from any working directory without injecting
        # third-party paths or secrets into the authored checks' environment.
        package_root = str(Path(__file__).resolve().parent.parent)
        env = {'PATH': os.defpath, 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
               'PYTHONPATH': package_root, 'PYTHONIOENCODING': 'utf-8',
               'PYTHONDONTWRITEBYTECODE': '1'}
        with (attempt_dir / 'worker.stderr').open('wb') as stderr:
            child = subprocess.Popen([sys.executable, '-m', 'swe_workbench.worker', '--job', str(job_path), '--result', str(result_path), '--control-fd', str(read_fd)],
                                     pass_fds=(read_fd,), close_fds=True, start_new_session=True,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr, env=env)
            os.close(read_fd)
            read_fd = -1
            identity = process_identity(child.pid)
            if identity['pgid'] != child.pid:
                raise WorkbenchError('worker-group', 'Worker does not own its dedicated process group.', 409)
            with store.transaction() as con:
                changed = con.execute("UPDATE attempts SET identity=?,state='registered' WHERE id=? AND state='intent'", (canonical(identity).decode(), claim['attempt_id'])).rowcount
                current = con.execute('SELECT active_attempt,generation,revision FROM submissions WHERE id=?', (claim['submission_id'],)).fetchone()
                if not changed or current['active_attempt'] != claim['attempt_id'] or current['generation'] != claim['generation'] or current['revision'] != claim['revision']:
                    raise WorkbenchError('launch-conflict', 'Worker permission refused for stale attempt.', 409)
                store.event(con, 'worker-registered', {'batch_id': claim['batch_id'], 'attempt_id': claim['attempt_id'], 'submission_id': claim['submission_id'], 'identity': identity})
            os.write(write_fd, b'G')
            # A finite timeout comes from the bounded manifest, never input.
            timeout = sum(float(c.get('timeout', 5)) for c in claim['task']['checks']) * 2 + 10
            try:
                child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.close(write_fd)
                write_fd = -1
                child.wait(timeout=3)
                return {'error': 'Worker exceeded its controller timeout.', 'identity': identity}
        if child.returncode != 0 or not result_path.exists():
            return {'error': 'Worker exited without a committed evidence envelope.', 'identity': identity}
        result = json.loads(result_path.read_bytes())
        result['source_unchanged'] = bool(result.get('source_unchanged') and catalog_before == digest((workbench.fixture_dir / 'catalog.json').read_bytes()))
        if not result['source_unchanged']:
            result['overall'] = 'error'
        result.update(claim['bindings'])
        result.update({'attempt_id': claim['attempt_id'], 'generation': claim['generation'], 'submission_id': claim['submission_id']})
        return {'result': result, 'identity': identity}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {'error': 'Worker launch or result error: ' + type(exc).__name__, 'identity': identity}
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)
        if child and child.poll() is None:
            # EOF is the sole normal cleanup signal; never signal a PID that may
            # have been recycled or an unrelated inherited process group.
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass


def commit_result(workbench, claim, outcome):
    store = workbench.store
    result = outcome.get('result')
    if result:
        expected = claim['bindings'] | {'attempt_id': claim['attempt_id'], 'generation': claim['generation'],
                                         'submission_id': claim['submission_id']}
        if any(result.get(key) != value for key, value in expected.items()):
            raise WorkbenchError('stale-result', 'Worker evidence does not bind this exact attempt and content.', 409)
        evidence_digest = store.artifact_write(canonical(result))
        result = dict(result, evidence_digest=evidence_digest)
    else:
        evidence_digest = None
    with store.transaction() as con:
        attempt = con.execute('SELECT * FROM attempts WHERE id=?', (claim['attempt_id'],)).fetchone()
        if attempt and attempt['state'] == 'committed' and evidence_digest and attempt['result_digest'] == evidence_digest:
            return False  # Lost acknowledgement: same immutable operation.
        item = con.execute('SELECT * FROM submissions WHERE id=?', (claim['submission_id'],)).fetchone()
        if not attempt or attempt['state'] not in {'intent','registered'} or not item or item['active_attempt'] != claim['attempt_id'] or item['generation'] != claim['generation'] or item['revision'] != claim['revision']:
            raise WorkbenchError('stale-result', 'Attempt result cannot overwrite current submission authority.', 409)
        state = owned_state(outcome.get('identity')) if outcome.get('identity') else 'stopped'
        if state != 'stopped':
            con.execute("UPDATE attempts SET state='uncertain' WHERE id=?", (claim['attempt_id'],))
            con.execute("UPDATE submissions SET execution_status='uncertain',revision=revision+1 WHERE id=?", (claim['submission_id'],))
            store.event(con, 'attempt-uncertain', {'batch_id': claim['batch_id'], 'submission_id': claim['submission_id'], 'attempt_id': claim['attempt_id'], 'observed_state': state})
            return False
        if result:
            status = 'completed' if result['overall'] in ('passed', 'failed') else 'execution-error'
            con.execute("UPDATE attempts SET state='committed',result_digest=? WHERE id=?", (evidence_digest, claim['attempt_id']))
            con.execute('UPDATE submissions SET execution_status=?,result=?,active_attempt=NULL,revision=revision+1 WHERE id=?', (status, canonical(result).decode(), claim['submission_id']))
            store.event(con, 'result-committed', {'batch_id': claim['batch_id'], 'run_id': claim['run_id'], 'submission_id': claim['submission_id'], 'attempt_id': claim['attempt_id'], 'generation': claim['generation'], 'evidence_digest': evidence_digest, 'overall': result['overall']})
        else:
            con.execute("UPDATE attempts SET state='execution-error' WHERE id=?", (claim['attempt_id'],))
            con.execute("UPDATE submissions SET execution_status='execution-error',active_attempt=NULL,revision=revision+1 WHERE id=?", (claim['submission_id'],))
            store.event(con, 'execution-error', {'batch_id': claim['batch_id'], 'submission_id': claim['submission_id'], 'attempt_id': claim['attempt_id'], 'error': outcome.get('error', 'Missing result')})
        return bool(result)


def process(workbench, batch_id, workers=1, *, stop_after=None):
    if type(workers) is not int or workers not in (1, 2):
        raise WorkbenchError('invalid-workers', 'Local fixture processing supports one or two workers.')
    if stop_after is not None and (type(stop_after) is not int or stop_after < 0):
        raise WorkbenchError('invalid-stop', 'stop_after must be a nonnegative integer.')
    if workers == 2:
        # Cheap current preflight, without changing host limits or services.
        available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))
        if available < 256 * 1024 or (os.cpu_count() or 1) < 2:
            raise WorkbenchError('capacity', 'Current local capacity does not permit two fixture workers.', 409)
    store = workbench.store
    completed, observed = [], 0
    started = time.monotonic()
    with controller_lock(workbench.root):
        workbench.batch(batch_id)
        blocked = recover(workbench)
        if blocked:
            raise WorkbenchError('unresolved-execution', 'Live or indeterminate owned attempts remain; no work was stolen.', 409)
        with store.transaction() as con:
            previous = con.execute("SELECT id FROM runs WHERE batch_id=? AND status='interrupted' ORDER BY created_at DESC LIMIT 1", (batch_id,)).fetchone()
            run_id = previous['id'] if previous else 'run-' + uuid.uuid4().hex
            identity = canonical(process_identity(os.getpid())).decode()
            if previous:
                con.execute("UPDATE runs SET status='running',controller=?,workers=? WHERE id=?", (identity, workers, run_id))
            else:
                con.execute('INSERT INTO runs VALUES(?,?,?,?,?,?)', (run_id, batch_id, 'running', identity, workers, now()))
            segment_id = 'segment-' + uuid.uuid4().hex
            con.execute('INSERT INTO segments(id,run_id) VALUES(?,?)', (segment_id, run_id))
            store.event(con, 'run-resumed' if previous else 'run-started', {'batch_id': batch_id, 'run_id': run_id, 'workers': workers, 'segment_id': segment_id})
        pending = {}
        launched = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            while True:
                while len(pending) < workers and (stop_after is None or launched < stop_after):
                    with store.transaction() as con:
                        claim = _claim(workbench, con, batch_id, run_id)
                    if not claim:
                        break
                    if claim.get('refused'):
                        continue
                    pending[executor.submit(_execute, workbench, claim)] = claim
                    launched += 1
                    observed = max(observed, len(pending))
                if not pending:
                    break
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    claim = pending.pop(future)
                    outcome = future.result()
                    if commit_result(workbench, claim, outcome):
                        completed.append(claim['submission_id'])
                    # Persist the count per segment after each commit; if this
                    # write is interrupted, incomplete means no throughput claim.
                    with store.transaction() as con:
                        con.execute('UPDATE segments SET completed_ids=? WHERE id=?', (canonical(completed).decode(), segment_id))
        elapsed = time.monotonic() - started
        with store.transaction() as con:
            remaining = con.execute("SELECT count(DISTINCT s.id) FROM submissions s JOIN memberships m ON s.id=m.submission_id WHERE m.batch_id=? AND s.execution_status IN ('queued','running','interrupted','uncertain')", (batch_id,)).fetchone()[0]
            interrupted = remaining > 0
            con.execute('UPDATE segments SET complete=1,elapsed_seconds=?,completed_ids=? WHERE id=?', (elapsed, canonical(completed).decode(), segment_id))
            con.execute('UPDATE runs SET status=? WHERE id=?', ('interrupted' if interrupted else 'completed', run_id))
            store.event(con, 'run-interrupted' if interrupted else 'run-completed', {'batch_id': batch_id, 'run_id': run_id, 'segment_id': segment_id,
                        'completed_ids': completed, 'elapsed_seconds': elapsed, 'observed_max_workers': observed, 'deliberate_stop': stop_after is not None and interrupted})
        return {'batch_id': batch_id, 'run_id': run_id, 'workers': workers, 'processed': len(completed), 'completed_ids': completed,
                'interrupted': interrupted, 'elapsed_seconds': elapsed, 'observed_max_workers': observed, 'counts': workbench.batch(batch_id)['counts']}
