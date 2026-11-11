"""Frozen all-outcome evaluation exports, separate from accepted-code JSONL."""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import shutil
import tempfile
from .evaluation import (VERSION, STATE_EVENTS, context, material_id, require,
                         score_snapshot, score_item, _load)
from .exporter import _snapshot, _verify_artifacts, _fsync_directory
from .store import canonical, digest
from .errors import WorkbenchError

SCHEMA = 'swe-workbench-evaluation-v1'
FILES = ('evaluation.json', 'evidence.json', 'manifest.json')


def _references(snapshot, state):
    refs = {state['material_digest'], state['state_digest']}
    for event in snapshot['audit']:
        payload = event['payload']
        if event['kind'] in STATE_EVENTS:
            refs.update(payload[key] for key in ('state_digest', 'material_digest'))
        elif event['kind'] == 'result-committed':
            refs.add(payload['evidence_digest'])
    refs.update(item['result']['evidence_digest'] for item in snapshot['items'] if item.get('result'))
    return refs


def _verify_state(state, snapshot, artifacts):
    require(material_id(state['material']) == state['id']
            and digest(canonical(state['material'])) == state['material_digest'],
            'Task material identity mismatch.', 'evaluation-integrity', 409)
    expected = dict(state); expected.pop('state_digest')
    require(artifacts[state['state_digest']] == canonical(expected)
            and artifacts[state['material_digest']] == canonical(state['material']),
            'Task state/material artifact differs from the frozen context.', 'evaluation-integrity', 409)
    task = state['material']['task']
    require(state['evaluation'] == task['evaluation'] and state['rubric'] == task['evaluation']['rubric']
            and state['requirements'] == task['evaluation']['requirements'],
            'Task score definition differs from pinned material.', 'evaluation-integrity', 409)
    latest = {}
    revisions = {}
    for event in snapshot['audit']:
        if event['kind'] not in STATE_EVENTS:
            continue
        payload = event['payload']; cid = payload['context_id']
        historic = json.loads(artifacts[payload['state_digest']])
        require(historic['id'] == cid and historic['revision'] == payload['revision']
                and historic['material_digest'] == payload['material_digest']
                and material_id(historic['material']) == cid
                and artifacts[payload['material_digest']] == canonical(historic['material']),
                'Historical task state does not bind its original audit/material.', 'evaluation-integrity', 409)
        require(historic['quality']['decision'] == payload['decision']
                and historic['revision'] == revisions.get(historic['task_id'], -1) + 1,
                'Task revision/decision audit is inconsistent.', 'evaluation-integrity', 409)
        revisions[historic['task_id']] = historic['revision']; latest[cid] = payload['state_digest']
    require(latest.get(state['id']) == state['state_digest'], 'Frozen quality state is stale at this cut.', 'evaluation-integrity', 409)
    if state['quality']['decision'] == 'approved':
        require(state['evaluation']['kind'] == 'clean'
                and not any(f['status'] == 'open' and f['severity'] in ('high','critical') for f in state['findings']),
                'Clean task membership bypasses quality gates.', 'evaluation-integrity', 409)
        qualification = state['quality'].get('qualification', {})
        require(set(qualification) == {'reference','alternate'}, 'Approval is missing reference/alternate evidence.', 'evaluation-integrity', 409)
        for role, proof in qualification.items():
            result = json.loads(artifacts[proof['evidence_digest']])
            patch_digest = state['evaluation'][role + '_patch_digest']
            require(result.get('submission_id') == proof['submission_id'] and result.get('patch_digest') == patch_digest
                    and proof['patch_digest'] == patch_digest, 'Qualified implementation identity mismatch.', 'evaluation-integrity', 409)
            item = {'id': proof['submission_id'], 'patch_digest': patch_digest, 'task_id': state['task_id'],
                    'task_text': task['task_text'], 'source_digest': state['material']['source_digest'],
                    'check_digest': state['material']['check_digest'],
                    'rubric_digest': state['material']['submission_rubric_digest'], 'execution_status': 'completed',
                    'result': result | {'evidence_digest': proof['evidence_digest']}}
            score = score_item(state, item)
            require(score['complete'] and score['score'] == score['max_score'] and score['critical_passed'] is True
                    and score['overall'] == 'passed', 'Reference/alternate qualification is not passing current evidence.', 'evaluation-integrity', 409)


def _files(export_id, envelope, encoded):
    require(export_id == 'evaluation-' + digest(canonical(envelope)), 'Evaluation export identity mismatch.', 'evaluation-integrity', 409)
    snapshot = _snapshot(envelope['snapshot'])
    state = envelope['context']
    require(set(encoded) == _references(snapshot, state), 'Evaluation artifact references are missing or extra.', 'evaluation-integrity', 409)
    artifacts = {}
    for key, value in encoded.items():
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as exc:
            raise WorkbenchError('evaluation-integrity', 'Artifact encoding is invalid.', 409) from exc
        require(digest(raw) == key, 'Evaluation artifact digest mismatch.', 'evaluation-integrity', 409)
        artifacts[key] = raw
    machine = {item['result']['evidence_digest'] for item in snapshot['items'] if item.get('result')}
    _verify_artifacts(snapshot, {key: encoded[key] for key in machine})
    _verify_state(state, snapshot, artifacts)
    scores = score_snapshot(state, snapshot)
    require(scores == envelope['scores'], 'Stored scores differ from actual criterion evidence.', 'evaluation-integrity', 409)
    record = {'context': state, 'items': scores['items'], 'summary': scores['summary']}
    clean = state['quality']['decision'] == 'approved' and state['evaluation']['kind'] == 'clean'
    evaluation = {'schema': SCHEMA, 'export_id': export_id, 'cut': snapshot['cut'],
                  'clean_tasks': [record] if clean else [], 'audit_tasks': [] if clean else [record],
                  'candidate_count': len(scores['items'])}
    evidence = {'schema': SCHEMA, 'snapshot': snapshot, 'context': state, 'scores': scores, 'artifacts': encoded}
    data = {'evaluation.json': canonical(evaluation) + b'\n', 'evidence.json': canonical(evidence) + b'\n'}
    manifest = {'schema': SCHEMA, 'export_id': export_id, 'batch_id': snapshot['batch']['id'],
                'context_id': state['id'], 'cut': snapshot['cut'], 'candidate_count': len(scores['items']),
                'clean_task_count': int(clean), 'audit_task_count': int(not clean),
                'files': {name: {'sha256': digest(raw), 'bytes': len(raw)} for name,raw in data.items()}}
    data['manifest.json'] = canonical(manifest) + b'\n'
    return data, manifest


def _prepare(w, batch_id, operation_key):
    task_ids = {item['task_id'] for item in w.submissions(batch_id)}
    require(len(task_ids) == 1, 'Evaluation exports require one task per batch.', 'evaluation-task-mismatch', 422)
    initial = context(w, next(iter(task_ids)))
    payload = {'batch_id': batch_id, 'context_id': initial['id']}
    with w.store.transaction() as con:
        prior = w.store.operation(con, 'evaluation-export', operation_key, payload)
        if prior is not None:
            row = con.execute('SELECT snapshot FROM exports WHERE id=?', (prior['export_id'],)).fetchone()
            return prior['export_id'], json.loads(row['snapshot'])
        snapshot = w._snapshot(con, batch_id)
        state = _load(w, con, initial['id'])
        envelope = {'schema': SCHEMA, 'snapshot': snapshot, 'context': state, 'scores': score_snapshot(state, snapshot)}
        export_id = 'evaluation-' + digest(canonical(envelope))
        if not con.execute('SELECT 1 FROM exports WHERE id=?', (export_id,)).fetchone():
            con.execute('INSERT INTO exports(id,batch_id,snapshot,status) VALUES(?,?,?,?)',
                        (export_id, batch_id, canonical(envelope).decode(), 'pending'))
            w.store.event(con, 'export-evaluation-prepared', {'batch_id': batch_id, 'export_id': export_id,
                                                            'context_id': initial['id'], 'cut': snapshot['cut']})
        w.store.remember(con, 'evaluation-export', operation_key, payload, {'export_id': export_id})
        return export_id, envelope


def export_evaluation(w, batch_id, output, operation_key):
    export_id, envelope = _prepare(w, batch_id, operation_key)
    encoded = {key: base64.b64encode(w.artifact_bytes(key)).decode('ascii')
               for key in sorted(_references(envelope['snapshot'], envelope['context']))}
    files, manifest = _files(export_id, envelope, encoded)
    manifest_digest = digest(files['manifest.json'])
    parent = Path(output); parent.mkdir(parents=True, exist_ok=True)
    destination = parent / manifest_digest
    if not destination.exists():
        temporary = Path(tempfile.mkdtemp(prefix='.pending-evaluation-', dir=parent))
        try:
            for name, raw in files.items():
                with (temporary / name).open('xb') as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            _fsync_directory(temporary)
            try:
                temporary.rename(destination)
            except OSError:
                if not destination.is_dir():
                    raise
            _fsync_directory(parent)
        finally:
            if temporary.exists(): shutil.rmtree(temporary)
    verified = verify_evaluation(destination)
    require(verified['ok'] and verified.get('manifest_digest') == manifest_digest,
            'Published evaluation export failed verification: ' + '; '.join(verified['errors']), 'evaluation-integrity', 409)
    for name in FILES:
        with (destination/name).open('rb') as stream: os.fsync(stream.fileno())
    _fsync_directory(destination); _fsync_directory(parent)
    with w.store.transaction() as con:
        row = con.execute('SELECT * FROM exports WHERE id=?', (export_id,)).fetchone()
        location = str(destination.resolve())
        if row['status'] == 'ready':
            require(row['manifest_digest'] == manifest_digest and row['location'] == location,
                    'Evaluation export is already bound to another publication.', 'export-conflict', 409)
        else:
            con.execute("UPDATE exports SET status='ready',manifest_digest=?,location=? WHERE id=?", (manifest_digest, location, export_id))
            w.store.event(con, 'export-evaluation-ready', {'batch_id': batch_id, 'export_id': export_id, 'manifest_digest': manifest_digest})
    return {'export_id': export_id, 'path': str(destination), 'manifest_digest': manifest_digest,
            'manifest': manifest, 'scores': envelope['scores']}


def verify_evaluation(path):
    try:
        root = Path(path)
        require(not root.is_symlink() and {p.name for p in root.iterdir()} == set(FILES)
                and all((root/name).is_file() and not (root/name).is_symlink() for name in FILES),
                'Evaluation export must contain exactly three regular files.', 'evaluation-integrity', 409)
        raw = {name: (root/name).read_bytes() for name in FILES}
        manifest = json.loads(raw['manifest.json']); evidence = json.loads(raw['evidence.json'])
        require(manifest['schema'] == SCHEMA and evidence['schema'] == SCHEMA, 'Unsupported evaluation schema.', 'evaluation-integrity', 409)
        envelope = {key: evidence[key] for key in ('schema','snapshot','context','scores')}
        expected, rebuilt = _files(manifest['export_id'], envelope, evidence['artifacts'])
        require(raw == expected, 'Evaluation bytes, scores, membership or manifest differ from frozen evidence.', 'evaluation-integrity', 409)
        return {'ok': True, 'errors': [], 'manifest_digest': digest(raw['manifest.json']),
                'export_id': rebuilt['export_id'], 'candidate_count': rebuilt['candidate_count'],
                'clean_task_count': rebuilt['clean_task_count'], 'audit_task_count': rebuilt['audit_task_count']}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, WorkbenchError) as exc:
        return {'ok': False, 'errors': [str(exc)]}
