"""Read-only Gitea commit status check. Expects a Gitea commit-status webhook."""
from __future__ import annotations

import os
import re
from urllib.parse import quote

import httpx
from prefect import flow, get_run_logger
from automation_hub.services.llm import summarize
from automation_hub.services.notify import notify

NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,100}$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


@flow(name="gitea-status", retries=1, retry_delay_seconds=15)
def gitea_status(owner: str, repo: str, sha: str) -> dict:
    if not NAME_RE.fullmatch(owner) or not NAME_RE.fullmatch(repo) or not SHA_RE.fullmatch(sha):
        raise ValueError("Invalid owner/repo/sha")
    base = os.getenv("GITEA_BASE_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("GITEA_BASE_URL must be configured")
    headers = {}
    if os.getenv("GITEA_TOKEN"):
        headers["Authorization"] = "token " + os.environ["GITEA_TOKEN"]
    url = f"{base}/api/v1/repos/{quote(owner)}/{quote(repo)}/statuses/{sha}"
    with httpx.Client(timeout=15, headers=headers) as client:
        res = client.get(url)
        res.raise_for_status()
        statuses = res.json()
    # Some Gitea releases use a list of statuses; keep the state/context/target only.
    results = [{"state": x.get("state", "unknown"), "context": x.get("context", ""), "target_url": x.get("target_url", "")} for x in statuses]
    failing = [s for s in results if s["state"] in ("failure", "error")]
    if failing:
        raw = f"{owner}/{repo}@{sha}\n" + "\n".join(str(s) for s in failing)
        summary = summarize(raw, "Summarize these CI failures in Chinese; do not pretend to know log causes without logs.")
        notify("[Gitea CI failed]\n" + summary)
        get_run_logger().warning("Gitea checks failed for %s/%s", owner, repo)
    return {"repository": f"{owner}/{repo}", "sha": sha, "statuses": results, "failed": bool(failing)}
