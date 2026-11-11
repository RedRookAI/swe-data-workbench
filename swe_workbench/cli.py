"""Small owner CLI; every mutation delegates the same core API as HTTP."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .core import Workbench
from .errors import WorkbenchError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Process and review owner-approved coding task bundles.')
    parser.add_argument('--root', type=Path, default=Path('.workbench'))
    parser.add_argument('--bundle', help='Owner-selected built-in name or local bundle directory')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init')
    commands.add_parser('verify')
    commands.add_parser('batches')
    commands.add_parser('bundle-info')
    sample = commands.add_parser('import-sample')
    sample.add_argument('--operation-key', required=True)
    approved = commands.add_parser('import-approved')
    approved.add_argument('--operation-key', required=True)
    intake = commands.add_parser('import')
    intake.add_argument('path', type=Path)
    intake.add_argument('--operation-key', required=True)
    intake.add_argument('--format', choices=('native', 'swebench'), default='native', dest='input_format')
    process = commands.add_parser('process')
    process.add_argument('batch_id')
    process.add_argument('--workers', type=int, default=1)
    process.add_argument('--stop-after', type=int)
    for command in ('items', 'snapshot', 'audit'):
        commands.add_parser(command).add_argument('batch_id')
    review = commands.add_parser('review')
    review.add_argument('submission_id')
    review.add_argument('--request', type=Path, required=True, help='JSON with exact revision/evidence/rubric/criteria bindings')
    export = commands.add_parser('export')
    export.add_argument('batch_id')
    export.add_argument('--output', type=Path, required=True)
    export.add_argument('--operation-key', required=True)
    args = parser.parse_args(argv)
    try:
        workbench = Workbench(args.root, fixture_dir=args.bundle)
        workbench.initialize()
        command = args.command
        if command == 'init':
            result = workbench.verify()
        elif command == 'verify':
            result = workbench.verify()
        elif command == 'batches':
            result = workbench.list_batches()
        elif command == 'bundle-info':
            result = workbench.bundle_info()
        elif command == 'import-approved':
            result = workbench.import_approved(args.operation_key)
        elif command == 'import-sample':
            result = workbench.import_sample(args.operation_key)
        elif command == 'import':
            result = workbench.import_jsonl(args.path, args.operation_key, args.input_format)
        elif command == 'process':
            result = workbench.process(args.batch_id, args.workers, stop_after=args.stop_after)
        elif command == 'items':
            result = workbench.submissions(args.batch_id)
        elif command == 'snapshot':
            result = workbench.snapshot(args.batch_id)
        elif command == 'audit':
            result = workbench.audit_events(args.batch_id)
        elif command == 'review':
            result = workbench.review(args.submission_id, **json.loads(args.request.read_text()))
        else:
            from .exporter import export_batch
            result = export_batch(workbench, args.batch_id, args.output, args.operation_key)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except WorkbenchError as exc:
        print(json.dumps({'error': {'code': exc.code, 'message': exc.message}}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
