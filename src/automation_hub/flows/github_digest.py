"""Digest of recently UPDATED GitHub projects matching a query (not Trending ranking)."""
from __future__ import annotations

import os
from urllib.parse import urlsplit
import httpx
from prefect import flow, get_run_logger
from automation_hub.services.llm import summarize
from automation_hub.services.notify import notify


@flow(name="github-digest", retries=2, retry_delay_seconds=20)
def github_digest(query: str = "topic:self-hosted automation", max_items: int = 10) -> dict:
    if not 1 <= max_items <= 20 or len(query) > 160:
        raise ValueError("Invalid GitHub search input")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ai-automation-hub/0.1"}
    if os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    api_base = (os.getenv("GITHUB_API_BASE_URL") or "https://api.github.com").rstrip("/")
    parsed = urlsplit(api_base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Invalid GITHUB_API_BASE_URL")
    with httpx.Client(timeout=20, headers=headers) as client:
        response = client.get(api_base + "/search/repositories", params={"q": query, "sort": "updated", "order": "desc", "per_page": max_items})
        response.raise_for_status()
        data = response.json()
    items = [{"name": x["full_name"], "url": x["html_url"], "description": x.get("description") or "", "updated_at": x["updated_at"], "stars": x["stargazers_count"]} for x in data["items"][:max_items]]
    raw = "\n".join(f"{i['name']} ({i['stars']} stars, updated {i['updated_at']}): {i['description'][:180]} {i['url']}" for i in items)
    digest = summarize(raw, "Summarize these GitHub repositories in Chinese. Keep links. Do not claim these are GitHub Trending entries.")
    notify("[GitHub project digest]\n" + digest)
    get_run_logger().info("GitHub digest fetched %d projects", len(items))
    return {"query": query, "items": items, "summary": digest}
