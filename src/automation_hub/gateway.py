"""Authenticated, allowlisted n8n -> Prefect dispatch API.

The gateway is intentionally NOT a generic proxy to Prefect or an arbitrary shell executor.
"""
from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    api_key: str
    prefect_api_url: str
    prefect_auth_string: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.getenv("GATEWAY_API_KEY", ""),
            prefect_api_url=os.getenv("PREFECT_API_URL", ""),
            prefect_auth_string=os.getenv("PREFECT_API_AUTH_STRING", ""),
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

    return app


app = create_app()
