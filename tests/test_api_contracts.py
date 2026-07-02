from fastapi.testclient import TestClient
from app.main import app


def test_security_headers_on_health():
    client = TestClient(app)
    res = client.get('/api/v1/health')
    assert 'x-request-id' in res.headers
    assert res.headers.get('x-content-type-options') == 'nosniff'


def test_openapi_contains_workbench_routes():
    client = TestClient(app)
    schema = client.get('/openapi.json').json()
    assert '/api/v1/workbench/states' in schema['paths']
