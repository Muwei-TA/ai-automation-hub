"""Authenticated, allowlisted n8n -> Prefect dispatch API.

The gateway is intentionally NOT a generic proxy to Prefect or an arbitrary shell executor.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    api_key: str
    prefect_api_url: str
    prefect_auth_string: str = ""
    gitea_webhook_secret: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.getenv("GATEWAY_API_KEY", ""),
            prefect_api_url=os.getenv("PREFECT_API_URL", ""),
            prefect_auth_string=os.getenv("PREFECT_API_AUTH_STRING", ""),
            gitea_webhook_secret=os.getenv("GITEA_WEBHOOK_SECRET", ""),
        )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NasHealth(StrictModel):
    # The targets are fixed by worker environment variables, not by the caller.
    pass


class GithubDigest(StrictModel):
    query: str = Field(default="topic:self-hosted automation", min_length=3, max_length=160)
    max_items: int = Field(default=10, ge=1, le=20)


class GiteaStatus(StrictModel):
    owner: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,100}$")
    repo: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,100}$")
    sha: str = Field(pattern=r"^[0-9a-fA-F]{7,64}$")


class ComfyUISubmit(StrictModel):
    workflow_name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    prompt_text: str = Field(min_length=1, max_length=1000)


# job name -> (Prefect flow name, deployment name, parameter schema)
JOB_REGISTRY: dict[str, tuple[str, str, type[StrictModel]]] = {
    "nas-health": ("nas-health", "nas-default", NasHealth),
    "github-digest": ("github-digest", "nas-default", GithubDigest),
    "gitea-status": ("gitea-status", "nas-default", GiteaStatus),
    "comfyui-submit": ("comfyui-submit", "nas-default", ComfyUISubmit),
}


class DispatchRequest(StrictModel):
    parameters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    app = FastAPI(title="AI Automation Hub gateway", version="0.1.0", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        """Readiness checks config and Prefect API; healthz remains liveness."""
        if not config.api_key or not config.prefect_api_url or not config.prefect_api_url.rstrip("/").endswith("/api"):
            raise HTTPException(status_code=503, detail="Gateway not ready")
        auth = None
        if config.prefect_auth_string:
            user, separator, password = config.prefect_auth_string.partition(":")
            if not separator:
                raise HTTPException(status_code=503, detail="Gateway not ready")
            auth = httpx.BasicAuth(user, password)
        try:
            async with httpx.AsyncClient(timeout=5, transport=transport, auth=auth) as client:
                result = await client.get(config.prefect_api_url.rstrip("/") + "/health")
                result.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="Prefect API not ready") from None
        return {"status": "ready"}

    async def submit_to_prefect(job_name: str, request: DispatchRequest) -> dict[str, str]:
        if not config.api_key or not config.prefect_api_url:
            raise HTTPException(status_code=503, detail="Gateway not configured")
        if job_name not in JOB_REGISTRY:
            raise HTTPException(status_code=404, detail="Unknown job")
        flow_name, deployment_name, schema = JOB_REGISTRY[job_name]
        try:
            params = schema.model_validate(request.parameters).model_dump()
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="Invalid job parameters") from exc
        url = config.prefect_api_url.rstrip("/")
        if not url.endswith("/api"):
            raise HTTPException(status_code=503, detail="PREFECT_API_URL must end in /api")
        auth = None
        if config.prefect_auth_string:
            user, sep, password = config.prefect_auth_string.partition(":")
            if not sep:
                raise HTTPException(status_code=503, detail="Invalid Prefect auth settings")
            auth = httpx.BasicAuth(user, password)
        path = f"/deployments/name/{quote(flow_name, safe='')}/{quote(deployment_name, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=15, auth=auth, transport=transport) as client:
                deployment_resp = await client.get(url + path)
                deployment_resp.raise_for_status()
                deployment_id = deployment_resp.json()["id"]
                body: dict[str, Any] = {"parameters": params}
                if request.idempotency_key:
                    body["idempotency_key"] = request.idempotency_key
                run_resp = await client.post(url + f"/deployments/{deployment_id}/create_flow_run", json=body)
                run_resp.raise_for_status()
                run_id = run_resp.json()["id"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            LOG.warning("Prefect dispatch failed for job %s: %s", job_name, type(exc).__name__)
            raise HTTPException(status_code=502, detail="Prefect API unavailable or deployment not registered") from exc
        return {"job": job_name, "flow_run_id": str(run_id), "status": "submitted"}

    @app.post("/v1/jobs/{job_name}", status_code=202)
    async def dispatch(
        job_name: str,
        request: DispatchRequest,
        x_automation_key: str | None = Header(default=None, alias="X-Automation-Key"),
    ) -> dict[str, str]:
        if not config.api_key or not config.prefect_api_url:
            raise HTTPException(status_code=503, detail="Gateway not configured")
        if not x_automation_key or not hmac.compare_digest(x_automation_key, config.api_key):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return await submit_to_prefect(job_name, request)

    @app.post("/v1/webhooks/gitea", status_code=202)
    async def gitea_webhook(request: Request) -> dict[str, str]:
        """Gitea signed-push ingress, with bounded raw-body HMAC validation."""
        secret = config.gitea_webhook_secret
        if not secret or len(secret) < 32 or not config.api_key or not config.prefect_api_url:
            raise HTTPException(status_code=503, detail="Gitea webhook not configured")
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise HTTPException(status_code=415, detail="Expected application/json")
        if request.headers.get("content-length", "").isdigit() and int(request.headers["content-length"]) > 262144:
            raise HTTPException(status_code=413, detail="Payload too large")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 262144:
                raise HTTPException(status_code=413, detail="Payload too large")
        expected = hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()
        signature = request.headers.get("X-Gitea-Signature", "")
        if not signature or not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        if request.headers.get("X-Gitea-Event", "") != "push":
            return {"status": "ignored", "job": "gitea-status"}
        try:
            payload = json.loads(data)
            repository = payload["repository"]
            owner = repository["owner"]["login"]
            repo = repository["name"]
            sha = payload["after"]
            if sha == "0" * 40 or sha == "0" * 64:
                return {"status": "ignored", "job": "gitea-status"}
            params = GiteaStatus.model_validate({"owner": owner, "repo": repo, "sha": sha}).model_dump()
        except (ValueError, KeyError, TypeError, ValidationError):
            raise HTTPException(status_code=422, detail="Invalid Gitea push payload") from None
        key = "gitea-" + hashlib.sha256(f"{owner}/{repo}:{sha}".encode()).hexdigest()
        return await submit_to_prefect("gitea-status", DispatchRequest(parameters=params, idempotency_key=key))

    return app


app = create_app()
