"""
Document-Evidence-Based Yes/No Evaluation Engine
=================================================
Evaluates Yes/No questions and boolean flags strictly based on explicit evidence
present in the student's stored documents.

Allowed Values:
- YES
- NO
- NOT_FOUND

Critical Rule:
- NOT_FOUND must NEVER be converted to NO.
- Never guess or fabricate answers.
- Never infer NO merely because a field is missing.
"""

import re
from typing import Any, Dict, List, Optional, Tuple


YES_NO_CANONICAL_FIELDS: set[str] = {
    "is_emis_id_available",
    "is_first_graduate",
    "special_admission_quota",
    "differently_abled",
    "communication_address_same",
    "orphan_category",
    "is_pwd",
    "is_sports_quota",
    "is_ex_serviceman",
}


def is_yes_no_field(name: Optional[str]) -> bool:
    """
    Check if a canonical field name or raw Excel header expects a YES/NO answer.
    """
    if not name:
        return False
    clean = str(name).strip().lower()
    clean_snake = re.sub(r'[^a-z0-9]+', '_', clean).strip('_')

    if clean_snake in YES_NO_CANONICAL_FIELDS:
        return True

    # Common prefixes / suffixes for boolean questions
    if any(clean.startswith(p) for p in ["is ", "did ", "does ", "whether ", "has "]):
        return True
    if clean.endswith("?"):
        return True
    if any(tag in clean for tag in ["yes/no", "(yes/no)", "yes / no", "[yes/no]"]):
        return True
    if any(phrase in clean for phrase in [
        "same as",
        "first graduate",
        "special admission",
        "differently abled",
        "orphan",
        "disability",
        "physically challenged",
        "handicapped",
    ]):
        return True

    return False


def normalize_yes_no_not_found(val: Any) -> str:
    """
    Strict normalizer for Yes/No/NOT_FOUND answers.
    Guarantees:
    - Positive evidence -> YES
    - Negative evidence -> NO
    - Missing/blank/unresolved -> NOT_FOUND
    - NOT_FOUND is NEVER converted to NO.
    """
    if val is None:
        return "NOT_FOUND"

    val_str = str(val).strip()
    if not val_str:
        return "NOT_FOUND"

    s = val_str.lower()
    if s in [
        "not_found",
        "not found",
        "field_not_found",
        "null",
        "none",
        "n/a",
        "not detected",
        "not_available",
        "not available",
        "review_required",
        "source_document_missing",
        "extraction_failed",
        "unresolved",
        "blank",
        "[blank]",
        "-",
        "--",
    ]:
        return "NOT_FOUND"

    if s in ["yes", "true", "y", "1", "available", "present", "applicable"]:
        return "YES"

    if s in ["no", "false", "n", "0", "not available", "absent", "not applicable", "nil"]:
        return "NO"

    if re.fullmatch(r"yes", s):
        return "YES"
    if re.fullmatch(r"no", s):
        return "NO"

    # Reject narrative sentences or addresses that aren't strict booleans
    return "NOT_FOUND"


def compare_addresses_for_similarity(addr1: Optional[str], addr2: Optional[str]) -> Tuple[bool, bool]:
    """
    Compare two address strings.
    Returns: (is_same, is_conclusive)
    - (True, True) if addresses are conclusively the same
    - (False, True) if addresses are conclusively different
    - (False, False) if comparison is inconclusive / missing data
    """
    if not addr1 or not addr2:
        return False, False

    clean1 = re.sub(r'[^a-z0-9]+', ' ', str(addr1).lower()).strip()
    clean2 = re.sub(r'[^a-z0-9]+', ' ', str(addr2).lower()).strip()

    if not clean1 or not clean2:
        return False, False

    # Exact or near-exact match
    if clean1 == clean2:
        return True, True

    tokens1 = set(clean1.split())
    tokens2 = set(clean2.split())

    if not tokens1 or not tokens2:
        return False, False

    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    jaccard = len(intersection) / len(union) if union else 0.0

    # If overlap >= 0.75, consider same
    if jaccard >= 0.75:
        return True, True

    # Extract pincodes if present
    pins1 = re.findall(r'\b[1-9][0-9]{5}\b', clean1)
    pins2 = re.findall(r'\b[1-9][0-9]{5}\b', clean2)
    if pins1 and pins2:
        if pins1[0] != pins2[0]:
            # Different pincodes -> conclusively different
            return False, True
        elif jaccard >= 0.50:
            # Same pincode and substantial token overlap -> conclusively same
            return True, True

    # If overlap < 0.40 and length is substantial, consider different
    if jaccard < 0.40 and len(tokens1) >= 4 and len(tokens2) >= 4:
        return False, True

    # Inconclusive
    return False, False


def evaluate_evidence_based_yes_no(
    field_key: str,
    raw_val: Any = None,
    document_text: str = "",
    document_type: str = "OTHER",
    all_extracted_fields: Optional[Dict[str, Any]] = None,
    page_number: Optional[int] = 1,
) -> Dict[str, Any]:
    """
    Evaluates Yes/No questions strictly based on document evidence.
    Returns structured answer dict:
    {
        "field": field_key,
        "value": "YES" | "NO" | "NOT_FOUND",
        "confidence": float,
        "evidence": str | None,
        "source_document": document_type,
        "source_page": page_number
    }
    """
    canon_field = re.sub(r'[^a-z0-9]+', '_', field_key.strip().lower()).strip('_')
    doc_text = str(document_text or "").replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    doc_lower = doc_text.lower()
    fields_pool = all_extracted_fields or {}

    # Default result structure
    result = {
        "field": canon_field,
        "value": "NOT_FOUND",
        "confidence": 0.0,
        "evidence": None,
        "source_document": document_type,
        "source_page": page_number,
    }

    # -------------------------------------------------------------------------
    # 1. EMIS ID Available: is_emis_id_available
    # -------------------------------------------------------------------------
    if canon_field == "is_emis_id_available" or "emis" in canon_field:
        # Check explicit negative in document text
        neg_emis = re.search(
            r'\bemis(?:\s*id|\s*no|\s*number)?\s*[:\-]?\s*(nil|no|none|n/a|not\s*applicable|unavailable)\b',
            doc_lower,
        )
        if neg_emis:
            result["value"] = "NO"
            result["confidence"] = 0.98
            start = max(0, neg_emis.start() - 10)
            end = min(len(doc_text), neg_emis.end() + 15)
            result["evidence"] = doc_text[start:end].strip()
            return result

        # Check positive: valid EMIS digits in document text or extracted fields
        pos_emis = re.search(
            r'\bemis(?:\s*id|\s*no|\s*number)?\s*[:\-]?\s*([0-9]{5,16})\b',
            doc_lower,
        )
        if pos_emis:
            result["value"] = "YES"
            result["confidence"] = 0.99
            digits = pos_emis.group(1)
            result["evidence"] = f"EMIS ID: {digits}"
            return result

        # Check pool for valid extracted EMIS ID
        pool_emis = fields_pool.get("emis_id") or fields_pool.get("emis")
        if pool_emis:
            pool_str = str(pool_emis).strip()
            pool_digits = re.sub(r'\D', '', pool_str)
            if len(pool_digits) >= 5 and pool_str.upper() not in ("NOT_AVAILABLE", "NOT_FOUND", "NONE", "NULL"):
                result["value"] = "YES"
                result["confidence"] = 0.99
                result["evidence"] = f"EMIS ID: {pool_str}"
                return result

        # Check raw_val if LLM explicitly extracted Yes/No with grounding or passed EMIS digits
        if raw_val is not None:
            raw_str = str(raw_val).strip()
            raw_digits = re.sub(r'\D', '', raw_str)
            if len(raw_digits) >= 5 and raw_str.upper() not in ("NOT_AVAILABLE", "NOT_FOUND", "NONE", "NULL"):
                result["value"] = "YES"
                result["confidence"] = 0.99
                result["evidence"] = f"EMIS ID: {raw_str}"
                return result

            norm = normalize_yes_no_not_found(raw_val)
            if norm == "YES":
                result["value"] = "YES"
                result["confidence"] = 0.95
                result["evidence"] = "EMIS ID present on document"
                return result
            elif norm == "NO":
                result["value"] = "NO"
                result["confidence"] = 0.95
                result["evidence"] = "EMIS ID explicitly marked unavailable"
                return result

        # Absent without explanation -> NOT_FOUND (never guess NO!)
        return result

    # -------------------------------------------------------------------------
    # 2. First Graduate: is_first_graduate
    # -------------------------------------------------------------------------
    if canon_field == "is_first_graduate" or "first_graduate" in canon_field:
        # Check explicit negative
        neg_fg = re.search(
            r'\bfirst\s*graduate(?:\s*student|\s*family|\s*quota)?\s*[:\-]?\s*(no|false|nil|none|n)\b',
            doc_lower,
        )
        if neg_fg:
            result["value"] = "NO"
            result["confidence"] = 0.98
            start = max(0, neg_fg.start() - 5)
            end = min(len(doc_text), neg_fg.end() + 10)
            result["evidence"] = doc_text[start:end].strip()
            return result

        # Check explicit positive
        pos_fg = re.search(
            r'\bfirst\s*graduate(?:\s*student|\s*family|\s*quota)?\s*[:\-]?\s*(yes|true|y)\b',
            doc_lower,
        )
        if pos_fg:
            result["value"] = "YES"
            result["confidence"] = 0.98
            start = max(0, pos_fg.start() - 5)
            end = min(len(doc_text), pos_fg.end() + 10)
            result["evidence"] = doc_text[start:end].strip()
            return result

        # Check raw_val from AI
        if raw_val is not None:
            norm = normalize_yes_no_not_found(raw_val)
            if norm in ("YES", "NO"):
                result["value"] = norm
                result["confidence"] = 0.95
                result["evidence"] = f"First Graduate: {norm.title()}"
                return result

        # Blank / missing information -> NOT_FOUND
        return result

    # -------------------------------------------------------------------------
    # 3. Differently Abled: differently_abled
    # -------------------------------------------------------------------------
    if canon_field in ("differently_abled", "is_pwd") or "differently_abled" in canon_field:
        neg_da = re.search(
            r'\b(?:differently\s*abled|physically\s*challenged|handicapped|pwd|disability)\s*[:\-]?\s*(no|false|nil|none|n|na|not\s*applicable)\b',
            doc_lower,
        )
        if neg_da:
            result["value"] = "NO"
            result["confidence"] = 0.98
            start = max(0, neg_da.start() - 5)
            end = min(len(doc_text), neg_da.end() + 10)
            result["evidence"] = doc_text[start:end].strip()
            return result

        pos_da = re.search(
            r'\b(?:differently\s*abled|physically\s*challenged|handicapped|pwd|disability)\s*[:\-]?\s*(yes|true|y)\b',
            doc_lower,
        )
        if pos_da:
            result["value"] = "YES"
            result["confidence"] = 0.98
            start = max(0, pos_da.start() - 5)
            end = min(len(doc_text), pos_da.end() + 10)
            result["evidence"] = doc_text[start:end].strip()
            return result

        if raw_val is not None:
            norm = normalize_yes_no_not_found(raw_val)
            if norm in ("YES", "NO"):
                result["value"] = norm
                result["confidence"] = 0.95
                result["evidence"] = f"Differently Abled: {norm.title()}"
                return result

        # No disability information -> NOT_FOUND
        return result

    # -------------------------------------------------------------------------
    # 4. Orphan Category: orphan_category
    # -------------------------------------------------------------------------
    if canon_field == "orphan_category" or "orphan" in canon_field:
        neg_orph = re.search(
            r'\b(?:orphan|destitute)\s*(?:category)?\s*[:\-]?\s*(no|false|nil|none|n|na|not\s*applicable)\b',
            doc_lower,
        )
        if neg_orph:
            result["value"] = "NO"
            result["confidence"] = 0.98
            start = max(0, neg_orph.start() - 5)
            end = min(len(doc_text), neg_orph.end() + 10)
            result["evidence"] = doc_text[start:end].strip()
            return result

        pos_orph = re.search(
            r'\b(?:orphan|destitute)\s*(?:category)?\s*[:\-]?\s*(yes|true|y)\b',
            doc_lower,
        )
        if pos_orph:
            result["value"] = "YES"
            result["confidence"] = 0.98
            start = max(0, pos_orph.start() - 5)
            end = min(len(doc_text), pos_orph.end() + 10)
            result["evidence"] = doc_text[start:end].strip()
            return result

        if raw_val is not None:
            norm = normalize_yes_no_not_found(raw_val)
            if norm in ("YES", "NO"):
                result["value"] = norm
                result["confidence"] = 0.95
                result["evidence"] = f"Orphan: {norm.title()}"
                return result

        # No orphan information -> NOT_FOUND
        return result

    # -------------------------------------------------------------------------
    # 5. Special Admission Quota: special_admission_quota
    # -------------------------------------------------------------------------
    if canon_field == "special_admission_quota" or "special_admission" in canon_field or "special_quota" in canon_field:
        neg_quota = re.search(
            r'\b(?:special\s*admission|special\s*quota)\s*[:\-]?\s*(no|false|nil|none|n|general)\b',
            doc_lower,
        )
        if neg_quota:
            result["value"] = "NO"
            result["confidence"] = 0.95
            result["evidence"] = "Special Admission Quota: No"
            return result

        pos_quota = re.search(
            r'\b(?:special\s*admission|special\s*quota)\s*[:\-]?\s*(yes|true|y|[a-z0-9\s]+quota)\b',
            doc_lower,
        )
        if pos_quota:
            result["value"] = "YES"
            result["confidence"] = 0.95
            result["evidence"] = "Special Admission Quota: Yes"
            return result

        if raw_val is not None:
            norm = normalize_yes_no_not_found(raw_val)
            if norm in ("YES", "NO"):
                result["value"] = norm
                result["confidence"] = 0.95
                result["evidence"] = f"Special Admission Quota: {norm.title()}"
                return result

        return result

    # -------------------------------------------------------------------------
    # 6. Communication Address Same as Permanent Address: communication_address_same
    # -------------------------------------------------------------------------
    if canon_field in ("communication_address_same", "same_as_permanent_address") or "address_same" in canon_field:
        # Check explicit text indication in document
        if any(phrase in doc_lower for phrase in [
            "same as permanent",
            "same as above",
            "communication address: same",
            "communication address : same",
            "address for communication: same",
        ]):
            result["value"] = "YES"
            result["confidence"] = 0.95
            result["evidence"] = "Communication address explicitly marked same as permanent address"
            return result

        # Derived comparison: compare permanent address vs communication address
        perm_addr = (
            fields_pool.get("permanent_address")
            or fields_pool.get("full_address")
            or fields_pool.get("address")
        )
        comm_addr = (
            fields_pool.get("communication_address")
            or fields_pool.get("address_for_communication")
            or fields_pool.get("present_address")
        )

        if perm_addr and comm_addr:
            is_same, is_conclusive = compare_addresses_for_similarity(str(perm_addr), str(comm_addr))
            if is_conclusive:
                if is_same:
                    result["value"] = "YES"
                    result["confidence"] = 0.95
                    result["evidence"] = f"Communication address matches permanent address: {perm_addr}"
                else:
                    result["value"] = "NO"
                    result["confidence"] = 0.95
                    result["evidence"] = f"Communication address differs from permanent address"
                return result

        # Check raw_val if AI compared them directly
        if raw_val is not None:
            norm = normalize_yes_no_not_found(raw_val)
            if norm in ("YES", "NO"):
                result["value"] = norm
                result["confidence"] = 0.92
                result["evidence"] = "AI verified address correspondence"
                return result

        # One or both addresses unavailable / inconclusive -> NOT_FOUND
        return result

    # -------------------------------------------------------------------------
    # 7. General Yes/No Question Field
    # -------------------------------------------------------------------------
    if raw_val is not None:
        norm = normalize_yes_no_not_found(raw_val)
        if norm in ("YES", "NO"):
            result["value"] = norm
            result["confidence"] = 0.90
            result["evidence"] = f"{canon_field}: {norm.title()}"
            return result

    return result
