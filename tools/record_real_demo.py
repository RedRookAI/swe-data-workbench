#!/usr/bin/env python3
"""Record actual upstream-case controls; replay explicitly labeled reference reviews."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from swe_workbench.core import Workbench
from swe_workbench.exporter import export_batch, verify_export
from run_real_demo import review_requests


def examined_replay(workbench, batch_id, assessment_file):
    """Bind previously examined reasons to this recording's actual evidence."""
    assessments = json.loads(assessment_file.read_text())['assessments']
    requests = []
    for item in workbench.submissions(batch_id):
        assessment = assessments.get(item['patch_digest'])
        if assessment is None:
            assert not item['trusted_tuple'] and item['result'] is None
            continue
        assert item['trusted_tuple'] and item['context_current'] and item['result']['source_unchanged']
        for key in ('source_digest', 'check_digest', 'rubric_digest', 'task_text'):
            assert item[key] == assessment[key], 'Changed assessment context: ' + key
        for phase in ('baseline', 'candidate'):
            assert [c['outcome'] for c in item['result'][phase]['checks']] == assessment[phase + '_outcomes']
        requests.append((item, dict(expected_revision=item['revision'], evidence_digest=item['result']['evidence_digest'],
            rubric_digest=item['rubric_digest'], decision=assessment['decision'], criteria=assessment['criteria'],
            reason='Scripted browser replay of the examined assessment: ' + assessment['reason'],
            reviewer_mode='scripted_adjudication', operation_key='examined-replay-' + item['id'])))
    assert len(requests) == len(assessments)
    return requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=REPO / '.state/recorded-real')
    parser.add_argument('--output', type=Path, default=REPO / 'recordings/real')
    parser.add_argument('--bundle', default='unicode-hyphen', help='Owner-selected local bundle or built-in name')
    parser.add_argument('--assessment-file', type=Path, help='Actual prior examined assessments to replay explicitly as scripted')
    args = parser.parse_args()
    root, out = args.root.resolve(), args.output.resolve()
    if root.exists() and any(root.iterdir()):
        parser.error('Use a fresh owned root; existing evidence is preserved.')
    root.mkdir(parents=True, exist_ok=True); out.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(40)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    origin = 'http://127.0.0.1:' + str(port)
    env = os.environ.copy(); env['SWE_WORKBENCH_OWNER_TOKEN'] = token
    serverlog = (out / 'server.log').open('wb')
    server = subprocess.Popen([sys.executable, '-m', 'swe_workbench.server', '--root', str(root),
        '--bundle', args.bundle, '--port', str(port)], cwd=REPO, env=env,
        stdout=serverlog, stderr=subprocess.STDOUT)
    browser = None; events = []; started = time.monotonic()
    def mark(caption):
        events.append({'seconds': round(time.monotonic() - started, 3), 'caption': caption})
    def api(path):
        request = urllib.request.Request(origin + path, headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError('Owned server failed to start.')
            try:
                with urllib.request.urlopen(origin + '/api/health', timeout=1) as response:
                    if json.load(response).get('ok'): break
            except OSError: time.sleep(.1)
        else: raise RuntimeError('Owned server did not become ready.')
        from playwright.sync_api import sync_playwright, expect
        if (REPO / '.browsers').exists():
            os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(REPO / '.browsers'))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000},
                record_video_dir=str(out / 'raw'), record_video_size={'width': 1440, 'height': 1000})
            page = context.new_page(); page.set_default_timeout(10000)
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            started = time.monotonic()
            mark('Real historical upstream case. Human reference patch, labeled synthetic controls. No model calls.')
            page.goto(origin + '/?mode=live')
            page.get_by_label('Owner token', exact=True).fill(token)
            page.get_by_role('button', name='Connect', exact=True).click()
            page.get_by_role('button', name='Import approved task', exact=True).wait_for()
            page.wait_for_timeout(1300)
            mark('Import four exact records: three unique patches and one repeated delivery. Only two tuples are approved.')
            page.get_by_role('button', name='Import approved task', exact=True).click()
            page.locator('#item-list button').nth(2).wait_for()
            page.wait_for_timeout(1800)
            batch_id = api('/api/batches')[0]['id']
            mark('Run actual baseline, Git application and candidate checks in separate workspaces. The unknown variant stays pending.')
            page.get_by_role('button', name='Run checks · 1 worker', exact=True).click()
            expect(page.get_by_role('button', name='Run checks · 1 worker', exact=True)).to_be_enabled()
            workbench = Workbench(root, fixture_dir=args.bundle); workbench.initialize()
            assessed = examined_replay(workbench, batch_id, args.assessment_file) if args.assessment_file else review_requests(workbench, batch_id)
            def select(item):
                items = api('/api/batches/' + batch_id + '/submissions')
                index = next(n for n, value in enumerate(items) if value['id'] == item['id'])
                page.locator('#filter').select_option('all')
                page.locator('#item-list button').nth(index).click()
                page.locator('#inspector h2').wait_for()
            # The plan is derived from examined exact code, not fixture_label or an input author claim.
            for item, request in sorted(assessed, key=lambda pair: pair[1]['decision'] == 'accepted'):
                select(item)
                label = 'selected upstream PR revision' if args.assessment_file else ('human upstream fix' if request['decision'] == 'accepted' else 'synthetic comment-only control')
                mark('Inspect the ' + label + ': exact diff, actual check output and source preservation.')
                page.get_by_role('tab', name='Task & patch', exact=True).click()
                page.locator('#inspector').scroll_into_view_if_needed(); page.wait_for_timeout(1800)
                page.get_by_role('tab', name='Machine evidence', exact=True).click(); page.wait_for_timeout(2200)
                mark('Replay the Codex-assisted code assessment through real controls. This is scripted adjudication, not independent human review.')
                page.get_by_role('tab', name='Adjudication', exact=True).click()
                page.locator('#reviewer-mode').select_option('scripted_adjudication')
                for criterion, verdict in request['criteria'].items():
                    page.locator('#criterion-' + criterion).select_option(verdict)
                page.locator('#decision').select_option(request['decision'])
                page.get_by_label('Reason and evidence', exact=True).fill(request['reason'])
                page.get_by_role('button', name='Save exact-version adjudication', exact=True).click()
                page.get_by_text('Scripted adjudication saved', exact=False).wait_for()
                assert api('/api/submissions/' + item['id'])['disposition'] == request['decision']
                page.wait_for_timeout(1400)
            mark('Freeze one accepted upstream patch with its full lineage. The failing and unapproved controls remain visible.')
            page.locator('#export-section').scroll_into_view_if_needed()
            page.get_by_role('button', name='Freeze accepted export', exact=True).click()
            page.locator('#export-receipt').wait_for(state='visible'); page.wait_for_timeout(1800)
            exported = export_batch(workbench, batch_id, root / 'exports', 'real-recording-export-v1')
            repeated = export_batch(workbench, batch_id, root / 'exports', 'real-recording-repeat-v1')
            assert exported['manifest_digest'] == repeated['manifest_digest']
            verification = verify_export(exported['path']); assert verification['ok'] and verification['accepted_count'] == 1
            batch = workbench.batch(batch_id)
            assert batch['counts']['rejected'] == 1 and batch['counts']['pending-evidence'] == 1
            assert not errors, errors
            page.locator('#main').scroll_into_view_if_needed(); page.wait_for_timeout(1600)
            page.screenshot(path=str(out / 'workbench.png'), full_page=True)
            video = page.video; page.close(); context.close()
            raw = Path(video.path()); browser.close(); browser = None
            receipt = {'schema': 'swe-workbench-browser-recording/v2', 'recorded_at': datetime.now(timezone.utc).isoformat(),
                'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
                'source_commit_role': 'Repository HEAD at recording; source_file_sha256 identifies the actual bytes, including uncommitted work.',
                'source_file_sha256': {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted([*REPO.glob('swe_workbench/*.py'), *REPO.glob('web/*')]) if p.is_file()},
                'case_origin': 'public upstream issue and human patch; labeled synthetic controls',
                'decision_origin': 'scripted browser replay of Codex-assisted code assessment', 'model_calls': 0,
                'assessment_reference_sha256': hashlib.sha256(args.assessment_file.read_bytes()).hexdigest() if args.assessment_file else None,
                'keep_dependency': False, 'batch': batch, 'export_path': exported['path'],
                'manifest_digest': exported['manifest_digest'], 'verification': verification, 'integrity': workbench.verify(),
                'browser_errors': errors, 'raw_video': str(raw), 'raw_video_sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
                'events': events, 'duration_seconds': round(time.monotonic() - started, 3)}
            (out / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
            def stamp(value):
                n = round(value * 1000); return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02}.{n%1000:03}'
            captions = ['WEBVTT\n']
            for n, event in enumerate(events):
                end = events[n+1]['seconds'] if n+1 < len(events) else receipt['duration_seconds']
                captions.append(stamp(event['seconds']) + ' --> ' + stamp(end) + '\n' + event['caption'] + '\n')
            (out / 'captions.vtt').write_text('\n'.join(captions))
            print(json.dumps({'receipt': str(out / 'receipt.json'), 'video': str(raw), 'export': exported['path'], 'browser_errors': errors}))
    finally:
        if browser:
            try: browser.close()
            except Exception: pass
        server.terminate()
        try: server.wait(timeout=10)
        except subprocess.TimeoutExpired: server.kill(); server.wait()
        serverlog.close()


if __name__ == '__main__':
    main()
