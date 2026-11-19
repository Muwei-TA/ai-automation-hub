"""Optional generic JSON webhook for alerts. Off unless explicitly configured."""
from __future__ import annotations

import os
import httpx


def notify(text: str) -> bool:
    url = os.getenv("NOTIFY_WEBHOOK_URL", "")
    if not url:
        return False
    if not url.startswith(("http://", "https://")):
        raise ValueError("NOTIFY_WEBHOOK_URL must be HTTP(S)")
    with httpx.Client(timeout=10) as client:
        res = client.post(url, json={"text": text[:3500]})
        res.raise_for_status()
    return True
