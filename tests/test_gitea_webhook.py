"""Signed webhook ingress tests using an in-process mocked Prefect transport."""
import hashlib
import hmac
import json

import httpx
from fastapi.testclient import TestClient
from automation_hub.gateway import Settings, create_app

SECRET = "local-test-secret-only-0123456789abcdefgh"
KEY = "local-only-gateway-key"

def client_with_requests():
    calls = []
    def handler(req):
        calls.append(req)
        if req.method == "GET":
            return httpx.Response(200,json={"id":"fake-deployment"})
        return httpx.Response(201,json={"id":"fake-run"})
    transport = httpx.MockTransport(handler)
    app = create_app(Settings(KEY,"http://prefect.invalid/api",gitea_webhook_secret=SECRET), transport=transport)
    return TestClient(app), calls

def signed_headers(data: bytes, event: str = "push"):
    return {"Content-Type":"application/json","X-Gitea-Event":event,"X-Gitea-Signature":hmac.new(SECRET.encode(),data,hashlib.sha256).hexdigest()}

def payload(sha="abcdef0123456789"):
    return json.dumps({"repository":{"owner":{"login":"owner"},"name":"project"},"after":sha}).encode()

def test_signed_push_dispatch_and_stable_key():
    client,calls=client_with_requests()
    data=payload()
    with client:
        response=client.post("/v1/webhooks/gitea",content=data,headers=signed_headers(data))
    assert response.status_code==202, response.text
    assert response.json()["flow_run_id"]=="fake-run"
    assert len(calls)==2
    assert calls[0].url.path=="/api/deployments/name/gitea-status/nas-default"
    body=json.loads(calls[1].content)
    assert body["parameters"]=={"owner":"owner","repo":"project","sha":"abcdef0123456789"}
    assert len(body["idempotency_key"])==70 and body["idempotency_key"].startswith("gitea-")

def test_signature_required_before_dispatch():
    client,calls=client_with_requests()
    data=payload()
    with client:
        assert client.post("/v1/webhooks/gitea",content=data,headers={"Content-Type":"application/json"}).status_code==401
        headers=signed_headers(data)
        headers["X-Gitea-Signature"]="0"*64
        assert client.post("/v1/webhooks/gitea",content=data,headers=headers).status_code==401
        tampered=payload("abcdef1234567890")
        assert client.post("/v1/webhooks/gitea",content=tampered,headers=signed_headers(data)).status_code==401
    assert calls==[]

def test_missing_webhook_secret_is_fail_closed():
    app=create_app(Settings(KEY,"http://prefect.invalid/api"))
    with TestClient(app) as client:
        assert client.post("/v1/webhooks/gitea",content=payload(),headers=signed_headers(payload())).status_code==503

def test_signed_invalid_and_unsupported_events():
    client,calls=client_with_requests()
    with client:
        data=payload()
        response=client.post("/v1/webhooks/gitea",content=data,headers=signed_headers(data,"issues"))
        assert response.status_code==202 and response.json()["status"]=="ignored"
        bad=json.dumps({"repository":{"owner":{"login":"evil!"},"name":"project"},"after":"abcdef0123456789"}).encode()
        assert client.post("/v1/webhooks/gitea",content=bad,headers=signed_headers(bad)).status_code==422
        deleted=payload("0"*40)
        assert client.post("/v1/webhooks/gitea",content=deleted,headers=signed_headers(deleted)).json()["status"]=="ignored"
    assert calls==[]

def test_signed_payload_size_limit():
    client,calls=client_with_requests()
    body=b"x"*262145
    with client:
        assert client.post("/v1/webhooks/gitea",content=body,headers=signed_headers(body)).status_code==413
    assert calls==[]

def test_wrong_media_type_rejected():
    client,calls=client_with_requests()
    with client:
        assert client.post("/v1/webhooks/gitea",content=b"{}",headers={"Content-Type":"text/plain"}).status_code==415
    assert calls==[]


def test_readiness_healthy_prefect():
    calls=[]
    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200,json={"status":"ok"})
    with TestClient(create_app(Settings(KEY,"http://prefect.invalid/api"),transport=httpx.MockTransport(handler))) as c:
        assert c.get("/healthz").status_code==200
        res=c.get("/readyz")
        assert res.status_code==200 and res.json()=={"status":"ready"}
    assert calls==["http://prefect.invalid/api/health"]

def test_readiness_downstream_failures():
    with TestClient(create_app(Settings(KEY,"http://prefect.invalid/api"),transport=httpx.MockTransport(lambda r:httpx.Response(503)))) as c:
        assert c.get("/readyz").status_code==503
        assert c.get("/healthz").status_code==200

def test_readiness_bad_configuration():
    with TestClient(create_app(Settings("",""))) as c:
        assert c.get("/readyz").status_code==503
    with TestClient(create_app(Settings(KEY,"http://prefect.invalid/api","broken-basic-auth"))) as c:
        assert c.get("/readyz").status_code==503

def test_readiness_transport_error():
    def handler(r):
        raise httpx.ConnectError("simulated offline")
    with TestClient(create_app(Settings(KEY,"http://prefect.invalid/api"),transport=httpx.MockTransport(handler))) as c:
        res=c.get("/readyz")
        assert res.status_code==503
        assert res.json()["detail"]=="Prefect API not ready"
