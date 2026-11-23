"""Ensure GitHub worker endpoints can be directed to disposable fixtures."""
import httpx
import pytest
from automation_hub.flows import github_digest as gh

def test_override_rejects_non_http_scheme(monkeypatch):
    monkeypatch.setenv("GITHUB_API_BASE_URL", "file:///etc/passwd")
    with pytest.raises(ValueError, match="Invalid GITHUB_API_BASE_URL"):
        gh.github_digest.fn("topic:automation", 1)

def test_override_hits_fixture_not_github(monkeypatch):
    monkeypatch.setenv("GITHUB_API_BASE_URL", "http://fixture.test")
    urls = []
    original = httpx.Client
    def replacement(*args, **kwargs):
        def handler(request):
            urls.append(str(request.url))
            return httpx.Response(200, json={"items": []})
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)
    monkeypatch.setattr(gh.httpx, "Client", replacement)
    monkeypatch.setattr(gh, "notify", lambda _: None)
    monkeypatch.setattr(gh, "get_run_logger", lambda: type("Logger", (), {"info": lambda *a: None})())
    result = gh.github_digest.fn("topic:automation", 1)
    assert result["items"] == []
    assert urls[0].startswith("http://fixture.test/search/repositories?")
