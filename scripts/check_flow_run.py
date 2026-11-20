#!/usr/bin/env python3
"""Wait for a real Prefect run terminal state; HTTP 202 alone is insufficient."""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import httpx

TERMINAL = {"COMPLETED", "FAILED", "CRASHED", "CANCELLED"}

def inspect_run(api_url: str, flow_run_id: str, timeout: float, interval: float) -> tuple[str, str]:
    auth = None
    cred = os.getenv("PREFECT_API_AUTH_STRING", "")
    if cred:
        user, sep, password = cred.partition(":")
        if not sep:
            raise ValueError("Invalid Prefect auth settings")
        auth = (user, password)
    start = time.monotonic()
    with httpx.Client(timeout=8, auth=auth) as client:
        while True:
            response = client.get(api_url.rstrip("/") + "/flow_runs/" + flow_run_id)
            response.raise_for_status()
            data = response.json()
            state = data.get("state_type", "UNKNOWN")
            if state in TERMINAL:
                return str(state), str(data.get("state_name", state))
            if time.monotonic() - start >= timeout:
                return "TIMEOUT", str(data.get("state_name", state))
            time.sleep(interval)

def main() -> int:
    parser = argparse.ArgumentParser(description="Check final Prefect Flow Run state")
    parser.add_argument("flow_run_id", help="UUID from Gateway flow_run_id response")
    parser.add_argument("--api-url", default=os.getenv("PREFECT_API_URL", ""))
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--interval", type=float, default=3)
    args = parser.parse_args()
    if not args.api_url.startswith(("http://", "https://")) or not args.api_url.rstrip("/").endswith("/api"):
        print("ERROR: set valid PREFECT_API_URL ending /api", file=sys.stderr)
        return 2
    if args.timeout < 0 or args.interval <= 0:
        print("ERROR: invalid polling parameters", file=sys.stderr)
        return 2
    try:
        state, name = inspect_run(args.api_url, args.flow_run_id, args.timeout, args.interval)
    except (httpx.HTTPError, ValueError, KeyError) as error:
        print("ERROR: unable to verify Prefect Flow Run state: " + type(error).__name__, file=sys.stderr)
        return 2
    print(json.dumps({"flow_run_id": args.flow_run_id, "state": state, "name": name}))
    return 0 if state == "COMPLETED" else 1

if __name__ == "__main__":
    raise SystemExit(main())
