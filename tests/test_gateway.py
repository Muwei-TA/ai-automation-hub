import httpx
from fastapi.testclient import TestClient

from automation_hub.gateway import Settings, create_app

API_KEY = "valid-test-key"


def make_client(handler=None):
    transport = httpx.MockTransport(handler or (lambda request: httpx.Response(200, json={})))
    return TestClient(create_app(Settings(API_KEY, "http://prefect:4200/api"), transport=transport))


def test_healthz_needs_no_credentials():
    with make_client() as client:
        assert client.get("/healthz").json() == {"status": "ok"}


def test_missing_api_key_rejected_without_prefect_access():
    called = []
    def handler(request):
        called.append(request)
        return httpx.Response(200)
    with make_client(handler) as client:
        assert client.post("/v1/jobs/nas-health", json={}).status_code == 401
        assert client.post("/v1/jobs/nas-health", headers={"X-Automation-Key": "wrong"}, json={}).status_code == 401
    assert called == []


def test_only_allowlisted_jobs_and_params():
    with make_client() as client:
        auth = {"X-Automation-Key": API_KEY}
        assert client.post("/v1/jobs/arbitrary-shell", headers=auth, json={}).status_code == 404
        assert client.post("/v1/jobs/nas-health", headers=auth, json={"parameters": {"shell": "rm -rf /"}}).status_code == 422
        assert client.post("/v1/jobs/comfyui-submit", headers=auth, json={"parameters": {"workflow_name": "../../etc/passwd", "prompt_text": "test"}}).status_code == 422


def test_prefect_lookup_and_trigger():
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "GET":
            assert request.url.path == "/api/deployments/name/github-digest/nas-default"
            return httpx.Response(200, json={"id": "00000000-0000-0000-0000-000000000123"})
        assert request.url.path == "/api/deployments/00000000-0000-0000-0000-000000000123/create_flow_run"
        assert request.method == "POST"
        assert b'daily-2026-11-19' in request.content
        return httpx.Response(201, json={"id": "00000000-0000-0000-0000-000000000456"})
    with make_client(handler) as client:
        res = client.post("/v1/jobs/github-digest", headers={"X-Automation-Key": API_KEY}, json={"parameters": {"query": "topic:self-hosted", "max_items": 4}, "idempotency_key": "daily-2026-11-19"})
    assert res.status_code == 202
    assert res.json()["flow_run_id"] == "00000000-0000-0000-0000-000000000456"
    assert len(requests) == 2


def test_prefect_failure_is_sanitized():
    with make_client(lambda _: httpx.Response(404, text="upstream-private-error")) as client:
        res = client.post("/v1/jobs/nas-health", headers={"X-Automation-Key": API_KEY}, json={})
    assert res.status_code == 502
    assert "upstream-private-error" not in res.text


def test_misconfigured_gateway_rejected():
    with TestClient(create_app(Settings("", ""))) as client:
        assert client.post("/v1/jobs/nas-health", json={}).status_code == 503
