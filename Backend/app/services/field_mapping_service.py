"""
Field Mapping Service
=====================

Adaptive, production-grade field mapping engine bridging AI-extracted document
attributes to arbitrary Excel template column headers uploaded by administrators.

Strategies:
1. Profile Context: Authenticated student session details (Name, Register No, Mobile, Email)
   are strictly injected for identity columns.
2. Direct Match: Exact case-insensitive and punctuation-stripped key matching.
3. Canonical Alias Resolution: Extensive domain registry covering Indian college formats.
4. Fuzzy Semantic Token Matching: RapidFuzz token_sort_ratio for column header variations.
5. Domain Category Matchers: Intelligent resolution for marks, communities, addresses, and IDs.
6. Safe Excel Export: Missing values resolve to None (blank cells), NEVER literal "NO".
"""

import re
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("app.services.field_mapping_service")

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

# Student profile identity fields
PROFILE_HEADER_ALIASES = {
    "student_name": [
        "student name", "name of the student", "name of candidate", "candidate name",
        "applicant name", "name", "student's name", "name of the applicant",
    ],
    "register_number": [
        "register number", "register no", "reg no", "reg. no", "reg. no.", "reg_no",
        "registration number", "registration no", "roll no", "roll number", "roll_no",
        "admission no", "admission number", "adm no", "adm. no", "sno", "s.no",
    ],
    "mobile_number": [
        "mobile number", "mobile no", "mobile", "phone number", "phone no", "phone",
        "contact number", "contact no", "cell", "cell no", "student mobile",
    ],
    "email": [
        "email", "email id", "email address", "e-mail", "e-mail id", "student email",
    ],
}

# Master Synonym & Alias Dictionary
CANONICAL_EXCEL_ALIASES: Dict[str, List[str]] = {
    # Aadhaar Number
    "Aadhaar Number": [
        "aadhaar number", "aadhaar no", "aadhaar card", "aadhaar card number",
        "aadhaar no.", "aadhaar id", "aadhar number", "aadhar no", "aadhar card",
        "aadhar card number", "aadhar", "aadhaar", "uid", "uidai", "aadhaar_number",
    ],
    "Aadhaar Number (without space)": [
        "aadhaar number (without space)", "aadhaar number without space", "aadhaar no without space",
        "aadhar without space", "aadhaar without space",
    ],

    # Community & Caste
    "Community Category": [
        "community category", "community", "caste category", "category", "comm category",
        "social status", "reservation category", "community / category",
    ],
    "Community Name": [
        "community name", "caste name", "caste", "sub caste", "sub-caste", "subcaste",
        "name of the community", "name of the caste", "caste / sub caste",
    ],
    "Community Code": [
        "community code", "caste code", "comm code",
    ],
    "Community Certificate Number": [
        "community certificate number", "community certificate no", "caste certificate number",
        "caste certificate no", "community cert no", "community cert number",
    ],

    # Date of Birth & Gender
    "Date of Birth": [
        "date of birth", "dob", "birth date", "student date of birth",
        "student date of birth(dd.mm.yyyy)", "dob (dd/mm/yyyy)", "d.o.b", "d.o.b.",
    ],
    "Gender": [
        "gender", "sex", "gender (m/f)", "gender(m/f)",
    ],

    # Parents & Family
    "Father's Name": [
        "father's name", "father name", "father", "name of father", "father / guardian name",
        "father/guardian name", "parent name", "name of the parent",
    ],
    "Mother's Name": [
        "mother's name", "mother name", "mother", "name of mother",
    ],
    "Guardian's Name": [
        "guardian's name", "guardian name", "guardian", "name of guardian",
    ],
    "Father's Occupation": [
        "father's occupation", "father occupation", "occupation of father", "parent occupation",
    ],
    "Mother's Occupation": [
        "mother's occupation", "mother occupation", "occupation of mother",
    ],
    "Annual Family Income": [
        "annual family income", "annual income", "family income", "income",
        "parent annual income", "annual family income (in rs)", "total income",
    ],

    # Address & Location
    "Permanent Address": [
        "permanent address", "address", "full address", "residential address",
        "postal address", "communication address", "address for communication",
        "home address", "native address",
    ],
    "Village": [
        "village", "village / town", "village/town", "town", "vtc", "city / village",
    ],
    "Taluk": [
        "taluk", "taluk name", "tehsil", "mandal", "tk",
    ],
    "District": [
        "district", "district name", "dist", "dt",
    ],
    "State": [
        "state", "state name", "province",
    ],
    "Pincode": [
        "pincode", "pin code", "pin", "postal code", "pin number", "postal pin",
    ],

    # Academic: SSLC / 10th
    "SSLC Total Marks": [
        "sslc total marks", "sslc total", "sslc mark", "sslc marks", "10th total",
        "10th marks", "10th mark", "10th total marks", "sslc mark obtained",
    ],
    "SSLC Mark Percentage": [
        "sslc mark percentage", "sslc percentage", "sslc %", "10th percentage",
        "10th %", "sslc percentage (%)", "10th mark percentage",
    ],
    "SSLC Register Number": [
        "sslc register number", "sslc reg no", "10th reg no", "10th register number",
        "sslc roll no", "10th roll no", "sslc registration number",
    ],
    "SSLC Year of Passing": [
        "sslc year of passing", "sslc passing year", "10th year of passing", "sslc year",
    ],

    # Academic: HSC / 12th
    "HSC Total Marks": [
        "hsc total marks", "hsc total", "hsc mark", "hsc marks", "12th total",
        "12th marks", "12th mark", "12th total marks", "+2 total", "+2 marks",
    ],
    "HSC Mark Percentage": [
        "hsc mark percentage", "hsc percentage", "hsc %", "12th percentage",
        "12th %", "hsc percentage (%)", "+2 percentage", "+2 %",
    ],
    "HSC Register Number": [
        "hsc register number", "hsc reg no", "12th reg no", "12th register number",
        "hsc roll no", "12th roll no", "+2 reg no",
    ],
    "HSC Cutoff": [
        "hsc cutoff", "cutoff", "cut off", "cut-off", "cutoff mark", "engineering cutoff",
    ],

    # Transfer Certificate & School
    "EMIS ID": [
        "emis id", "emis no", "emis number", "emis_id", "emis", "student emis id",
    ],
    "Transfer Certificate Number": [
        "transfer certificate number", "transfer certificate no", "tc number",
        "tc no", "tc no.", "t.c. no", "tc_number", "t.c. number",
    ],
    "School Name": [
        "school name", "name of the school", "school last studied", "last studied school",
        "institution name", "name of school",
    ],
    "Date of Leaving": [
        "date of leaving", "leaving date", "tc date", "tc issue date",
    ],

    # Personal & Quotas
    "Blood Group": [
        "blood group", "blood_group", "blood grp",
    ],
    "Nationality": [
        "nationality", "nation",
    ],
    "Religion": [
        "religion", "faith",
    ],
    "First Graduate": [
        "first graduate", "is first graduate", "is the student the first graduate in the family?",
        "first graduate (yes/no)", "fg", "first graduate certificate number",
    ],
    "Special Quota": [
        "did you come under any special admission quota?", "special quota", "admission quota",
    ],
    "Differently Abled": [
        "did you belong to differently abled category?", "differently abled", "physically challenged",
        "ph category", "pwd",
    ],
}


class FieldMappingService:
    """
    Adaptive Semantic Field Mapping Engine.
    """

    def __init__(self):
        # Build inverted alias index for O(1) canonical lookups
        self._alias_to_canonical: Dict[str, str] = {}
        for canonical, aliases in CANONICAL_EXCEL_ALIASES.items():
            self._alias_to_canonical[self._normalize_key(canonical)] = canonical
            for alias in aliases:
                self._alias_to_canonical[self._normalize_key(alias)] = canonical

    @staticmethod
    def _normalize_key(k: str) -> str:
        """Strip non-alphanumeric characters and lowercase."""
        if not k:
            return ""
        return re.sub(r"[^a-z0-9]", "", k.lower().strip())

    def is_profile_header(self, header: str) -> Tuple[bool, Optional[str]]:
        """
        Check if an Excel header represents a login profile field.
        Returns: (is_profile, profile_key) e.g. (True, "student_name")
        """
        norm = self._normalize_key(header)
        for profile_key, aliases in PROFILE_HEADER_ALIASES.items():
            for alias in aliases:
                if norm == self._normalize_key(alias):
                    return True, profile_key
        return False, None

    def find_best_canonical_match(self, header: str) -> Optional[str]:
        """
        Identify the canonical field name for any given Excel header string.
        """
        if not header:
            return None

        norm_header = self._normalize_key(header)

        # 1. Direct match in dictionary
        if norm_header in self._alias_to_canonical:
            return self._alias_to_canonical[norm_header]

        # 2. Fuzzy match against canonical names and aliases
        if HAS_RAPIDFUZZ:
            best_score = 0.0
            best_canonical = None

            for alias_norm, canonical in self._alias_to_canonical.items():
                score = fuzz.token_sort_ratio(norm_header, alias_norm)
                if score > best_score:
                    best_score = score
                    best_canonical = canonical

            if best_score >= 82 and best_canonical:
                return best_canonical

        return None

    def resolve_field_value(
        self,
        excel_header: str,
        extracted_data_pool: Dict[str, Any],
        student_profile: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[Any], int, str]:
        """
        Resolve the value for a single Excel column header from available data.

        Returns:
            (resolved_value, confidence, source_description)
            If not found, resolved_value is None and confidence is 0.
        """
        header_clean = excel_header.strip()

        # Step 1: Check Login Profile Context
        is_profile, profile_key = self.is_profile_header(header_clean)
        if is_profile and student_profile and profile_key in student_profile:
            val = student_profile.get(profile_key)
            if val and str(val).strip() and str(val).strip().lower() not in ["null", "none", "n/a"]:
                return str(val).strip(), 100, "Student Profile"

        from app.utils.field_canonicalizer import (
            is_name_conflict,
            is_number_conflict,
            is_category_conflict,
            is_phone_conflict,
            is_address_conflict,
        )

        def _has_conflict(h: str, candidate: str) -> bool:
            return (
                is_name_conflict(h, candidate)
                or is_number_conflict(h, candidate)
                or is_category_conflict(h, candidate)
                or is_phone_conflict(h, candidate)
                or is_address_conflict(h, candidate)
            )

        # Step 2: Direct match in extracted_data_pool
        for k, v in extracted_data_pool.items():
            if _has_conflict(header_clean, k):
                continue
            if self._normalize_key(k) == self._normalize_key(header_clean):
                val, conf = self._extract_value_and_confidence(v)
                if self._is_valid_value(val) and conf >= 50:
                    return val, conf, "Direct Match"

        # Step 3: Canonical alias resolution
        canonical_target = self.find_best_canonical_match(header_clean)
        if canonical_target:
            # Check if canonical target exists directly in pool
            for k, v in extracted_data_pool.items():
                if _has_conflict(header_clean, k):
                    continue
                canon_k = self.find_best_canonical_match(k) or k
                if _has_conflict(header_clean, canon_k):
                    continue
                if canon_k.lower() == canonical_target.lower():
                    val, conf = self._extract_value_and_confidence(v)
                    if self._is_valid_value(val) and conf >= 50:
                        formatted_val = self._format_special_field(header_clean, val)
                        return formatted_val, conf, f"Canonical Match ({canonical_target})"

        # Step 4: Fuzzy substring matching in pool
        norm_h = self._normalize_key(header_clean)
        for k, v in extracted_data_pool.items():
            if _has_conflict(header_clean, k):
                continue
            if not self._is_boolean_question(header_clean) and self._is_boolean_question(k):
                continue
            if self._is_boolean_question(header_clean) and not self._is_boolean_question(k):
                continue
            norm_k = self._normalize_key(k)
            # Prevent generic word matches like 'name', 'number', 'mark', 'code'
            if norm_h in ["name", "number", "code", "mark", "id", "date"] or norm_k in ["name", "number", "code", "mark", "id", "date"]:
                continue
            if len(norm_h) >= 5 and len(norm_k) >= 5:
                if norm_h in norm_k or norm_k in norm_h:
                    val, conf = self._extract_value_and_confidence(v)
                    if self._is_valid_value(val) and conf >= 60:
                        return val, max(75, conf), "Substring Match"

        # Step 5: Boolean / Yes-No question check
        if self._is_boolean_question(header_clean):
            # If an affirmative value exists
            if canonical_target:
                for k, v in extracted_data_pool.items():
                    if canonical_target.lower() in k.lower():
                        val, conf = self._extract_value_and_confidence(v)
                        if self._is_valid_value(val):
                            return "Yes", 95, "Inferred Boolean"

        # Not found -> Return None, NEVER write literal "NO"
        return None, 0, "Not Found"

    def map_all_excel_headers(
        self,
        excel_headers: List[str],
        extracted_data_pool: Dict[str, Any],
        student_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Map complete list of Excel column headers to extracted attributes.

        Returns:
            Dictionary suitable for UI verification and audit logging:
            {
                "Excel Header": {
                    "value": "...",       # Clean value or None
                    "confidence": 95,
                    "source": "...",
                    "is_profile": False,
                }
            }
        """
        mapping_result: Dict[str, Dict[str, Any]] = {}

        for header in excel_headers:
            header_clean = header.strip()
            if not header_clean:
                continue

            val, conf, src = self.resolve_field_value(
                excel_header=header_clean,
                extracted_data_pool=extracted_data_pool,
                student_profile=student_profile,
            )

            is_prof, _ = self.is_profile_header(header_clean)

            mapping_result[header_clean] = {
                "value": val,
                "confidence": conf,
                "source": src,
                "is_profile": is_prof,
            }

        return mapping_result

    def format_for_excel_write(
        self,
        excel_headers: List[str],
        mapped_fields: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Extract clean write values for openpyxl row updating.
        Values are non-destructive: None represents empty cell, preserving existing cell content.
        """
        write_dict: Dict[str, Any] = {}
        for h in excel_headers:
            item = mapped_fields.get(h)
            if item and item.get("value") is not None:
                val = item["value"]
                # Guard: Never write literal placeholder words
                if str(val).strip().upper() in ["NO", "NULL", "NONE", "N/A", "NOT DETECTED", "NOT FOUND"]:
                    # Check if header itself is a Yes/No question
                    if self._is_boolean_question(h):
                        write_dict[h] = "No"
                    else:
                        write_dict[h] = None
                else:
                    write_dict[h] = val
            else:
                write_dict[h] = None
        return write_dict

    @staticmethod
    def _extract_value_and_confidence(v: Any) -> Tuple[Optional[Any], int]:
        """Safely unpack {value, confidence} or raw scalar value."""
        if v is None:
            return None, 0
        if isinstance(v, dict):
            val = v.get("value")
            conf = v.get("confidence", 85)
            try:
                conf = int(conf)
            except Exception:
                conf = 85
            return val, conf
        return v, 85

    @staticmethod
    def _is_valid_value(val: Any) -> bool:
        """Check if value is meaningful and not a null placeholder."""
        if val is None:
            return False
        val_str = str(val).strip()
        if not val_str:
            return False
        if val_str.upper() in ["NO", "NULL", "NONE", "N/A", "NOT DETECTED", "NOT FOUND", "UNAVAILABLE"]:
            return False
        return True

    @staticmethod
    def _is_boolean_question(header: str) -> bool:
        """Check if header represents a Yes/No question."""
        h_lower = header.lower()
        if any(tag in h_lower for tag in ["yes/no", "(yes/no)", "yes / no"]):
            return True
        if any(h_lower.startswith(p) for p in ["is ", "did ", "whether ", "does "]):
            return True
        if h_lower.endswith("?"):
            return True
        return False

    @staticmethod
    def _format_special_field(header: str, val: Any) -> Any:
        """Special normalization for Aadhaar, Phone, and Dates."""
        if val is None:
            return None

        h_lower = header.lower()
        v_str = str(val).strip()

        # Aadhaar Number (without space)
        if "aadhaar" in h_lower and "without space" in h_lower:
            return re.sub(r"\D", "", v_str)

        # Aadhaar Number (formatted)
        if "aadhaar" in h_lower and "without space" not in h_lower:
            digits = re.sub(r"\D", "", v_str)
            if len(digits) == 12:
                return f"{digits[:4]} {digits[4:8]} {digits[8:]}"

        # Mobile Number (10 digits)
        if "mobile" in h_lower or "phone" in h_lower:
            digits = re.sub(r"\D", "", v_str)
            if len(digits) == 10:
                return digits
            if len(digits) == 12 and digits.startswith("91"):
                return digits[2:]

        return val
