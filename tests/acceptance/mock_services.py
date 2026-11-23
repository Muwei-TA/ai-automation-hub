"""No-network fixture for isolated Docker acceptance: never a real Gitea, GPU or LLM."""
from __future__ import annotations
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

EVENTS = []
LOCK = threading.Lock()

def record(kind, **fields):
    with LOCK:
        EVENTS.append({"type": kind, **fields})

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass
    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size < 0 or size > 262144:
            raise ValueError("invalid fixture payload length")
        return json.loads(self.rfile.read(size))
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/healthz":
            return self.send_json(200, {"status": "ok"})
        if path == "/__events":
            with LOCK:
                data = list(EVENTS)
            return self.send_json(200, {"events": data})
        if path.startswith("/api/v1/repos/") and "/statuses/" in path:
            record("gitea_status", path=path)
            return self.send_json(200, [{"state": "failure", "context": "ci/sandbox", "target_url": "http://fixture-api:8088/log"}])
        if path == "/search/repositories":
            record("github_search")
            return self.send_json(200, {"items": [{
                "full_name": "sandbox/fixture",
                "html_url": "https://github.invalid/sandbox/fixture",
                "description": "Simulated search result",
                "updated_at": "2026-11-01T00:00:00Z",
                "stargazers_count": 7
            }]})
        return self.send_json(404, {"error": "not found"})
    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            body = self.read_json()
        except (ValueError, UnicodeDecodeError):
            return self.send_json(400, {"error": "invalid fixture payload"})
        if path == "/prompt":
            if not isinstance(body, dict) or not isinstance(body.get("prompt"), dict):
                return self.send_json(422, {"error": "expected ComfyUI API graph"})
            record("comfyui_submit", graph=body["prompt"])
            return self.send_json(200, {"prompt_id": "fixture-prompt-0001", "number": 1, "node_errors": {}})
        if path == "/v1/chat/completions":
            record("llm_call", model=body.get("model") if isinstance(body, dict) else None)
            return self.send_json(200, {"choices": [{"message": {"content": "sandbox fixture summary"}}]})
        if path == "/notify":
            record("notification", text=body.get("text") if isinstance(body, dict) else "")
            return self.send_json(200, {"accepted": True})
        return self.send_json(404, {"error": "not found"})

if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8088), Handler).serve_forever()
