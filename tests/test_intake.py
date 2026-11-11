import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from swe_workbench.core import Workbench
from swe_workbench.errors import WorkbenchError
from swe_workbench.intake import MAX_LINE_BYTES, MAX_FILE_BYTES
from swe_workbench.store import canonical, digest


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.w = Workbench(self.root / 'state')
        self.w.initialize()

    def input(self, data):
        path = self.root / 'input.jsonl'
        path.write_bytes(data)
        return path

    def test_accounting_idempotency_context_and_fresh_reload(self):
        batch = self.w.import_sample('import')
        self.assertEqual([batch[k] for k in ('raw_lines','invalid_lines','duplicate_lines','unique_items')], [8,1,1,6])
        self.assertEqual(self.w.import_sample('import')['id'], batch['id'])
        self.assertEqual(self.w.import_sample('alias')['id'], batch['id'])
        self.assertEqual(len(self.w.audit_events()), 1)
        other = Workbench(self.root / 'state')
        other.initialize()
        items = {i['fixture_label']:i for i in other.submissions(batch['id'])}
        self.assertEqual(len(items['good']['lineage']), 2)
        self.assertNotEqual(items['good']['id'],items['same-patch-different-context']['id'])
        self.assertNotEqual(items['good']['id'],items['unsupported-tuple']['id'])
        self.assertEqual(items['missing-evidence']['execution_status'], 'pending-evidence')
        with self.w.store.transaction(write=False) as con:
            raw = con.execute('SELECT raw,raw_digest FROM memberships WHERE batch_id=? AND ordinal=1',(batch['id'],)).fetchone()
            self.assertEqual(digest(raw['raw']),raw['raw_digest'])
        with self.assertRaises(WorkbenchError) as caught:
            self.w.import_jsonl(self.input(b'{}\n'),'import')
        self.assertEqual(caught.exception.code, 'operation-conflict')

    def test_invalid_encoding_schema_line_limits_and_empty(self):
        records = [b'\xff\n', b'{"schema_version":2}\n', b'{}\n', b' '*(MAX_LINE_BYTES+1)+b'\n', b'{"schema_version":1,"task_id":"t","patch":4}\n', b'{"schema_version":1,"task_id":"t","patch":"\\ud800"}\n']
        batch = self.w.import_jsonl(self.input(b''.join(records)),'invalid')
        self.assertEqual(batch['invalid_lines'], 6)
        self.assertEqual([r['error'] for r in batch['invalid_records']], ['invalid-utf8','unsupported-schema','unsupported-schema','line-too-large','invalid-patch','invalid-unicode-or-number'])
        empty = self.w.import_jsonl(self.input(b''),'empty')
        self.assertEqual(empty['unique_items'],0)
        self.assertEqual(empty['raw_lines'],0)
        with self.assertRaises(WorkbenchError) as caught:
            self.w.import_jsonl(self.input(b'x'*(MAX_FILE_BYTES+1)),'oversized')
        self.assertEqual(caught.exception.code,'file-too-large')
        self.assertEqual(len(self.w.list_batches()),2)

    def test_transaction_rolls_back_state_and_audit_together(self):
        original = self.w.store.event
        def fail_after_event(*args,**kwargs):
            original(*args,**kwargs)
            raise RuntimeError('Injected before SQL commit')
        with patch.object(self.w.store,'event',fail_after_event):
            with self.assertRaises(RuntimeError):
                self.w.import_sample('rollback')
        self.assertEqual(self.w.list_batches(),[])
        self.assertEqual(self.w.audit_events(),[])
        self.w.import_sample('rollback')
        self.assertTrue(self.w.verify()['ok'])

    def test_correction_preserves_old_identity_and_raw_lineage(self):
        batch = self.w.import_sample('sample')
        items = {i['fixture_label']:i for i in self.w.submissions(batch['id'])}
        record = {'schema_version':1,'task_id':'order-dedupe','patch':items['weak-check-wrong']['patch'],'correction_of':items['failing']['id']}
        corrected = self.w.import_jsonl(self.input(canonical(record)+b'\n'),'correction')
        # Existing exact tuples are shared, while all raw correction lineage is retained.
        fixed = self.w.submissions(corrected['id'])[0]
        self.assertEqual(fixed['id'],items['weak-check-wrong']['id'])
        self.assertTrue(any(line.get('correction_of') == items['failing']['id'] for line in fixed['lineage']))
        self.assertEqual(self.w.submission(items['failing']['id'])['patch'],items['failing']['patch'])
        with self.w.store.transaction(write=False) as con:
            self.assertEqual(json.loads(con.execute('SELECT raw FROM memberships WHERE batch_id=?',(corrected['id'],)).fetchone()[0])['correction_of'],items['failing']['id'])

    def test_corrupt_and_incompatible_databases_are_preserved(self):
        corrupt = self.root / 'corrupt'
        corrupt.mkdir()
        path = corrupt/'workbench.sqlite3'
        data = b'this is not sqlite'
        path.write_bytes(data)
        with self.assertRaises(WorkbenchError):
            Workbench(corrupt).initialize()
        self.assertEqual(path.read_bytes(),data)
        with self.w.store.transaction() as con:
            con.execute('PRAGMA user_version=99')
        with self.assertRaises(WorkbenchError) as caught:
            Workbench(self.w.root).initialize()
        self.assertEqual(caught.exception.code,'schema-version')


if __name__ == '__main__':
    unittest.main()
