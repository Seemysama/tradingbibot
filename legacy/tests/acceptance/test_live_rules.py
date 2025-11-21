import os, pytest
from fastapi.testclient import TestClient
from api.server import app

pytestmark = pytest.mark.skip(reason="live rules opt-in")

def test_live_rules_fetch():
    os.environ['MARKETS_WARMUP'] = '1'
    client = TestClient(app)
    r = client.get('/healthz')
    assert r.status_code == 200
