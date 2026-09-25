"""
Application Configuration Module
=================================

Centralized configuration using Pydantic Settings.
Automatically loads environment variables from `.env`.
If `.env` is missing on a fresh installation, it is automatically
bootstrapped from `.env.example`.
"""

import logging
import re
import shutil
from pathlib import Path
import os
from typing import Any, Literal
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("app.core.config")

# Resolve project directories
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BACKEND_DIR / ".env"
ENV_EXAMPLE_FILE = BACKEND_DIR / ".env.example"

# ------------------------------------------------------------------------------
# Auto-bootstrap .env from .env.example if missing (Local development only)
# ------------------------------------------------------------------------------
# Under no circumstances should .env be auto-generated when running on Render,
# in production/staging, or when configuration is already supplied via environment.
is_render = bool(os.getenv("RENDER") or os.getenv("IS_RENDER"))
is_production = os.getenv("APP_ENV", "").lower() in ("production", "staging")
has_env_mongodb = bool(os.getenv("MONGODB_URI"))
is_ci = bool(os.getenv("CI"))

should_skip_bootstrap = is_render or is_production or has_env_mongodb or is_ci

if not ENV_FILE.exists():
    if not should_skip_bootstrap:
        if ENV_EXAMPLE_FILE.exists():
            try:
                shutil.copy(ENV_EXAMPLE_FILE, ENV_FILE)
                print(f"[CONFIG] Initialized '{ENV_FILE.name}' from '{ENV_EXAMPLE_FILE.name}'.")
            except Exception as e:
                print(f"[CONFIG WARNING] Could not auto-generate .env from .env.example: {e}")
        else:
            print("[CONFIG] Neither .env nor .env.example found; using built-in development defaults.")


class Settings(BaseSettings):
    """
    Application Settings
    ====================
    All configuration values are loaded from environment variables or local '.env'.
    Sensible defaults are provided for seamless zero-configuration startup.
    """

    # 1. Application Settings
    APP_NAME: str = "Automate API"
    APP_VERSION: str = "1.0.0"
    APP_ENV: Literal["development", "staging", "production", "testing"] = "development"

    # 2. Server Network Settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # 3. Database Settings (MongoDB)
    MONGODB_URI: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "admiextract"

    # 4. Security & Authentication Settings (JWT)
    SECRET_KEY: str = "dev-insecure-secret-key-change-in-production-admiextract-2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # 5. AI & OCR Service Settings (Gemini AI & Mistral AI)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.6-flash"
    MISTRAL_API_KEY: str = ""
    EXTRACTION_BYPASS_CACHE: bool = False

    # 6. Public App & CORS Settings
    PUBLIC_APP_URL: str = "http://localhost:5173"
    CORS_ORIGINS: str = ""

    # 7. Concurrent Worker Pool & Queue Settings
    EXTRACTION_WORKER_CONCURRENCY: int = 4
    GEMINI_CONCURRENCY_LIMIT: int = 3
    JOB_TIMEOUT_SECONDS: int = 300

    def __init__(self, **values: Any):
        # On Render / cloud production, explicitly bypass loading any local .env file.
        # OS environment variables are the sole source of truth in production.
        is_render_or_prod = bool(
            os.getenv("RENDER") or os.getenv("IS_RENDER") or os.getenv("APP_ENV") in ("production", "staging")
        )
        if is_render_or_prod:
            values["_env_file"] = None
            # If MONGODB_URI is not provided via environment or values in production/Render,
            # clear it to ensure the validator rejects missing cloud database configuration
            # instead of silently falling back to localhost.
            if "MONGODB_URI" not in values and not os.getenv("MONGODB_URI"):
                values["MONGODB_URI"] = ""
        super().__init__(**values)

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if (ENV_FILE.exists() and not (os.getenv("RENDER") or os.getenv("IS_RENDER"))) else None,
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("PORT")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"PORT must be between 1 and 65535, received: {v}")
        return v

    @field_validator("MONGODB_URI")
    @classmethod
    def validate_mongodb_uri(cls, v: str) -> str:
        v_clean = v.strip()
        is_render_or_prod = bool(
            os.getenv("RENDER") or os.getenv("IS_RENDER") or os.getenv("APP_ENV") in ("production", "staging")
        )

        # On Render / Production: MONGODB_URI MUST be a valid cloud/remote URI, NEVER localhost
        if is_render_or_prod:
            if not v_clean or v_clean.startswith("<") or "localhost" in v_clean.lower() or "127.0.0.1" in v_clean:
                raise ValueError(
                    "[FATAL CONFIG ERROR] Running in Production/Render environment, but MONGODB_URI is missing, "
                    "a placeholder, or pointing to localhost/127.0.0.1. "
                    "A valid remote MongoDB connection string (e.g. MongoDB Atlas 'mongodb+srv://...') "
                    "MUST be configured as the 'MONGODB_URI' environment variable in your Render dashboard."
                )

        # In Local development: allow unpopulated template placeholder fallback to localhost
        if v_clean.startswith("<") and v_clean.endswith(">"):
            logger.warning(
                "Placeholder '%s' detected for MONGODB_URI; falling back to default 'mongodb://localhost:27017'.",
                v_clean
            )
            return "mongodb://localhost:27017"

        if not (v_clean.startswith("mongodb://") or v_clean.startswith("mongodb+srv://")):
            raise ValueError(
                f"Invalid MONGODB_URI: '{v}'. Must start with 'mongodb://' or 'mongodb+srv://'."
            )
        return v_clean

    @field_validator("DATABASE_NAME")
    @classmethod
    def validate_database_name(cls, v: str) -> str:
        v_clean = v.strip()
        if not v_clean:
            raise ValueError("DATABASE_NAME cannot be empty.")
        # MongoDB database names cannot contain spaces, slashes, dots, null, or special chars
        forbidden_chars = r'[ /\\. "*<>:|?$]'
        if re.search(forbidden_chars, v_clean):
            raise ValueError(
                f"Invalid DATABASE_NAME: '{v}'. Database names cannot contain spaces, slashes, dots, or special characters [ /\\. \"*<>:|?$]."
            )
        return v_clean

    @field_validator("ACCESS_TOKEN_EXPIRE_MINUTES")
    @classmethod
    def validate_access_token_expire(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"ACCESS_TOKEN_EXPIRE_MINUTES must be positive, received: {v}")
        return v


settings = Settings()