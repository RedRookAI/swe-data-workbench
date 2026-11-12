"""SQLite authority and canonical envelopes (UTF-8, sorted keys, compact JSON).

This serialization is application-specific, not an interoperable canonical JSON
standard. Audit hash = sha256(canonical(event excluding hash)); genesis prev_hash
is 64 zeroes. Artifact names are SHA-256 of exact bytes.
"""
from __future__ import annotations
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timezone
from .errors import WorkbenchError


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


SCHEMA = '''
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE batches(id TEXT PRIMARY KEY, digest TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE submissions(id TEXT PRIMARY KEY, data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 execution_status TEXT NOT NULL, disposition TEXT NOT NULL DEFAULT 'pending', result TEXT, review TEXT,
 generation INTEGER NOT NULL DEFAULT 0, active_attempt TEXT);
CREATE TABLE memberships(batch_id TEXT NOT NULL REFERENCES batches(id), ordinal INTEGER NOT NULL,
 submission_id TEXT REFERENCES submissions(id), error TEXT, duplicate_of INTEGER, raw BLOB NOT NULL,
 raw_digest TEXT NOT NULL, PRIMARY KEY(batch_id,ordinal));
CREATE TABLE operations(kind TEXT NOT NULL, key TEXT NOT NULL, payload_digest TEXT NOT NULL,
 response TEXT NOT NULL, PRIMARY KEY(kind,key));
CREATE TABLE runs(id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
 status TEXT NOT NULL, controller TEXT NOT NULL, workers INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE attempts(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
 submission_id TEXT NOT NULL REFERENCES submissions(id), generation INTEGER NOT NULL,
 expected_revision INTEGER NOT NULL, state TEXT NOT NULL, identity TEXT, created_at TEXT NOT NULL,
 result_digest TEXT, UNIQUE(submission_id,generation));
CREATE TABLE segments(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
 complete INTEGER NOT NULL DEFAULT 0, elapsed_seconds REAL, completed_ids TEXT NOT NULL DEFAULT '[]');
CREATE TABLE exports(id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
 snapshot TEXT NOT NULL, status TEXT NOT NULL, manifest_digest TEXT, location TEXT);
CREATE TABLE audit(seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, actor TEXT NOT NULL,
 payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL, created_at TEXT NOT NULL);
PRAGMA user_version=1;
'''


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.db = self.root / 'workbench.sqlite3'
        self.artifacts = self.root / 'artifacts'

    def connect(self):
        con = sqlite3.connect(self.db, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA synchronous=FULL')
        if con.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
            con.close()
            raise WorkbenchError('database-mode', 'Rollback-journal DELETE mode is required.', 409)
        return con

    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.artifacts.mkdir(exist_ok=True, mode=0o700)
        fresh = not self.db.exists()
        try:
            with contextlib.closing(self.connect()) as con:
                version = con.execute('PRAGMA user_version').fetchone()[0]
                if fresh:
                    con.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nCOMMIT;')
                elif version != 1:
                    raise WorkbenchError('schema-version', f'Unsupported database schema version {version}; original data preserved.', 409)
                if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise WorkbenchError('database-integrity', 'SQLite integrity check failed; original data preserved.', 409)
                if con.execute('PRAGMA foreign_key_check').fetchall():
                    raise WorkbenchError('database-integrity', 'Foreign-key integrity check failed.', 409)
                self.verify_audit(con)
        except sqlite3.DatabaseError as exc:
            raise WorkbenchError('database-integrity', 'Cannot open compatible database; original data preserved.', 409) from exc

    @contextlib.contextmanager
    def transaction(self, write=True):
        con = self.connect()
        try:
            con.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield con
            con.execute('COMMIT')
        except BaseException:
            if con.in_transaction:
                con.execute('ROLLBACK')
            raise
        finally:
            con.close()

    def event(self, con, kind, payload, actor='system'):
        prior = con.execute('SELECT seq,hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        event = {'seq': prior['seq'] + 1 if prior else 1, 'kind': kind, 'actor': actor,
                 'payload': payload, 'prev_hash': prior['hash'] if prior else '0' * 64, 'created_at': now()}
        event['hash'] = digest(canonical(event))
        con.execute('INSERT INTO audit VALUES(?,?,?,?,?,?,?)',
                    (event['seq'], kind, actor, canonical(payload).decode(), event['prev_hash'], event['hash'], event['created_at']))
        return event

    @staticmethod
    def events(con, batch_id=None):
        rows = con.execute('SELECT * FROM audit ORDER BY seq').fetchall()
        events = [dict(row) | {'payload': json.loads(row['payload'])} for row in rows]
        return events if batch_id is None else [e for e in events if e['payload'].get('batch_id') == batch_id]

    def validated_events(self, con):
        if con.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise WorkbenchError('schema-version','Unsupported database schema.',409)
        if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or con.execute('PRAGMA foreign_key_check').fetchall():
            raise WorkbenchError('database-integrity','SQLite integrity check failed.',409)
        events=self.events(con)
        self.verify_events(events)
        return events

    def verify_audit(self, con):
        return self.verify_events(self.events(con))

    @staticmethod
    def verify_events(events):
        prev = '0' * 64
        for seq, event in enumerate(events, 1):
            candidate = dict(event)
            actual = candidate.pop('hash')
            if candidate['seq'] != seq or candidate['prev_hash'] != prev or digest(canonical(candidate)) != actual:
                raise WorkbenchError('audit-integrity', f'Audit chain failed at sequence {seq}.', 409)
            prev = actual
        return prev

    @staticmethod
    def operation(con, kind, key, payload):
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise WorkbenchError('operation-key', 'A nonempty operation key of at most 200 characters is required.')
        payload_digest = digest(canonical(payload))
        row = con.execute('SELECT * FROM operations WHERE kind=? AND key=?', (kind, key)).fetchone()
        if row:
            if row['payload_digest'] != payload_digest:
                raise WorkbenchError('operation-conflict', 'Operation key was already used for different content.', 409)
            return json.loads(row['response'])
        return None

    @staticmethod
    def remember(con, kind, key, payload, response):
        con.execute('INSERT INTO operations VALUES(?,?,?,?)',
                    (kind, key, digest(canonical(payload)), canonical(response).decode()))

    def artifact_write(self, data: bytes) -> str:
        name = digest(data)
        target = self.artifacts / name
        if target.exists():
            self.artifact_bytes(name)
            return name
        temporary = self.artifacts / ('.' + name + '-' + os.urandom(8).hex())
        try:
            with temporary.open('xb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            with os.scandir(self.artifacts):
                fd = os.open(self.artifacts, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)
        return name

    def artifact_bytes(self, name):
        if not isinstance(name, str) or not re.fullmatch('[0-9a-f]{64}', name):
            raise WorkbenchError('artifact-digest', 'Expected a SHA-256 artifact digest.')
        try:
            data = (self.artifacts / name).read_bytes()
        except OSError as exc:
            raise WorkbenchError('artifact-missing', 'Referenced evidence artifact is unavailable.', 409) from exc
        if digest(data) != name:
            raise WorkbenchError('artifact-integrity', 'Referenced evidence artifact digest does not match.', 409)
        return data
