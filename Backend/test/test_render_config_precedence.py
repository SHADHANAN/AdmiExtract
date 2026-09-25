"""
Tests for Production / Render Configuration Precedence and Safety
=================================================================
Verifies:
1. MONGODB_URI from environment is preserved with 100% fidelity.
2. .env.example placeholder cannot override the environment variable.
3. On Render, local .env is bypassed so OS environment variables are the sole source of truth.
4. Localhost remains usable and functional for local development.
5. Template placeholders (<...>) safely fall back to localhost without crashing.
"""

import os
import tempfile
from pathlib import Path
import pytest
from app.core.config import Settings


def test_mongodb_uri_from_environment_is_preserved(monkeypatch):
    """Verify that MONGODB_URI provided via OS environment is preserved exactly."""
    atlas_uri = "mongodb+srv://atlas_admin:secure_pass123@cluster0.mongodb.net/admiextract?retryWrites=true&w=majority"
    monkeypatch.setenv("MONGODB_URI", atlas_uri)
    monkeypatch.setenv("APP_ENV", "production")

    settings = Settings()
    assert settings.MONGODB_URI == atlas_uri


def test_env_example_placeholder_cannot_override_environment(monkeypatch):
    """Verify that .env.example placeholder cannot override MONGODB_URI from the environment."""
    atlas_uri = "mongodb+srv://prod_user:prod_pass@cluster0.mongodb.net/admiextract"
    monkeypatch.setenv("MONGODB_URI", atlas_uri)

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_env_file = Path(tmpdir) / ".env"
        temp_env_file.write_text("MONGODB_URI=<MONGODB_ATLAS_CONNECTION_STRING>\n", encoding="utf-8")

        # Even if pointing to a .env with the placeholder, environment variable must prevail
        settings = Settings(_env_file=str(temp_env_file))
        assert settings.MONGODB_URI == atlas_uri


def test_render_environment_bypasses_env_file(monkeypatch):
    """Verify that on Render (RENDER=true), local .env files are completely bypassed."""
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("MONGODB_URI", raising=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_env_file = Path(tmpdir) / ".env"
        temp_env_file.write_text("MONGODB_URI=mongodb://spoofed-host:27017\n", encoding="utf-8")

        # On Render, Settings must ignore .env and use built-in default
        settings = Settings(_env_file=str(temp_env_file))
        assert settings.MONGODB_URI == "mongodb://localhost:27017"


def test_localhost_remains_usable_for_local_development(monkeypatch):
    """Verify that default localhost connection remains standard for local dev."""
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("IS_RENDER", raising=False)

    settings = Settings(_env_file=None)
    assert settings.MONGODB_URI == "mongodb://localhost:27017"


def test_placeholder_safely_falls_back_to_localhost(monkeypatch):
    """Verify that unconfigured template placeholders (<...>) fall back to localhost safely."""
    monkeypatch.delenv("RENDER", raising=False)
    settings = Settings(MONGODB_URI="<MONGODB_ATLAS_CONNECTION_STRING>", _env_file=None)
    assert settings.MONGODB_URI == "mongodb://localhost:27017"
