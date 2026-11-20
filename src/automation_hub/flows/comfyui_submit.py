"""Queue an allowlisted ComfyUI API workflow. No arbitrary graph submitted via the gateway."""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
from prefect import flow


def inject_prompt(value: Any, prompt: str) -> Any:
    if isinstance(value, str):
        return value.replace("{{PROMPT}}", prompt)
    if isinstance(value, list):
        return [inject_prompt(x, prompt) for x in value]
    if isinstance(value, dict):
        return {k: inject_prompt(v, prompt) for k, v in value.items()}
    return value


@flow(name="comfyui-submit", retries=0)
def comfyui_submit(workflow_name: str, prompt_text: str) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", workflow_name):
        raise ValueError("Invalid workflow name")
    if not 1 <= len(prompt_text) <= 1000:
        raise ValueError("Invalid prompt length")
    base = os.getenv("COMFYUI_BASE_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("COMFYUI_BASE_URL must be configured")
    directory = Path(os.getenv("COMFYUI_WORKFLOW_DIR", "/app/workflows"))
    workflow_path = directory / f"{workflow_name}.json"
    if not workflow_path.is_file():
        raise FileNotFoundError(f"Unknown approved workflow: {workflow_name}")
    graph = inject_prompt(json.loads(workflow_path.read_text(encoding="utf-8")), prompt_text)
    with httpx.Client(timeout=30) as client:
        res = client.post(base + "/prompt", json={"prompt": graph, "client_id": str(uuid.uuid4())})
        res.raise_for_status()
        response = res.json()
    return {"workflow_name": workflow_name, "prompt_id": response["prompt_id"], "status": "queued"}
