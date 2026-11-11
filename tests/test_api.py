"""Focused transport/security checks; doubles do not claim core semantics."""
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from swe_workbench.api import CRITERIA, MAX_BODY, create_app
from swe_workbench.errors import WorkbenchError

TOKEN = 'test-owner-secret-' + 'x' * 40
AUTH = {'Authorization': 'Bearer ' + TOKEN}
POST = AUTH | {'Origin': 'http://testserver', 'Content-Type': 'application/json'}


class AdapterDouble:
    def __init__(self, root):
        self.calls = []

    def initialize(self):
        pass

    def import_sample(self, **body):
        self.calls.append(('import', body))
        return {'id': 'batch-one'}

    def list_batches(self):
        return [{'id': 'batch-one'}]

    def batch(self, batch_id):
        if batch_id == 'missing':
            raise WorkbenchError('not-found', 'Batch absent.', 404)
        return {'id': batch_id}

    def submissions(self, batch_id):
        return [{'id': 'one', 'title': '<script>window.pwned=1</script>'}]

    def submission(self, submission_id):
        return {'id': submission_id}

    def audit_events(self, batch_id):
        return []

    def review(self, submission_id, **body):
        self.calls.append(('review', submission_id, body))
        return {'id': submission_id, 'review': body}

    def process(self, batch_id, workers):
        self.calls.append(('process', batch_id, workers))
        return {'completed': 1}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr('swe_workbench.core.Workbench', AdapterDouble)
    with TestClient(create_app(tmp_path, owner_token=TOKEN)) as test:
        yield test


def test_owner_required_for_all_private_reads_and_mutations(client):
    for path in ['/api/batches', '/api/submissions/one', '/api/batches/one/audit']:
        assert client.get(path).status_code == 401
    assert client.post('/api/import-sample', json={'operation_key': 'one'}, headers={'Origin': 'http://testserver'}).status_code == 401
    assert client.get('/api/health').json()['ok'] is True
    assert client.get('/api/batches', headers=AUTH).status_code == 200
    assert client.get('/').status_code == 200


@pytest.mark.parametrize('origin', [None, 'null', 'https://testserver', 'http://testserver.evil', 'http://testserver:80', 'http://evil.example'])
def test_exact_origin_required_even_with_valid_bearer(client, origin):
    headers = AUTH.copy()
    if origin is not None:
        headers['Origin'] = origin
    response = client.post('/api/import-sample', json={'operation_key': 'one'}, headers=headers)
    assert response.status_code == 403
    assert not client.app.state.workbench.calls


def test_cross_site_and_same_site_fetch_denied(client):
    for site in ['cross-site', 'same-site']:
        assert client.post('/api/import-sample', json={'operation_key': 'one'}, headers=POST | {'Sec-Fetch-Site': site}).status_code == 403
    assert client.post('/api/import-sample', json={'operation_key': 'one'}, headers=POST | {'Sec-Fetch-Site': 'same-origin'}).status_code == 200
    assert len(client.app.state.workbench.calls) == 1


def test_malformed_host_cannot_bypass_raw_scope_authorization(client):
    assert client.get('/api/batches', headers={'Host': 'testserver/api/health?x='}).status_code == 400
    assert client.post('/api/import-sample', headers=POST | {'Host': 'testserver#fragment'}, json={'operation_key': 'one'}).status_code == 400
    assert client.get('/api/batches?path=/api/health').status_code == 401


def test_no_default_owner_authority(tmp_path, monkeypatch):
    monkeypatch.setattr('swe_workbench.core.Workbench', AdapterDouble)
    with TestClient(create_app(tmp_path)) as test:
        assert test.get('/api/batches', headers=AUTH).status_code == 401
        assert test.post('/api/import-sample', json={'operation_key': 'one'}, headers=POST).status_code == 401
    with pytest.raises(ValueError):
        create_app(tmp_path, owner_token='short')


def test_strict_bounded_json_and_no_actor_override(client):
    assert client.post('/api/import-sample', content='a=1', headers=AUTH | {'Origin': 'http://testserver', 'Content-Type': 'application/x-www-form-urlencoded'}).status_code == 415
    assert client.post('/api/import-sample', content='x' * (MAX_BODY + 1), headers=POST).status_code == 413
    assert client.post('/api/import-sample', content='{broken', headers=POST).status_code == 422
    for workers in [0, 3, True, '1']:
        assert client.post('/api/batches/one/process', json={'workers': workers}, headers=POST).status_code == 422
    payload = {'operation_key': 'review', 'expected_revision': 2, 'evidence_digest': 'evidence', 'rubric_digest': 'rubric', 'decision': 'rejected', 'reason': 'Semantic defect', 'criteria': {name: 'uncertain' for name in CRITERIA}}
    assert client.post('/api/submissions/one/review', json=payload | {'actor': 'forged'}, headers=POST).status_code == 422
    response = client.post('/api/submissions/one/review', json=payload, headers=POST)
    assert response.status_code == 200
    assert response.json()['review']['actor'] == 'operator'
    assert client.post('/api/submissions/one/review', json=payload | {'criteria': {}}, headers=POST).status_code == 422


def test_fixed_routes_errors_cache_csp_and_no_cors(client):
    response = client.get('/api/batches/missing', headers=AUTH)
    assert response.status_code == 404
    assert response.json() == {'error': {'code': 'not-found', 'message': 'Batch absent.'}}
    assert response.headers['cache-control'] == 'no-store'
    assert 'access-control-allow-origin' not in response.headers
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert 'set-cookie' not in response.headers
    for path in ['/state.sqlite3', '/fixtures/catalog.json', '/coordination/ui-status.json', '/api.py']:
        assert client.get(path).status_code == 404
    body = client.get('/api/batches/one/submissions', headers=AUTH).json()
    assert body[0]['title'] == '<script>window.pwned=1</script>'


def test_export_import_is_lazy_and_paths_not_returned(client, monkeypatch):
    calls = []
    def export(*args):
        calls.append(args)
        return {'export_id': 'export-one', 'path': '/private/path', 'location': '/private/path', 'manifest_digest': 'hash', 'metrics': {'accepted': 1}}
    monkeypatch.setitem(sys.modules, 'swe_workbench.exporter', SimpleNamespace(export_batch=export))
    response = client.post('/api/batches/one/export', headers=POST, json={'operation_key': 'freeze'})
    assert response.status_code == 200
    assert 'path' not in response.json() and 'location' not in response.json()
    assert len(calls) == 1


def test_real_core_process_exact_reviews_and_frozen_export(tmp_path):
    """One actual serial fixture run through the adapter; no simulated checks."""
    app = create_app(tmp_path / 'real-owner-api', owner_token=TOKEN)
    with TestClient(app) as test:
        batch = test.post('/api/import-sample', headers=POST, json={'operation_key': 'api-real-import'}).json()
        batch_id = batch['id']
        prefix = '/api/batches/' + batch_id
        processed = test.post(prefix + '/process', headers=POST, json={'workers': 1})
        assert processed.status_code == 200, processed.text
        items = test.get(prefix + '/submissions', headers=AUTH).json()
        good = next(item for item in items if item.get('fixture_label') == 'good')
        wrong = next(item for item in items if item.get('fixture_label') == 'weak-check-wrong')
        failing = next(item for item in items if item.get('fixture_label') == 'failing')
        missing = next(item for item in items if item.get('fixture_label') == 'missing-evidence')
        assert good['result']['overall'] == wrong['result']['overall'] == 'passed'
        assert good['result']['baseline']['overall'] == 'failed'
        assert good['result']['source_unchanged'] is True
        assert failing['result']['overall'] == 'failed'
        assert missing['result'] is None

        def payload(item, key, **changes):
            return {'expected_revision': item['revision'], 'evidence_digest': (item.get('result') or {}).get('evidence_digest', 'absent'), 'rubric_digest': item['rubric_digest'], 'decision': 'accepted', 'reason': 'Actual developer-run API integration: inspected first-seen order preservation and the exact machine evidence.', 'criteria': {name: 'pass' for name in CRITERIA}, 'operation_key': key} | changes

        good_url = '/api/submissions/' + good['id'] + '/review'
        for changes in [{'evidence_digest': 'obsolete'}, {'rubric_digest': 'changed'}, {'expected_revision': good['revision'] - 1}]:
            response = test.post(good_url, headers=POST, json=payload(good, 'invalid-' + next(iter(changes)), **changes))
            assert response.status_code == 409, response.text
        assert test.post('/api/submissions/' + failing['id'] + '/review', headers=POST, json=payload(failing, 'reject-failing-acceptance')).status_code == 422
        assert test.post('/api/submissions/' + missing['id'] + '/review', headers=POST, json=payload(missing, 'reject-missing-acceptance')).status_code == 409
        wrong_criteria = {name: 'pass' for name in CRITERIA} | {'requested_behavior': 'fail', 'evidence_adequacy': 'uncertain'}
        sent_back = test.post('/api/submissions/' + wrong['id'] + '/review', headers=POST, json=payload(wrong, 'semantic-sendback', decision='needs-work', reason='sorted(set(items)) changes first-seen order for ["b", "a", "b"]. Visible ascending-only checks pass; the ordering requirement fails.', criteria=wrong_criteria))
        assert sent_back.status_code == 200, sent_back.text
        assert sent_back.json()['disposition'] == 'needs-work'
        accepted = test.post(good_url, headers=POST, json=payload(good, 'accept-current'))
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()['review']['origin'] == 'developer_adjudication'
        assert accepted.json()['review']['actor'] == 'operator'
        replay = test.post(good_url, headers=POST, json=payload(good, 'accept-current'))
        assert replay.json() == accepted.json()
        assert test.post(good_url, headers=POST, json=payload(good, 'accept-current', reason='changed under same key')).status_code == 409
        assert test.post(good_url, headers=POST, json=payload(good, 'stale-concurrent')).status_code == 409
        frozen = test.post(prefix + '/export', headers=POST, json={'operation_key': 'freeze-real'})
        assert frozen.status_code == 200, frozen.text
        repeated = test.post(prefix + '/export', headers=POST, json={'operation_key': 'same-cut-new-key'})
        assert repeated.status_code == 200, repeated.text
        assert frozen.json()['manifest_digest'] == repeated.json()['manifest_digest']
        assert frozen.json()['metrics']['counts']['accepted'] == 1
        assert frozen.json()['metrics']['counts']['needs-work'] == 1
        assert 'path' not in frozen.json()
        assert app.state.workbench.verify()['ok'] is True
