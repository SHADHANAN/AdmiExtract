"""
Tests for Production / Render Configuration Precedence and Safety
=================================================================
Verifies:
1. MONGODB_URI from environment is preserved with 100% fidelity.
2. .env.example placeholder cannot override the environment variable.
3. On Render, missing MONGODB_URI fails fast with a fatal configuration error.
4. On Render, localhost / 127.0.0.1 MONGODB_URI fails fast with a fatal configuration error.
5. On Render, template placeholder MONGODB_URI fails fast with a fatal configuration error.
6. On Render, valid Atlas URI succeeds and local .env files are completely bypassed.
7. Localhost remains standard and usable for local development.
8. Template placeholders (<...>) safely fall back to localhost in local development.
9. DATABASE_NAME defaults to 'admiextract'.
"""

import os
import tempfile
from pathlib import Path
import pytest
from pydantic import ValidationError
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

        settings = Settings(_env_file=str(temp_env_file))
        assert settings.MONGODB_URI == atlas_uri


def test_render_without_mongodb_uri_fails_fast(monkeypatch):
    """Verify that on Render, missing MONGODB_URI raises a fatal configuration error."""
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("MONGODB_URI", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "Production/Render environment, but MONGODB_URI is missing" in str(exc_info.value)


def test_render_with_localhost_fails_fast(monkeypatch):
    """Verify that on Render, localhost or 127.0.0.1 MONGODB_URI raises a fatal configuration error."""
    monkeypatch.setenv("RENDER", "true")

    for localhost_uri in ["mongodb://localhost:27017", "mongodb://127.0.0.1:27017/admiextract"]:
        monkeypatch.setenv("MONGODB_URI", localhost_uri)
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        assert "pointing to localhost/127.0.0.1" in str(exc_info.value)


def test_render_with_placeholder_fails_fast(monkeypatch):
    """Verify that on Render, unconfigured placeholder raises a fatal configuration error."""
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("MONGODB_URI", "<MONGODB_ATLAS_CONNECTION_STRING>")

    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "a placeholder" in str(exc_info.value)


def test_render_with_valid_atlas_uri_succeeds_and_bypasses_env_file(monkeypatch):
    """Verify that on Render with valid Atlas URI, settings succeed and bypass local .env files."""
    valid_atlas = "mongodb+srv://valid_user:valid_pass@cluster.mongodb.net/admiextract"
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("MONGODB_URI", valid_atlas)

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_env_file = Path(tmpdir) / ".env"
        temp_env_file.write_text("MONGODB_URI=mongodb://spoofed-host:27017\nDATABASE_NAME=spoofed_db\n", encoding="utf-8")

        settings = Settings(_env_file=str(temp_env_file))
        assert settings.MONGODB_URI == valid_atlas
        assert settings.DATABASE_NAME == "admiextract"


def test_localhost_remains_usable_for_local_development(monkeypatch):
    """Verify that default localhost connection remains standard for local dev."""
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("IS_RENDER", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    settings = Settings(_env_file=None)
    assert settings.MONGODB_URI == "mongodb://localhost:27017"


def test_placeholder_safely_falls_back_to_localhost_in_dev(monkeypatch):
    """Verify that unconfigured template placeholders (<...>) fall back to localhost in dev."""
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("IS_RENDER", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    settings = Settings(MONGODB_URI="<MONGODB_ATLAS_CONNECTION_STRING>", _env_file=None)
    assert settings.MONGODB_URI == "mongodb://localhost:27017"


def test_database_name_defaults_to_admiextract():
    """Verify that DATABASE_NAME defaults to 'admiextract'."""
    settings = Settings(_env_file=None)
    assert settings.DATABASE_NAME == "admiextract"

