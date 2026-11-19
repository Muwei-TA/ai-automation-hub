"""Read-only health checks for worker storage, optional trusted HTTP endpoints and containers."""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from prefect import flow, get_run_logger
from automation_hub.services.llm import summarize
from automation_hub.services.notify import notify


def snapshot() -> dict:
    checks = []
    warnings = []
    disk_path = os.getenv("HEALTH_DISK_PATH", "")
    if disk_path:
        stat = os.statvfs(Path(disk_path))
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        pct = round(100 * (1 - free / total), 1) if total else 0
        checks.append({"name": "disk", "path": disk_path, "used_percent": pct})
        if pct >= 90:
            warnings.append(f"Disk usage {pct}% at {disk_path}")
    urls = [x.strip() for x in os.getenv("HEALTH_URLS", "").split(",") if x.strip()]
    with httpx.Client(timeout=5) as client:
        for url in urls:
            # URL values are operator-owned environment variables, never supplied by webhook clients.
            if not url.startswith(("http://", "https://")):
                warnings.append(f"Invalid configured health URL: {url[:60]}")
                continue
            try:
                response = client.get(url)
                checks.append({"name": "http", "url": url, "status": response.status_code})
                if response.status_code >= 400:
                    warnings.append(f"HTTP {response.status_code}: {url}")
            except httpx.HTTPError:
                warnings.append(f"Health endpoint unavailable: {url}")
    socket_path = os.getenv("DOCKER_SOCKET", "")
    if socket_path:
        # Docker socket grants host-equivalent privileges; opt-in ONLY on trusted worker.
        with httpx.Client(transport=httpx.HTTPTransport(uds=socket_path), base_url="http://docker", timeout=5) as client:
            response = client.get("/containers/json", params={"all": 1})
            response.raise_for_status()
            for item in response.json():
                name = ",".join(item.get("Names", []))
                state = item.get("State", "unknown")
                checks.append({"name": "container", "container": name, "state": state})
                if state not in ("running", "exited"):
                    warnings.append(f"Docker container {name}: {state}")
    return {"checks": checks, "warnings": warnings}


@flow(name="nas-health", retries=1, retry_delay_seconds=15)
def nas_health() -> dict:
    logger = get_run_logger()
    result = snapshot()
    if result["warnings"]:
        summary = summarize("\n".join(result["warnings"]), "Summarize operator alerts briefly in Chinese. Do not invent facts or remediation steps.")
        notify("[NAS health alert]\n" + summary)
        logger.warning("NAS health warnings: %s", summary)
    else:
        logger.info("NAS health: %d checks OK", len(result["checks"]))
    return result
