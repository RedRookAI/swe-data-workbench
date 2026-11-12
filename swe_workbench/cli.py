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
    capture = commands.add_parser('capture-handoff', help='Capture a committed change and external evidence without executing checks')
    for name in ('repo', 'base', 'candidate', 'request', 'operation-key'):
        capture.add_argument('--' + name, required=True)
    capture.add_argument('--evidence', action='append', default=[], help='Owner-selected NAME=FILE attachment; never executed')
    commands.add_parser('handoff').add_argument('change_id')
    change_review = commands.add_parser('review-handoff')
    change_review.add_argument('change_id'); change_review.add_argument('--request', type=Path, required=True)
    change_export = commands.add_parser('export-handoff')
    change_export.add_argument('change_id'); change_export.add_argument('--output', type=Path, required=True)
    commands.add_parser('verify-handoff').add_argument('path', type=Path)
    prepare = commands.add_parser('prepare-bundle', help='Read committed source and selected inputs into a fresh trusted bundle; runs no checks')
    prepare.add_argument('--repo', type=Path, required=True, help='Local Git repository with all selected objects present')
    prepare.add_argument('--commit', required=True, help='Explicit base commit/revision, resolved to its exact commit ID')
    prepare.add_argument('--task-id', required=True)
    prepare.add_argument('--task-text', type=Path, required=True)
    prepare.add_argument('--source', action='append', dest='sources', required=True, help='Tracked repository-relative regular file; repeat to select more')
    prepare.add_argument('--checks', type=Path, required=True, help='JSON list of {name,argv,timeout}')
    prepare.add_argument('--verifier-files', type=Path, help='Optional JSON mapping of protected verifier paths to UTF-8 text')
    prepare.add_argument('--evaluation', type=Path, help='Optional versioned evaluation requirements/rubric and admitted reference roles')
    prepare.add_argument('--candidates', type=Path, required=True, help='JSON list of {patch_file,model_name_or_path,provenance}; these exact patches are admitted')
    prepare.add_argument('--provenance', type=Path, required=True, help='Source JSON with origin,license,repository')
    prepare.add_argument('--notice', action='append', dest='notices', required=True, help='Tracked repository-relative notice; repeat as needed')
    prepare.add_argument('--output', type=Path, required=True, help='Fresh directory outside the repository; parent must exist')
    prepare.add_argument('--predictions', type=Path, help='Optional JSONL copied exactly; does not admit additional patches')
    prepare.add_argument('--format', choices=('native', 'swebench'), default='native', dest='input_format')
    prepare.add_argument('--name')
    prepare.add_argument('--title')
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
        if args.command in ('capture-handoff', 'handoff', 'review-handoff', 'export-handoff', 'verify-handoff'):
            from . import handoff
            from .bundle import _read
            if args.command == 'capture-handoff':
                evidence = {}
                for item in args.evidence:
                    if '=' not in item or item.split('=', 1)[0] in evidence:
                        raise WorkbenchError('invalid-handoff', 'Supply unique NAME=FILE evidence attachments.')
                    name, path = item.split('=', 1); evidence[name] = path
                result = handoff.capture(args.root, repo=args.repo, base=args.base, candidate=args.candidate,
                    request=handoff.parse(_read(args.request)), evidence=evidence, operation_key=args.operation_key)
            elif args.command == 'handoff': result = handoff.read(args.root, args.change_id)
            elif args.command == 'review-handoff': result = handoff.review(args.root, args.change_id, **handoff.parse(_read(args.request)))
            elif args.command == 'export-handoff': result = handoff.export(args.root, args.change_id, args.output)
            else: result = handoff.verify(args.path)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get('ok', True) else 1
        if args.command == 'prepare-bundle':
            from .bundle import prepare_bundle
            arguments = vars(args).copy()
            for name in ('command', 'root', 'bundle'):
                arguments.pop(name)
            result = prepare_bundle(**arguments)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
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
