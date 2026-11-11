"""Public, framework-independent Workbench API. SQLite is the mutation authority."""
from __future__ import annotations
import json
import base64
from pathlib import Path
import platform
import sqlite3
import sys
import uuid
from .errors import WorkbenchError
from .store import Store, canonical, digest
from .assets import resolve_bundle

CRITERIA = ('task_clarity', 'evidence_adequacy', 'requested_behavior', 'preserved_behavior', 'unsupported_claims')
VERDICTS = {'pass', 'fail', 'uncertain', 'not-assessed'}
REVIEWER_MODES = {'developer_adjudication', 'ai_assisted_adjudication', 'owner_adjudication', 'scripted_adjudication'}


class Workbench:
    def __init__(self, root, fixture_dir=None):
        self.root = Path(root).resolve()
        self.fixture_dir = resolve_bundle(fixture_dir)
        self.store = Store(self.root)
        self._initialized = False
        try:
            self.catalog = json.loads((self.fixture_dir / 'catalog.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise WorkbenchError('fixture-catalog', 'Trusted fixture catalog is unavailable or invalid.', 409) from exc
        self.rubric_digest = digest(canonical(self.catalog['rubric']))

    def initialize(self):
        self.store.initialize()
        # Artifacts are part of durable authority, so startup verifies each reference.
        with self.store.transaction(write=False) as con:
            for row in con.execute('SELECT result FROM submissions WHERE result IS NOT NULL'):
                self._verify_result(json.loads(row['result']))
        self._initialized = True

    def _ready(self):
        if not self._initialized:
            self.initialize()

    def _record(self, record):
        task_id, patch = record['task_id'], record.get('patch')
        task = self.catalog['tasks'].get(task_id)
        source_digest = digest(canonical(task['source_files'])) if task else None
        check_digest = digest(canonical({'checks': task['checks'], 'verifier_files': task['verifier_files']}
                                        if 'verifier_files' in task else task['checks'])) if task else None
        task_text = record.get('task_text', task['task_text'] if task else '')
        patch_digest = digest(patch.encode('utf-8')) if patch is not None else None
        trusted = bool(task and patch in task['patches'] and task_text == task['task_text'])
        patch_provenance = task.get('patch_provenance', {}).get(patch_digest, {}) if trusted else {}
        origin = patch_provenance.get('origin', 'imported_unverified')
        if trusted and not patch_provenance and self.catalog.get('origin') == 'synthetic_fixture':
            origin = 'synthetic_fixture'
        identity = {'task_id': task_id, 'source_digest': source_digest, 'check_digest': check_digest,
                    'rubric_digest': self.rubric_digest, 'task_text': task_text, 'patch_digest': patch_digest}
        return identity | {'id': 'sub-' + digest(canonical(identity)), 'title': record.get('title', task['title'] if task else task_id),
                           'patch': patch, 'origin': origin, 'patch_provenance': patch_provenance,
                           'declared_origin': record.get('origin', 'unspecified'), 'trusted_tuple': trusted,
                           'fixture_label': record.get('fixture_label'), 'correction_of': record.get('correction_of'),
                           'provenance': task.get('provenance', {}) if task else {},
                           'seeded_reviews': [dict(r, origin='synthetic_seed') for r in record.get('seeded_reviews', []) if isinstance(r, dict)]}

    def import_jsonl(self, path, operation_key, input_format='native'):
        self._ready()
        from .intake import import_jsonl
        return import_jsonl(self, path, operation_key, input_format)

    def import_sample(self, operation_key):
        return self.import_jsonl(self.fixture_dir / 'sample.jsonl', operation_key)

    def bundle_info(self):
        return {'name': self.catalog.get('name', 'synthetic-fixtures'),
                'title': self.catalog.get('title', 'Synthetic fixture demonstration'),
                'origin': self.catalog.get('origin', 'unspecified'),
                'prediction_format': self.catalog.get('prediction_format', 'native')}

    def import_approved(self, operation_key):
        """Only the configured owner bundle chooses a local prediction path."""
        relative = self.catalog.get('prediction_file', 'sample.jsonl')
        if not isinstance(relative, str) or not relative:
            raise WorkbenchError('prediction-path', 'Bundle predictions require a confined relative file path.')
        candidate = Path(relative)
        root = self.fixture_dir.resolve()
        if candidate.is_absolute() or '..' in candidate.parts:
            raise WorkbenchError('prediction-path', 'Bundle predictions require a confined relative file path.')
        path = (root / candidate).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise WorkbenchError('prediction-path', 'Configured bundle prediction file is unavailable or outside the bundle.')
        return self.import_jsonl(path, operation_key, self.catalog.get('prediction_format', 'native'))

    def _project_context(self, item):
        """Expose current eligibility without rewriting historical decisions.

        Evidence and reviews remain bound to their immutable imported context.
        A changed catalog requires importing the new tuple and new evidence.
        Frozen export snapshots retain the eligibility recorded at their cut.
        """
        current = self._record({'task_id': item['task_id'], 'patch': item['patch']})
        changed = [key for key in ('source_digest', 'check_digest', 'rubric_digest', 'task_text')
                   if item.get(key) != current.get(key)]
        if item.get('trusted_tuple') and not current['trusted_tuple']:
            changed.append('trusted_tuple')
        projected = item | {'context_current': not changed, 'stale_context': changed}
        if changed:
            projected['recorded_disposition'] = item['disposition']
            projected['recorded_execution_status'] = item['execution_status']
            projected['disposition'] = 'pending'
            if item['execution_status'] not in {'running', 'uncertain', 'interrupted'}:
                projected['execution_status'] = 'pending-evidence'
        return projected

    def _batch(self, con, batch_id):
        batch = con.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone()
        if not batch:
            raise WorkbenchError('batch-not-found', 'Batch does not exist.', 404)
        members = con.execute('SELECT * FROM memberships WHERE batch_id=? ORDER BY ordinal', (batch_id,)).fetchall()
        rows = con.execute('SELECT DISTINCT s.id,s.data,s.execution_status,s.disposition FROM submissions s JOIN memberships m ON s.id=m.submission_id WHERE m.batch_id=?', (batch_id,)).fetchall()
        items = [self._project_context(json.loads(row['data']) | {'execution_status': row['execution_status'], 'disposition': row['disposition']}) for row in rows]
        counts = {k: 0 for k in ('queued','running','interrupted','completed','execution-error','uncertain','pending-evidence','accepted','rejected','needs-work','pending_review')}
        for item in items:
            counts[item['execution_status']] += 1
            counts['pending_review' if item['disposition'] == 'pending' else item['disposition']] += 1
        return {'id': batch_id, 'created_at': batch['created_at'], 'raw_digest': batch['digest'],
                'raw_lines': len(members), 'invalid_lines': sum(m['error'] is not None for m in members),
                'duplicate_lines': sum(m['duplicate_of'] is not None for m in members), 'unique_items': len(items), 'counts': counts,
                'invalid_records': [{'line': m['ordinal'], 'error': m['error'], 'raw_digest': m['raw_digest']} for m in members if m['error']],
                'occurrences': [{'line': m['ordinal'], 'submission_id': m['submission_id'], 'duplicate_of': m['duplicate_of'], 'error': m['error'], 'raw_digest': m['raw_digest']} for m in members]}

    def batch(self, batch_id):
        self._ready()
        with self.store.transaction(write=False) as con:
            return self._batch(con, batch_id)

    def list_batches(self):
        self._ready()
        with self.store.transaction(write=False) as con:
            return [self._batch(con, r['id']) for r in con.execute('SELECT id FROM batches ORDER BY created_at,id').fetchall()]

    def _item(self, con, submission_id, batch_id=None):
        row = con.execute('SELECT * FROM submissions WHERE id=?', (submission_id,)).fetchone()
        if not row:
            raise WorkbenchError('submission-not-found', 'Submission does not exist.', 404)
        lineages = []
        from .intake import occurrence_claims
        formats = {event['payload']['batch_id']: event['payload'].get('input_format', 'native')
                   for event in self.store.events(con) if event['kind'] == 'batch-imported'}
        for membership in con.execute('SELECT batch_id,ordinal AS line,raw_digest,duplicate_of,raw FROM memberships WHERE submission_id=? ORDER BY batch_id,ordinal', (submission_id,)):
            lineage = {key: membership[key] for key in ('batch_id', 'line', 'raw_digest', 'duplicate_of')}
            record = json.loads(membership['raw'])
            lineage.update(occurrence_claims(record, formats.get(membership['batch_id'], 'native')))
            lineage['raw_record_base64'] = base64.b64encode(membership['raw']).decode('ascii')
            if record.get('correction_of'):
                lineage['correction_of'] = record['correction_of']
            lineages.append(lineage)
        return self._project_context(json.loads(row['data']) | {'batch_id': batch_id or lineages[0]['batch_id'], 'revision': row['revision'],
                                           'execution_status': row['execution_status'], 'disposition': row['disposition'],
                                           'result': json.loads(row['result']) if row['result'] else None,
                                           'review': json.loads(row['review']) if row['review'] else None, 'lineage': lineages,
                                           'attempt_generation': row['generation']})

    def submissions(self, batch_id):
        self._ready()
        with self.store.transaction(write=False) as con:
            self._batch(con, batch_id)
            return [self._item(con, r['submission_id'], batch_id) for r in con.execute('SELECT DISTINCT submission_id FROM memberships WHERE batch_id=? AND submission_id IS NOT NULL ORDER BY submission_id', (batch_id,))]

    def submission(self, submission_id):
        self._ready()
        with self.store.transaction(write=False) as con:
            return self._item(con, submission_id)

    def _verify_result(self, result):
        artifact = self.store.artifact_bytes(result['evidence_digest'])
        expected = dict(result)
        expected.pop('evidence_digest')
        if artifact != canonical(expected):
            raise WorkbenchError('evidence-integrity', 'Stored result differs from its immutable evidence artifact.', 409)

    def artifact_bytes(self, name):
        self._ready()
        return self.store.artifact_bytes(name)

    def review(self, submission_id, *, expected_revision, evidence_digest, rubric_digest, decision, reason, criteria, operation_key, actor='operator', reviewer_mode='developer_adjudication'):
        self._ready()
        if not isinstance(decision, str) or decision not in {'accepted','rejected','needs-work'} or not isinstance(reason, str) or not isinstance(criteria, dict):
            raise WorkbenchError('invalid-review', 'Review decision, criteria and reason are required.')
        if set(criteria) != set(CRITERIA) or any(not isinstance(v, str) or v not in VERDICTS for v in criteria.values()):
            raise WorkbenchError('invalid-criteria', 'Supply all five rubric criteria using pass/fail/uncertain/not-assessed.')
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 200:
            raise WorkbenchError('invalid-actor', 'A reviewer identity is required.')
        if not isinstance(reviewer_mode, str) or reviewer_mode not in REVIEWER_MODES:
            raise WorkbenchError('invalid-reviewer-mode', 'Unsupported adjudication mode.')
        if decision != 'accepted' and not reason.strip():
            raise WorkbenchError('review-reason', 'A reason is required for rejected or needs-work decisions.')
        payload = {'submission_id': submission_id, 'expected_revision': expected_revision, 'evidence_digest': evidence_digest,
                   'rubric_digest': rubric_digest, 'decision': decision, 'reason': reason, 'criteria': criteria, 'actor': actor,
                   'reviewer_mode': reviewer_mode}
        with self.store.transaction() as con:
            prior = self.store.operation(con, 'review', operation_key, payload)
            if prior is not None:
                return self._project_context(prior)
            item = self._item(con, submission_id)
            if type(expected_revision) is not int or item['revision'] != expected_revision:
                raise WorkbenchError('stale-review', 'Submission revision changed; reload current evidence.', 409)
            if rubric_digest != item['rubric_digest'] or rubric_digest != self.rubric_digest:
                raise WorkbenchError('stale-rubric', 'Review rubric does not match current submission rubric.', 409)
            current_context = self._record({'task_id': item['task_id'], 'patch': item['patch'], 'task_text': item['task_text']})
            if not item['context_current'] or any(item.get(key) != current_context.get(key) for key in ('source_digest', 'check_digest', 'patch_digest', 'task_text')):
                raise WorkbenchError('stale-context', 'Source or check context changed; current machine evidence is required.', 409)
            if not item['result'] or not evidence_digest or evidence_digest != item['result']['evidence_digest']:
                raise WorkbenchError('stale-evidence', 'Review requires the current existing evidence digest.', 409)
            self._verify_result(item['result'])
            active = con.execute('SELECT active_attempt FROM submissions WHERE id=?', (submission_id,)).fetchone()[0]
            if active or item['execution_status'] in {'running','uncertain','interrupted'}:
                raise WorkbenchError('unresolved-execution', 'Execution must be resolved before review.', 409)
            if decision == 'accepted' and (item['execution_status'] != 'completed' or item['result']['overall'] != 'passed' or not item['result'].get('source_unchanged') or any(v != 'pass' for v in criteria.values()) or not item['trusted_tuple']):
                raise WorkbenchError('ineligible-acceptance', 'Acceptance requires complete passing machine evidence and all rubric criteria passing.', 422)
            review = {'decision': decision, 'reason': reason, 'criteria': criteria, 'actor': actor,
                      'origin': reviewer_mode, 'reviewer_mode': reviewer_mode, 'evidence_digest': evidence_digest, 'rubric_digest': rubric_digest,
                      'submission_revision': expected_revision}
            con.execute('UPDATE submissions SET disposition=?,review=?,revision=revision+1 WHERE id=? AND revision=?',
                        (decision, canonical(review).decode(), submission_id, expected_revision))
            self.store.event(con, 'submission-reviewed', {'batch_id': item['batch_id'], 'submission_id': submission_id,
                                                        'revision': expected_revision + 1, **review}, actor=actor)
            response = self._item(con, submission_id)
            self.store.remember(con, 'review', operation_key, payload, response)
            return response

    def audit_events(self, batch_id=None):
        self._ready()
        with self.store.transaction(write=False) as con:
            if batch_id is not None:
                self._batch(con, batch_id)
            return self.store.events(con, batch_id)

    def _snapshot(self, con, batch_id):
        batch = self._batch(con, batch_id)
        ids = [r[0] for r in con.execute('SELECT DISTINCT submission_id FROM memberships WHERE batch_id=? AND submission_id IS NOT NULL ORDER BY submission_id', (batch_id,))]
        items = [self._item(con, sid, batch_id) for sid in ids]
        for item in items:
            if item['result']:
                self._verify_result(item['result'])
        # Export bookkeeping cannot move an otherwise unchanged data/evidence cut.
        events = self.store.events(con)
        material = [e for e in events if not e['kind'].startswith('export-')]
        cut = {'seq': material[-1]['seq'], 'hash': material[-1]['hash']} if material else {'seq': 0, 'hash': '0' * 64}
        audit = [e for e in events if e['seq'] <= cut['seq']]
        segments = [dict(r) for r in con.execute('SELECT s.id,s.complete,s.elapsed_seconds,s.completed_ids FROM segments s JOIN runs r ON r.id=s.run_id WHERE r.batch_id=? ORDER BY s.id', (batch_id,))]
        for segment in segments:
            segment['complete'] = bool(segment['complete'])
            segment['completed_ids'] = json.loads(segment['completed_ids'])
        return {'batch': batch, 'items': items, 'audit': audit, 'cut': cut, 'timing_segments': segments,
                'runtime': {'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
                            'platform': sys.platform, 'schema_version': 1, 'runner_version': 'trusted-task-worker-v4',
                            'intake_version': 'raw-occurrence-v2', 'bundle': self.bundle_info(),
                            'fixture_catalog_digest': digest(canonical(self.catalog)), 'rubric_digest': self.rubric_digest}}

    def snapshot(self, batch_id):
        self._ready()
        with self.store.transaction(write=False) as con:
            return self._snapshot(con, batch_id)

    def prepare_export(self, batch_id, operation_key):
        self._ready()
        payload = {'batch_id': batch_id}
        with self.store.transaction() as con:
            prior = self.store.operation(con, 'export', operation_key, payload)
            if prior is not None:
                return self._export(con, prior['export_id'])
            snapshot = self._snapshot(con, batch_id)
            export_id = 'export-' + digest(canonical(snapshot))
            if not con.execute('SELECT 1 FROM exports WHERE id=?', (export_id,)).fetchone():
                con.execute('INSERT INTO exports(id,batch_id,snapshot,status) VALUES(?,?,?,?)',
                            (export_id, batch_id, canonical(snapshot).decode(), 'pending'))
                self.store.event(con, 'export-prepared', {'batch_id': batch_id, 'export_id': export_id, 'cut': snapshot['cut']})
            self.store.remember(con, 'export', operation_key, payload, {'export_id': export_id})
            return self._export(con, export_id)

    def _export(self, con, export_id):
        row = con.execute('SELECT * FROM exports WHERE id=?', (export_id,)).fetchone()
        if not row:
            raise WorkbenchError('export-not-found', 'Prepared export does not exist.', 404)
        result = {'export_id': row['id'], 'snapshot': json.loads(row['snapshot']), 'status': row['status']}
        if row['manifest_digest']:
            result |= {'manifest_digest': row['manifest_digest'], 'location': row['location']}
        return result

    def complete_export(self, export_id, manifest_digest, location):
        self._ready()
        import re
        if not isinstance(manifest_digest, str) or not re.fullmatch('[0-9a-f]{64}', manifest_digest) or not isinstance(location, str) or not location:
            raise WorkbenchError('invalid-export', 'A manifest digest and published location are required.')
        with self.store.transaction() as con:
            current = self._export(con, export_id)
            if current['status'] == 'ready':
                if current['manifest_digest'] != manifest_digest or current['location'] != location:
                    raise WorkbenchError('export-conflict', 'Export is already bound to different published content.', 409)
                return current
            con.execute('UPDATE exports SET status=?,manifest_digest=?,location=? WHERE id=?', ('ready', manifest_digest, location, export_id))
            self.store.event(con, 'export-ready', {'batch_id': current['snapshot']['batch']['id'], 'export_id': export_id, 'manifest_digest': manifest_digest})
            return self._export(con, export_id)

    def exports(self, batch_id):
        self._ready()
        with self.store.transaction(write=False) as con:
            self._batch(con, batch_id)
            return [self._export(con, r['id']) for r in con.execute('SELECT id FROM exports WHERE batch_id=? ORDER BY id', (batch_id,)).fetchall()]

    def verify(self):
        self._ready()
        with self.store.transaction(write=False) as con:
            root = self.store.verify_audit(con)
            results = [json.loads(r[0]) for r in con.execute('SELECT result FROM submissions WHERE result IS NOT NULL')]
            for result in results:
                self._verify_result(result)
            ok = con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and not con.execute('PRAGMA foreign_key_check').fetchall()
            return {'ok': ok, 'schema_version': 1, 'audit_root': root, 'audit_events': con.execute('SELECT count(*) FROM audit').fetchone()[0],
                    'verified_results': len(results), 'journal_mode': con.execute('PRAGMA journal_mode').fetchone()[0],
                    'synchronous': con.execute('PRAGMA synchronous').fetchone()[0], 'foreign_keys': con.execute('PRAGMA foreign_keys').fetchone()[0]}

    def process(self, batch_id, workers=1, *, stop_after=None):
        self._ready()
        from .runner import process
        return process(self, batch_id, workers, stop_after=stop_after)
