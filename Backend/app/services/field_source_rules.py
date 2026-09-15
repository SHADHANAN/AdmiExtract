"""
Field-to-Document Source Rules & Authority Service
===================================================
Centralized, deterministic configuration and evaluation service enforcing
strict field-to-document source authority mapping.

Business Rules:
- Fields such as DOB, Aadhaar Number, EMIS ID, Community, Caste, Income,
  and Academic Marks must be extracted ONLY from their designated authoritative source.
- If a candidate's source document does not match a strict rule, it is deterministically
  REJECTED with decision=REJECT and reason=SOURCE_MISMATCH before final merge.
- Candidates rejected as SOURCE_MISMATCH can never reach final merge or Excel.
- Safe logging is enforced: NO PII (names, Aadhaar, DOB, phone, address) is ever logged.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("app.services.field_source_rules")


# =========================================================================
# 1. Document Type Normalization
# =========================================================================

DOCUMENT_TYPE_ALIASES: Dict[str, str] = {
    # Aadhaar
    "AADHAAR": "AADHAAR",
    "AADHAR": "AADHAAR",
    "AADHAAR_CARD": "AADHAAR",
    "AADHAAR CARD": "AADHAAR",
    "AADHAR_CARD": "AADHAAR",
    "AADHAR CARD": "AADHAAR",
    "UID": "AADHAAR",
    "UIDAI": "AADHAAR",

    # Transfer Certificate
    "TRANSFER_CERTIFICATE": "TRANSFER_CERTIFICATE",
    "TRANSFER CERTIFICATE": "TRANSFER_CERTIFICATE",
    "TRANSFER": "TRANSFER_CERTIFICATE",
    "TC": "TRANSFER_CERTIFICATE",
    "TC_CERTIFICATE": "TRANSFER_CERTIFICATE",

    # Community Certificate
    "COMMUNITY": "COMMUNITY",
    "COMMUNITY_CERTIFICATE": "COMMUNITY",
    "COMMUNITY CERTIFICATE": "COMMUNITY",
    "CASTE": "COMMUNITY",
    "CASTE_CERTIFICATE": "COMMUNITY",
    "CASTE CERTIFICATE": "COMMUNITY",

    # Income Certificate
    "INCOME": "INCOME",
    "INCOME_CERTIFICATE": "INCOME",
    "INCOME CERTIFICATE": "INCOME",

    # SSLC / 10th
    "SSLC": "SSLC",
    "10TH": "SSLC",
    "10TH_MARKSHEET": "SSLC",
    "10TH MARKSHEET": "SSLC",
    "10TH MARK SHEET": "SSLC",
    "10TH_MARK_SHEET": "SSLC",
    "SECONDARY": "SSLC",
    "SECONDARY_SCHOOL": "SSLC",

    # HSC / 12th
    "HSC": "HSC",
    "12TH": "HSC",
    "12TH_MARKSHEET": "HSC",
    "12TH MARKSHEET": "HSC",
    "12TH MARK SHEET": "HSC",
    "12TH_MARK_SHEET": "HSC",
    "HIGHER_SECONDARY": "HSC",
    "HIGHER SECONDARY": "HSC",
    "PLUS_TWO": "HSC",
    "+2": "HSC",

    # Nativity / Residence
    "NATIVITY": "NATIVITY",
    "NATIVITY_CERTIFICATE": "NATIVITY",
    "NATIVITY CERTIFICATE": "NATIVITY",
    "RESIDENCE": "NATIVITY",
    "RESIDENCE_CERTIFICATE": "NATIVITY",

    # Bonafide
    "BONAFIDE": "BONAFIDE",
    "BONAFIDE_CERTIFICATE": "BONAFIDE",

    # Migration
    "MIGRATION": "MIGRATION",
    "MIGRATION_CERTIFICATE": "MIGRATION",

    # Allotment Order
    "ALLOTMENT_ORDER": "ALLOTMENT_ORDER",
    "ALLOTMENT ORDER": "ALLOTMENT_ORDER",
    "PROVISIONAL_ALLOTMENT": "ALLOTMENT_ORDER",
    "PROVISIONAL ALLOTMENT": "ALLOTMENT_ORDER",
    "TNEA": "ALLOTMENT_ORDER",

    # General
    "STUDENT_DOCUMENT": "STUDENT_DOCUMENT",
    "UNKNOWN": "UNKNOWN",
}


def normalize_document_type(doc_type: Any) -> str:
    """
    Deterministically normalize any document classification string, alias,
    or format variant into standard canonical document type key.
    """
    if not doc_type:
        return "UNKNOWN"
    clean = str(doc_type).strip().upper().replace("-", "_")
    if clean in DOCUMENT_TYPE_ALIASES:
        return DOCUMENT_TYPE_ALIASES[clean]

    # Keyword heuristic matching for complex or raw strings
    clean_spaced = clean.replace("_", " ")
    if any(k in clean_spaced for k in ["ALLOTMENT", "PROVISIONAL", "TNEA"]):
        return "ALLOTMENT_ORDER"
    if any(k in clean_spaced for k in ["TRANSFER", "TC"]):
        return "TRANSFER_CERTIFICATE"
    if any(k in clean_spaced for k in ["10TH", "SSLC", "SECONDARY"]):
        return "SSLC"
    if any(k in clean_spaced for k in ["12TH", "HSC", "HIGHER SECONDARY", "PLUS TWO"]):
        return "HSC"
    if any(k in clean_spaced for k in ["COMMUNITY", "CASTE"]):
        return "COMMUNITY"
    if any(k in clean_spaced for k in ["INCOME"]):
        return "INCOME"
    if any(k in clean_spaced for k in ["AADHAAR", "AADHAR", "UID"]):
        return "AADHAAR"
    if any(k in clean_spaced for k in ["NATIVITY", "RESIDENCE"]):
        return "NATIVITY"
    if any(k in clean_spaced for k in ["BONAFIDE"]):
        return "BONAFIDE"
    if any(k in clean_spaced for k in ["MIGRATION"]):
        return "MIGRATION"

    return clean.replace(" ", "_")


# =========================================================================
# 2. Centralized Field Source Rules Configuration
# =========================================================================

FIELD_SOURCE_RULES: Dict[str, Dict[str, Any]] = {
    # ---------------------------------------------------------------------
    # Student Name: SSLC > HSC > TC > Aadhaar > Allotment > Community
    # ---------------------------------------------------------------------
    "student_name": {
        "sources": [
            {"document_type": "SSLC", "priority": 100},
            {"document_type": "HSC", "priority": 95},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "AADHAAR", "priority": 85},
            {"document_type": "ALLOTMENT_ORDER", "priority": 80},
            {"document_type": "COMMUNITY", "priority": 75},
        ],
        "strict": False,
    },
    "student name": {
        "sources": [
            {"document_type": "SSLC", "priority": 100},
            {"document_type": "HSC", "priority": 95},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "AADHAAR", "priority": 85},
            {"document_type": "ALLOTMENT_ORDER", "priority": 80},
            {"document_type": "COMMUNITY", "priority": 75},
        ],
        "strict": False,
    },
    "name": {
        "sources": [
            {"document_type": "SSLC", "priority": 100},
            {"document_type": "HSC", "priority": 95},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "AADHAAR", "priority": 85},
            {"document_type": "ALLOTMENT_ORDER", "priority": 80},
            {"document_type": "COMMUNITY", "priority": 75},
        ],
        "strict": False,
    },
    "name of student": {
        "sources": [
            {"document_type": "SSLC", "priority": 100},
            {"document_type": "HSC", "priority": 95},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "AADHAAR", "priority": 85},
            {"document_type": "ALLOTMENT_ORDER", "priority": 80},
            {"document_type": "COMMUNITY", "priority": 75},
        ],
        "strict": False,
    },
    "candidate name": {
        "sources": [
            {"document_type": "SSLC", "priority": 100},
            {"document_type": "HSC", "priority": 95},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "AADHAAR", "priority": 85},
            {"document_type": "ALLOTMENT_ORDER", "priority": 80},
            {"document_type": "COMMUNITY", "priority": 75},
        ],
        "strict": False,
    },
    "applicant name": {
        "sources": [
            {"document_type": "SSLC", "priority": 100},
            {"document_type": "HSC", "priority": 95},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "AADHAAR", "priority": 85},
            {"document_type": "ALLOTMENT_ORDER", "priority": 80},
            {"document_type": "COMMUNITY", "priority": 75},
        ],
        "strict": False,
    },

    # ---------------------------------------------------------------------
    # Aadhaar Number: STRICT to Aadhaar Card (UIDAI)
    # ---------------------------------------------------------------------
    "aadhaar_number": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar number": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar number (without space)": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar number without space": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar card": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar card number": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar no": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar no.": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhar": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhar number": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhar card": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },

    # ---------------------------------------------------------------------
    # Date of Birth: STRICT to Aadhaar > TC > SSLC > HSC
    # ---------------------------------------------------------------------
    "dob": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 70},
        ],
        "strict": True,
    },
    "student date of birth(dd.mm.yyyy)": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 70},
        ],
        "strict": True,
    },
    "date of birth": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 70},
        ],
        "strict": True,
    },
    "student date of birth": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 70},
        ],
        "strict": True,
    },
    "birth date": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 70},
        ],
        "strict": True,
    },

    # ---------------------------------------------------------------------
    # Aadhaar Number: STRICT to Aadhaar ONLY
    # ---------------------------------------------------------------------
    "aadhaar_number": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar number": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar number (without space)": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar card": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar card number": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar no": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },
    "aadhaar id": {
        "sources": [{"document_type": "AADHAAR", "priority": 100}],
        "strict": True,
    },

    # ---------------------------------------------------------------------
    # EMIS ID: STRICT to Transfer Certificate (TC) > SSLC > HSC
    # ---------------------------------------------------------------------
    "emis_id": {
        "sources": [
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 100},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 70},
        ],
        "strict": True,
    },
    "emis id": {
        "sources": [
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 100},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 70},
        ],
        "strict": True,
    },
    "emis": {
        "sources": [
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 100},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 70},
        ],
        "strict": True,
    },
    "emis number": {
        "sources": [
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 100},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 70},
        ],
        "strict": True,
    },
    "is emis id available": {
        "sources": [
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 100},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 70},
        ],
        "strict": True,
    },

    # ---------------------------------------------------------------------
    # Community: Community Certificate > TC > SSLC > Allotment Order
    # ---------------------------------------------------------------------
    "community": {
        "sources": [
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "SSLC", "priority": 70},
            {"document_type": "ALLOTMENT_ORDER", "priority": 60},
        ],
        "strict": True,
    },
    "community category": {
        "sources": [
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "SSLC", "priority": 70},
            {"document_type": "ALLOTMENT_ORDER", "priority": 60},
        ],
        "strict": True,
    },
    "community certificate": {
        "sources": [
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "SSLC", "priority": 70},
        ],
        "strict": True,
    },
    "community code": {
        "sources": [
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "SSLC", "priority": 70},
        ],
        "strict": True,
    },
    "caste category": {
        "sources": [
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "SSLC", "priority": 70},
        ],
        "strict": True,
    },

    # ---------------------------------------------------------------------
    # Caste / Sub-Caste: STRICT to Community Certificate > TC > SSLC
    # ---------------------------------------------------------------------
    "caste": {
        "sources": [
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "SSLC", "priority": 70},
        ],
        "strict": True,
    },
    "caste name": {
        "sources": [
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "SSLC", "priority": 70},
        ],
        "strict": True,
    },
    "community name": {
        "sources": [
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "SSLC", "priority": 70},
        ],
        "strict": True,
    },
    "sub caste": {
        "sources": [
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "SSLC", "priority": 70},
        ],
        "strict": True,
    },
    "sub_caste": {
        "sources": [
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "SSLC", "priority": 70},
        ],
        "strict": True,
    },

    # ---------------------------------------------------------------------
    # Income: STRICT to Income Certificate ONLY
    # ---------------------------------------------------------------------
    "income": {
        "sources": [{"document_type": "INCOME", "priority": 100}],
        "strict": True,
    },
    "annual family income": {
        "sources": [{"document_type": "INCOME", "priority": 100}],
        "strict": True,
    },
    "family income": {
        "sources": [{"document_type": "INCOME", "priority": 100}],
        "strict": True,
    },
    "annual income": {
        "sources": [{"document_type": "INCOME", "priority": 100}],
        "strict": True,
    },

    # ---------------------------------------------------------------------
    # 10th / SSLC Marks: STRICT to SSLC Marksheet ONLY
    # ---------------------------------------------------------------------
    "tenth_marks": {
        "sources": [{"document_type": "SSLC", "priority": 100}],
        "strict": True,
    },
    "sslc marks": {
        "sources": [{"document_type": "SSLC", "priority": 100}],
        "strict": True,
    },
    "sslc mark percentage": {
        "sources": [{"document_type": "SSLC", "priority": 100}],
        "strict": True,
    },
    "sslc total marks": {
        "sources": [{"document_type": "SSLC", "priority": 100}],
        "strict": True,
    },
    "10th mark": {
        "sources": [{"document_type": "SSLC", "priority": 100}],
        "strict": True,
    },
    "10th percentage": {
        "sources": [{"document_type": "SSLC", "priority": 100}],
        "strict": True,
    },
    "10th total": {
        "sources": [{"document_type": "SSLC", "priority": 100}],
        "strict": True,
    },
    "sslc register number": {
        "sources": [{"document_type": "SSLC", "priority": 100}],
        "strict": True,
    },
    "sslc year of passing": {
        "sources": [{"document_type": "SSLC", "priority": 100}],
        "strict": True,
    },

    # ---------------------------------------------------------------------
    # 12th / HSC Marks: STRICT to HSC Marksheet ONLY
    # ---------------------------------------------------------------------
    "twelfth_marks": {
        "sources": [{"document_type": "HSC", "priority": 100}],
        "strict": True,
    },
    "hsc marks": {
        "sources": [{"document_type": "HSC", "priority": 100}],
        "strict": True,
    },
    "hsc mark percentage": {
        "sources": [{"document_type": "HSC", "priority": 100}],
        "strict": True,
    },
    "hsc total marks": {
        "sources": [{"document_type": "HSC", "priority": 100}],
        "strict": True,
    },
    "12th mark": {
        "sources": [{"document_type": "HSC", "priority": 100}],
        "strict": True,
    },
    "12th percentage": {
        "sources": [{"document_type": "HSC", "priority": 100}],
        "strict": True,
    },
    "12th total": {
        "sources": [{"document_type": "HSC", "priority": 100}],
        "strict": True,
    },
    "hsc register number": {
        "sources": [{"document_type": "HSC", "priority": 100}],
        "strict": True,
    },
    "hsc cutoff": {
        "sources": [{"document_type": "HSC", "priority": 100}],
        "strict": True,
    },

    # ---------------------------------------------------------------------
    # Transfer Certificate Specific: STRICT to Transfer Certificate (TC)
    # ---------------------------------------------------------------------
    "transfer certificate number": {
        "sources": [{"document_type": "TRANSFER_CERTIFICATE", "priority": 100}],
        "strict": True,
    },
    "tc number": {
        "sources": [{"document_type": "TRANSFER_CERTIFICATE", "priority": 100}],
        "strict": True,
    },
    "tc no": {
        "sources": [{"document_type": "TRANSFER_CERTIFICATE", "priority": 100}],
        "strict": True,
    },
    "admission number": {
        "sources": [{"document_type": "TRANSFER_CERTIFICATE", "priority": 100}],
        "strict": True,
    },
    "school name": {
        "sources": [{"document_type": "TRANSFER_CERTIFICATE", "priority": 100}],
        "strict": True,
    },
    "leaving date": {
        "sources": [{"document_type": "TRANSFER_CERTIFICATE", "priority": 100}],
        "strict": True,
    },
    "date of leaving": {
        "sources": [{"document_type": "TRANSFER_CERTIFICATE", "priority": 100}],
        "strict": True,
    },
    "tc issue date": {
        "sources": [{"document_type": "TRANSFER_CERTIFICATE", "priority": 100}],
        "strict": True,
    },

    # ---------------------------------------------------------------------
    # Address & Location: Multi-source with prioritized fallback (strict: False)
    # ---------------------------------------------------------------------
    "permanent address": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },
    "address": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },
    "full address": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },
    "communication address": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },

    # ---------------------------------------------------------------------
    # Personal & Family (Non-strict with prioritized sources)
    # ---------------------------------------------------------------------
    "gender": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 80},
            {"document_type": "COMMUNITY", "priority": 70},
        ],
        "strict": False,
    },
    "sex": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 80},
            {"document_type": "COMMUNITY", "priority": 70},
        ],
        "strict": False,
    },
    "nationality": {
        "sources": [
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 100},
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 100},
            {"document_type": "COMMUNITY", "priority": 70},
        ],
        "strict": False,
    },
    "religion": {
        "sources": [
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "NATIVITY", "priority": 70},
        ],
        "strict": False,
    },
    "father's name": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 80},
            {"document_type": "INCOME", "priority": 70},
        ],
        "strict": False,
    },
    "father name": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 80},
            {"document_type": "INCOME", "priority": 70},
        ],
        "strict": False,
    },
    "mother's name": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 80},
            {"document_type": "INCOME", "priority": 70},
        ],
        "strict": False,
    },
    "mother name": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "COMMUNITY", "priority": 100},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 90},
            {"document_type": "SSLC", "priority": 80},
            {"document_type": "HSC", "priority": 80},
            {"document_type": "INCOME", "priority": 70},
        ],
        "strict": False,
    },
    "guardian name": {
        "sources": [
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 100},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "AADHAAR", "priority": 60},
        ],
        "strict": False,
    },
    "guardian's name": {
        "sources": [
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 100},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "AADHAAR", "priority": 60},
        ],
        "strict": False,
    },

    # ---------------------------------------------------------------------
    # Location Components (Aadhaar > Nativity > Community > Income > TC)
    # ---------------------------------------------------------------------
    "district": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 90},
            {"document_type": "INCOME", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },
    "district name": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 90},
            {"document_type": "INCOME", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },
    "taluk": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 90},
            {"document_type": "INCOME", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },
    "taluk name": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 90},
            {"document_type": "INCOME", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },
    "village": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 90},
            {"document_type": "INCOME", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },
    "village name": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 90},
            {"document_type": "INCOME", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },
    "village panchayat": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 80},
        ],
        "strict": False,
    },
    "village_panchayat": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 80},
        ],
        "strict": False,
    },
    "state": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },
    "state name": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },
    "pincode": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },
    "pin code": {
        "sources": [
            {"document_type": "AADHAAR", "priority": 100},
            {"document_type": "NATIVITY", "priority": 90},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 70},
        ],
        "strict": False,
    },

    # ---------------------------------------------------------------------
    # Occupation (Income > Community > TC > Aadhaar)
    # ---------------------------------------------------------------------
    "father's occupation": {
        "sources": [
            {"document_type": "INCOME", "priority": 100},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "AADHAAR", "priority": 70},
        ],
        "strict": False,
    },
    "father occupation": {
        "sources": [
            {"document_type": "INCOME", "priority": 100},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "AADHAAR", "priority": 70},
        ],
        "strict": False,
    },
    "mother's occupation": {
        "sources": [
            {"document_type": "INCOME", "priority": 100},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "AADHAAR", "priority": 70},
        ],
        "strict": False,
    },
    "mother occupation": {
        "sources": [
            {"document_type": "INCOME", "priority": 100},
            {"document_type": "COMMUNITY", "priority": 80},
            {"document_type": "TRANSFER_CERTIFICATE", "priority": 80},
            {"document_type": "AADHAAR", "priority": 70},
        ],
        "strict": False,
    },
}


# =========================================================================
# 3. Source Authority Evaluation Engine
# =========================================================================

class SourceAuthorityService:
    """
    Evaluates candidate field extractions against configured field source rules.
    Provides deterministic authorization decisions, authority priorities, and safe audit logging.
    """

    def __init__(self, rules: Optional[Dict[str, Dict[str, Any]]] = None):
        self.rules = rules if rules is not None else FIELD_SOURCE_RULES

    def get_rule_for_field(self, field_name: str) -> Optional[Dict[str, Any]]:
        """Find matching rule for field name or canonical alias."""
        if not field_name:
            return None
        fn_clean = field_name.strip().lower()

        # 1. Exact match
        if fn_clean in self.rules:
            return self.rules[fn_clean]

        # 2. Canonical mapping lookup
        from app.utils.field_canonicalizer import get_canonical_field_name
        canonical_name = get_canonical_field_name(field_name).strip().lower()
        if canonical_name in self.rules:
            return self.rules[canonical_name]

        # 3. Dynamic semantic match for common keywords
        if any(k in fn_clean for k in ["dob", "birth"]):
            return self.rules.get("dob")
        if any(k in fn_clean for k in ["aadhaar", "aadhar"]):
            return self.rules.get("aadhaar_number")
        if "emis" in fn_clean:
            return self.rules.get("emis_id")
        if any(k in fn_clean for k in ["caste", "community"]):
            return self.rules.get("community")
        if "income" in fn_clean:
            return self.rules.get("income")
        if any(k in fn_clean for k in ["sslc", "10th"]):
            return self.rules.get("tenth_marks")
        if any(k in fn_clean for k in ["hsc", "12th", "+2"]):
            return self.rules.get("twelfth_marks")
        if "address" in fn_clean and not any(comp in fn_clean for comp in ["email", "mail"]):
            return self.rules.get("permanent address")
        if "district" in fn_clean:
            return self.rules.get("district")
        if "taluk" in fn_clean:
            return self.rules.get("taluk")
        if "village" in fn_clean:
            if "panchayat" in fn_clean:
                return self.rules.get("village panchayat")
            return self.rules.get("village")
        if "state" in fn_clean:
            return self.rules.get("state")
        if any(k in fn_clean for k in ["pincode", "pin code", "postal code"]):
            return self.rules.get("pincode")
        if "occupation" in fn_clean:
            if "mother" in fn_clean:
                return self.rules.get("mother's occupation")
            return self.rules.get("father's occupation")
        if any(k in fn_clean for k in ["student name", "candidate name", "applicant name"]):
            return self.rules.get("student_name")

        return None

    def evaluate_candidate(
        self,
        field_name: str,
        document_type: str,
    ) -> Tuple[bool, str, int, str]:
        """
        Evaluate whether a document_type is authorized for field_name.

        Returns:
            (is_authorized, decision_or_reason, priority, rule_name)
            - is_authorized: bool
            - reason: "AUTHORIZED", "SOURCE_MISMATCH", or "UNKNOWN_DOCUMENT"
            - priority: int (higher score = higher authority)
            - rule_name: str (identifying the source rule applied)
        """
        norm_doc = normalize_document_type(document_type)
        if norm_doc == "UNKNOWN":
            self.log_decision(
                field_name=field_name,
                candidate_source=document_type,
                allowed_sources=["KNOWN_DOCUMENTS"],
                decision="REJECT",
                reason="UNKNOWN_DOCUMENT",
            )
            return False, "UNKNOWN_DOCUMENT", 0, "UNKNOWN_DOCUMENT"

        rule = self.get_rule_for_field(field_name)

        if not rule:
            # Unconfigured / generic custom field: preserve existing behavior
            # Check baseline document validity (not UNKNOWN)
            return True, "AUTHORIZED", 50, "UNCONFIGURED_DEFAULT"

        is_strict = rule.get("strict", False)
        sources = rule.get("sources", [])
        allowed_docs = [normalize_document_type(s.get("document_type")) for s in sources]

        # Check if norm_doc matches any allowed source
        for source_spec in sources:
            src_norm = normalize_document_type(source_spec.get("document_type"))
            if norm_doc == src_norm:
                prio = int(source_spec.get("priority", 100))
                rule_desc = f"STRICT_{src_norm}" if is_strict else f"PRIORITIZED_{src_norm}"
                return True, "AUTHORIZED", prio, rule_desc

        if is_strict:
            # STRICT RULE VIOLATION: candidate is rejected with SOURCE_MISMATCH
            self.log_decision(
                field_name=field_name,
                candidate_source=document_type,
                allowed_sources=allowed_docs,
                decision="REJECT",
                reason="SOURCE_MISMATCH",
            )
            return False, "SOURCE_MISMATCH", 0, "STRICT_RULE_VIOLATION"

        # Non-strict field with designated sources, but candidate came from unlisted source
        # Lower authority, but not hard rejected if allowed by general document compatibility
        self.log_decision(
            field_name=field_name,
            candidate_source=document_type,
            allowed_sources=allowed_docs,
            decision="REJECT",
            reason="SOURCE_MISMATCH",
        )
        return False, "SOURCE_MISMATCH", 0, "NON_STRICT_UNLISTED_SOURCE"

    @staticmethod
    def log_decision(
        field_name: str,
        candidate_source: str,
        allowed_sources: List[str],
        decision: str,
        reason: str,
    ) -> None:
        """
        Log safe structured audit trace without exposing PII (student name, Aadhaar, DOB, address).
        """
        allowed_str = ",".join(allowed_sources) if allowed_sources else "NONE"
        msg = (
            f"[SourceAuthority] "
            f"field={field_name} "
            f"candidate_source={candidate_source} "
            f"allowed_sources={allowed_str} "
            f"decision={decision} "
            f"reason={reason}"
        )
        logger.info(msg)
        print(msg, flush=True)


_global_source_service = SourceAuthorityService()


def evaluate_field_source(field_name: str, document_type: str) -> Tuple[bool, str, int, str]:
    """Convenience functional interface for source authority evaluation."""
    return _global_source_service.evaluate_candidate(field_name, document_type)
