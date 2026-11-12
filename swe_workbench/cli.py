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
    for capture_command in ('capture-handoff','preview-handoff'):
        capture = commands.add_parser(capture_command, help='Inspect selected committed source/evidence; preview writes no state')
        for name in ('repo', 'base', 'candidate'):
            capture.add_argument('--' + name, required=True)
        capture_input = capture.add_mutually_exclusive_group(required=True)
        capture_input.add_argument('--request'); capture_input.add_argument('--profile', help='Explicit owner-selected reusable JSON profile')
        for name in ('operation-key', 'change-id', 'title', 'goal'):
            capture.add_argument('--' + name)
        capture.add_argument('--evidence', action='append', default=[], help='Owner-selected NAME=FILE attachment; never executed')
        capture.add_argument('--evidence-dir', help='Bind only profile-declared attachment names from this selected directory')
    receipt = commands.add_parser('write-receipt',help='Write explicitly supplied check facts; executes nothing')
    receipt.add_argument('--request',type=Path,required=True);receipt.add_argument('--output',type=Path,required=True)
    backup=commands.add_parser('backup-state',help='Private quiescent SQLite/artifact snapshot');backup.add_argument('--output',type=Path,required=True)
    restore=commands.add_parser('restore-state',help='Restore a private snapshot to a fresh root');restore.add_argument('path',type=Path);restore.add_argument('--output',type=Path,required=True)
    view=commands.add_parser('build-handoff-view',help='Build a selected read-only view without task data/DB');view.add_argument('path',type=Path);view.add_argument('--output',type=Path,required=True)
    junit=commands.add_parser('import-junit',help='Read an existing pytest XML report; executes nothing');junit.add_argument('path',type=Path);junit.add_argument('--context',type=Path);junit.add_argument('--output',type=Path,required=True)
    context=commands.add_parser('configure-project',help='Save explicitly selected owner defaults');context.add_argument('--output',type=Path,required=True)
    for name in ('repo','profile','evidence-directory','state','base-ref','candidate-ref'):context.add_argument('--'+name,required=True)
    association=commands.add_parser('associate-project',help='Explicitly associate legacy state; audited --relocate supports deliberate source moves');association.add_argument('context',type=Path);association.add_argument('--relocate',action='store_true')
    collect=commands.add_parser('project-capture',help='Resolve selected refs and reuse a saved context');collect.add_argument('context',type=Path);collect.add_argument('change_id')
    for name in ('title','goal'):collect.add_argument('--'+name,required=True)
    for name in ('base','candidate','evidence-directory'):collect.add_argument('--'+name)
    collect.add_argument('--preview',action='store_true');collect.add_argument('--compact',action='store_true');collect.add_argument('--output',type=Path)
    selected=commands.add_parser('review-selection',help='Explicit decision using saved exact tokens');selected.add_argument('context',type=Path);selected.add_argument('selection',type=Path)
    for name in ('decision','reason','next-action'):selected.add_argument('--'+name,required=True)
    selected.add_argument('--finding',action='append',default=[]);selected.add_argument('--responsible-party');selected.add_argument('--operation-key');selected.add_argument('--reviewer-mode',default='ai_assisted_adjudication')
    package=commands.add_parser('prepare-review',help='Assemble one existing report/change into a selected review package; never approves or publishes');package.add_argument('context',type=Path);package.add_argument('--output',type=Path,required=True);package.add_argument('--resume',action='store_true')
    for name in ('change-id','title','goal','base','candidate'):package.add_argument('--'+name)
    package.add_argument('--report',type=Path);package.add_argument('--run-context',type=Path)
    project_view=commands.add_parser('build-project-view',help='Freeze selected attention list and views');project_view.add_argument('context',type=Path);project_view.add_argument('--output',type=Path,required=True)
    attention=commands.add_parser('attention',help='List captured changes in the selected owned context');attention.add_argument('context',type=Path);attention.add_argument('--only-attention',action='store_true')
    summary=commands.add_parser('handoff-summary',help='Readable summary from retained current evidence');summary.add_argument('context',type=Path);summary.add_argument('change_id')
    show_handoff = commands.add_parser('handoff'); show_handoff.add_argument('change_id'); show_handoff.add_argument('--baseline-revision', type=int)
    change_review = commands.add_parser('review-handoff')
    change_review.add_argument('change_id'); change_review.add_argument('--request', type=Path)
    for name in ('material-digest', 'decision', 'reason', 'next-action', 'operation-key', 'responsible-party'):
        change_review.add_argument('--' + name)
    change_review.add_argument('--expected-revision', type=int)
    change_review.add_argument('--finding', action='append', default=[])
    change_review.add_argument('--reviewer-mode', default='ai_assisted_adjudication')
    change_export = commands.add_parser('export-handoff')
    change_export.add_argument('change_id'); change_export.add_argument('--output', type=Path, required=True)
    change_export.add_argument('--baseline-revision', type=int)
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
        if args.command in ('capture-handoff', 'preview-handoff', 'write-receipt', 'backup-state', 'restore-state', 'build-handoff-view', 'import-junit', 'configure-project', 'associate-project', 'prepare-review', 'project-capture', 'review-selection', 'build-project-view', 'attention', 'handoff-summary', 'handoff', 'review-handoff', 'export-handoff', 'verify-handoff'):
            from . import handoff
            from .bundle import _read
            if args.command in ('capture-handoff','preview-handoff'):
                evidence = {}
                for item in args.evidence:
                    if '=' not in item or item.split('=', 1)[0] in evidence:
                        raise WorkbenchError('invalid-handoff', 'Supply unique NAME=FILE evidence attachments.')
                    name, path = item.split('=', 1); evidence[name] = path
                if args.profile:
                    from .handoff_profile import expand, bind_directory
                    definition=handoff.parse(_read(args.profile))
                    effective=expand(definition, change_id=args.change_id, title=args.title, goal=args.goal)
                    if args.evidence_dir:evidence=bind_directory(definition,args.evidence_dir,evidence)
                else:
                    if args.evidence_dir:raise WorkbenchError('invalid-handoff','Directory binding requires an explicitly selected profile.')
                    if any(v is not None for v in (args.change_id,args.title,args.goal)):
                        raise WorkbenchError('invalid-handoff','Change metadata belongs in --request or is supplied with --profile, never both.')
                    effective=handoff.parse(_read(args.request))
                if args.command=='preview-handoff':
                    if args.operation_key:raise WorkbenchError('invalid-handoff','Preview does not record operation keys.')
                    from .store import canonical,digest
                    material=handoff.inspect(args.root,repo=args.repo,base=args.base,candidate=args.candidate,request=effective,evidence=evidence)
                    from .handoff_context import eligible
                    result={'operation':'preview','runtime_writes':0,'material_digest':digest(canonical(material)),
                            'evidence_bindings':{k:str(v) for k,v in evidence.items()},'required_bindings_complete':eligible(material),
                            'notice':'Inspection only; capture rereads selected bytes. Reported checks are not executed.', 'material':material}
                else:
                    result = handoff.capture(args.root, repo=args.repo, base=args.base, candidate=args.candidate,
                        request=effective, evidence=evidence, operation_key=args.operation_key)
            elif args.command=='build-project-view':
                from .handoff_view import build_project
                result=build_project(args.context,args.output)
            elif args.command in ('attention','handoff-summary'):
                from .attention import list_changes,summary
                result=list_changes(args.context,args.only_attention) if args.command=='attention' else summary(args.context,args.change_id)
            elif args.command=='configure-project':
                from .project_context import configure
                result=configure(args.output,**{k:getattr(args,k) for k in ('repo','profile','evidence_directory','state','base_ref','candidate_ref')})
            elif args.command=='prepare-review':
                from .review_package import assemble
                result=assemble(args.context,args.output,resume=args.resume,change_id=args.change_id,title=args.title,goal=args.goal,report=args.report,run_context=args.run_context,base=args.base,candidate=args.candidate)
            elif args.command=='associate-project':
                from .project_scope import associate
                result=associate(args.context,relocate=args.relocate)
            elif args.command=='project-capture':
                from .project_context import collect
                result=collect(args.context,change_id=args.change_id,title=args.title,goal=args.goal,base=args.base,candidate=args.candidate,evidence_directory=args.evidence_directory,preview=args.preview,compact=args.compact,output=args.output)
            elif args.command=='review-selection':
                from .project_context import review_selection
                result=review_selection(args.context,args.selection,decision=args.decision,reason=args.reason,findings=args.finding,next_action=args.next_action,responsible_party=args.responsible_party,operation_key=args.operation_key,reviewer_mode=args.reviewer_mode)
            elif args.command=='import-junit':
                from .junit_report import import_report
                result=import_report(args.path,args.output,args.context)
            elif args.command=='build-handoff-view':
                from .handoff_view import build
                result=build(args.path,args.output)
            elif args.command in ('backup-state','restore-state'):
                from .state_backup import backup,restore
                result=backup(args.root,args.output) if args.command=='backup-state' else restore(args.path,args.output)
            elif args.command=='write-receipt':
                from .check_receipt import write
                result=write(handoff.parse(_read(args.request)),args.output)
            elif args.command == 'handoff': result = handoff.read(args.root, args.change_id, args.baseline_revision)
            elif args.command == 'review-handoff':
                if args.request:
                    if any(v is not None for v in (args.expected_revision,args.material_digest,args.decision,args.reason,args.next_action,args.operation_key,args.responsible_party)) or args.finding:
                        raise WorkbenchError('invalid-handoff','Use a review request or explicit review fields, never both.')
                    fields=handoff.parse(_read(args.request))
                    from .handoff_validation import obj
                    obj(fields,'review',('expected_revision','material_digest','decision','reason','findings','next_action','operation_key'),('reviewer_mode','responsible_party'))
                else:
                    fields=dict(expected_revision=args.expected_revision, material_digest=args.material_digest, decision=args.decision,
                        reason=args.reason, findings=args.finding, next_action=args.next_action, operation_key=args.operation_key,
                        reviewer_mode=args.reviewer_mode, responsible_party=args.responsible_party)
                result = handoff.review(args.root, args.change_id, **fields)
            elif args.command == 'export-handoff': result = handoff.export(args.root, args.change_id, args.output, args.baseline_revision)
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
