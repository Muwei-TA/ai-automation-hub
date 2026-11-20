import json, logging
from pathlib import Path
from unittest.mock import patch
import httpx, pytest
from automation_hub.flows import nas_health as health, github_digest as github, gitea_status as gitea, comfyui_submit as comfy
from automation_hub.services import llm, notify as notification

ALL_ENV=["HEALTH_DISK_PATH","HEALTH_URLS","DOCKER_SOCKET","GITHUB_TOKEN","GITEA_BASE_URL","GITEA_TOKEN","COMFYUI_BASE_URL","COMFYUI_WORKFLOW_DIR","LLM_BASE_URL","LLM_MODEL","NOTIFY_WEBHOOK_URL"]

@pytest.fixture(autouse=True)
def clear_external_config(monkeypatch):
    for name in ALL_ENV: monkeypatch.delenv(name,raising=False)

def replace_http(monkeypatch, handler):
    original=httpx.Client
    def factory(*args, **kwargs):
        kwargs["transport"]=httpx.MockTransport(handler)
        return original(*args, **kwargs)
    monkeypatch.setattr(httpx,"Client",factory)

def test_health_snapshot_storage_and_http(monkeypatch,tmp_path):
    monkeypatch.setenv("HEALTH_DISK_PATH",str(tmp_path))
    monkeypatch.setenv("HEALTH_URLS","https://health.invalid/check,bad-url")
    replace_http(monkeypatch,lambda r:httpx.Response(503))
    result=health.snapshot()
    assert any(x["name"]=="disk" for x in result["checks"])
    assert any(x["status"]==503 for x in result["checks"] if x["name"]=="http")
    assert any("HTTP 503" in x for x in result["warnings"])
    assert any("Invalid configured health URL" in x for x in result["warnings"])

def test_health_empty_config(monkeypatch):
    result=health.snapshot()
    assert result=={"checks":[],"warnings":[]}

def test_github_flow_fetch_and_summary(monkeypatch):
    events=[]
    def handler(r):
        events.append((str(r.url),dict(r.headers)))
        return httpx.Response(200,json={"items":[{"full_name":"owner/repo","html_url":"https://github.com/owner/repo","description":"demo","updated_at":"2026-11-20T00:00:00Z","stargazers_count":99}]})
    replace_http(monkeypatch,handler)
    monkeypatch.setattr(github,"summarize",lambda s,i:"DIGEST")
    monkeypatch.setattr(github,"notify",lambda message:events.append(("notify",message)))
    monkeypatch.setattr(github,"get_run_logger",lambda:logging.getLogger("smoke"))
    result=github.github_digest.fn("topic:automation",2)
    assert result["items"][0]["stars"]==99
    assert result["summary"]=="DIGEST"
    assert events[0][0].startswith("https://api.github.com/search/repositories?")
    assert events[1]==("notify","[GitHub project digest]\nDIGEST")

def test_github_invalid_max_items():
    with pytest.raises(ValueError):github.github_digest.fn("topic:automation",99)

def test_gitea_failure_notify(monkeypatch):
    calls=[]
    monkeypatch.setenv("GITEA_BASE_URL","http://gitea.internal")
    replace_http(monkeypatch,lambda r:(calls.append(str(r.url)) or httpx.Response(200,json=[{"state":"failure","context":"unit-test","target_url":"http://ci/log"}])))
    monkeypatch.setattr(gitea,"summarize",lambda s,i:"CI failed")
    monkeypatch.setattr(gitea,"notify",lambda s:calls.append(s))
    monkeypatch.setattr(gitea,"get_run_logger",lambda:logging.getLogger("smoke"))
    result=gitea.gitea_status.fn("Muwei","project","abcdef0")
    assert result["failed"] is True
    assert "/api/v1/repos/Muwei/project/statuses/abcdef0" in calls[0]
    assert "CI failed" in calls[1]

def test_gitea_rejects_bad_sha(monkeypatch):
    with pytest.raises(ValueError):gitea.gitea_status.fn("o","r","INVALID")

def test_comfyui_workflow_template_and_queue(monkeypatch,tmp_path):
    monkeypatch.setenv("COMFYUI_BASE_URL","http://comfy.internal")
    monkeypatch.setenv("COMFYUI_WORKFLOW_DIR",str(tmp_path))
    (tmp_path/"demo.json").write_text(json.dumps({"node":{"inputs":{"text":"hello {{PROMPT}}","nested":["{{PROMPT}}"]}}}))
    calls=[]
    def handler(r):
        calls.append(json.loads(r.content))
        assert r.url.path=="/prompt"
        return httpx.Response(200,json={"prompt_id":"mock-comfy-id"})
    replace_http(monkeypatch,handler)
    res=comfy.comfyui_submit.fn("demo","prompt-smoke")
    assert res["status"]=="queued" and res["prompt_id"]=="mock-comfy-id"
    assert calls[0]["prompt"]["node"]["inputs"]["text"]=="hello prompt-smoke"
    assert calls[0]["prompt"]["node"]["inputs"]["nested"]==["prompt-smoke"]

def test_comfyui_rejects_unapproved_workflows(monkeypatch,tmp_path):
    monkeypatch.setenv("COMFYUI_BASE_URL","http://comfy.internal")
    monkeypatch.setenv("COMFYUI_WORKFLOW_DIR",str(tmp_path))
    with pytest.raises(FileNotFoundError):comfy.comfyui_submit.fn("not-approved","test")

def test_llm_fallback_and_invalid_url(monkeypatch):
    assert llm.summarize("deterministic","instruction")=="deterministic"
    monkeypatch.setenv("LLM_BASE_URL","file:///tmp/forbidden")
    monkeypatch.setenv("LLM_MODEL","demo")
    with pytest.raises(ValueError):llm.summarize("x","test")

def test_llm_mock_compatible_api(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL","https://llm.internal/v1")
    monkeypatch.setenv("LLM_MODEL","mock-model")
    def handler(r):
        payload=json.loads(r.content)
        assert payload["model"]=="mock-model"
        assert r.url.path=="/v1/chat/completions"
        return httpx.Response(200,json={"choices":[{"message":{"content":"摘要完成"}}]})
    replace_http(monkeypatch,handler)
    assert llm.summarize("sample","system")=="摘要完成"

def test_notification_opt_in(monkeypatch):
    assert notification.notify("no webhook")==False
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL","http://notification.internal/alert")
    calls=[]
    replace_http(monkeypatch,lambda r:(calls.append(json.loads(r.content)) or httpx.Response(200)))
    assert notification.notify("hello")==True
    assert calls==[{"text":"hello"}]


def test_health_disk_threshold_alert(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv("HEALTH_DISK_PATH", "/fake/volume")
    monkeypatch.setattr(health.os, "statvfs", lambda _: SimpleNamespace(f_blocks=100, f_frsize=10, f_bavail=5))
    result=health.snapshot()
    assert result["checks"][0]["used_percent"] == 95.0
    assert any("95.0%" in x for x in result["warnings"])


def test_health_docker_socket_status(monkeypatch):
    monkeypatch.setenv("DOCKER_SOCKET", "/tmp/not-a-real-docker-socket")
    def handler(r):
        assert r.url.path=="/containers/json"
        return httpx.Response(200,json=[{"Names":["/running"],"State":"running"},{"Names":["/paused"],"State":"paused"}])
    monkeypatch.setattr(health.httpx, "HTTPTransport", lambda **kwargs:httpx.MockTransport(handler))
    result=health.snapshot()
    assert len(result["checks"])==2
    assert len(result["warnings"])==1 and "paused" in result["warnings"][0]


def test_health_flow_alert_calls_notification(monkeypatch):
    monkeypatch.setattr(health,"snapshot",lambda:{"checks":[],"warnings":["disk full"]})
    monkeypatch.setattr(health,"summarize",lambda txt,instructions:"alert summary")
    sent=[]
    monkeypatch.setattr(health,"notify",sent.append)
    monkeypatch.setattr(health,"get_run_logger",lambda:logging.getLogger("smoke"))
    result=health.nas_health.fn()
    assert result["warnings"]==["disk full"]
    assert sent==["[NAS health alert]\nalert summary"]
