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


def recorded_routes(page, api_calls):
    def route(request_route):
        url = request_route.request.url
        if '/api/' in url:
            api_calls.append(url)
            request_route.fulfill(status=500, body='{}')
        elif url.endswith('/data/evidence.json'):
            request_route.fulfill(content_type='application/json', body=json.dumps(snapshot()))
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
        if path == '/api/batches': result = [data['batch']]
        elif path.endswith('/submissions'): result = data['items']
        elif path.endswith('/audit'): result = data['audit']
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
    page.get_by_role('tab', name='Adjudication').click()
    page.get_by_label('Reason and evidence').fill('Weak check misses the requested semantics.')
    page.get_by_label('Requested behavior', exact=True).select_option('fail')
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
