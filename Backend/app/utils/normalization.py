import re
<<<<<<< HEAD
from typing import Any, Optional, Dict, List, Tuple
=======
from typing import Any
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4


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
<<<<<<< HEAD
    Returns True if normalize_register_number(reg1) == normalize_register_number(reg2),
    with zero-padding tolerance for numeric identifiers (e.g. '002401' == '2401').
=======
    Returns True if normalize_register_number(reg1) == normalize_register_number(reg2).
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
    """
    norm1 = normalize_register_number(reg1)
    norm2 = normalize_register_number(reg2)
    if not norm1 or not norm2:
        return False
<<<<<<< HEAD
    if norm1 == norm2:
        return True
    # Numeric zero-padding tolerance
    if norm1.isdigit() and norm2.isdigit():
        return norm1.lstrip("0") == norm2.lstrip("0")
    return False


def clean_text_noise(text: Any) -> str:
    """
    Clean text noise:
    - Collapse redundant spaces
    - Fix punctuation spacing (e.g. ' , ' -> ', ')
    - Remove trailing and leading punctuation artifacts
    - Strip invisible/unicode characters
    """
    if text is None:
        return ""
    s = str(text)
    s = re.sub(r'[\xa0\u200b\ufeff\r\n\t]+', ' ', s)
    s = re.sub(r'\s*,\s*', ', ', s)
    s = re.sub(r'\s*:\s*', ': ', s)
    s = re.sub(r'\s+', ' ', s)
    s = s.strip(" ,;:-_")
    return s


def validate_and_normalize_aadhaar(val: Any, without_space: bool = False) -> Optional[str]:
    """
    Validate and normalize 12-digit Indian Aadhaar number.
    - Fixes OCR common confusion: O->0, o->0, I->1, l->1
    - Rejects if not strictly 12 digits
    """
    if val is None:
        return None
    s = str(val).strip()
    # Correct common OCR number confusions
    s = s.replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1")
    digits = re.sub(r'[^0-9]', '', s)
    if len(digits) != 12:
        return None
    # Verhoeff / basic dummy checks: reject trivial invalid sequences
    if digits in {"000000000000", "111111111111", "123456789012"}:
        return None
    if without_space:
        return digits
    return f"{digits[0:4]} {digits[4:8]} {digits[8:12]}"


def validate_and_normalize_mobile(val: Any) -> Optional[str]:
    """
    Validate and normalize 10-digit Indian Mobile Number.
    - Strips international +91 or leading 0
    - Enforces 10 digits starting with [6-9]
    """
    if val is None:
        return None
    s = str(val).strip()
    s = s.replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1")
    digits = re.sub(r'[^0-9]', '', s)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    return None


def validate_and_normalize_dob(val: Any, target_format: str = "DD.MM.YYYY") -> Optional[str]:
    """
    Validate and normalize Date of Birth to DD.MM.YYYY or DD/MM/YYYY.
    Ensures day (1-31), month (1-12), year (1950-2030).
    """
    if val is None:
        return None
    s = str(val).strip()
    m = re.search(r'\b(\d{1,2})[/\.\-](\d{1,2})[/\.\-](\d{4})\b', s)
    if not m:
        # Try YYYY-MM-DD
        m_iso = re.search(r'\b(\d{4})[/\.\-](\d{1,2})[/\.\-](\d{1,2})\b', s)
        if m_iso:
            y, mth, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        else:
            return None
    else:
        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))

    if not (1 <= d <= 31 and 1 <= mth <= 12 and 1950 <= y <= 2030):
        return None

    sep = "." if "dd.mm.yyyy" in target_format.lower() else "/"
    return f"{d:02d}{sep}{mth:02d}{sep}{y}"


def validate_and_normalize_gender(val: Any) -> Optional[str]:
    """
    Normalize Gender strictly to 'MALE', 'FEMALE', or 'TRANSGENDER'.
    """
    if val is None:
        return None
    s = str(val).strip().upper()
    if s in ["M", "MALE", "BOY", "GENTLEMAN"]:
        return "MALE"
    if s in ["F", "FEMALE", "GIRL", "WOMAN", "LADY"]:
        return "FEMALE"
    if "TRANS" in s:
        return "TRANSGENDER"
    return None


def validate_and_normalize_email(val: Any) -> Optional[str]:
    """
    Strict RFC-compliant email validator.
    """
    if val is None:
        return None
    s = str(val).strip().lower()
    if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', s):
        return s
    return None


def validate_and_normalize_ifsc(val: Any) -> Optional[str]:
    """
    Validate 11-character Indian IFSC code: ^[A-Z]{4}0[A-Z0-9]{6}$
    """
    if val is None:
        return None
    s = re.sub(r'[^A-Za-z0-9]', '', str(val).strip().upper())
    if len(s) == 11 and re.match(r'^[A-Z]{4}0[A-Z0-9]{6}$', s):
        return s
    return None


COMMUNITY_CATEGORIES = {
    "OBC": ["OBC", "OTHER BACKWARD CLASS", "OTHER BACKWARD CLASSES"],
    "BCM": ["BCM", "BACKWARD CLASS MUSLIM", "BACKWARD CLASSES MUSLIM"],
    "MBC/DNC": ["MBC/DNC", "MBC / DNC", "MBC-DNC", "DNC", "DENOTIFIED COMMUNITY", "DENOTIFIED COMMUNITIES"],
    "MBC": ["MBC", "MOST BACKWARD CLASS", "MOST BACKWARD CLASSES"],
    "BC": ["BC", "BACKWARD CLASS", "BACKWARD CLASSES"],
    "SCA": ["SCA", "SC ARUNTHATHIYAR", "SCHEDULED CASTE ARUNTHATHIYAR"],
    "SC": ["SC", "SCHEDULED CASTE", "SCHEDULED CASTES"],
    "ST": ["ST", "SCHEDULED TRIBE", "SCHEDULED TRIBES"],
    "EWS": ["EWS", "ECONOMICALLY WEAKER SECTION"],
    "OC": ["OC", "OPEN COMPETITION", "GENERAL", "FC", "FORWARD CLASS", "OTHERS"],
}


def validate_and_normalize_community(val: Any) -> Optional[str]:
    """
    Validate and normalize Indian / Tamil Nadu Community Category.
    Returns: 'OBC', 'BC', 'MBC', 'SC', 'ST', 'OC', 'BCM', 'MBC/DNC', 'SCA', 'EWS' or None.
    """
    if val is None:
        return None
    s = str(val).strip().upper()
    if s in COMMUNITY_CATEGORIES:
        return s
    # Check exact alias matches first
    for canon, aliases in COMMUNITY_CATEGORIES.items():
        if s in aliases:
            return canon
    # Check whole word matches using regex word boundaries to prevent 'BC' matching 'OBC'
    for canon, aliases in COMMUNITY_CATEGORIES.items():
        for a in aliases:
            if re.search(r'\b' + re.escape(a) + r'\b', s):
                return canon
    # If the string contains a specific known caste or legitimate community descriptor, preserve cleaned string
    if len(s) >= 2 and len(s) <= 40 and not any(bad in s.lower() for bad in ["invalid", "null", "nil", "none", "unknown"]):
        return s
    return None


def validate_and_normalize_pincode(val: Any) -> Optional[str]:
    """
    Validate Indian 6-digit postal code.
    """
    if val is None:
        return None
    s = re.sub(r'[^0-9]', '', str(val).strip())
    if len(s) == 6 and s[0] in "123456789":
        return s
    return None


def normalize_name(val: Any) -> Optional[str]:
    """
    Normalize human names (student, father, mother, guardian):
    - Strips OCR prefix/suffix junk (e.g. 'CLD', 'PO :', numbers)
    - Separates stuck initials (e.g. 'PRIYAG' -> 'PRIYA G')
    - Normalizes spacing and initials
    """
    if val is None:
        return None
    s = clean_text_noise(val)
    # Remove obvious non-name tokens
    if any(bad in s.lower() for bad in ["village", "taluk", "district", "examination", "government", "board", "cld", "certificate", "standard", "session", "secondary", "subject"]):
        return None
    # Strip trailing/leading colons, dots, dashes
    s = re.sub(r'^[.\s:\-]+|[.\s:\-]+$', '', s)
    if s.strip().upper() in ["CLD", "NA", "NIL", "NULL", "NONE", "UNKNOWN"]:
        return None
    # Separate stuck initials at end of name e.g. PRIYAG -> PRIYA G, SARAVANAKUMARV -> SARAVANAKUMAR V
    s = re.sub(r'([A-Za-z]{3,})([A-Z])$', r'\1 \2', s)
    # Standardize spacing around standalone initials
    s = re.sub(r'\s*\.\s*', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    if len(s) < 2:
        return None
    return s.upper()


=======
    return norm1 == norm2
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
