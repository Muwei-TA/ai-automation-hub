import json
import subprocess
import sys
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "preflight.py"
spec = importlib.util.spec_from_file_location("aihub_preflight", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

VALID_CONFIG = {
    "GATEWAY_API_KEY": "g" * 48,
    "N8N_ENCRYPTION_KEY": "n" * 48,
    "N8N_DB_PASSWORD": "p" * 24,
    "PREFECT_API_URL": "http://192.168.50.10:4200/api",
}


def test_valid_configuration():
    result = module.validate(VALID_CONFIG)
    assert result == {"errors": [], "warnings": []}


def test_example_is_not_deployable():
    config = module.load_env_file(ROOT / ".env.example")
    result = module.validate(config)
    assert any("GATEWAY_API_KEY" in error for error in result["errors"])
    assert any("N8N_DB_PASSWORD" in error for error in result["errors"])


def test_insecure_or_broken_configuration():
    config = {
        **VALID_CONFIG,
        "PREFECT_API_URL": "http://localhost:4200/api",
        "DOCKER_SOCKET": "/var/run/docker.sock",
        "LLM_MODEL": "configured-without-url",
        "COMFYUI_BASE_URL": "file:///etc/passwd",
        "N8N_EDITOR_BASE_URL": "https://n8n.example.org",
        "N8N_SECURE_COOKIE": "false",
    }
    result = module.validate(config)
    assert any("COMFYUI_BASE_URL" in error for error in result["errors"])
    assert len(result["warnings"]) >= 4
    assert not any("configured-without-url" in item for item in result["warnings"])


def test_cli_json_does_not_expose_secrets(tmp_path):
    config = tmp_path / "sample.env"
    config.write_text("\n".join(f"{key}={value}" for key,value in VALID_CONFIG.items()))
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--env-file", str(config), "--json"],
        capture_output=True, text=True, check=True
    )
    payload = json.loads(run.stdout)
    assert payload["errors"] == []
    assert VALID_CONFIG["GATEWAY_API_KEY"] not in run.stdout
    assert VALID_CONFIG["N8N_DB_PASSWORD"] not in run.stdout


def test_cli_fails_for_missing_file(tmp_path):
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--env-file", str(tmp_path / "missing.env")],
        capture_output=True, text=True
    )
    assert run.returncode == 1
