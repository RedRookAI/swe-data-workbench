"""Narrow browser checks use explicitly synthetic transport doubles, not run evidence."""
import functools
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

playwright = pytest.importorskip('playwright.sync_api')
WEB = Path(__file__).resolve().parents[1] / 'web'


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope='module')
def browser():
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.environ.get('SWE_WORKBENCH_CHROMIUM'))
        yield browser
        browser.close()


@pytest.fixture(scope='module')
def origin():
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(WEB)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield 'http://127.0.0.1:' + str(server.server_port)
    server.shutdown()
    thread.join()
    server.server_close()


def snapshot():
    attack = '<script>window.pwned=1</script><img src="https://example.invalid/exfil" onerror="window.pwned=1">'
    return {'export_schema': 'synthetic-browser-test', 'batch': {'id': 'browser-test', 'created_at': 'Synthetic browser fixture', 'raw_lines': 3, 'invalid_lines': 1, 'duplicate_lines': 1, 'unique_items': 1, 'counts': {'completed': 1, 'accepted': 0}}, 'items': [{'id': 'item-one', 'task_id': 'synthetic-dom-test', 'title': 'Browser test ' + attack, 'task_text': 'Preserve behavior. ' + attack, 'patch': '+ ' + attack, 'revision': 2, 'origin': 'synthetic_browser_fixture', 'execution_status': 'completed', 'disposition': 'needs-work', 'rubric_digest': 'rubric-one', 'result': {'evidence_digest': 'evidence-one', 'overall': 'passed', 'baseline': {'overall': 'failed', 'stdout': attack}, 'candidate': {'overall': 'passed'}, 'source_unchanged': True, 'checks': [{'name': 'Synthetic rendered output', 'outcome': 'passed', 'stdout': attack}]}, 'review': {'decision': 'needs-work', 'actor': 'operator', 'origin': 'developer_adjudication', 'reason': 'Synthetic browser test review', 'criteria': {'requested_behavior': 'fail'}}, 'seeded_reviews': [{'origin': 'synthetic_seed', 'decision': 'accepted'}]}], 'audit': [{'seq': 1, 'kind': 'synthetic_browser_test', 'actor': 'test', 'payload': {'text': attack}, 'hash': 'hash'}], 'cut': {'seq': 1, 'hash': 'hash'}, 'runtime': {}}


def recorded_routes(page, api_calls, data=None):
    def route(request_route):
        url = request_route.request.url
        if '/api/' in url:
            api_calls.append(url)
            request_route.fulfill(status=500, body='{}')
        elif url.endswith('/data/evidence.json'):
            request_route.fulfill(content_type='application/json', body=json.dumps(data or snapshot()))
        elif url.endswith('/data/manifest.json'):
            request_route.fulfill(content_type='application/json', body=json.dumps({'metrics': {'availability': 'synthetic browser check'}}))
        elif url.endswith('/recording.webm'):
            request_route.fulfill(content_type='video/webm', body='')
        else:
            request_route.continue_()
    page.route('**/*', route)


def test_recorded_is_inert_read_only_keyboard_usable_and_muted(browser, origin):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors, api_calls, external = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(origin) else None)
    recorded_routes(page, api_calls)
    page.goto(origin)
    page.get_by_role('button', name='Browser test', exact=False).wait_for()
    assert page.locator('#mode').inner_text() == 'Recorded · read only'
    assert page.get_by_text('Raw records received').is_visible()
    assert page.evaluate('window.pwned') is None
    assert page.locator('img').count() == 0
    assert page.locator('#owner-actions').is_hidden()
    assert page.locator('#export').is_hidden()
    page.get_by_role('tab', name='Task & patch').focus()
    page.keyboard.press('ArrowRight')
    assert page.get_by_role('tab', name='Machine evidence').get_attribute('aria-selected') == 'true'
    assert page.get_by_text('Baseline measurement').is_visible()
    page.keyboard.press('ArrowRight')
    assert page.get_by_text('Current developer adjudication').is_visible()
    assert page.get_by_text('Recorded read-only evidence.', exact=False).is_visible()
    assert page.locator('#review-form').count() == 0
    page.get_by_role('tab', name='Provenance').click()
    assert page.get_by_text('Synthetic seeded reviewers', exact=True).is_visible()
    assert page.evaluate('window.pwned') is None
    page.locator('#recording-section').wait_for(state='visible')
    assert page.locator('video').evaluate('(v) => v.paused && v.muted && v.controls && !v.autoplay && v.volume === 0.1')
    assert page.locator('video').get_attribute('preload') == 'none'
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert not api_calls and not external and not errors
    page.close()


def test_live_token_only_in_headers_review_binds_current_identity(browser, origin):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    token = 'browser-owner-test-' + 'x' * 40
    requests = []
    data = snapshot()
    def api(route):
        req = route.request
        requests.append({'url': req.url, 'headers': req.headers, 'body': req.post_data_json if req.method == 'POST' else None})
        path = req.url.split(origin, 1)[1]
        if path == '/api/bundle': result = {'name': 'synthetic-fixtures', 'title': 'Authored sample', 'origin': 'synthetic_fixture', 'prediction_format': 'native'}
        elif path == '/api/batches': result = [data['batch']]
        elif path.endswith('/submissions'): result = data['items']
        elif path.endswith('/audit'): result = data['audit']
        elif path.endswith('/evaluation'):
            route.fulfill(status=422, content_type='application/json', body=json.dumps({'error': {'code': 'evaluation-unavailable', 'message': 'Legacy task has no evaluation definition.'}}))
            return
        elif '/review' in path: result = data['items'][0]
        elif path.startswith('/api/submissions/'): result = data['items'][0]
        else: result = data['batch']
        route.fulfill(content_type='application/json', body=json.dumps(result))
    page.route('**/api/**', api)
    page.goto(origin + '/?mode=live')
    page.get_by_label('Owner token', exact=True).fill(token)
    page.get_by_role('button', name='Connect', exact=True).click()
    page.get_by_role('button', name='Browser test', exact=False).wait_for()
    assert page.get_by_label('Owner token', exact=True).input_value() == ''
    assert page.get_by_role('button', name='Import trusted sample', exact=True).is_visible()
    assert page.locator('#quality-section').is_hidden()
    page.get_by_role('tab', name='Adjudication').click()
    page.get_by_label('Reason and evidence').fill('Weak check misses the requested semantics.')
    page.get_by_label('Requested behavior', exact=True).select_option('fail')
    page.get_by_label('Disposition', exact=True).select_option('needs-work')
    page.get_by_role('button', name='Save exact-version adjudication').click()
    page.get_by_text('Developer adjudication saved', exact=False).wait_for()
    reviews = [request for request in requests if '/review' in request['url']]
    assert len(reviews) == 1
    body = reviews[0]['body']
    assert body['expected_revision'] == 2
    assert body['evidence_digest'] == 'evidence-one'
    assert body['rubric_digest'] == 'rubric-one'
    assert body['criteria']['requested_behavior'] == 'fail'
    assert body['criteria']['preserved_behavior'] == 'not-assessed'
    assert body['operation_key']
    assert 'actor' not in body
    assert all(request['headers']['authorization'] == 'Bearer ' + token for request in requests)
    assert all(token not in request['url'] for request in requests)
    assert page.evaluate('localStorage.length') == 0
    assert page.evaluate('document.cookie') == ''
    page.get_by_role('button', name='Disconnect', exact=True).click()
    assert page.locator('#owner-actions').is_hidden()
    assert page.locator('#item-list').inner_text() == 'No submissions in this view.'
    page.close()


def test_missing_snapshot_has_honest_empty_state(browser, origin):
    page = browser.new_page()
    page.route('**/data/evidence.json', lambda route: route.fulfill(status=404, body='missing'))
    page.goto(origin)
    page.get_by_text('The recorded evidence snapshot is unavailable.').wait_for()
    assert page.locator('#downloads').is_hidden()
    assert page.locator('#owner-actions').is_hidden()
    assert page.get_by_text('No recorded snapshot available.').is_visible()
    page.close()


def real_case_browser_fixture():
    """Synthetic browser fixture representing the new public-case view contract."""
    data = snapshot()
    item = data['items'][0]
    claim = '<img src="https://example.invalid/model" onerror="window.pwned=1">'
    item.update(origin='public_upstream', trusted_tuple=True, provenance={'repository': 'https://example.invalid/upstream', 'base_commit': 'pinned', 'checker_origin': 'Synthetic browser contract check'}, patch_provenance={'origin': 'public_upstream', 'source': 'https://example.invalid/reference', 'license': 'MIT'}, lineage=[{'line': 1, 'input_format': 'swebench', 'declared_source': 'public delivery', 'declared_model': claim, 'raw_digest': 'first-raw-digest', 'raw_record_base64': 'ZXhhY3QgcmF3'}, {'line': 2, 'input_format': 'swebench', 'declared_source': 'repeated reference', 'declared_model': 'another source claim', 'raw_digest': 'second-raw-digest', 'duplicate_of': 1}])
    item['review'].update(origin='scripted_adjudication', reviewer_mode='scripted_adjudication')
    data['runtime']['bundle'] = {'name': 'unicode-hyphen', 'title': 'Configured recorded public case', 'origin': 'public_upstream', 'prediction_format': 'swebench'}
    data['items'].append({'id': 'synthetic-control', 'task_id': 'same-task', 'title': 'Synthetic negative control', 'origin': 'synthetic_control', 'execution_status': 'completed', 'disposition': 'pending', 'revision': 2, 'patch': '+ // synthetic negative', 'result': None})
    return data


def test_public_provenance_and_claims_are_inert_modes_honest_zero_volume_retained(browser, origin):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.add_init_script("sessionStorage.setItem('workbench-preview-volume', '0')")
    api_calls, external = [], []
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(origin) else None)
    recorded_routes(page, api_calls, real_case_browser_fixture())
    page.goto(origin)
    page.locator('#synthetic-link').wait_for(state='visible')
    assert page.locator('#case-kind').inner_text() == 'PUBLIC UPSTREAM CASE'
    assert page.locator('#case-title').inner_text() == 'Configured recorded public case'
    assert page.locator('#synthetic-link').get_attribute('href') == './synthetic/'
    assert page.locator('#owner-actions').is_hidden()
    page.get_by_role('tab', name='Provenance').click()
    assert page.get_by_text('Approved source and patch provenance', exact=True).is_visible()
    claims = page.get_by_role('tabpanel', name='Provenance').inner_text()
    assert 'public delivery' in claims and 'repeated reference' in claims
    assert 'first-raw-digest' in claims and 'second-raw-digest' in claims
    assert 'another source claim' in claims and 'example.invalid/model' in claims
    assert 'ZXhhY3QgcmF3' not in claims
    assert page.locator('img').count() == 0 and page.evaluate('window.pwned') is None
    page.get_by_role('tab', name='Adjudication').click()
    assert page.get_by_text('Current scripted adjudication', exact=True).is_visible()
    page.locator('#recording-section').wait_for(state='visible')
    assert page.locator('video').evaluate('(v) => v.volume === 0 && v.paused && v.muted && v.controls')
    page.get_by_role('button', name='Synthetic negative control', exact=False).click()
    assert page.locator('#inspector').get_by_text('synthetic_control', exact=True).is_visible()
    assert not api_calls and not external
    page.close()


def test_live_approved_import_and_deliberate_scripted_mode(browser, origin):
    page = browser.new_page()
    data = real_case_browser_fixture()
    imported = False
    requests = []
    def api(route):
        nonlocal imported
        req = route.request
        path = req.url.split(origin, 1)[1]
        body = req.post_data_json if req.method == 'POST' else None
        requests.append((path, body))
        if path == '/api/bundle': result = {'name': 'unicode-hyphen', 'title': 'Configured public case', 'origin': 'public_upstream', 'prediction_format': 'swebench'}
        elif path == '/api/import-approved': imported = True; result = data['batch']
        elif path == '/api/batches': result = [data['batch']] if imported else []
        elif path.endswith('/submissions'): result = data['items']
        elif path.endswith('/audit'): result = data['audit']
        elif path.endswith('/review'):
            data['items'][0]['review']['reviewer_mode'] = body['reviewer_mode']
            data['items'][0]['review']['origin'] = body['reviewer_mode']
            result = data['items'][0]
        elif path.startswith('/api/submissions/'): result = data['items'][0]
        else: result = data['batch']
        route.fulfill(content_type='application/json', body=json.dumps(result))
    page.route('**/api/**', api)
    page.goto(origin + '/?mode=live')
    page.get_by_label('Owner token', exact=True).fill('owner-browser-test-' + 'x' * 40)
    page.get_by_role('button', name='Connect', exact=True).click()
    page.get_by_role('button', name='Import approved task').wait_for(state='visible')
    assert page.locator('#synthetic-link').is_hidden()
    page.get_by_role('button', name='Import approved task').click()
    page.get_by_role('tab', name='Adjudication').click()
    assert page.get_by_label('Disposition', exact=True).input_value() == ''
    assert page.get_by_label('Reviewer mode', exact=True).input_value() == 'developer_adjudication'
    page.get_by_label('Reviewer mode', exact=True).select_option('scripted_adjudication')
    page.get_by_label('Disposition', exact=True).select_option('needs-work')
    page.get_by_label('Reason and evidence').fill('Scripted browser contract check against current evidence.')
    page.get_by_role('button', name='Save exact-version adjudication').click()
    page.get_by_text('Scripted adjudication saved', exact=False).wait_for()
    imports = [body for path, body in requests if path == '/api/import-approved']
    assert len(imports) == 1 and set(imports[0]) == {'operation_key'}
    assert all(path != '/api/import-sample' for path, _ in requests)
    reviews = [body for path, body in requests if path.endswith('/review')]
    assert len(reviews) == 1 and reviews[0]['reviewer_mode'] == 'scripted_adjudication'
    assert 'actor' not in reviews[0]
    page.close()


def quality_browser_fixture():
    """Synthetic view-contract data only; never publish these as measured results."""
    import copy
    attack = '<img src="https://example.invalid/quality" onerror="window.pwned=1">'
    rubric = [{'id': 'ordinary', 'points': 25, 'critical': False}, {'id': 'identity', 'points': 25, 'critical': False}, {'id': 'recovery', 'points': 50, 'critical': True}]
    finding = {'id': 'recovery-gap', 'kind': 'coverage', 'severity': 'critical', 'status': 'open', 'reason': 'Synthetic browser fixture ' + attack, 'assignee': 'test-author', 'requested_correction': 'Exercise the commit-before-ack replay window.'}
    reviews = [{'review_id': 'synthetic-view-' + str(n), 'actor': 'test-reviewer-' + str(n), 'reviewer_mode': 'ai_assisted_adjudication', 'decision': 'needs-repair', 'reason': 'Synthetic rendering fixture', 'input_digest': 'a' * 64, 'output_digest': str(n) * 64} for n in [1, 2]]
    calibration = {'actor': 'operator', 'reviews': reviews, 'reason': 'Synthetic browser contract calibration', 'author_feedback': 'Add replay evidence ' + attack, 'guideline_update': 'Check the committed-but-unacknowledged window.', 'agreement': {'matching_pairs': 1, 'pairs': 1, 'value': 1, 'origin': 'separately_recorded_ai_assisted_reviews'}}
    context = {'task_id': 'ingest-recovery', 'id': 'quality-test-context', 'revision': 3, 'material_digest': 'material', 'quality': {'decision': 'needs-repair', 'reason': 'Missing recovery coverage.', 'actor': 'operator', 'reviewer_mode': 'ai_assisted_adjudication'}, 'findings': [finding], 'calibration': [calibration], 'rubric': rubric, 'requirements': [{'id': 'replay', 'text': 'An acknowledged record appears exactly once.'}], 'evaluation': {'family': 'ingestion', 'version': 'weak-test', 'kind': 'audit_challenge'}}
    def item(label, score, critical, pending=False):
        return {'submission_id': label, 'patch_digest': label + '-digest', 'role': label, 'origin': 'synthetic_browser_fixture', 'score': score, 'max_score': 100, 'complete': not pending, 'critical_passed': critical, 'evidence_digest': None if pending else label + '-evidence', 'criteria': [{'id': row['id'], 'points': row['points'], 'critical': row['critical'], 'earned': None if pending else row['points'], 'outcome': 'unassessed' if pending else 'passed', 'checks': []} for row in rubric]}
    before = {'context': context, 'items': [item('reference', 100, True), item('weak-control', 100, True), item('pending', None, None, True)], 'summary': {'task_count': 1, 'unique_submissions': 3, 'unassessed_scores': 1}, 'batch_id': 'browser-test', 'cut': {'seq': 1, 'hash': 'cut'}}
    after = copy.deepcopy(before)
    after['context'].update(id='quality-repaired-context', revision=4, evaluation={'family': 'ingestion', 'version': 'fixed-test', 'kind': 'clean'}, quality={'decision': 'approved', 'reason': 'Synthetic browser test approval label.', 'actor': 'operator', 'reviewer_mode': 'scripted_adjudication'})
    after['context']['findings'][0].update(status='resolved', resolution='fixed-test verifier now exercises replay.')
    after['items'][1].update(score=50, critical_passed=False)
    after['items'][1]['criteria'][2].update(earned=0, outcome='failed')
    return {'schema': 'swe-workbench-quality-demo/v1', 'versions': [before, after], 'comparison': [{'patch_digest': 'weak-control-digest', 'label': 'Synthetic weak-check control', 'origin': 'synthetic_browser_fixture', 'before_score': 100, 'after_score': 50, 'before_critical': True, 'after_critical': False, 'false_pass': True}]}


def test_recorded_quality_versions_matrix_and_feedback_are_inert_all_outcomes_visible(browser, origin):
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    calls, external, errors = [], [], []
    recorded_routes(page, calls)
    page.route('**/quality.json', lambda route: route.fulfill(content_type='application/json', body=json.dumps(quality_browser_fixture())))
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(origin) else None)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(origin)
    page.get_by_role('heading', name='Evaluation quality', exact=True).wait_for()
    assert page.locator('#quality-section').is_visible()
    assert page.get_by_text('False pass exposed', exact=True).is_visible()
    assert page.get_by_role('heading', name='Before · original checker').is_visible()
    assert page.get_by_role('heading', name='After · revised checker').is_visible()
    versions = page.locator('.quality-version')
    assert versions.count() == 2
    failed = versions.nth(1).get_by_role('row', name='weak-control', exact=False)
    assert '50 / 100' in failed.inner_text() and 'failed' in failed.inner_text()
    assert failed.locator('td').last.inner_text() == 'failed'
    pending = versions.nth(1).get_by_role('row', name='pending', exact=False)
    assert 'Unassessed' in pending.inner_text() and '0 / 100' not in pending.inner_text()
    assert page.get_by_role('heading', name='Review calibration and author feedback').count() == 2
    assert page.get_by_text('Recorded calibration · operator', exact=True).count() == 2
    assert page.get_by_text('test-reviewer-1 · AI-assisted adjudication', exact=True).count() == 2
    assert page.locator('#task-quality-form').count() == 0
    assert page.get_by_role('link', name='Prepared bundle example').get_attribute('href') == './prepared/'
    assert page.evaluate('window.pwned') is None and page.locator('img').count() == 0
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert not calls and not external and not errors
    page.close()


def test_live_quality_revision_findings_calibration_and_separate_export(browser, origin):
    page = browser.new_page()
    data = snapshot()
    scores = quality_browser_fixture()['versions'][0]
    requests = []
    def api(route):
        request = route.request
        path = request.url.split(origin, 1)[1]
        body = request.post_data_json if request.method == 'POST' else None
        requests.append((path, body))
        if path == '/api/bundle': result = {'name': 'ingestion', 'title': 'Synthetic API view contract', 'origin': 'synthetic_fixture', 'prediction_format': 'native'}
        elif path == '/api/batches': result = [data['batch']]
        elif path.endswith('/submissions'): result = data['items']
        elif path.endswith('/audit'): result = data['audit']
        elif path.endswith('/evaluation'): result = scores
        elif path.endswith('/quality'):
            scores['context']['revision'] += 1
            scores['context']['quality'] = body
            scores['context']['findings'] = body['findings']
            result = scores['context']
        elif path.endswith('/calibration'):
            scores['context']['revision'] += 1
            scores['context']['calibration'].append(body | {'actor': 'operator'})
            result = scores['context']
        elif path.endswith('/evaluation-export'): result = {'manifest_digest': 'quality-only-manifest'}
        elif path.startswith('/api/submissions/'): result = data['items'][0]
        else: result = data['batch']
        route.fulfill(content_type='application/json', body=json.dumps(result))
    page.route('**/api/**', api)
    page.goto(origin + '/?mode=live')
    page.get_by_label('Owner token', exact=True).fill('quality-owner-test-' + 'x' * 40)
    page.get_by_role('button', name='Connect', exact=True).click()
    page.get_by_role('heading', name='Evaluation quality', exact=True).wait_for()
    page.get_by_text('Review task quality', exact=True).click()
    page.get_by_label('Task quality decision').select_option('needs-repair')
    page.get_by_label('Task quality reason').fill('Synthetic browser revision binding check.')
    page.get_by_label('Findings (JSON array)').fill('{broken')
    page.get_by_role('button', name='Save task quality', exact=True).click()
    page.get_by_text('Findings must be valid JSON.', exact=True).wait_for()
    assert not [entry for entry in requests if entry[0].endswith('/quality')]
    page.get_by_label('Findings (JSON array)').fill(json.dumps(scores['context']['findings']))
    page.get_by_role('button', name='Save task quality', exact=True).click()
    page.get_by_text('Task quality saved against the current task revision.', exact=True).wait_for()
    saved = next(body for path, body in requests if path.endswith('/quality'))
    assert saved['expected_revision'] == 3 and saved['reviewer_mode'] == 'ai_assisted_adjudication'
    assert saved['findings'][0]['severity'] == 'critical' and 'actor' not in saved
    page.get_by_text('Record calibration and author feedback', exact=True).click()
    reviews = quality_browser_fixture()['versions'][0]['context']['calibration'][0]['reviews']
    page.get_by_label('Recorded AI-assisted reviews (JSON array)').fill(json.dumps(reviews))
    page.get_by_label('Calibration reason', exact=True).fill('Compare two separately recorded test reviews.')
    page.get_by_label('Author feedback', exact=True).fill('Synthetic feedback payload.')
    page.get_by_label('Guideline update', exact=True).fill('Synthetic guideline payload.')
    page.get_by_role('button', name='Save calibration', exact=True).click()
    page.get_by_text('Calibration, author feedback and guideline update recorded.', exact=True).wait_for()
    calibration = next(body for path, body in requests if path.endswith('/calibration'))
    assert calibration['reviews'] == reviews and calibration['author_feedback'] == 'Synthetic feedback payload.'
    assert 'actor' not in calibration
    page.get_by_role('button', name='Freeze evaluation dataset').click()
    page.get_by_text('Evaluation dataset frozen with every candidate outcome.', exact=True).wait_for()
    assert 'quality-only-manifest' in page.locator('#evaluation-export-receipt').inner_text()
    exported = [body for path, body in requests if path.endswith('/evaluation-export')]
    assert len(exported) == 1 and set(exported[0]) == {'operation_key'}
    page.get_by_role('button', name='Disconnect', exact=True).click()
    assert page.locator('#quality-section').is_hidden()
    page.close()
