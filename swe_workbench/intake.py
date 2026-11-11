"""Bounded streamed JSONL intake. IDs and input strings never choose execution."""
from __future__ import annotations
import json
from pathlib import Path
from .errors import WorkbenchError
from .store import canonical, digest, now

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
MAX_RECORDS = 10000


def reject_constant(value):
    raise ValueError('Non-finite JSON number is unsupported')


def read_jsonl(path):
    rows, sha = [], __import__('hashlib').sha256()
    total = 0
    try:
        with Path(path).open('rb') as stream:
            for ordinal, raw in enumerate(iter(lambda: stream.readline(MAX_FILE_BYTES + 1), b''), 1):
                total += len(raw)
                if total > MAX_FILE_BYTES:
                    raise WorkbenchError('file-too-large', f'Input exceeds {MAX_FILE_BYTES} bytes; no batch committed.')
                if ordinal > MAX_RECORDS:
                    raise WorkbenchError('too-many-records', f'Input exceeds {MAX_RECORDS} records; no batch committed.')
                sha.update(raw)
                error, record = None, None
                if len(raw) > MAX_LINE_BYTES:
                    error = 'line-too-large'
                else:
                    try:
                        record = json.loads(raw.decode('utf-8'), parse_constant=reject_constant)
                    except UnicodeDecodeError:
                        error = 'invalid-utf8'
                    except (json.JSONDecodeError, ValueError, RecursionError):
                        error = 'invalid-json'
                if not error:
                    if not isinstance(record, dict) or type(record.get('schema_version')) is not int or record['schema_version'] != 1:
                        error = 'unsupported-schema'
                    elif not isinstance(record.get('task_id'), str) or not record['task_id'] or len(record['task_id']) > 200:
                        error = 'invalid-task-id'
                    elif record.get('patch') is not None and not isinstance(record['patch'], str):
                        error = 'invalid-patch'
                    elif any(key in record and not isinstance(record[key], str) for key in ('title', 'task_text', 'origin', 'correction_of')):
                        error = 'invalid-field'
                    elif 'seeded_reviews' in record and not isinstance(record['seeded_reviews'], list):
                        error = 'invalid-seeded-reviews'
                    else:
                        try:
                            canonical(record)
                        except (ValueError, UnicodeEncodeError, RecursionError):
                            error = 'invalid-unicode-or-number'
                rows.append({'ordinal': ordinal, 'raw': raw, 'raw_digest': digest(raw), 'error': error, 'record': record})
    except OSError as exc:
        raise WorkbenchError('input-unavailable', 'Input file cannot be read.') from exc
    return sha.hexdigest(), rows


def import_jsonl(workbench, path, operation_key):
    file_digest, rows = read_jsonl(path)
    store = workbench.store
    contexts = []
    for row in rows:
        if not row['error']:
            item = workbench._record(row['record'])
            contexts.append({'line': row['ordinal'], 'submission_id': item['id'], 'trusted_tuple': item['trusted_tuple']})
    payload = {'file_digest': file_digest, 'context_digest': digest(canonical(contexts))}
    with store.transaction() as con:
        prior = store.operation(con, 'import', operation_key, payload)
        if prior is not None:
            return workbench._batch(con, prior['id'])
        # Replay shares membership only within the same effective task context.
        batch_id = 'batch-' + digest(canonical(payload))[:24]
        if con.execute('SELECT 1 FROM batches WHERE id=?', (batch_id,)).fetchone():
            response = workbench._batch(con, batch_id)
            store.remember(con, 'import', operation_key, payload, {'id': batch_id})
            return response
        con.execute('INSERT INTO batches VALUES(?,?,?)', (batch_id, file_digest, now()))
        seen = {}
        for row in rows:
            item, error, duplicate_of = None, row['error'], None
            if not error:
                record = row['record']
                item = workbench._record(record)
                correction = record.get('correction_of')
                if correction:
                    original = con.execute('SELECT data FROM submissions WHERE id=?', (correction,)).fetchone()
                    if not original or json.loads(original['data'])['task_id'] != item['task_id'] or correction == item['id']:
                        error, item = 'invalid-correction', None
                if item:
                    if item['id'] in seen:
                        duplicate_of = seen[item['id']]
                    else:
                        seen[item['id']] = row['ordinal']
                    con.execute('INSERT OR IGNORE INTO submissions(id,data,execution_status) VALUES(?,?,?)',
                                (item['id'], canonical(item).decode(), 'queued' if item['trusted_tuple'] else 'pending-evidence'))
            con.execute('INSERT INTO memberships VALUES(?,?,?,?,?,?,?)',
                        (batch_id, row['ordinal'], item['id'] if item else None, error, duplicate_of, row['raw'], row['raw_digest']))
        response = workbench._batch(con, batch_id)
        store.event(con, 'batch-imported', {'batch_id': batch_id, **payload,
                                          'raw_lines': response['raw_lines'], 'invalid_lines': response['invalid_lines'],
                                          'duplicate_lines': response['duplicate_lines'], 'unique_items': response['unique_items']}, actor='operator')
        store.remember(con, 'import', operation_key, payload, {'id': batch_id})
        return response
