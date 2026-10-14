"""
Logger Masking Utility
======================
Masks sensitive document identifiers and secrets in logging outputs:
- 12-digit Aadhaar numbers -> XXXX XXXX 1234
- Bank account numbers -> XXXXXXX1234
- API keys / bearer tokens
"""

import re
from typing import Any


def mask_aadhaar(text: str) -> str:
    """Mask 12-digit Aadhaar numbers to XXXX XXXX 1234 format."""
    if not text:
        return ""
    # Formatted 4-4-4
    text = re.sub(
        r"\b(\d{4})[\s-](\d{4})[\s-](\d{4})\b",
        r"XXXX XXXX \3",
        text,
    )
    # Continuous 12 digits
    text = re.sub(
        r"\b(\d{8})(\d{4})\b",
        r"XXXXXXXX\2",
        text,
    )
    return text


def mask_bank_account(text: str) -> str:
    """Mask 9 to 18-digit bank account numbers, keeping last 4 digits."""
    if not text:
        return ""
    return re.sub(
        r"\b(\d{5,14})(\d{4})\b",
        lambda m: "X" * len(m.group(1)) + m.group(2),
        text,
    )


def mask_sensitive_text(text: Any) -> str:
    """Mask sensitive PII and secrets in string for logging."""
    if text is None:
        return ""
    s = str(text)
    s = mask_aadhaar(s)
    # Mask API keys
    s = re.sub(r"(AIza[0-9A-Za-z-_]{35})", r"AIza...[MASKED_KEY]", s)
    s = re.sub(r"Bearer\s+[A-Za-z0-9\-_.]+", "Bearer [MASKED_TOKEN]", s)
    return s


def mask_sensitive_value(val: Any) -> str:
    """Mask arbitrary field values safely for logging."""
    if val is None:
        return "None"
    s = str(val).strip()
    if not s or s == "NOT_AVAILABLE":
        return s
    s_masked = mask_sensitive_text(s)
    s_masked = mask_bank_account(s_masked)
    if re.fullmatch(r"\d{10,18}", s_masked):
        return "X" * (len(s_masked) - 4) + s_masked[-4:]
    return s_masked
