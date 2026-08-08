import re
from typing import Any


def normalize_register_number(val: Any) -> str:
    """
    Normalize register number string for reliable verification and matching:
    - Convert float/int representations (e.g. 24076.0 -> "24076") cleanly
    - Remove non-printable/hidden characters (\xa0, \u200b, \ufeff, non-breaking spaces)
    - Trim whitespace
    - Convert to uppercase
    """
    if val is None:
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    # Remove all whitespace, non-breaking spaces, and hidden unicode characters
    s = re.sub(r'[\s\xa0\u200b\ufeff]+', '', s)
    return s.upper()


def compare_register_numbers(reg1: Any, reg2: Any) -> bool:
    """
    Normalized comparison between two register numbers:
    Returns True if normalize_register_number(reg1) == normalize_register_number(reg2).
    """
    norm1 = normalize_register_number(reg1)
    norm2 = normalize_register_number(reg2)
    if not norm1 or not norm2:
        return False
    return norm1 == norm2
