"""
Mistral Client Initialization
=============================

Core client factory for Mistral AI Python SDK v2.9.1.
"""

import os
from mistralai.client import Mistral
from app.core.config import settings


def get_mistral_client() -> Mistral:
    """
    Instantiate and return an authenticated Mistral API client.

    Reads API key from application settings or environment variable MISTRAL_API_KEY.
    Raises ValueError if key is not configured.
    """
    api_key = getattr(settings, "MISTRAL_API_KEY", None) or os.getenv("MISTRAL_API_KEY")

    if not api_key:
        raise ValueError(
            "MISTRAL_API_KEY is not configured. "
            "Please set MISTRAL_API_KEY in your .env file or environment variables."
        )

    return Mistral(api_key=api_key)
