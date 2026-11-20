import importlib.util
import httpx

from pathlib import Path

PATH=Path(__file__).resolve().parents[1]/"scripts/check_flow_run.py"
spec=importlib.util.spec_from_file_location("prefect_run_check", PATH)
check=importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

def test_flow_run_terminal_categories():
    assert check.TERMINAL == {"COMPLETED", "FAILED", "CRASHED", "CANCELLED"}

def test_flow_run_verifier_mocked(monkeypatch):
    original=httpx.Client
    def fake_client(*args, **kwargs):
        kwargs["transport"]=httpx.MockTransport(lambda r:httpx.Response(200,json={"state_type":"COMPLETED","state_name":"Completed"}))
        return original(*args, **kwargs)
    monkeypatch.setattr(check.httpx,"Client",fake_client)
    monkeypatch.delenv("PREFECT_API_AUTH_STRING",raising=False)
    assert check.inspect_run("http://prefect.invalid/api","run-1",timeout=1,interval=0.01)==("COMPLETED","Completed")

def test_flow_run_verifier_failure_state(monkeypatch):
    original=httpx.Client
    def fake_client(*args, **kwargs):
        kwargs["transport"]=httpx.MockTransport(lambda r:httpx.Response(200,json={"state_type":"CRASHED","state_name":"Crashed"}))
        return original(*args, **kwargs)
    monkeypatch.setattr(check.httpx,"Client",fake_client)
    monkeypatch.delenv("PREFECT_API_AUTH_STRING",raising=False)
    assert check.inspect_run("http://prefect.invalid/api","run-1",timeout=1,interval=0.01)[0]=="CRASHED"
