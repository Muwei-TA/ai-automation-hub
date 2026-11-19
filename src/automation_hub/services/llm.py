"""Opt-in OpenAI-compatible model. Never silently send data to a public provider."""
from __future__ import annotations

import os

import httpx


def summarize(text: str, system_instruction: str) -> str:
    base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    model = os.getenv("LLM_MODEL", "")
    if not base or not model:
        return text  # deterministic fallback
    if not (base.startswith("http://") or base.startswith("https://")):
        raise ValueError("LLM_BASE_URL must be HTTP(S)")
    headers = {}
    key = os.getenv("LLM_API_KEY", "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    with httpx.Client(timeout=40, headers=headers) as client:
        result = client.post(
            f"{base}/chat/completions",
            json={
                "model": model,
                "temperature": 0.2,
                "max_tokens": 700,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": text[:12000]},
                ],
            },
        )
        result.raise_for_status()
        return result.json()["choices"][0]["message"]["content"]
