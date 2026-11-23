#!/usr/bin/env python3
"""Create and destroy a complete isolated Docker acceptance environment.

Real Gateway, Prefect Server and Process Worker. Gitea/ComfyUI/LLM/GitHub
are intentionally simulated, with no account credentials or GPU usage.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.ci.yaml",
           "-f", "compose.acceptance.yaml", "--profile", "worker"]
GATEWAY = "http://127.0.0.1:8099"
FIXTURE = "http://127.0.0.1:18088"
API = "http://prefect-ci:4200/api"
REPORT = {"passed": [], "failed": [], "run_ids": {},
          "environment": "ephemeral GitHub Actions Docker; simulated external APIs"}
SECRET = os.environ["GITEA_WEBHOOK_SECRET"]
GATEWAY_KEY = os.environ["GATEWAY_API_KEY"]


def run(*args: str, timeout: int = 180, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run([*COMPOSE, *args], cwd=ROOT, text=True, timeout=timeout,
                          check=True, capture_output=capture)


def http(url: str, *, payload: bytes | None = None, headers: dict | None = None):
    req = Request(url, data=payload, headers=headers or {},
                  method="POST" if payload is not None else "GET")
    try:
        with urlopen(req, timeout=8) as resp:
            status, data = resp.status, resp.read()
    except HTTPError as exc:
        status, data = exc.code, exc.read()
    try:
        return status, json.loads(data) if data else {}
    except ValueError:
        return status, {"raw": data.decode(errors="replace")[:300]}


def check(name: str, condition: bool, detail: str = ""):
    if not condition:
        REPORT["failed"].append({"name": name, "detail": detail[:1600]})
        raise AssertionError(name + ": " + detail)
    REPORT["passed"].append(name)
    print("PASS", name, flush=True)


def submit(name: str, params: dict, key: str) -> str:
    payload = json.dumps({"parameters": params, "idempotency_key": key}).encode()
    code, body = http(f"{GATEWAY}/v1/jobs/{name}", payload=payload,
                      headers={"X-Automation-Key": GATEWAY_KEY, "Content-Type": "application/json"})
    check(name + ": Gateway accepted", code == 202 and bool(body.get("flow_run_id")),
          str((code, body)))
    REPORT["run_ids"][name] = body["flow_run_id"]
    return body["flow_run_id"]


def flow_state(flow_id: str, timeout: int = 100):
    p = subprocess.run([*COMPOSE, "run", "--rm", "--no-deps", "worker", "python",
                        "scripts/check_flow_run.py", flow_id,
                        "--api-url", API, "--timeout", str(timeout), "--interval", "2"],
                       cwd=ROOT, text=True, capture_output=True, timeout=timeout + 35)
    lines = [line.strip() for line in p.stdout.splitlines() if line.strip()]
    state = {}
    for line in reversed(lines):
        try:
            state = json.loads(line)
            break
        except ValueError:
            continue
    return p.returncode, state, (p.stdout + p.stderr)[-1500:]


def assert_completed(name: str, flow_id: str) -> None:
    code, state, logs = flow_state(flow_id)
    check(name + ": real Flow Run Completed", code == 0 and state.get("state") == "COMPLETED",
          logs)


def signed_push(sha: str):
    data = json.dumps({"repository": {"owner": {"login": "sandbox"}, "name": "demo"},
                       "after": sha}, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "X-Gitea-Event": "push",
               "X-Gitea-Signature": hmac.new(SECRET.encode(), data, hashlib.sha256).hexdigest()}
    return data, headers


def wait_ready(url: str, label: str, timeout: int = 100) -> None:
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            code, _ = http(url)
            if code == 200:
                return
        except (URLError, OSError, TimeoutError):
            pass
        time.sleep(2)
    raise TimeoutError(label + " not ready")


def acceptance() -> None:
    run("config", "--quiet")
    check("Compose config structurally valid", True)
    run("build", "gateway", "worker", "prefect-ci", "fixture-api", timeout=600)
    check("Four acceptance images actually built", True)
    run("up", "-d", "--wait", "prefect-ci", "fixture-api", timeout=240)
    run("run", "--rm", "--no-deps", "worker", "prefect", "work-pool", "create",
        "nas-local", "--type", "process")
    run("run", "--rm", "--no-deps", "worker", "prefect", "deploy", "--all")
    check("Four real Prefect deployments registered", True)
    run("up", "-d", "worker", "gateway")
    wait_ready(GATEWAY + "/readyz", "Gateway Prefect readiness")
    wait_ready(FIXTURE + "/healthz", "Fixture API")
    check("Real Gateway and Prefect readiness", True)

    empty = json.dumps({"parameters": {}}).encode()
    code, _ = http(GATEWAY + "/v1/jobs/nas-health", payload=empty,
                   headers={"Content-Type": "application/json"})
    check("Missing API key refused", code == 401, str(code))
    code, _ = http(GATEWAY + "/v1/jobs/not-allowlisted", payload=empty,
                   headers={"Content-Type": "application/json", "X-Automation-Key": GATEWAY_KEY})
    check("Nonallowlisted task refused", code == 404, str(code))
    invalid = json.dumps({"parameters": {"max_items": 100}}).encode()
    code, _ = http(GATEWAY + "/v1/jobs/github-digest", payload=invalid,
                   headers={"Content-Type": "application/json", "X-Automation-Key": GATEWAY_KEY})
    check("Invalid task arguments refused", code == 422, str(code))

    data, headers = signed_push("a" * 40)
    code, _ = http(GATEWAY + "/v1/webhooks/gitea", payload=data,
                   headers={**headers, "X-Gitea-Signature": "0" * 64})
    check("Forged Gitea HMAC refused", code == 401, str(code))
    code, _ = http(GATEWAY + "/v1/webhooks/gitea", payload=data,
                   headers={**headers, "Content-Type": "text/plain"})
    check("Incorrect Webhook content type refused", code == 415, str(code))
    code, ignored = http(GATEWAY + "/v1/webhooks/gitea", payload=data,
                         headers={**headers, "X-Gitea-Event": "issues"})
    check("Signed irrelevant Webhook ignored", code == 202 and ignored.get("status") == "ignored",
          str((code, ignored)))

    run_id = submit("nas-health", {}, "acceptance-nas-health")
    assert_completed("nas-health", run_id)

    code, reply = http(GATEWAY + "/v1/webhooks/gitea", payload=data, headers=headers)
    check("Signed Gitea Push accepted", code == 202 and bool(reply.get("flow_run_id")),
          str((code, reply)))
    gitea_id = reply["flow_run_id"]
    REPORT["run_ids"]["gitea-status"] = gitea_id
    code, repeated = http(GATEWAY + "/v1/webhooks/gitea", payload=data, headers=headers)
    check("Duplicate Gitea push reuses run ID", code == 202 and repeated.get("flow_run_id") == gitea_id,
          str((code, repeated)))
    assert_completed("gitea-status", gitea_id)

    run_id = submit("comfyui-submit", {"workflow_name": "ci_fixture",
                                        "prompt_text": "SANDBOX_ONLY_TEST_PROMPT"},
                    "acceptance-comfyui-001")
    assert_completed("comfyui-submit", run_id)

    run_id = submit("github-digest", {"query": "topic:automation", "max_items": 1},
                    "acceptance-github-001")
    assert_completed("github-digest", run_id)

    run_id = submit("comfyui-submit", {"workflow_name": "unknown_fixture",
                                        "prompt_text": "invalid-graph"},
                    "acceptance-invalid-comfyui")
    exit_code, state, logs = flow_state(run_id, timeout=85)
    check("Unknown ComfyUI graph results in FAILED state",
          exit_code != 0 and state.get("state") == "FAILED", logs)

    status, body = http(FIXTURE + "/__events")
    events = body.get("events", [])
    kinds = [e["type"] for e in events]
    check("Fixture received Gitea statuses", status == 200 and "gitea_status" in kinds, str(kinds))
    check("Fixture received GitHub API query", "github_search" in kinds, str(kinds))
    check("Fixture received simulated LLM calls", kinds.count("llm_call") >= 2, str(kinds))
    check("Fixture received alert notifications", kinds.count("notification") >= 2, str(kinds))
    submissions = [e for e in events if e["type"] == "comfyui_submit"]
    prompt = submissions[0]["graph"]["1"]["inputs"]["text"] if submissions else ""
    check("ComfyUI allowlisted template substituted", prompt == "SANDBOX_ONLY_TEST_PROMPT", prompt)
    check("Exactly one simulated GPU submission", len(submissions) == 1, str(len(submissions)))
    REPORT["fixture_event_counts"] = {k: kinds.count(k) for k in sorted(set(kinds))}


def main() -> int:
    failed = False
    try:
        acceptance()
    except Exception as exc:
        failed = True
        REPORT["failed"].append({"name": type(exc).__name__, "detail": str(exc)[:1500]})
        traceback.print_exc()
        try:
            result = run("logs", "--no-color", "--tail", "60", "gateway",
                         "worker", "prefect-ci", "fixture-api", capture=True, timeout=30)
            print(result.stdout[-14000:], file=sys.stderr)
        except Exception as err:
            print("Diagnostics unavailable:", type(err).__name__, file=sys.stderr)
    finally:
        REPORT["outcome"] = "FAIL" if failed else "PASS"
        target = ROOT / "artifacts" / "sandbox-acceptance.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2) + "\n")
        print("Evidence:", target, REPORT["outcome"], flush=True)
        try:
            run("down", "--volumes", timeout=85)
        except Exception as err:
            print("Cleanup failed:", type(err).__name__, file=sys.stderr)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
