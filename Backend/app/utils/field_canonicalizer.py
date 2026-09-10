"""
Field Canonicalization & Alias Normalization Service
=====================================================
Maps raw document field aliases to canonical field names,
and merges duplicate field extraction results based on confidence.
"""

import re
from typing import Any, Dict, Optional



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
    "caste":"Community Name",
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

    #collage reg
    "Collage Register No":"register_number",
    "collage register no":"register_number",

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

    # Bank Details
    "ifsc": "IFSC Code",
    "ifsc code": "IFSC Code",
    "ifsc_code": "IFSC Code",
    "bank name": "Bank Name",
    "bank_name": "Bank Name",
    "bank branch": "Bank Branch",
    "account number": "Account Number",
    "account_number": "Account Number",
    "bank account number": "Account Number",
    "account no": "Account Number",
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

            def _is_present(v):
                return v is not None and str(v).strip() != "" and str(v).strip().upper() not in ["NO", "NULL"]

            # Rule 1: Replace missing/NO existing with valid non-NO new item
            if not _is_present(existing_val) and _is_present(new_val):
                canonical_dict[canonical_key] = item
            # Rule 2: If both valid non-NULL, keep higher confidence item
            elif _is_present(existing_val) and _is_present(new_val):
                if new_conf > existing_conf:
                    canonical_dict[canonical_key] = item
            # Rule 3: Keep existing if new item is missing or lower confidence

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
    # Question / boolean flag fields must NOT be treated as postal address text fields
    if any(q in n_clean for q in ["same as", "is ", "whether", "yes/no", "?"]):
        return False
    if n_clean in ADDRESS_FIELD_ALIASES:
        return True
    canon = get_canonical_field_name(name).strip().lower()
    return canon == "address" or canon in ADDRESS_FIELD_ALIASES


def is_yes_no_question_field(name: str) -> bool:
    """
    Check if a field name represents a Yes/No question or boolean indicator.
    Examples:
    - "Orphan Category (Yes/No)"
    - "Communication address same as permanent address"
    - "Is EMIS ID Available"
    - "Is the student the first graduate in the family?"
    - "Did you come under any special admission Quota?"
    - "Did you belong to differently abled category?"
    """
    if not name:
        return False
    n_lower = name.strip().lower()
    if any(tag in n_lower for tag in ["yes/no", "(yes/no)", "yes / no", "yes/no"]):
        return True
    if any(n_lower.startswith(p) for p in ["is ", "did ", "does ", "whether ", "has "]):
        return True
    if re.search(r"\b(is|did|does|whether|has)\b", n_lower):
        return True
    if any(phrase in n_lower for phrase in ["same as", "first graduate", "special admission", "differently abled", "orphan"]):
        return True
    if n_lower.endswith("?"):
        return True
    return False


<<<<<<< HEAD
def is_name_conflict(header: str, candidate_key: str) -> bool:
    """
    Check if matching candidate_key to header violates person name semantic boundaries:
    - Student Name cannot match Father/Mother/Guardian/School Name
    - Father Name cannot match Mother/Student Name
    - Mother Name cannot match Father/Student Name
    """
    if not header or not candidate_key:
        return False
    h = header.lower().strip()
    c = candidate_key.lower().strip()

    # Student Name header
    if any(k in h for k in ["student name", "candidate name", "applicant name", "name of candidate", "name of student", "name of the student"]) or (
        "name" in h and not any(p in h for p in ["father", "mother", "parent", "guardian", "spouse", "school", "college", "bank", "branch"])
    ):
        if any(bad in c for bad in ["father", "mother", "guardian", "spouse", "school", "college", "bank", "branch"]):
            return True

    # Father's Name header
    if "father" in h:
        if any(bad in c for bad in ["mother", "student name", "candidate name", "applicant name"]):
            return True

    # Mother's Name header
    if "mother" in h:
        if any(bad in c for bad in ["father", "student name", "candidate name", "applicant name", "guardian"]):
            return True

    # Guardian / Spouse Name header
    if "guardian" in h or "spouse" in h:
        if "mother" in c:
            return True

    return False


def is_number_conflict(header: str, candidate_key: str) -> bool:
    """
    Check if matching candidate_key to header violates identifier semantic boundaries:
    - Register/Roll No vs Aadhaar vs EMIS vs Serial No (SL.NO) vs Mobile
    """
    if not header or not candidate_key:
        return False
    h = header.lower().strip()
    c = candidate_key.lower().strip()

    # Aadhaar Number
    if "aadhaar" in h or "aadhar" in h:
        if any(bad in c for bad in ["emis", "register", "roll", "sl.no", "serial", "tc no", "mobile", "phone"]):
            return True
    elif "aadhaar" in c or "aadhar" in c:
        if not ("aadhaar" in h or "aadhar" in h):
            return True

    # EMIS ID
    if "emis" in h:
        if any(bad in c for bad in ["aadhaar", "aadhar", "register", "roll", "mobile", "phone", "sl.no"]):
            return True
    elif "emis" in c:
        if not ("emis" in h):
            return True

    # Register / Roll Number
    if any(k in h for k in ["register number", "registration number", "roll number", "reg no", "roll no"]):
        if any(bad in c for bad in ["aadhaar", "aadhar", "emis", "mobile", "phone", "sl.no", "serial no"]):
            return True

    # SL.NO / Serial Number
    if any(k in h for k in ["sl.no", "sl no", "s.no", "serial no"]):
        if any(bad in c for bad in ["register", "registration", "roll", "aadhaar", "emis"]):
            return True

    return False


def is_category_conflict(header: str, candidate_key: str) -> bool:
    """
    Disambiguate Community vs Caste vs Religion vs Nationality.
    """
    if not header or not candidate_key:
        return False
    h = header.lower().strip()
    c = candidate_key.lower().strip()

    # Religion vs Community / Caste
    if "religion" in h:
        if any(bad in c for bad in ["community", "caste", "nationality"]):
            return True
    if "religion" in c:
        if not ("religion" in h):
            return True

    # Nationality vs Community / Caste / Religion
    if "nationality" in h or "nation" in h:
        if any(bad in c for bad in ["community", "caste", "religion"]):
            return True
    if "nationality" in c:
        if not ("nationality" in h or "nation" in h):
            return True

    return False


def is_phone_conflict(header: str, candidate_key: str) -> bool:
    """
    Disambiguate Student Mobile from Parent/Guardian Mobile.
    """
    if not header or not candidate_key:
        return False
    h = header.lower().strip()
    c = candidate_key.lower().strip()

    is_h_parent = any(p in h for p in ["parent", "father", "mother", "guardian", "emergency"])
    is_c_parent = any(p in c for p in ["parent", "father", "mother", "guardian", "emergency"])

    # If header is specifically student mobile, reject parent mobile
    if not is_h_parent and any(m in h for m in ["mobile", "phone", "cell"]):
        if is_c_parent:
            return True

    # If header is specifically parent/guardian mobile, reject bare student mobile if parent mobile exists
    if is_h_parent and any(m in h for m in ["mobile", "phone", "cell"]):
        if not is_c_parent and any(m in c for m in ["student mobile", "candidate mobile"]):
            return True

    return False


def is_address_conflict(header: str, candidate_key: str) -> bool:
    """
    Prevent full address text from matching single-word components (District, State, Taluk, Village, Pincode),
    and vice versa.
    """
    if not header or not candidate_key:
        return False
    h = header.lower().strip()
    c = candidate_key.lower().strip()

    single_components = ["district", "taluk", "village", "state", "pincode", "pin code", "block", "country"]
    is_h_single = any(comp == h or comp in h.split() for comp in single_components)
    is_h_full_addr = "address" in h and not is_h_single

    is_c_single = any(comp == c or comp in c.split() for comp in single_components)
    is_c_full_addr = "address" in c and not is_c_single

    if is_h_single and is_c_full_addr:
        return True
    if is_h_full_addr and is_c_single:
        return True

    return False


=======
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
def normalize_yes_no_value(raw_val: Any) -> Any:
    """
    Normalize raw LLM or string value strictly to 'Yes', 'No', or None.
    """
    if raw_val is None:
        return None
    val_str = str(raw_val).strip().lower()
    if not val_str or val_str in ["null", "none", "n/a", "not detected"]:
        return None
    if val_str in ["yes", "true", "y", "available", "present", "applicable", "1"]:
        return "Yes"
    if val_str in ["no", "false", "n", "not available", "absent", "not applicable", "0"]:
        return "No"
    if "yes" in val_str:
        return "Yes"
    if "no" in val_str:
        return "No"
    return None


import logging

logger = logging.getLogger(__name__)

ADDRESS_SOURCE_PRIORITY: list[str] = [
    "AADHAAR",
    "RESIDENCE",
    "RESIDENCE_CERTIFICATE",
    "NATIVITY",
    "COMMUNITY",
    "PASSPORT",
    "DRIVING_LICENCE",
    "DRIVING_LICENSE",
    "VOTER_ID",
    "BANK_PASSBOOK",
    "TRANSFER_CERTIFICATE",
    "INCOME",
    "BONAFIDE",
    "MIGRATION",
]

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
        "Caste",
        "Community Certificate",
    ],
<<<<<<< HEAD
    "Caste": [
        "Community Category",
        "Community Name",
        "Community",
        "Caste Name",
        "Caste Category",
        "Caste",
        "Community Certificate",
    ],
    "Community / Caste": [
        "Community Category",
        "Community Name",
        "Community",
        "Caste Name",
        "Caste Category",
        "Caste",
    ],
=======
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
    "Community Category": [
        "Community Category",
        "Community",
        "Community Name",
        "Community Code",
        "Caste Category",
        "Caste Name",
        "Caste Code",
        "Caste",
        "Community Certificate",
    ],
<<<<<<< HEAD
    "Community Name": [
        "Community Name",
        "Community Category",
        "Community",
        "Caste Name",
        "Caste Category",
        "Caste",
    ],
=======
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
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
    "Aadhaar Number (without space)": [
        "Aadhaar Number (without space)",
        "Aadhaar Number",
        "Aadhaar Card Number",
        "Aadhaar Card",
        "Aadhaar No",
        "Aadhaar No.",
        "Aadhaar ID",
        "Aadhar Number",
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
    "Gender": [
        "Gender",
        "Sex",
    ],
    "Blood Group": [
        "Blood Group",
        "Blood Group / Rh Factor",
    ],
    "Nationality": [
        "Nationality",
        "Citizenship",
    ],
    "Religion": [
        "Religion",
    ],
    "Father's Name": [
        "Father's Name",
        "Father Name",
        "Father/Guardian Name",
        "Father's Name / Husband Name",
    ],
    "Mother's Name": [
        "Mother's Name",
        "Mother Name",
    ],
    "Father's Occupation": [
        "Father's Occupation",
        "Father Occupation",
    ],
    "Mother's Occupation": [
        "Mother's Occupation",
        "Mother Occupation",
    ],
    "Guardian's / Spouse's Name": [
        "Guardian's / Spouse's Name",
        "Guardian Name",
        "Spouse Name",
        "Guardian / Spouse Name",
    ],
    "Date of Birth": [
        "Date of Birth",
        "DOB",
        "Birth Date",
        "Student Date of Birth(DD.MM.YYYY)",
    ],
    "Student Date of Birth(DD.MM.YYYY)": [
        "Student Date of Birth(DD.MM.YYYY)",
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
    "Country": [
        "Country",
        "Nation",
    ],
    "State": [
        "State",
        "State Name",
    ],
    "District": [
        "District",
        "District Name",
        "Dist",
    ],
    "Taluk": [
        "Taluk",
        "Taluk Name",
        "Tehsil",
    ],
    "Village": [
        "Village",
        "Village Name",
        "Town",
    ],
    "City": [
        "City",
        "City Name",
    ],
    "IFSC Code": [
        "IFSC Code",
        "IFSC",
        "IFSC CODE",
        "IFSC Code No",
        "IFSC Code Number",
        "RTGS / IFSC Code",
        "IFS Code",
    ],
    "Bank Name": [
        "Bank Name",
        "Name of the Bank",
        "Bank",
    ],
    "Bank Branch": [
        "Bank Branch",
        "Branch Name",
        "Branch",
    ],
    "Account Number": [
        "Account Number",
        "Bank Account Number",
        "Account No",
        "Bank Account No",
        "A/c No",
        "A/c Number",
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
            # Skip loose substring matching for Yes/No question or boolean flag headers
            if not any(q in header_lower for q in ["same as", "is ", "whether", "yes/no", "?"]):
                for k, raw in extracted_data.items():
                    if not k or is_profile_field(k):
                        continue
                    k_lower = k.strip().lower()
                    if (header_lower in k_lower or k_lower in header_lower) and len(k_lower) > 3:
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
            log_msg = f"Excel Header : {header_clean} | Matched Alias : None | Value : NO"
            logger.info(log_msg)
            print(log_msg, flush=True)
            result_dict[header_clean] = {
                "value": "NO",
                "confidence": 0,
            }

    return result_dict


FIELD_SOURCE_RULES: Dict[str, list[str]] = {
    # Aadhaar & ID Cards
    "Aadhaar Number": ["AADHAAR"],
    "Aadhaar Card": ["AADHAAR"],
    "Aadhaar Card Number": ["AADHAAR"],
    "Aadhaar Number (without space)": ["AADHAAR"],
    "Aadhar Number": ["AADHAAR"],
    "Aadhar Card": ["AADHAAR"],

    # Address & Location
    "Address": ADDRESS_SOURCE_PRIORITY,
    "Full Address": ADDRESS_SOURCE_PRIORITY,
    "Permanent Address": ADDRESS_SOURCE_PRIORITY,
    "Postal Address": ADDRESS_SOURCE_PRIORITY,
    "Residential Address": ADDRESS_SOURCE_PRIORITY,
    "Communication Address": ADDRESS_SOURCE_PRIORITY,
    "Communication address": ADDRESS_SOURCE_PRIORITY,
    "Current Address": ADDRESS_SOURCE_PRIORITY,
    "House Address": ADDRESS_SOURCE_PRIORITY,
    "Country": ADDRESS_SOURCE_PRIORITY,
    "State": ADDRESS_SOURCE_PRIORITY,
    "State Name": ADDRESS_SOURCE_PRIORITY,
    "District": ADDRESS_SOURCE_PRIORITY,
    "District Name": ADDRESS_SOURCE_PRIORITY,
    "Dist": ADDRESS_SOURCE_PRIORITY,
    "Taluk": ADDRESS_SOURCE_PRIORITY,
    "Taluk Name": ADDRESS_SOURCE_PRIORITY,
    "Tehsil": ADDRESS_SOURCE_PRIORITY,
    "Village": ADDRESS_SOURCE_PRIORITY,
    "Village Name": ADDRESS_SOURCE_PRIORITY,
    "Town": ADDRESS_SOURCE_PRIORITY,
    "VTC": ADDRESS_SOURCE_PRIORITY,
    "Pincode": ADDRESS_SOURCE_PRIORITY,
    "Pin Code": ADDRESS_SOURCE_PRIORITY,
    "PIN Code": ADDRESS_SOURCE_PRIORITY,
    "PIN": ADDRESS_SOURCE_PRIORITY,
    "Postal Code": ADDRESS_SOURCE_PRIORITY,
    "City": ADDRESS_SOURCE_PRIORITY,
    "Location Type": ADDRESS_SOURCE_PRIORITY,
    "Block": ADDRESS_SOURCE_PRIORITY,
    "Village Panchayat": ADDRESS_SOURCE_PRIORITY,
    "Communication address same as permanent address": ADDRESS_SOURCE_PRIORITY,



    # Personal Details
    "Gender": ["AADHAAR", "TRANSFER_CERTIFICATE", "SSLC", "HSC", "COMMUNITY", "NATIVITY"],
    "Sex": ["AADHAAR", "TRANSFER_CERTIFICATE", "SSLC", "HSC", "COMMUNITY", "NATIVITY"],
    "Salutation": ["AADHAAR", "TRANSFER_CERTIFICATE", "SSLC", "HSC", "COMMUNITY"],
    "Blood Group": ["TRANSFER_CERTIFICATE", "AADHAAR"],
    "Nationality": ["AADHAAR", "COMMUNITY", "NATIVITY", "TRANSFER_CERTIFICATE"],
    "Religion": ["COMMUNITY", "TRANSFER_CERTIFICATE", "NATIVITY"],

    # Community & Caste
    "Community": ["COMMUNITY", "TRANSFER_CERTIFICATE"],
    "Community Category": ["COMMUNITY"],
    "Community Code": ["COMMUNITY"],
    "Community Name": ["COMMUNITY"],
    "Caste Category": ["COMMUNITY"],
    "Caste Name": ["COMMUNITY"],
    "Caste Code": ["COMMUNITY"],
    "Caste": ["COMMUNITY", "TRANSFER_CERTIFICATE"],
    "Community Certificate": ["COMMUNITY"],

    # Parent & Guardian Details
    "Father's Name": ["AADHAAR", "COMMUNITY", "TRANSFER_CERTIFICATE", "INCOME", "NATIVITY", "SSLC", "HSC"],
    "Father Name": ["AADHAAR", "COMMUNITY", "TRANSFER_CERTIFICATE", "INCOME", "NATIVITY", "SSLC", "HSC"],
    "Father's Occupation": ["INCOME", "COMMUNITY", "TRANSFER_CERTIFICATE"],
    "Father Occupation": ["INCOME", "COMMUNITY", "TRANSFER_CERTIFICATE"],
    "Mother's Name": ["AADHAAR", "COMMUNITY", "TRANSFER_CERTIFICATE", "INCOME", "NATIVITY", "SSLC", "HSC"],
    "Mother Name": ["AADHAAR", "COMMUNITY", "TRANSFER_CERTIFICATE", "INCOME", "NATIVITY", "SSLC", "HSC"],
    "Mother's Occupation": ["INCOME", "COMMUNITY", "TRANSFER_CERTIFICATE"],
    "Mother Occupation": ["INCOME", "COMMUNITY", "TRANSFER_CERTIFICATE"],
    "Guardian's / Spouse's Name": ["AADHAAR", "COMMUNITY", "TRANSFER_CERTIFICATE", "INCOME"],
    "Guardian Name": ["AADHAAR", "COMMUNITY", "TRANSFER_CERTIFICATE", "INCOME"],
    "Parent / spouse / Guardian Mobile Number": ["AADHAAR", "TRANSFER_CERTIFICATE"],

    # Academic & TC & EMIS
    "EMIS ID": ["TRANSFER_CERTIFICATE"],
    "Is EMIS ID Available": ["TRANSFER_CERTIFICATE"],
    "UMIS NO": ["TRANSFER_CERTIFICATE", "SSLC", "HSC"],
    "Registration Number": ["TRANSFER_CERTIFICATE", "SSLC", "HSC"],
    "Transfer Certificate Number": ["TRANSFER_CERTIFICATE"],
    "TC Number": ["TRANSFER_CERTIFICATE"],
    "TC No": ["TRANSFER_CERTIFICATE"],
    "Admission Number": ["TRANSFER_CERTIFICATE"],
    "School Name": ["TRANSFER_CERTIFICATE", "SSLC", "HSC"],
    "Issue Date": ["TRANSFER_CERTIFICATE"],
    "Leaving Date": ["TRANSFER_CERTIFICATE"],
    "TC Issue Date": ["TRANSFER_CERTIFICATE"],
    "Academic Year of Joining": ["TRANSFER_CERTIFICATE", "SSLC", "HSC", "BONAFIDE"],
    "Stream Type": ["TRANSFER_CERTIFICATE", "SSLC", "HSC", "BONAFIDE"],
    "Course Type": ["TRANSFER_CERTIFICATE", "SSLC", "HSC", "BONAFIDE"],
    "COURSE": ["TRANSFER_CERTIFICATE", "SSLC", "HSC", "BONAFIDE"],
    "Branch / Specialization": ["TRANSFER_CERTIFICATE", "SSLC", "HSC", "BONAFIDE"],
    "Medium of Intruction": ["TRANSFER_CERTIFICATE", "SSLC", "HSC"],
    "Mode of Study": ["TRANSFER_CERTIFICATE", "SSLC", "HSC", "BONAFIDE"],

    # Income
    "Annual Family Income": ["INCOME"],
    "Income": ["INCOME"],
    "Family Income": ["INCOME"],

    # Marks
    "SSLC Mark Percentage": ["SSLC"],
    "SSLC Marks": ["SSLC"],
    "10th Mark": ["SSLC"],
    "10th Percentage": ["SSLC"],

    "HSC Mark Percentage": ["HSC"],
    "HSC Marks": ["HSC"],
    "12th Mark": ["HSC"],
    "12th Percentage": ["HSC"],

    # Certificates & Quotas
    "Nativity": ["NATIVITY"],
    "Nativity Certificate": ["NATIVITY"],
    "Migration Number": ["MIGRATION"],
    "University": ["MIGRATION"],
    "Year": ["MIGRATION"],
    "Bonafide": ["BONAFIDE"],
    "Date of Birth": ["AADHAAR", "TRANSFER_CERTIFICATE", "SSLC", "HSC", "COMMUNITY", "NATIVITY"],
    "Student Date of Birth(DD.MM.YYYY)": ["AADHAAR", "TRANSFER_CERTIFICATE", "SSLC", "HSC", "COMMUNITY", "NATIVITY"],
    "DOB": ["AADHAAR", "TRANSFER_CERTIFICATE", "SSLC", "HSC", "COMMUNITY", "NATIVITY"],
    "Is the student the first graduate in the family?": ["BONAFIDE", "TRANSFER_CERTIFICATE", "INCOME"],
    "First Graduate Number": ["BONAFIDE", "TRANSFER_CERTIFICATE", "INCOME"],
    "Did you come under any special admission Quota?": ["TRANSFER_CERTIFICATE", "BONAFIDE"],
    "Did you belong to differently abled category?": ["TRANSFER_CERTIFICATE", "BONAFIDE"],
    "Orphan Category (Yes/No)": ["TRANSFER_CERTIFICATE", "INCOME", "COMMUNITY", "BONAFIDE"],

    # Bank Details
    "IFSC Code": ["INCOME", "BONAFIDE", "TRANSFER_CERTIFICATE", "AADHAAR"],
    "Bank Name": ["INCOME", "BONAFIDE", "TRANSFER_CERTIFICATE", "AADHAAR"],
    "Bank Branch": ["INCOME", "BONAFIDE", "TRANSFER_CERTIFICATE", "AADHAAR"],
    "Account Number": ["INCOME", "BONAFIDE", "TRANSFER_CERTIFICATE", "AADHAAR"],
}


def get_allowed_sources_for_field(field_name: str) -> list[str]:
    """
    Get allowed document types for a field using FIELD_SOURCE_RULES.
    Returns list of document types, e.g. ["AADHAAR"] or ["COMMUNITY"].
    If no source rule matches, returns default set of valid document types.
    """
    if not field_name:
        return []

    fn_clean = field_name.strip()
    if fn_clean in FIELD_SOURCE_RULES:
        return FIELD_SOURCE_RULES[fn_clean]

    fn_lower = fn_clean.lower()
    for k, v in FIELD_SOURCE_RULES.items():
        if k.lower() == fn_lower:
            return v

    # Dynamic Fallback Rules (evaluated in strict order)
    if is_address_field(fn_clean) or any(c in fn_lower for c in ["address", "village", "taluk", "tehsil", "district", "pincode", "pin code", "postal code", "state", "city", "country", "location", "block", "panchayat"]):
        return ADDRESS_SOURCE_PRIORITY

    if any(c in fn_lower for c in ["gender", "sex", "salutation"]):
        return ["AADHAAR", "TRANSFER_CERTIFICATE", "SSLC", "HSC", "COMMUNITY", "NATIVITY"]
    if any(c in fn_lower for c in ["father", "mother", "parent", "guardian", "spouse"]):
        return ["AADHAAR", "COMMUNITY", "TRANSFER_CERTIFICATE", "INCOME", "NATIVITY", "SSLC", "HSC"]
    if any(c in fn_lower for c in ["religion", "nationality", "blood group", "blood"]):
        return ["AADHAAR", "COMMUNITY", "NATIVITY", "TRANSFER_CERTIFICATE"]

    if any(c in fn_lower for c in ["community", "caste"]):
        return ["COMMUNITY", "TRANSFER_CERTIFICATE"]
    if any(c in fn_lower for c in ["transfer certificate", "emis id", "leaving date", "admission number", "tc no", "tc number"]):
        return ["TRANSFER_CERTIFICATE"]
    if any(c in fn_lower for c in ["bank", "ifsc", "account"]):
        return ["INCOME", "BONAFIDE", "TRANSFER_CERTIFICATE", "AADHAAR"]
    if any(c in fn_lower for c in ["course", "stream", "medium", "branch", "specialization", "academic year", "mode of study"]):
        return ["TRANSFER_CERTIFICATE", "SSLC", "HSC", "BONAFIDE"]
    if "income" in fn_lower:
        return ["INCOME"]
    if "sslc" in fn_lower or "10th" in fn_lower:
        return ["SSLC"]
    if "hsc" in fn_lower or "12th" in fn_lower:
        return ["HSC"]
    if "nativity" in fn_lower:
        return ["NATIVITY"]
    if "migration" in fn_lower:
        return ["MIGRATION"]
    if "bonafide" in fn_lower:
        return ["BONAFIDE"]
    if "dob" in fn_lower or "birth" in fn_lower:
        return ["AADHAAR", "TRANSFER_CERTIFICATE", "SSLC", "HSC", "COMMUNITY", "NATIVITY"]

    # For any unrecognized custom field, allow searching across known document types (excluding UNKNOWN)
    return ["AADHAAR", "TRANSFER_CERTIFICATE", "COMMUNITY", "INCOME", "NATIVITY", "SSLC", "HSC", "BONAFIDE", "MIGRATION"]


def is_document_authorized_for_field(doc_type: str, field_name: str) -> bool:
    """
<<<<<<< HEAD
    Document-Field Alignment Rule:
=======
    Strict Document-Field Alignment Rule:
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
    - Return True ONLY if doc_type is a valid allowed source for field_name.
    - UNKNOWN document types return False.
    """
    if not doc_type or doc_type == "UNKNOWN":
        return False

    allowed_sources = get_allowed_sources_for_field(field_name)
    return doc_type in allowed_sources


<<<<<<< HEAD


=======
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
def get_doc_type_for_requirement(doc_name: str) -> str:
    """
    Map document requirement name (e.g., 'Income Certificate', 'Aadhaar Card')
    to standard document classification type (e.g. 'INCOME', 'AADHAAR').
    """
    if not doc_name:
        return "UNKNOWN"
    lower = doc_name.lower().strip()
    if "aadhaar" in lower or "aadhar" in lower:
        return "AADHAAR"
    if "community" in lower or "caste" in lower:
        return "COMMUNITY"
    if "income" in lower:
        return "INCOME"
    if "transfer" in lower or "tc" in lower:
        return "TRANSFER_CERTIFICATE"
    if "sslc" in lower or "10th" in lower:
        return "SSLC"
    if "hsc" in lower or "12th" in lower:
        return "HSC"
    if "nativity" in lower:
        return "NATIVITY"
    if "migration" in lower:
        return "MIGRATION"
    if "bonafide" in lower:
        return "BONAFIDE"
    return doc_name.upper().replace(" ", "_")


def is_optional_requirement(doc_req_item: Any) -> bool:
    """
    Check if a document requirement item is configured as OPTIONAL.
    """
    if not doc_req_item:
        return False
    if isinstance(doc_req_item, dict):
        req_type = str(doc_req_item.get("type", "")).upper()
        required = doc_req_item.get("required", True)
    else:
        req_type = str(getattr(doc_req_item, "type", "")).upper()
        required = getattr(doc_req_item, "required", True)
    return req_type == "OPTIONAL" or not required


def is_field_belonging_to_optional_doc(
    field_name: str,
    doc_requirements: list,
) -> tuple[bool, str | None]:
    """
    Determine if field_name belongs to an OPTIONAL document requirement.
    Returns (is_optional, doc_type_str).
    """
    if not field_name or not doc_requirements:
        return False, None

    fn_clean = field_name.strip()
    fn_lower = fn_clean.lower()

    for doc_req in doc_requirements:
        is_opt = is_optional_requirement(doc_req)
        if not is_opt:
            continue

        req_name = getattr(doc_req, "name", "") if not isinstance(doc_req, dict) else doc_req.get("name", "")
        req_doc_type = get_doc_type_for_requirement(req_name)
        extraction_fields = getattr(doc_req, "extraction_fields", []) if not isinstance(doc_req, dict) else doc_req.get("extraction_fields", [])

        # 1. Direct match in requirement's extraction_fields
        if any(f.strip().lower() == fn_lower for f in (extraction_fields or [])):
            return True, req_doc_type

        # 2. Match requirement name substring in field name
        if req_name and len(req_name.strip()) > 3 and req_name.lower().strip() in fn_lower:
            return True, req_doc_type

    # 3. Check allowed sources for field
    allowed_sources = get_allowed_sources_for_field(fn_clean)
    for doc_req in doc_requirements:
        is_opt = is_optional_requirement(doc_req)
        if not is_opt:
            continue
        req_name = getattr(doc_req, "name", "") if not isinstance(doc_req, dict) else doc_req.get("name", "")
        req_doc_type = get_doc_type_for_requirement(req_name)
        if req_doc_type in allowed_sources:
            non_opt_sources = [s for s in allowed_sources if s != req_doc_type]
            if not non_opt_sources or len(allowed_sources) == 1:
                return True, req_doc_type

    return False, None


INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry", "Pondicherry"
]


PIN_CODE_LOOKUP_DATABASE: dict[str, dict[str, str]] = {
    "641016": {"district": "Coimbatore", "taluk": "Sulur", "village": "Pattanam", "state": "Tamil Nadu"},
    "625106": {"district": "Madurai", "taluk": "Melur", "village": "Melur", "state": "Tamil Nadu"},
    "625532": {"district": "Madurai", "taluk": "Usilampatti", "village": "Kallupatti", "state": "Tamil Nadu"},
    "625001": {"district": "Madurai", "taluk": "Madurai South", "village": "Madurai", "state": "Tamil Nadu"},
    "625002": {"district": "Madurai", "taluk": "Madurai South", "village": "Madurai", "state": "Tamil Nadu"},
    "600001": {"district": "Chennai", "taluk": "Fort Tondiarpet", "village": "George Town", "state": "Tamil Nadu"},
    "600028": {"district": "Chennai", "taluk": "Mylapore", "village": "Raja Annamalaipuram", "state": "Tamil Nadu"},
    "641001": {"district": "Coimbatore", "taluk": "Coimbatore South", "village": "Coimbatore", "state": "Tamil Nadu"},
    "641004": {"district": "Coimbatore", "taluk": "Coimbatore South", "village": "Peelamedu", "state": "Tamil Nadu"},
    "641014": {"district": "Coimbatore", "taluk": "Coimbatore South", "village": "Civil Aerodrome", "state": "Tamil Nadu"},
    "641035": {"district": "Coimbatore", "taluk": "Coimbatore North", "village": "Saravanampatti", "state": "Tamil Nadu"},
    "641046": {"district": "Coimbatore", "taluk": "Coimbatore South", "village": "Bharathiar University", "state": "Tamil Nadu"},
    "641601": {"district": "Tiruppur", "taluk": "Tiruppur North", "village": "Tiruppur", "state": "Tamil Nadu"},
    "638001": {"district": "Erode", "taluk": "Erode", "village": "Erode", "state": "Tamil Nadu"},
    "636001": {"district": "Salem", "taluk": "Salem", "village": "Salem", "state": "Tamil Nadu"},
    "620001": {"district": "Tiruchirappalli", "taluk": "Tiruchirappalli", "village": "Tiruchirappalli", "state": "Tamil Nadu"},
    "627001": {"district": "Tirunelveli", "taluk": "Tirunelveli", "village": "Tirunelveli", "state": "Tamil Nadu"},
    "629001": {"district": "Kanniyakumari", "taluk": "Agastheeswaram", "village": "Nagercoil", "state": "Tamil Nadu"},
}


def parse_location_components_from_address(address_str: str) -> dict[str, dict[str, Any]]:
    """
    Intelligently derive location sub-fields (Pincode, State, District, Taluk, Village)
    from a full address string using text parsing and PIN code lookup database.
    Returns dictionary mapping field keys to {"value": val, "confidence": conf}.
    Missing or non-derivable components return {"value": "NO", "confidence": 0}.
    """
    result: dict[str, dict[str, Any]] = {
        "Address": {"value": "NO", "confidence": 0},
        "Pincode": {"value": "NO", "confidence": 0},
        "State": {"value": "NO", "confidence": 0},
        "District": {"value": "NO", "confidence": 0},
        "Taluk": {"value": "NO", "confidence": 0},
        "Village": {"value": "NO", "confidence": 0},
    }

    if not address_str or not isinstance(address_str, str):
        return result

    clean_addr = address_str.strip()
    result["Address"] = {"value": clean_addr, "confidence": 100}

    # 1. PINCODE (6 digits)
    pin_match = re.search(r"\b([1-9]\d{5})\b", clean_addr)
    pin_code = None
    if pin_match:
        pin_code = pin_match.group(1)
        result["Pincode"] = {"value": pin_code, "confidence": 100}

    pin_info = PIN_CODE_LOOKUP_DATABASE.get(pin_code) if pin_code else None

    # 2. STATE
    for state in INDIAN_STATES:
        if re.search(r"\b" + re.escape(state) + r"\b", clean_addr, re.IGNORECASE):
            result["State"] = {"value": state, "confidence": 100}
            break
    if result["State"]["value"] in [None, "NO", "NULL"] and pin_info and pin_info.get("state"):
        result["State"] = {"value": pin_info["state"], "confidence": 100}

    # 3. DISTRICT
    dist_match = re.search(
        r"\b([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+(?:District|Dist\.?|Dt\.?)\b",
        clean_addr,
        re.IGNORECASE
    )
    if not dist_match:
        dist_match = re.search(
            r"\b(?:District|Dist\.?|Dt\.?)\s*[:.-]?\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)\b",
            clean_addr,
            re.IGNORECASE
        )
    if dist_match:
        raw_dist = dist_match.group(1).strip()
        words = raw_dist.split()
        filtered_words = [w for w in words if w.lower() not in ["the", "of", "in", "from", "state"]]
        if filtered_words:
            result["District"] = {"value": " ".join(filtered_words), "confidence": 100}

    if result["District"]["value"] in [None, "NO", "NULL"] and pin_info and pin_info.get("district"):
        result["District"] = {"value": pin_info["district"], "confidence": 100}

    # 4. TALUK
    taluk_match = re.search(
        r"\b([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+(?:Taluk|Tk\.?|Tehsil|T\.k\.?)\b",
        clean_addr,
        re.IGNORECASE
    )
    if not taluk_match:
        taluk_match = re.search(
            r"\b(?:Taluk|Tk\.?|Tehsil)\s*[:.-]?\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)\b",
            clean_addr,
            re.IGNORECASE
        )
    if taluk_match:
        raw_taluk = taluk_match.group(1).strip()
        words = raw_taluk.split()
        filtered_words = [w for w in words if w.lower() not in ["the", "of", "in", "from", "district", "village"]]
        if filtered_words:
            result["Taluk"] = {"value": " ".join(filtered_words), "confidence": 95}

    if result["Taluk"]["value"] in [None, "NO", "NULL"] and pin_info and pin_info.get("taluk"):
        result["Taluk"] = {"value": pin_info["taluk"], "confidence": 90}

    # 5. VILLAGE
    village_match = re.search(
        r"\b([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+(?:Village|Town|VTC|Panchayat|Gramam)\b",
        clean_addr,
        re.IGNORECASE
    )
    if not village_match:
        village_match = re.search(
            r"\b(?:VTC|Village|Town|Panchayat|Gramam|PO|P\.O)\s*[:.-]?\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)\b",
            clean_addr,
            re.IGNORECASE
        )
    if village_match:
        raw_village = village_match.group(1).strip()
        words = raw_village.split()
        filtered_words = [w for w in words if w.lower() not in ["the", "of", "in", "from", "district", "taluk"]]
        if filtered_words:
            result["Village"] = {"value": " ".join(filtered_words), "confidence": 95}

    if result["Village"]["value"] in [None, "NO", "NULL"] and pin_info and pin_info.get("village"):
        result["Village"] = {"value": pin_info["village"], "confidence": 90}

    return result


SALUTATION_GENDER_MAP: dict[str, str] = {
    "mr.": "Male",
    "mr": "Male",
    "master": "Male",
    "mrs.": "Female",
    "mrs": "Female",
    "ms.": "Female",
    "ms": "Female",
    "miss": "Female",
}

AMBIGUOUS_SALUTATIONS: list[str] = ["dr.", "dr", "prof.", "prof", "rev.", "rev", "er.", "er", "shri", "smt", "smt.", "sir", "madam"]


def infer_gender_from_salutation(
    salutation_val: Optional[str] = None,
    name_val: Optional[str] = None,
    all_extracted: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Infers Gender strictly from explicit title/salutation (e.g. Mr., Master -> Male; Mrs., Ms., Miss -> Female).
    Do NOT infer gender from person's name alone!
    Ambiguous titles (Dr., Prof., Rev., Er., Shri, Smt.) or missing titles return None.
    """
    candidates_to_check: list[str] = []

    if salutation_val:
        candidates_to_check.append(str(salutation_val).strip())

    if all_extracted and isinstance(all_extracted, dict):
        for k in ["Salutation", "Title", "Student Name", "Name", "Father's Name", "Mother's Name"]:
            if k in all_extracted:
                v = all_extracted[k]
                val_str = v.get("value") if isinstance(v, dict) else v
                if val_str and str(val_str).strip():
                    candidates_to_check.append(str(val_str).strip())

    if name_val:
        candidates_to_check.append(str(name_val).strip())

    for text in candidates_to_check:
        if not text:
            continue

        words = text.strip().split()
        if not words:
            continue

        first_word = words[0].lower()
        first_word_clean = first_word.rstrip(".")

        # Check explicit ambiguous titles first — if ambiguous, do NOT infer
        if first_word in AMBIGUOUS_SALUTATIONS or first_word_clean in [a.rstrip(".") for a in AMBIGUOUS_SALUTATIONS]:
            return None

        # Check explicit salutation mapping
        for title_key, gender in SALUTATION_GENDER_MAP.items():
            key_clean = title_key.rstrip(".")
            if first_word == title_key or first_word_clean == key_clean:
                display_title = title_key.title()
                if not display_title.endswith(".") and title_key.endswith("."):
                    display_title += "."
                elif display_title.endswith(".") and not title_key.endswith("."):
                    display_title = display_title.rstrip(".")

                return {
                    "value": gender,
                    "confidence": 95,
                    "source": "Salutation",
                    "rule_applied": f"{display_title} -> {gender}",
                }

    return None









