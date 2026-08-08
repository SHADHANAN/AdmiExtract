"""
Field Canonicalization & Alias Normalization Service
=====================================================
Maps raw document field aliases to canonical field names,
and merges duplicate field extraction results based on confidence.
"""

from typing import Any, Dict


# Alias to Canonical Field Mapping
CANONICAL_FIELD_MAP: Dict[str, str] = {
    # Aadhaar Number
    "aadhaar": "Aadhaar Card",
    "aadhaar card": "Aadhaar Card",
    "aadhaar number": "Aadhaar Card",
    "aadhaar card number": "Aadhaar Card",
    "aadhaar no": "Aadhaar Card",
    "aadhaar no.": "Aadhaar Card",
    "aadhaar id": "Aadhaar Card",
    "aadhar": "Aadhaar Card",
    "aadhar card": "Aadhaar Card",
    "aadhar number": "Aadhaar Card",
    "aadhaar_number": "Aadhaar Card",
    "aadhaar_card": "Aadhaar Card",

    # Community Details
    "community certificate": "Community Certificate",
    "caste certificate": "Community Certificate",
    "community_certificate": "Community Certificate",
    "community": "Community Category",

    "community code": "Community Code",
    "community_code": "Community Code",
    "caste code": "Community Code",

    "community name": "Community Name",
    "community_name": "Community Name",
    "caste name": "Community Name",
    "sub caste": "Community Name",
    "sub_caste": "Community Name",

    "community category": "Community Category",
    "community_category": "Community Category",
    "caste category": "Community Category",

    # Student Name
    "student name": "Student Name",
    "candidate name": "Student Name",
    "applicant name": "Student Name",
    "name": "Student Name",
    "student_name": "Student Name",

    # Register Number
    "register number": "Register Number",
    "reg no": "Register Number",
    "register no": "Register Number",
    "register_number": "Register Number",

    # Mobile Number
    "mobile": "Mobile Number",
    "phone": "Mobile Number",
    "mobile number": "Mobile Number",
    "phone number": "Mobile Number",
    "mobile_number": "Mobile Number",

    # Address
    "address": "Address",
    "full address": "Address",
    "permanent address": "Address",
    "postal address": "Address",
    "communication address": "Address",
}


PROFILE_FIELDS = {
    "student name",
    "student_name",
    "candidate name",
    "applicant name",
    "name",
    "register number",
    "register_number",
    "reg no",
    "registration number",
    "roll number",
    "mobile number",
    "mobile_number",
    "phone number",
    "mobile",
    "phone",
    "email",
    "email id",
    "email_id",
}


def is_profile_field(field_name: str) -> bool:
    """
    Check if a field is a student account login profile field (Student Name, Register Number, Mobile Number, Email).
    These fields must be sourced exclusively from authenticated login session context, never OCR/AI.
    """
    if not field_name:
        return False
    return field_name.strip().lower() in PROFILE_FIELDS


def get_canonical_field_name(raw_name: str) -> str:
    """
    Map raw field alias to canonical field name.
    If no alias match exists, returns stripped original name.
    """
    if not raw_name:
        return ""
    clean = raw_name.strip().lower()
    return CANONICAL_FIELD_MAP.get(clean, raw_name.strip())


def normalize_and_merge_extracted_data(extracted_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Consolidate extracted fields into canonical field names.
    Merging Rules:
    1. Map every field key to its canonical name using get_canonical_field_name.
    2. If multiple aliases return values for the same canonical field:
       - Keep non-null value over null value.
       - If both non-null, keep the value with the higher confidence score.
       - Discard the rest.
    3. Ensure ONLY ONE entry per canonical field exists in the returned dictionary.
    """
    if not isinstance(extracted_dict, dict):
        return {}

    canonical_dict: Dict[str, Dict[str, Any]] = {}

    for raw_key, item in extracted_dict.items():
        if not isinstance(item, dict):
            item = {"value": item, "confidence": 100}

        canonical_key = get_canonical_field_name(raw_key)

        existing = canonical_dict.get(canonical_key)
        if existing is None:
            canonical_dict[canonical_key] = item
        else:
            existing_val = existing.get("value")
            existing_conf = existing.get("confidence", 0)
            new_val = item.get("value")
            new_conf = item.get("confidence", 0)

            # Rule 1: Replace null existing with non-null new item
            if existing_val is None and new_val is not None:
                canonical_dict[canonical_key] = item
            # Rule 2: If both non-null, keep higher confidence item
            elif existing_val is not None and new_val is not None:
                if new_conf > existing_conf:
                    canonical_dict[canonical_key] = item
            # Rule 3: Keep existing if new item is null or lower confidence

    return canonical_dict


PROFILE_FIELD_ALIASES: set[str] = {
    "student name", "student_name", "candidate name", "applicant name", "name",
    "register number", "register_number", "register no", "reg no",
    "mobile number", "mobile_number", "mobile", "phone", "phone number",
    "email", "email address"
}


def is_profile_field(name: str) -> bool:
    """Check if field name corresponds to account profile / student identification fields."""
    if not name:
        return False
    n_clean = name.strip().lower()
    if n_clean in PROFILE_FIELD_ALIASES:
        return True
    canon = get_canonical_field_name(name).strip().lower()
    return canon in ["student name", "register number", "mobile number"] or canon in PROFILE_FIELD_ALIASES


ADDRESS_FIELD_ALIASES: set[str] = {
    "address",
    "full address",
    "permanent address",
    "postal address",
    "communication address",
}


def is_address_field(name: str) -> bool:
    """Check if field name corresponds to postal address fields."""
    if not name:
        return False
    n_clean = name.strip().lower()
    if n_clean in ADDRESS_FIELD_ALIASES:
        return True
    canon = get_canonical_field_name(name).strip().lower()
    return canon == "address" or canon in ADDRESS_FIELD_ALIASES


import logging

logger = logging.getLogger(__name__)

# Master Extensible Field Alias Registry (Ordered by priority)
FIELD_ALIASES: Dict[str, list[str]] = {
    "Community": [
        "Community Category",
        "Community",
        "Community Name",
        "Community Code",
        "Caste Category",
        "Caste Name",
        "Caste Code",
        "Community Certificate",
    ],
    "Community Category": [
        "Community Category",
        "Community",
        "Community Name",
        "Community Code",
        "Caste Category",
        "Caste Name",
        "Caste Code",
        "Community Certificate",
    ],
    "Aadhaar Number": [
        "Aadhaar Number",
        "Aadhaar Card Number",
        "Aadhaar Card",
        "Aadhaar No",
        "Aadhaar No.",
        "Aadhaar ID",
        "Aadhar Number",
        "Aadhar Card Number",
        "Aadhar Card",
        "Aadhar",
    ],
    "Aadhaar Card": [
        "Aadhaar Number",
        "Aadhaar Card Number",
        "Aadhaar Card",
        "Aadhaar No",
        "Aadhaar No.",
        "Aadhaar ID",
        "Aadhar Number",
        "Aadhar Card Number",
        "Aadhar Card",
        "Aadhar",
    ],
    "Student Name": [
        "Student Name",
        "Student Full Name",
        "Candidate Name",
        "Applicant Name",
        "Name",
    ],
    "Register Number": [
        "Register Number",
        "Reg No",
        "Registration Number",
        "Register No.",
        "Roll Number",
    ],
    "Mobile Number": [
        "Mobile Number",
        "Phone Number",
        "Mobile",
        "Phone",
        "Mobile No",
    ],
    "Date of Birth": [
        "Date of Birth",
        "DOB",
        "Birth Date",
    ],
    "DOB": [
        "Date of Birth",
        "DOB",
        "Birth Date",
    ],
    "Annual Family Income": [
        "Annual Family Income",
        "Annual Income",
        "Family Income",
        "Income",
    ],
    "Income": [
        "Annual Family Income",
        "Annual Income",
        "Family Income",
        "Income",
    ],
    "SSLC Mark Percentage": [
        "SSLC Mark Percentage",
        "SSLC Marks",
        "SSLC Mark",
        "10th Mark",
        "10th Percentage",
        "SSLC Percentage",
    ],
    "HSC Mark Percentage": [
        "HSC Mark Percentage",
        "HSC Marks",
        "HSC Mark",
        "12th Mark",
        "12th Percentage",
        "HSC Percentage",
    ],
    "Transfer Certificate Number": [
        "Transfer Certificate Number",
        "TC Number",
        "TC No",
        "Transfer Certificate No",
    ],
    "School Name": [
        "School Name",
        "Institution Name",
        "School/College Name",
    ],
    "Admission Number": [
        "Admission Number",
        "Admission No",
        "Admission No.",
    ],
    "Issue Date": [
        "Issue Date",
        "Date of Issue",
        "TC Issue Date",
    ],
    "Leaving Date": [
        "Leaving Date",
        "Date of Leaving",
    ],
    "Migration Number": [
        "Migration Number",
        "Migration No",
        "Migration Certificate Number",
    ],
    "University": [
        "University Name",
        "University",
        "Board/University",
    ],
    "Year": [
        "Year of Passing",
        "Passing Year",
        "Year",
    ],
    "Nativity": [
        "Nativity",
        "Nativity Certificate",
        "Native Place",
    ],
    "Address": [
        "Address",
        "Full Address",
        "Permanent Address",
        "Postal Address",
        "Communication Address",
        "Residential Address",
        "Current Address",
        "Address Line",
        "Address Details",
        "House Address",
        "Location",
    ],
    "Full Address": [
        "Address",
        "Full Address",
        "Permanent Address",
        "Postal Address",
        "Communication Address",
        "Residential Address",
        "Current Address",
    ],
    "Permanent Address": [
        "Address",
        "Full Address",
        "Permanent Address",
        "Postal Address",
        "Communication Address",
        "Residential Address",
        "Current Address",
    ],
}


def get_aliases_for_header(header: str) -> list[str]:
    """
    Retrieve ordered alias candidate list for an Excel column header or dynamic field.
    If not explicitly in FIELD_ALIASES, dynamically constructs fallback aliases.
    """
    if not header:
        return []

    header_clean = header.strip()

    # 1. Direct match in dictionary (case-insensitive)
    for k, aliases in FIELD_ALIASES.items():
        if k.lower() == header_clean.lower():
            return aliases

    # 2. Canonical field match
    canon = get_canonical_field_name(header_clean)
    for k, aliases in FIELD_ALIASES.items():
        if k.lower() == canon.lower():
            return aliases

    # 3. Dynamic Fallback: Construct standard variations
    dynamic_aliases = [header_clean]
    if "category" not in header_clean.lower():
        dynamic_aliases.append(f"{header_clean} Category")
    if "number" not in header_clean.lower() and "no" not in header_clean.lower():
        dynamic_aliases.append(f"{header_clean} Number")
        dynamic_aliases.append(f"{header_clean} No")
    if "name" not in header_clean.lower():
        dynamic_aliases.append(f"{header_clean} Name")
    if "code" not in header_clean.lower():
        dynamic_aliases.append(f"{header_clean} Code")

    return dynamic_aliases


def filter_extracted_data_by_excel_headers(
    extracted_data: Dict[str, Any],
    excel_headers: list[str],
) -> Dict[str, Any]:
    """
    Filter extracted AI fields using ordered alias matching for Excel template column headers.
    Student profile fields (Student Name, Register Number, Mobile Number, Email) are strictly excluded from document extraction.
    Columns in Excel template are matched against alias priority order (e.g. Community Category > Community Name > Community Code).
    Logs mapping decisions for audit visibility.
    """
    if not isinstance(extracted_data, dict):
        extracted_data = {}

    if not excel_headers:
        return {k: v for k, v in extracted_data.items() if not is_profile_field(k)}

    result_dict: Dict[str, Dict[str, Any]] = {}

    for header in excel_headers:
        header_clean = header.strip()
        if not header_clean or is_profile_field(header_clean):
            continue

        aliases = get_aliases_for_header(header_clean)

        matched_alias = None
        matched_val = None
        matched_conf = 100

        # Check aliases in priority order
        for alias in aliases:
            alias_lower = alias.lower()

            for k, raw in extracted_data.items():
                if not k or is_profile_field(k):
                    continue

                if k.strip().lower() == alias_lower:
                    if isinstance(raw, dict):
                        v = raw.get("value")
                        c = raw.get("confidence", 100)
                    else:
                        v = raw
                        c = 100

                    if v is not None and str(v).strip() != "":
                        matched_alias = alias
                        matched_val = v
                        matched_conf = c
                        break

            if matched_alias is not None:
                break

        # Secondary Fallback: Keyword substring match if exact alias did not match
        if matched_alias is None:
            header_lower = header_clean.lower()
            for k, raw in extracted_data.items():
                if not k or is_profile_field(k):
                    continue
                k_lower = k.strip().lower()
                if header_lower in k_lower or k_lower in header_lower:
                    if isinstance(raw, dict):
                        v = raw.get("value")
                        c = raw.get("confidence", 100)
                    else:
                        v = raw
                        c = 100
                    if v is not None and str(v).strip() != "":
                        matched_alias = k
                        matched_val = v
                        matched_conf = c
                        break

        # Log mapping decisions
        if matched_alias is not None:
            log_msg = f"Excel Header : {header_clean} | Matched Alias : {matched_alias} | Value : {matched_val}"
            logger.info(log_msg)
            print(log_msg, flush=True)
            result_dict[header_clean] = {
                "value": matched_val,
                "confidence": matched_conf,
            }
        else:
            log_msg = f"Excel Header : {header_clean} | Matched Alias : None | Value : None"
            logger.info(log_msg)
            print(log_msg, flush=True)
            result_dict[header_clean] = {
                "value": None,
                "confidence": 0,
            }

    return result_dict


FIELD_SOURCE_RULES: Dict[str, list[str]] = {
    "Aadhaar Number": ["AADHAAR"],
    "Aadhaar Card": ["AADHAAR"],
    "Address": ["AADHAAR"],
    "Full Address": ["AADHAAR"],
    "Permanent Address": ["AADHAAR"],
    "Postal Address": ["AADHAAR"],
    "Residential Address": ["AADHAAR"],
    "Communication Address": ["AADHAAR"],

    "Community": ["COMMUNITY"],
    "Community Category": ["COMMUNITY"],
    "Community Code": ["COMMUNITY"],
    "Community Name": ["COMMUNITY"],

    "EMIS ID": ["TRANSFER_CERTIFICATE"],
    "Transfer Certificate Number": ["TRANSFER_CERTIFICATE"],
    "Admission Number": ["TRANSFER_CERTIFICATE"],
    "School Name": ["TRANSFER_CERTIFICATE", "SSLC", "HSC"],
    "Issue Date": ["TRANSFER_CERTIFICATE"],
    "Leaving Date": ["TRANSFER_CERTIFICATE"],

    "Annual Family Income": ["INCOME"],
    "Income": ["INCOME"],

    "SSLC Mark Percentage": ["SSLC"],
    "HSC Mark Percentage": ["HSC"],
    "Nativity": ["NATIVITY"],
}


def get_allowed_sources_for_field(field_name: str) -> list[str]:
    """
    Get allowed document types for a field using FIELD_SOURCE_RULES.
    Returns list of document types, e.g. ["AADHAAR"] or ["COMMUNITY"].
    """
    fn_clean = field_name.strip()
    if fn_clean in FIELD_SOURCE_RULES:
        return FIELD_SOURCE_RULES[fn_clean]

    fn_lower = fn_clean.lower()
    for k, v in FIELD_SOURCE_RULES.items():
        if k.lower() == fn_lower:
            return v

    if is_address_field(fn_clean) or "address" in fn_lower:
        return ["AADHAAR"]
    if any(c in fn_lower for c in ["community", "caste"]):
        return ["COMMUNITY"]
    if any(c in fn_lower for c in ["transfer certificate", "emis id", "leaving date", "admission number"]):
        return ["TRANSFER_CERTIFICATE"]
    if "income" in fn_lower:
        return ["INCOME"]

    return ["ALL"]


def is_document_authorized_for_field(doc_type: str, field_name: str) -> bool:
    """
    Strict Document-Field Alignment Rule:
    - Address fields must ONLY come from AADHAAR.
    - Community fields must ONLY come from COMMUNITY.
    - Transfer Certificate fields must ONLY come from TRANSFER_CERTIFICATE.
    - Income fields must ONLY come from INCOME.
    - UNKNOWN documents allow extraction if features are present.
    """
    if not doc_type or doc_type == "UNKNOWN":
        return True

    allowed_sources = get_allowed_sources_for_field(field_name)
    if "ALL" in allowed_sources:
        return True

    return doc_type in allowed_sources



