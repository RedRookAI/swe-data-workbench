#!/usr/bin/env python3
"""Record a scripted replay of existing ingestion-quality assessments.

Input is a completed run_quality_demo.py receipt with root (or workbench_root)
and versions [{version, bundle, batch_id, score}]. No intake, processing, candidate
creation or model request occurs here. Root launches this once after qualification.
All task decisions use real browser forms; final export bookkeeping uses the
existing verified exporters. The original driver receipt and results are retained.
"""
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
from urllib.parse import quote
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from swe_workbench.core import Workbench
from swe_workbench.evaluation import score_batch
from swe_workbench.evaluation_export import export_evaluation, verify_evaluation
from swe_workbench.exporter import export_batch, verify_export

TASK = REPO / 'examples' / 'ingest-recovery'
REPLAY_PREFIX = 'Scripted replay of recorded assessment: '


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local_path(value):
    require(isinstance(value, str) and bool(value), 'Receipt requires a local owner-selected path.')
    path = Path(value)
    return (path if path.is_absolute() else REPO / path).resolve()


def evidence_identity(scores):
    """Ignore quality/audit revisions while retaining exact prior machine evidence."""
    return sorted((item['submission_id'], item['patch_digest'], item.get('evidence_digest'),
                   item.get('execution_status'), item.get('score'), item.get('critical_passed'),
                   json.dumps(item['criteria'], sort_keys=True)) for item in scores['items'])


def validate_scores(scores, control_digest, candidate_digest):
    by_digest = {item['patch_digest']: item for item in scores['items']}
    require(control_digest in by_digest and candidate_digest in by_digest,
            'Recorded control/candidate patch identities are missing.')
    control, candidate = by_digest[control_digest], by_digest[candidate_digest]
    require(candidate.get('origin') == 'recorded_codex_attempt', 'Candidate origin is not the recorded attempt.')
    for role in ('reference', 'alternate'):
        selected = [item for item in scores['items'] if item['role'] == role]
        require(len(selected) == 1 and selected[0]['complete']
                and selected[0]['score'] == selected[0]['max_score']
                and selected[0]['critical_passed'] is True,
                'Reference/alternate lacks current complete passing evidence.')
    require(candidate['complete'] and candidate['score'] == candidate['max_score']
            and candidate['critical_passed'] is True, 'Recorded candidate lacks its expected passing prior measurements.')
    require(any(item['score'] is None and item['critical_passed'] is None for item in scores['items']),
            'The unmeasured candidate must remain visible and unassessed.')
    if scores['context']['evaluation']['kind'] == 'audit_challenge':
        require(control['score'] == control['max_score'] and control['critical_passed'] is True,
                'The original checker no longer demonstrates the recorded false pass.')
    else:
        require(control['complete'] and control['score'] < control['max_score']
                and control['critical_passed'] is False,
                'The revised checker does not demonstrate the recorded critical failure.')
    return control, candidate


def wait_server(process, origin):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        require(process.poll() is None, 'Owned recording server exited; inspect its private log.')
        try:
            with urllib.request.urlopen(origin + '/api/health', timeout=1) as response:
                if json.load(response).get('ok'):
                    return
        except OSError:
            time.sleep(.1)
    raise RuntimeError('Owned recording server readiness timed out.')


def api_read(origin, token, path):
    request = urllib.request.Request(origin + path, headers={'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def caption_time(seconds):
    milliseconds = round(seconds * 1000)
    return f'{milliseconds // 3600000:02}:{milliseconds // 60000 % 60:02}:{milliseconds // 1000 % 60:02}.{milliseconds % 1000:03}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True, help='Completed prior quality-driver receipt; no checks are rerun')
    parser.add_argument('--output', type=Path, required=True, help='Fresh owned recording directory')
    parser.add_argument('--assessment-file', type=Path, default=TASK / 'assessment.json', help='Root-owned actual assessment reference')
    args = parser.parse_args()
    receipt_path, assessment_path, output = args.receipt.resolve(), args.assessment_file.resolve(), args.output.resolve()
    driver = json.loads(receipt_path.read_text(encoding='utf-8'))
    assessment = json.loads(assessment_path.read_text(encoding='utf-8'))
    require(isinstance(assessment, (dict, list)) and bool(assessment), 'Actual root assessment reference is empty.')
    require(not output.exists() or not any(output.iterdir()), 'Use a fresh recording directory; earlier recordings are preserved.')
    root = local_path(driver.get('state') or driver.get('root') or driver.get('workbench_root'))
    require((root / 'workbench.sqlite3').is_file(), 'Driver receipt must identify an existing processed workbench.')
    versions = driver.get('versions')
    require(isinstance(versions, list) and len(versions) == 2, 'Receipt must contain the original and repaired score versions.')
    records = []
    for version in versions:
        require(isinstance(version, dict) and isinstance(version.get('score'), dict),
                'Each driver version needs version, bundle, batch_id and actual score_batch under score.')
        bundle = local_path(version['bundle'])
        workbench = Workbench(root, fixture_dir=bundle)
        workbench.initialize()
        current = score_batch(workbench, version['batch_id'])
        require(current['context']['id'] == version['score']['context']['id']
                and evidence_identity(current) == evidence_identity(version['score']),
                'Task material or prior machine results changed since the driver receipt.')
        require(current['context']['quality'] == version['score']['context']['quality']
                and current['context']['findings'] == version['score']['context']['findings'],
                'Recorded task assessment changed; supply the current driver receipt.')
        require(bool(current['context'].get('calibration')), 'Actual recorded calibration and author feedback must already exist.')
        decision = current['context']['quality']
        desired = 'needs-repair' if current['context']['evaluation']['kind'] == 'audit_challenge' else 'approved'
        require(decision.get('decision') == desired and bool(decision.get('reason', '').strip()),
                'Replay requires an existing reasoned task assessment for this version.')
        records.append({'input': version, 'bundle': bundle, 'workbench': workbench,
                        'before': current, 'decision': desired, 'reason': decision['reason']})
    records.sort(key=lambda record: record['before']['context']['evaluation']['kind'] != 'audit_challenge')
    require([r['before']['context']['evaluation']['kind'] for r in records] == ['audit_challenge', 'clean'],
            'Receipt must pair one audit challenge with one clean repaired task.')
    control_digest, candidate_digest = sha(TASK / 'unchanged-control.patch'), sha(TASK / 'candidate-001.patch')
    for record in records:
        validate_scores(record['before'], control_digest, candidate_digest)
    output.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(40)
    environment = os.environ.copy()
    environment['SWE_WORKBENCH_OWNER_TOKEN'] = token
    if (REPO / '.browsers').is_dir():
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(REPO / '.browsers'))
    servers, logs, events, mutations, browser_errors, blocked_requests = [], [], [], [], [], []
    started = time.monotonic()

    def mark(text):
        events.append({'seconds': round(time.monotonic() - started, 3), 'caption': text})

    try:
        for index, record in enumerate(records):
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            origin = 'http://127.0.0.1:' + str(port)
            log = (output / f'server-{index}.log').open('wb')
            logs.append(log)
            process = subprocess.Popen([sys.executable, '-m', 'swe_workbench.server', '--root', str(root),
                '--bundle', str(record['bundle']), '--port', str(port)], cwd=REPO, env=environment,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            servers.append(process)
            record['origin'] = origin
            wait_server(process, origin)

        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={'width': 1440, 'height': 1000},
                    record_video_dir=str(output / 'raw'), record_video_size={'width': 1440, 'height': 1000})
                page = context.new_page()
                page.set_default_timeout(15000)
                page.on('pageerror', lambda error: browser_errors.append(str(error)))

                def guard(route):
                    request = route.request
                    if request.method != 'GET':
                        allowed = request.method == 'POST' and (request.url.endswith('/quality') or request.url.endswith('/evaluation-export'))
                        if not allowed:
                            blocked_requests.append({'method': request.method, 'path': request.url.split('/api/', 1)[-1]})
                            route.abort()
                            return
                        payload = request.post_data_json
                        mutations.append({'path': request.url.split('/api/', 1)[-1],
                                          'decision': payload.get('decision'), 'reviewer_mode': payload.get('reviewer_mode'),
                                          'expected_revision': payload.get('expected_revision'), 'operation_key': payload['operation_key']})
                    route.continue_()
                page.route('**/api/**', guard)
                started = time.monotonic()
                mark('Scripted browser replay of recorded AI-assisted task assessments and prior executable evidence.')
                for index, record in enumerate(records):
                    origin, prior = record['origin'], record['before']
                    batch_id = record['input']['batch_id']
                    batch_path = '/api/batches/' + quote(batch_id, safe='')
                    read = lambda path: api_read(origin, token, path)
                    page.goto(origin + '/?mode=live')
                    require(page.get_by_label('Owner token', exact=True).get_attribute('type') == 'password', 'Owner entry must stay masked.')
                    page.get_by_label('Owner token', exact=True).fill(token)
                    page.get_by_role('button', name='Connect', exact=True).click()
                    page.get_by_text('Connected to the private owner API.', exact=True).wait_for()
                    if page.locator('#batch-select').input_value() != batch_id:
                        with page.expect_response(lambda response: response.url.endswith(batch_path + '/evaluation')):
                            page.locator('#batch-select').select_option(batch_id)
                        page.wait_for_timeout(150)
                    context_id = prior['context']['id']
                    page.get_by_text('Context: ' + context_id, exact=True).wait_for(state='attached')
                    page.locator('.quality-version table').first.scroll_into_view_if_needed()
                    page.wait_for_timeout(1200)
                    scores = read(batch_path + '/evaluation')
                    require(evidence_identity(scores) == evidence_identity(prior), 'Browser read differs from prior actual measurements.')
                    control, candidate = validate_scores(scores, control_digest, candidate_digest)
                    control_row = page.locator('.quality-version table tbody tr').filter(has_text=control_digest[:14])
                    expect(control_row).to_contain_text(f'{control["score"]} / {control["max_score"]}')
                    expect(control_row.locator('td').last).to_have_text('passed' if control['critical_passed'] else 'failed')
                    if index == 0:
                        mark(f'Original checker: existing-behavior control receives {control["score"]}/{control["max_score"]} with a passing critical gate. The recovery finding stays open.')
                    else:
                        mark(f'Repaired checker: unchanged control receives {control["score"]}/{control["max_score"]} and fails the critical recovery gate. Unmeasured input remains unassessed.')
                    page.wait_for_timeout(2200)
                    page.screenshot(path=str(output / ('weak.png' if index == 0 else 'workbench.png')))
                    items = read(batch_path + '/submissions')
                    require(all(item['disposition'] == 'pending' for item in items), 'This workflow preserves legacy code acceptance as pending.')
                    inspected = next(item for item in items if item['patch_digest'] == (control_digest if index == 0 else candidate_digest))
                    position = next(n for n, item in enumerate(items) if item['id'] == inspected['id'])
                    page.locator('#filter').select_option('all')
                    page.locator('#item-list button').nth(position).click()
                    page.get_by_role('tab', name='Task & patch', exact=True).click()
                    page.locator('#inspector').scroll_into_view_if_needed()
                    mark('Inspect the unchanged control patch and prior output.' if index == 0 else 'Inspect the recorded candidate patch and its prior check output. Candidate generation is recorded separately.')
                    page.wait_for_timeout(1700)
                    page.get_by_role('tab', name='Machine evidence', exact=True).click()
                    page.wait_for_timeout(1800)
                    page.locator('#quality-section').scroll_into_view_if_needed()
                    page.get_by_text('Review task quality', exact=True).click()
                    current = read(batch_path + '/evaluation')['context']
                    require(current['quality']['reason'] == record['reason'], 'Prior examined reason changed during replay.')
                    page.locator('#task-quality-decision').select_option(record['decision'])
                    page.locator('#task-reviewer-mode').select_option('scripted_adjudication')
                    page.locator('#task-quality-reason').fill((record['reason'] if record['reason'].startswith(REPLAY_PREFIX) else REPLAY_PREFIX + record['reason']))
                    page.locator('#task-findings').fill(json.dumps(current['findings'], ensure_ascii=False, indent=2))
                    mark('Replay the existing task diagnosis through the real review form; attribution is scripted_adjudication.')
                    page.get_by_role('button', name='Save task quality', exact=True).click()
                    page.get_by_text('Task quality saved against the current task revision.', exact=True).wait_for()
                    updated = read(batch_path + '/evaluation')
                    require(updated['context']['quality']['reviewer_mode'] == 'scripted_adjudication'
                            and updated['context']['quality']['decision'] == record['decision']
                            and updated['context']['quality']['reason'] == (record['reason'] if record['reason'].startswith(REPLAY_PREFIX) else REPLAY_PREFIX + record['reason'])
                            and updated['context']['revision'] > current['revision'],
                            'Browser task decision did not bind the current task revision.')
                    require(evidence_identity(updated) == evidence_identity(prior), 'Replay changed the prior machine evidence.')
                    calibration = page.get_by_text('Recorded calibration · operator', exact=True)
                    calibration.first.scroll_into_view_if_needed()
                    mark('Inspect the actual recorded AI-assisted review inputs, outputs, author feedback and guideline update.')
                    page.wait_for_timeout(1800)
                    if index == 1:
                        page.locator('#evaluation-export').scroll_into_view_if_needed()
                        mark('Freeze the approved evaluation task with every candidate outcome, including critical failure and unassessed input.')
                        page.get_by_role('button', name='Freeze evaluation dataset', exact=True).click()
                        page.locator('#evaluation-export-receipt').wait_for(state='visible')
                        expect(page.get_by_role('button', name='Freeze evaluation dataset', exact=True)).to_be_enabled()
                        page.wait_for_timeout(1700)
                    record['after_browser'] = updated
                mark('Task approval, criterion scores and all candidate outcomes remain separate from accepted-code curation. Model calls in this replay: zero.')
                page.locator('.quality-version table').first.scroll_into_view_if_needed()
                page.wait_for_timeout(1800)
                require(not browser_errors and not blocked_requests, 'Browser replay reported errors or prohibited mutation attempts.')
                recording_duration = round(time.monotonic() - started, 3)
                video = page.video
                page.close()
                context.close()
                video_path = output / 'recording.webm'
                video.save_as(str(video_path))
            finally:
                browser.close()

        results = []
        for record in records:
            workbench, batch_id = record['workbench'], record['input']['batch_id']
            scores = score_batch(workbench, batch_id)
            require(evidence_identity(scores) == evidence_identity(record['before']), 'Machine evidence changed after recording.')
            exported = export_evaluation(workbench, batch_id, root / 'evaluation-exports', 'quality-recording-' + secrets.token_hex(12))
            verification = verify_evaluation(exported['path'])
            require(verification['ok'], 'New evaluation export did not verify offline.')
            results.append({'version': record['input']['version'], 'bundle': str(record['bundle']), 'batch_id': batch_id,
                            'score': scores, 'export': exported, 'verification': verification})
        fixed = records[1]
        ordinary = export_batch(fixed['workbench'], fixed['input']['batch_id'], root / 'exports', 'quality-recording-ordinary-' + secrets.token_hex(12))
        ordinary_verification = verify_export(ordinary['path'])
        require(ordinary_verification['ok'] and ordinary['metrics']['counts']['accepted'] == 0,
                'Ordinary accepted-code export must retain zero accepted code records.')
        integrity = fixed['workbench'].verify()
        require(integrity['ok'], 'Final workbench integrity check failed.')
        duration = recording_duration
        source_files = sorted([*REPO.glob('swe_workbench/*.py'), *REPO.glob('web/*'), Path(__file__)])
        result = {'schema': 'swe-workbench-quality-recording/v1', 'recorded_at': datetime.now(timezone.utc).isoformat(),
                  'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
                  'source_commit_role': 'HEAD at replay; source_file_sha256 identifies actual bytes.',
                  'source_file_sha256': {str(path.relative_to(REPO)): sha(path) for path in source_files if path.is_file()},
                  'root': str(root), 'driver_receipt': str(receipt_path), 'driver_receipt_sha256': sha(receipt_path),
                  'assessment_reference': str(assessment_path), 'assessment_reference_sha256': sha(assessment_path),
                  'assessment_reason_source': 'Exact saved task-quality reason in the completed driver receipt; replay prefix added explicitly.',
                  'versions': results, 'ordinary_export': ordinary, 'ordinary_verification': ordinary_verification,
                  'model_calls': 0, 'model_calls_scope': 'This browser replay; prior recorded candidate generation remains separately attributed.',
                  'decision_origin': 'scripted browser replay of actual prior AI-assisted task assessments',
                  'reviewer_mode': 'scripted_adjudication', 'viewport': {'width': 1440, 'height': 1000},
                  'browser_errors': browser_errors, 'browser_error_count': len(browser_errors), 'blocked_requests': blocked_requests,
                  'browser_mutations': mutations, 'events': events, 'duration_seconds': duration,
                  'raw_video': str(video_path), 'raw_video_sha256': sha(video_path), 'integrity': integrity,
                  'image_sha256': {name: sha(output / name) for name in ('weak.png', 'workbench.png')}}
        (output / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        captions = ['WEBVTT\n']
        for index, event in enumerate(events):
            end = events[index + 1]['seconds'] if index + 1 < len(events) else duration
            captions.append(caption_time(event['seconds']) + ' --> ' + caption_time(end) + '\n' + event['caption'] + '\n')
        (output / 'captions.vtt').write_text('\n'.join(captions), encoding='utf-8')
        print(json.dumps({'receipt': str(output / 'receipt.json'), 'video': str(video_path),
                          'ordinary_export': ordinary['path'], 'model_calls': 0, 'browser_errors': 0}))
    finally:
        for process in reversed(servers):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()
