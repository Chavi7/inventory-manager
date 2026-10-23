"""The session-secret guard: a misconfigured deploy must not start silently.

Runs `import app` in a subprocess, because the guard fires at import time and
calls sys.exit().
"""
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(REPO_ROOT, "app")
PLACEHOLDER = "dev-only-change-me"


def _import_app(**env_overrides):
    env = {k: v for k, v in os.environ.items()
           if k not in ("INVENTORY_SECRET_KEY", "INVENTORY_DB_PATH")}
    env["INVENTORY_DB_PATH"] = os.path.join(
        tempfile.mkdtemp(prefix="inventory-secret-test-"), "inventory.db")
    env["PYTHONPATH"] = APP_DIR
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=APP_DIR, env=env, capture_output=True, text=True, timeout=120,
    )


def test_absent_secret_still_boots_with_a_warning():
    result = _import_app(INVENTORY_SECRET_KEY=None)
    assert result.returncode == 0, result.stderr
    assert "WARNING" in result.stderr
    assert "INVENTORY_SECRET_KEY" in result.stderr


def test_blank_secret_refuses_to_start():
    result = _import_app(INVENTORY_SECRET_KEY="")
    assert result.returncode != 0
    assert "set but EMPTY" in result.stderr


def test_whitespace_only_secret_refuses_to_start():
    result = _import_app(INVENTORY_SECRET_KEY="   ")
    assert result.returncode != 0
    assert "set but EMPTY" in result.stderr


def test_placeholder_secret_refuses_to_start():
    result = _import_app(INVENTORY_SECRET_KEY=PLACEHOLDER)
    assert result.returncode != 0
    assert "development placeholder" in result.stderr


def test_short_secret_refuses_to_start():
    result = _import_app(INVENTORY_SECRET_KEY="too-short")
    assert result.returncode != 0
    assert "characters" in result.stderr


def test_valid_secret_boots_without_warning():
    result = _import_app(INVENTORY_SECRET_KEY="a" * 32)
    assert result.returncode == 0, result.stderr
    assert "WARNING" not in result.stderr
