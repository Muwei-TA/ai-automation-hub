from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_invariants", ROOT / "scripts/validate_release.py")
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)

def test_release_repo_invariants():
    assert validation.validate_repository(ROOT) == []
