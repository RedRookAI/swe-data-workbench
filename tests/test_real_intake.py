"""Focused native/SWE-bench adapter, source attribution and bundle checks."""
import base64
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from swe_workbench.assets import resolve_bundle
from swe_workbench.cli import main
from swe_workbench.core import Workbench
from swe_workbench.errors import WorkbenchError
from swe_workbench.intake import MAX_LINE_BYTES
from swe_workbench.store import canonical, digest


class RealIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle = resolve_bundle('unicode-hyphen')
        self.w = Workbench(self.root / 'state', fixture_dir=self.bundle)
        self.records = [json.loads(line) for line in (self.bundle / 'predictions.jsonl').read_bytes().splitlines()]

    def input(self, records):
        path = self.root / 'predictions.jsonl'
        path.write_bytes(b''.join(canonical(record) + b'\n' for record in records))
        return path

    def test_original_bytes_distinct_delivery_claims_and_permission(self):
        self.records[0].update(origin='synthetic_fixture', source='publisher-a', trusted_tuple=True)
        self.records[2].update(model_name_or_path='second-publisher', source='publisher-b')
        self.records[3].update(origin='public_upstream', trusted_tuple=True,
                               patch_provenance={'origin':'public_upstream'})
        path = self.input(self.records)
        originals = path.read_bytes().splitlines(keepends=True)
        batch = self.w.import_jsonl(path, 'predictions', input_format='swebench')
        self.assertEqual([batch[k] for k in ('raw_lines','invalid_lines','duplicate_lines','unique_items')], [4,0,1,3])
        items = {i['origin']:i for i in self.w.submissions(batch['id'])}
        positive = items['public_upstream']
        self.assertTrue(positive['trusted_tuple'])
        self.assertEqual(positive['patch'], self.records[0]['model_patch'])
        self.assertEqual(positive['patch_provenance']['source_commit'], '732905da074f0220487ad6a27590f89bd0819374')
        self.assertEqual([(o['declared_model'],o['declared_source']) for o in positive['lineage']],
                         [('upstream-human-reference','publisher-a'),('second-publisher','publisher-b')])
        for occurrence in positive['lineage']:
            raw = base64.b64decode(occurrence['raw_record_base64'])
            self.assertEqual(raw, originals[occurrence['line']-1])
            self.assertEqual(digest(raw), occurrence['raw_digest'])
            self.assertEqual(occurrence['input_format'], 'swebench')
        self.assertEqual(items['synthetic_control']['execution_status'], 'queued')
        self.assertFalse(items['imported_unverified']['trusted_tuple'])
        self.assertEqual(items['imported_unverified']['execution_status'], 'pending-evidence')
        self.assertEqual(items['imported_unverified']['patch_provenance'], {})
        self.assertFalse((self.w.root / 'attempts').exists())
        with self.w.store.transaction(write=False) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM attempts').fetchone()[0], 0)
            self.assertEqual([r[0] for r in con.execute('SELECT raw FROM memberships ORDER BY ordinal')], originals)
        self.assertEqual(self.w.import_jsonl(path,'predictions',input_format='swebench')['id'], batch['id'])
        reloaded = Workbench(self.w.root, fixture_dir=self.bundle)
        reloaded.initialize()
        self.assertEqual(reloaded.submission(positive['id']), positive)

    def test_native_and_swebench_share_computation_preserve_each_source(self):
        batch = self.w.import_approved('approved')
        positive = next(i for i in self.w.submissions(batch['id']) if i['origin']=='public_upstream')
        record = {'schema_version':1,'task_id':positive['task_id'],'patch':positive['patch'],
                  'model':'native-delivery','source':'local-curation','origin':'input-claim'}
        path = self.input([record])
        # Final newline is retained exactly, never normalized by the adapter.
        path.write_bytes(path.read_bytes().rstrip(b'\n'))
        native_raw = path.read_bytes()
        native = self.w.import_jsonl(path,'native')
        item = self.w.submissions(native['id'])[0]
        self.assertEqual(item['id'], positive['id'])
        self.assertEqual(len(item['lineage']),3)
        native_occurrence = next(o for o in item['lineage'] if o['input_format']=='native')
        self.assertEqual(native_occurrence['declared_model'],'native-delivery')
        self.assertEqual(native_occurrence['declared_source'],'local-curation')
        self.assertEqual(base64.b64decode(native_occurrence['raw_record_base64']),native_raw)
        with self.assertRaises(WorkbenchError) as caught:
            self.w.import_jsonl(path,'native',input_format='swebench')
        self.assertEqual(caught.exception.code,'operation-conflict')

    def test_adapter_invalid_unknown_and_bounded_outcomes(self):
        rows = [b'\xff\n', b'{"instance_id":"x","model_name_or_path":"m"}\n',
                b'{"instance_id":"x","model_name_or_path":"m","model_patch":null}\n',
                b'[]\n', b' '*(MAX_LINE_BYTES+1)+b'\n',
                canonical({'instance_id':'unknown/task','model_name_or_path':'claim','model_patch':'not approved'})+b'\n']
        path = self.root / 'invalid.jsonl';path.write_bytes(b''.join(rows))
        batch = self.w.import_jsonl(path,'invalid',input_format='swebench')
        self.assertEqual(batch['invalid_lines'],5)
        self.assertEqual([e['error'] for e in batch['invalid_records']],
                         ['invalid-utf8','invalid-swebench-record','invalid-swebench-record','unsupported-schema','line-too-large'])
        unknown = self.w.submissions(batch['id'])[0]
        self.assertEqual(unknown['task_id'],'unknown/task')
        self.assertEqual(unknown['execution_status'],'pending-evidence')
        with self.assertRaises(WorkbenchError) as caught:
            self.w.import_jsonl(path,'other',input_format='guessed')
        self.assertEqual(caught.exception.code,'unsupported-format')

    def test_confined_approved_file_builtin_installed_lookup_and_cli(self):
        self.assertEqual(set(self.w.bundle_info()),{'name','title','origin','prediction_format'})
        self.assertNotIn(str(self.bundle),json.dumps(self.w.bundle_info()))
        for candidate in ('../outside.jsonl','/tmp/outside.jsonl','https://example.invalid/data'):
            self.w.catalog['prediction_file'] = candidate
            with self.assertRaises(WorkbenchError) as caught:self.w.import_approved('path')
            self.assertEqual(caught.exception.code,'prediction-path')
        # An existing symlink outside the configured bundle is refused too.
        local = self.root/'owner-bundle';local.mkdir()
        (local/'catalog.json').write_bytes(canonical(self.w.catalog | {'prediction_file':'link.jsonl'}))
        outside = self.root/'outside.jsonl';outside.write_bytes(b'{}\n')
        (local/'link.jsonl').symlink_to(outside)
        with self.assertRaises(WorkbenchError):Workbench(self.root/'other',fixture_dir=local).import_approved('path')
        installed = self.root/'installed'
        catalog = installed/'share/swe-data-workbench/bundles/unicode-hyphen/catalog.json'
        catalog.parent.mkdir(parents=True);catalog.write_bytes(b'{}')
        with patch('swe_workbench.assets.__file__',str(self.root/'source/pkg/assets.py')), patch('swe_workbench.assets.sys.prefix',str(installed)):
            self.assertEqual(resolve_bundle('unicode-hyphen'),catalog.parent)
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(['--root',str(self.root/'cli'),'--bundle','unicode-hyphen','import-approved','--operation-key','cli'])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(output.getvalue())['unique_items'],3)


if __name__=='__main__':unittest.main()
