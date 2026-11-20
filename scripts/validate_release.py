#!/usr/bin/env python3
"""Static release invariants; runtime acceptance remains a separate hard gate."""
from __future__ import annotations
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FLOWS = {
    "src/automation_hub/flows/nas_health.py:nas_health",
    "src/automation_hub/flows/github_digest.py:github_digest",
    "src/automation_hub/flows/gitea_status.py:gitea_status",
    "src/automation_hub/flows/comfyui_submit.py:comfyui_submit",
}

def validate_repository(root: Path = ROOT) -> list[str]:
    errors = []
    compose = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
    services = compose.get("services", {})
    for name in ("n8n-db", "n8n", "gateway", "worker"):
        if name not in services:
            errors.append(f"Missing Compose service: {name}")
    gateway = services.get("gateway", {})
    gateway_ports = gateway.get("ports", [])
    if not gateway_ports or not all(str(port).startswith("127.0.0.1:") for port in gateway_ports):
        errors.append("Gateway host ports must bind to loopback by default")
    if "GITEA_WEBHOOK_SECRET" not in gateway.get("environment", {}):
        errors.append("Gateway missing GITEA_WEBHOOK_SECRET setting")
    if not gateway.get("healthcheck"):
        errors.append("Gateway missing container healthcheck")
    if services.get("worker", {}).get("volumes"):
        errors.append("Worker volume mounts require review (expected no default volumes)")
    deployments = yaml.safe_load((root / "prefect.yaml").read_text(encoding="utf-8")).get("deployments", [])
    entrypoints = {d.get("entrypoint") for d in deployments}
    if entrypoints != EXPECTED_FLOWS or len(deployments) != 4:
        errors.append("Expected exactly four known Prefect deployments")
    for entry in entrypoints:
        if not isinstance(entry,str) or ":" not in entry or not (root / entry.split(":", 1)[0]).is_file():
            errors.append(f"Missing deployment source: {entry}")
    legacy = root / "n8n/workflows/gitea-status-webhook.json"
    if legacy.exists():
        errors.append("Unsigned legacy Gitea Webhook workflow must not be present")
    for file in (root / "n8n/workflows").glob("*.json"):
        data = json.loads(file.read_text(encoding="utf-8"))
        nodes = {node["name"] for node in data.get("nodes", [])}
        for source, targets in data.get("connections", {}).items():
            if source not in nodes:
                errors.append(f"{file.name}: missing source node {source}")
            for branch in targets.get("main", []):
                for target in branch:
                    if target["node"] not in nodes:
                        errors.append(f"{file.name}: missing target node {target['node']}")
    return errors

if __name__ == "__main__":
    failures = validate_repository()
    if failures:
        for item in failures:
            print("FAIL:", item)
        raise SystemExit(1)
    print("PASS: static repository release invariants")
