"""Actual private-server regression; original check retained separately from product."""
from fastapi.testclient import TestClient
from swe_workbench.api import create_app

def test_private_module_graph(tmp_path):
    client=TestClient(create_app(tmp_path/'state',owner_token='a'*40))
    assert client.get('/').status_code==200
    app=client.get('/app.js');assert app.status_code==200
    assert "from './handoff-verify.js'" in app.text
    verifier=client.get('/handoff-verify.js')
    assert verifier.status_code==200, 'The imported handoff verifier must be served by the private API'
    assert 'javascript' in verifier.headers['content-type']
    assert client.get('/workbench.sqlite3').status_code==404
    assert client.get('/not-an-authored-asset.js').status_code==404
    assert client.get('/api/batches').status_code==401
