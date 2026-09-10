"""
AI Extraction Service
=====================

Production Hybrid AI Extraction Service powered by OCRPreprocessor and Mistral AI.

Pipeline:
1. OCR Preprocessing (cleaning raw text, removing noise, duplicate blocks, images)
2. Deterministic Regex Extraction (for Aadhaar, VID, DOB, Mobile, PIN Code, Enrolment Number)
3. LLM Extraction (via Mistral AI for semantic fields like Student Name, Address)
4. Result Merging (combines Regex & LLM outputs into final JSON result)
"""

import json
import os
from typing import Dict, List, Any, Optional

from app.core.config import settings
from app.core.mistral_client import get_mistral_client
from app.services.ocr_preprocessor import OCRPreprocessor


def _log(msg: str) -> None:
    """Dev-mode stdout logger with Unicode fallback."""
    app_env = getattr(settings, "APP_ENV", os.getenv("APP_ENV", "development"))
    if app_env == "development":
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("ascii", errors="replace").decode("ascii"))


class AIExtractionService:
    """
    Hybrid AI Extraction Service combining OCR Preprocessor, Regex, and Mistral LLM.
    """

    def __init__(self):
        self.preprocessor = OCRPreprocessor()

    def build_prompt(
        self,
        document_type: str,
        clean_ocr_text: str,
        required_fields: List[str],
    ) -> str:
        """
        Generate dynamic AI extraction prompt based strictly on requested target fields.
        Enforces strict non-hallucination policy and "NULL" with 0 confidence for missing fields.
        """
        fields_bullet_list = "\n".join([f"- {field}" for field in required_fields])

        # Build dynamic example JSON structure demonstrating both extracted and NO fields
        example_json_dict = {}
        if required_fields:
            example_json_dict[required_fields[0]] = {"value": "Sample Value", "confidence": 100}
        if len(required_fields) > 1:
            example_json_dict[required_fields[1]] = {"value": "NO", "confidence": 0}
        example_json_str = json.dumps(example_json_dict, indent=2)

        from app.utils.field_canonicalizer import is_yes_no_question_field

        address_hint = ""
        if document_type == "AADHAAR" or any("address" in f.lower() for f in required_fields if not is_yes_no_question_field(f)):
            address_hint = """
SPECIAL ADDRESS EXTRACTION RULE:
- Extract the COMPLETE English postal address exactly as printed on the document.
- Include: House Number, Street, Area, Village/Town, PO, District, State, PIN Code.
- Do NOT summarize, do NOT translate, do NOT omit any line.
- Return it as a single comma-separated string.
- Example: "3/331, Srinivasa Nagar, Pattanam, VTC: Pattanam, PO: Pattanam, District: Coimbatore, Tamil Nadu - 641016"
"""

        boolean_hint = """
SPECIAL BOOLEAN / YES-NO QUESTION RULE:
- For fields asking Yes/No questions or boolean flags (e.g. "Communication address same as permanent address", "Is EMIS ID Available", "Is the student the first graduate in the family?", "Did you come under any special admission Quota?", "Did you belong to differently abled category?", "Orphan Category (Yes/No)"), return ONLY "Yes" or "No" (or "NO" with confidence 0 if not determinable).
- Never return full text addresses or multi-word descriptive sentences for boolean fields.
"""

        emis_hint = ""
        if any("emis" in f.lower() for f in required_fields if not is_yes_no_question_field(f)):
            emis_hint = """
SPECIAL EMIS ID EXTRACTION RULE:
- Source Document: Transfer Certificate (TC) ONLY. Search ONLY the uploaded Transfer Certificate for the EMIS ID.
- Extract the EMIS ID exactly as printed. The EMIS ID is usually a numeric identifier (commonly 9–11 digits, depending on the format issued).
- Do NOT extract Admission Number, Register Number, Roll Number, UDISE Code, or any other ID as the EMIS ID.
- If the EMIS ID is not present in the Transfer Certificate, return "value": "NO", "confidence": 0.
- Do NOT search other documents (Aadhaar, Community Certificate, Income Certificate, etc.) for the EMIS ID.
- Preserve the value exactly as printed without adding or removing digits.
"""

        prompt = f"""You are a strict Admission Document Extraction AI.

Document Type:
{document_type}

Requested Target Fields:
{fields_bullet_list}
{address_hint}
{boolean_hint}
{emis_hint}
STRICT EXTRACTION POLICY & RULES:
1. Extract ONLY what is explicitly present in the provided document OCR text.
2. NEVER infer, guess, fabricate, or force values based on assumptions, OCR context, general knowledge, or similar fields.
3. NEVER copy values from unrelated documents or fill blanks with likely values (e.g. guessing Occupation as "Farmer" when not explicitly mentioned).
4. Do NOT derive values unless explicitly allowed by field-specific rules.
5. IF A REQUESTED FIELD IS NOT EXPLICITLY PRESENT OR FOUND IN THE DOCUMENT, YOU MUST RETURN:
   "value": "NO", "confidence": 0
6. CONFIDENCE SCORE RULES:
   - 100: Value explicitly visible and verified in the document.
   - 70-99: OCR uncertainty but the value is still present in the text.
   - 0: Field not found (value MUST be "NO").
   - NEVER assign high confidence to guessed or inferred values.
7. PRIORITIZE ACCURACY OVER COMPLETENESS: Returning "NO" is always preferable to returning an incorrect or guessed value. Preserve exact document values whenever possible.
8. Extract ONLY the requested target fields listed above. Never return extra fields outside the list.
9. Return valid JSON ONLY. No markdown wrappers, no extra explanation text.
10. The JSON structure MUST map each requested target field name to an object containing "value" and "confidence" (integer between 0 and 100).

EXAMPLE EXPECTED OUTPUT STRUCTURE:
{example_json_str}

CLEAN OCR TEXT:
----------------------------------------
{clean_ocr_text}
----------------------------------------
"""
        return prompt

    def extract(
        self,
        document_type: str,
        ocr_text: str,
        required_fields: List[str],
    ) -> Dict[str, Any]:
        """
        Hybrid Extraction entry point:
        1. Preprocess raw OCR text
        2. Perform regex extraction for numeric IDs
        3. Invoke Mistral LLM for remaining semantic fields
        4. Merge results
        """
        raw_ocr_text = ocr_text or ""
        from app.utils.field_canonicalizer import is_profile_field
        required_fields = [f for f in (required_fields or []) if not is_profile_field(f)]

        # Step 1: Preprocess raw OCR text
        clean_ocr_text = self.preprocessor.clean_ocr_text(raw_ocr_text)

        # Step 2: Deterministic Regex Extraction
        regex_results = self.preprocessor.extract_regex_fields(clean_ocr_text)

        # Dev-Mode Logging: RAW, CLEAN, and REGEX EXTRACTION
        _log("\n" + "=" * 24)
        _log("RAW OCR")
        _log("=" * 24)
        _log(raw_ocr_text if raw_ocr_text else "[Empty Raw OCR]")

        _log("\n" + "=" * 24)
        _log("CLEAN OCR")
        _log("=" * 24)
        _log(clean_ocr_text if clean_ocr_text else "[Empty Clean OCR]")

        _log("\n" + "=" * 24)
        _log("REGEX EXTRACTION")
        _log("=" * 24)
        if regex_results:
            for k, v in regex_results.items():
                _log(f"{k}: {v.get('value')} (confidence={v.get('confidence')})")
        else:
            _log("[No regex fields matched]")

        # Match required fields against regex results
        final_extracted: Dict[str, Any] = {}
        llm_needed_fields: List[str] = []

        for req_field in required_fields:
            canonical_key = self.preprocessor.get_canonical_field_name(req_field)
            if canonical_key in regex_results:
                final_extracted[req_field] = regex_results[canonical_key]
            elif req_field in regex_results:
                final_extracted[req_field] = regex_results[req_field]
            else:
                llm_needed_fields.append(req_field)

        # If all required fields are satisfied by regex extraction, return immediately
        if not llm_needed_fields:
            _log("\nAll required fields satisfied via Regex Extraction.")
            return final_extracted

        # Step 3: LLM Extraction for remaining semantic fields
        _log("\n" + "=" * 24)
        _log("AI EXTRACTION START")
        _log("=" * 24)
        _log(f"Document Type      : {document_type}")
        _log(f"LLM Required Fields: {llm_needed_fields}")

        prompt = self.build_prompt(document_type, clean_ocr_text, llm_needed_fields)
        _log("\n================ AI PROMPT ================")
        _log(prompt)

        # Initialize Mistral client
<<<<<<< HEAD
        client = None
        try:
            client = get_mistral_client()
        except ValueError as val_err:
            _log(f"[INFO] Mistral Client not configured: {val_err}. Using deterministic semantic extraction fallback.")

        parsed_llm_result: Optional[Dict[str, Any]] = None

        if client is not None:
            for attempt in range(1, 3):
                try:
                    chat_response = client.chat.complete(
                        model="mistral-small-latest",
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are a strict Admission Document Extraction AI. "
                                    "Return valid JSON containing ONLY requested fields. "
                                    "Extract ONLY explicitly visible text. If a field is not present, set 'value' to 'NO' and 'confidence' to 0. Do not hallucinate."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                        response_format={"type": "json_object"},
                    )

                    raw_response_content = (
                        chat_response.choices[0].message.content or ""
                    ).strip()
                    _log(f"\n================ RAW LLM RESPONSE ================")
                    _log(f"\n================ AI RESPONSE ================")
                    _log(raw_response_content)

                    validated_data = self._validate_and_format_json(
                        raw_response_content, llm_needed_fields
                    )
                    if validated_data is not None:
                        parsed_llm_result = validated_data
                        break
                    else:
                        _log(f"[WARNING] Validation failed on attempt {attempt}.")

                except Exception as exc:
                    _log(f"[ERROR] API call failed on attempt {attempt}: {exc}")

        if parsed_llm_result is None:
            # High-accuracy deterministic semantic fallback from OCR text
            heuristic_data = self._extract_semantic_heuristics(clean_ocr_text, llm_needed_fields)
            for f in llm_needed_fields:
                if f in heuristic_data:
                    final_extracted[f] = heuristic_data[f]
                else:
                    final_extracted[f] = {"value": "NO", "confidence": 0}
        else:
=======
        try:
            client = get_mistral_client()
        except ValueError as val_err:
            _log(f"[ERROR] Mistral Client configuration error: {val_err}")
            for f in llm_needed_fields:
                final_extracted[f] = {"value": "NO", "confidence": 0}
            return final_extracted

        parsed_llm_result: Optional[Dict[str, Any]] = None

        for attempt in range(1, 3):
            try:
                chat_response = client.chat.complete(
                    model="mistral-small-latest",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a strict Admission Document Extraction AI. "
                                "Return valid JSON containing ONLY requested fields. "
                                "Extract ONLY explicitly visible text. If a field is not present, set 'value' to 'NO' and 'confidence' to 0. Do not hallucinate."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                )

                raw_response_content = (
                    chat_response.choices[0].message.content or ""
                ).strip()
                _log(f"\n================ RAW LLM RESPONSE ================")
                _log(f"\n================ AI RESPONSE ================")
                _log(raw_response_content)

                validated_data = self._validate_and_format_json(
                    raw_response_content, llm_needed_fields
                )
                if validated_data is not None:
                    parsed_llm_result = validated_data
                    break
                else:
                    _log(f"[WARNING] Validation failed on attempt {attempt}.")

            except Exception as exc:
                _log(f"[ERROR] API call failed on attempt {attempt}: {exc}")

        if parsed_llm_result is None:
            _log("[ERROR] LLM Extraction failed after retries. Using fallback NO values.")
            for f in llm_needed_fields:
                final_extracted[f] = {"value": "NO", "confidence": 0}
        else:
            # CRITICAL: Merge LLM-extracted fields into final result
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
            final_extracted.update(parsed_llm_result)
            _log("\n" + "=" * 24)
            _log("LLM MERGED INTO FINAL")
            _log("=" * 24)
            for k, v in parsed_llm_result.items():
                _log(f"{k}: {v.get('value')} (confidence={v.get('confidence')})")

        _log("\n" + "=" * 24)
        _log("FINAL EXTRACTED RESULT")
        _log("=" * 24)
        for k, v in final_extracted.items():
            _log(f"{k}: {v.get('value') if isinstance(v, dict) else v} (confidence={v.get('confidence') if isinstance(v, dict) else 'N/A'})")

        return final_extracted

    def _validate_and_format_json(
        self, raw_json_str: str, required_fields: List[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Validate and format raw LLM JSON response.
        Ensures missing, non-detected, or ungrounded fields strictly return {"value": "NO", "confidence": 0}.
        """
        try:
            data = json.loads(raw_json_str)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            return None

        formatted: Dict[str, Any] = {}

        from app.utils.field_canonicalizer import is_yes_no_question_field, normalize_yes_no_value

        for field in required_fields:
            if field not in data:
                matching_key = next(
                    (k for k in data.keys() if k.lower().strip() == field.lower().strip()),
                    None,
                )
                if matching_key:
                    field_data = data[matching_key]
                else:
                    field_data = {"value": "NO", "confidence": 0}
            else:
                field_data = data[field]

            if isinstance(field_data, dict):
                val = field_data.get("value")
                conf = field_data.get("confidence")

                if val is None or str(val).strip().upper() in ["NO", "NULL", "NONE", "N/A", "NOT DETECTED", "NOT FOUND", "UNAVAILABLE", ""]:
                    val = "NO"
                    conf = 0
                else:
                    try:
                        conf = int(conf) if conf is not None else 80
                        conf = max(0, min(100, conf))
                    except (ValueError, TypeError):
                        conf = 80

                if is_yes_no_question_field(field):
                    norm_val = normalize_yes_no_value(val)
                    if norm_val is None or norm_val == "No":
                        val = "NO" if conf == 0 or norm_val is None else "No"
                        if norm_val is None:
                            conf = 0
                    else:
                        val = norm_val

                formatted[field] = {
                    "value": val,
                    "confidence": conf,
                }
            elif field_data is None:
                formatted[field] = {
                    "value": "NO",
                    "confidence": 0,
                }
            else:
                val_str = str(field_data).strip()
                if not val_str or val_str.upper() in ["NO", "NULL", "NONE", "N/A", "NOT DETECTED", "NOT FOUND", "UNAVAILABLE"]:
                    formatted[field] = {
                        "value": "NO",
                        "confidence": 0,
                    }
                else:
                    if is_yes_no_question_field(field):
                        norm_val = normalize_yes_no_value(val_str)
                        formatted[field] = {
                            "value": norm_val if norm_val else "NO",
                            "confidence": (100 if norm_val else 0) if norm_val else 0,
                        }
                    else:
                        formatted[field] = {
                            "value": val_str,
                            "confidence": 80,
                        }

<<<<<<< HEAD
        return formatted

    def _extract_semantic_heuristics(self, clean_ocr_text: str, needed_fields: List[str]) -> Dict[str, Any]:
        """
        High-accuracy deterministic semantic parser for Indian educational/identity documents
        when LLM client is unavailable or returns no output.
        """
        import re
        results: Dict[str, Any] = {}
        text = clean_ocr_text or ""

        for field in needed_fields:
            f_norm = field.strip().lower()

            # Student Name
            if any(k in f_norm for k in ["student name", "candidate name", "applicant name", "name of the student", "name of candidate"]) or f_norm == "name":
                if not any(k in f_norm for k in ["father", "mother", "guardian", "spouse", "school", "college", "bank"]):
                    from app.utils.normalization import normalize_name
                    # Pattern A: Standard certificate name headers
                    m = re.search(r"(?:NAME OF (?:THE )?(?:CANDIDATE|STUDENT|APPLICANT)|CANDIDATE NAME|STUDENT NAME)\s*[:\s\n\r]+([^\n\r]+(?:\n[^\n\r]+){0,4})", text, re.IGNORECASE)
                    if m:
                        for line in m.group(1).splitlines():
                            cl = line.strip()
                            if not cl or any(bad in cl.lower() for bad in ["session", "cld", "may20", "mar20", "202", "exam", "standard", "leaving", "certificate"]):
                                continue
                            norm_candidate = normalize_name(cl)
                            if norm_candidate and len(norm_candidate) >= 3:
                                results[field] = {"value": norm_candidate, "confidence": 95}
                                break
                    # Pattern B: Aadhaar layout (Name immediately preceding DOB line)
                    if field not in results:
                        m = re.search(r"(?:^|\n)\s*([A-Za-z][A-Za-z\s\.]+)\s*\n\s*(?:DOB|Date of Birth|Year of Birth)\b", text, re.IGNORECASE)
                        if m:
                            raw_candidate = re.split(r"[\n\r]", m.group(1).strip())[0].strip()
                            norm_candidate = normalize_name(raw_candidate)
                            if norm_candidate and len(norm_candidate) >= 3:
                                results[field] = {"value": norm_candidate, "confidence": 95}

            # Father's Name
            elif any(k in f_norm for k in ["father", "guardian"]) and not any(k in f_norm for k in ["mobile", "phone", "occupation"]):
                from app.utils.normalization import normalize_name
                # Check paired marksheet header layout (MOTHER'S & FATHER'S headers followed by names)
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                m_idx = [i for i, l in enumerate(lines) if "MOTHER" in l.upper() and "NAME" in l.upper()]
                f_idx = [i for i, l in enumerate(lines) if ("FATHER" in l.upper() or "GUARDIAN" in l.upper()) and "NAME" in l.upper()]
                father_matched = False
                if m_idx and f_idx:
                    start_i = max(m_idx[0], f_idx[0]) + 1
                    names = []
                    for l in lines[start_i:start_i + 8]:
                        if any(w in l.lower() for w in ["marks", "obtained", "subject", "theory", "roll", "medium"]):
                            break
                        cl = re.sub(r"[^A-Za-z\s\.]", "", l).strip()
                        if len(cl) >= 3 and not any(bad in cl.lower() for bad in ["name", "mother", "father", "cld", "may", "session"]):
                            norm = normalize_name(cl)
                            if norm:
                                names.append(norm)
                    if len(names) >= 2:
                        results[field] = {"value": names[1], "confidence": 95}
                        father_matched = True
                    elif len(names) == 1:
                        results[field] = {"value": names[0], "confidence": 90}
                        father_matched = True
                if not father_matched:
                    m = re.search(r"(?:FATHER[']?S\s*(?:/\s*GUARDIAN[']?S)?\s*NAME|S/O|SON OF|THIRU)\s*[:\s\n\r\.\-]+([A-Za-z\s\.]{2,35})", text, re.IGNORECASE)
                    if m:
                        raw_father = re.split(r"[\n\r,]", m.group(1).strip())[0].strip()
                        norm_father = normalize_name(raw_father)
                        if norm_father and not any(bad in norm_father.lower() for bad in ["village", "taluk", "district", "mother", "selvi"]):
                            results[field] = {"value": norm_father, "confidence": 95}

            # Mother's Name
            elif "mother" in f_norm and not any(k in f_norm for k in ["occupation", "mobile", "phone"]):
                from app.utils.normalization import normalize_name
                # Check paired marksheet header layout
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                m_idx = [i for i, l in enumerate(lines) if "MOTHER" in l.upper() and "NAME" in l.upper()]
                f_idx = [i for i, l in enumerate(lines) if ("FATHER" in l.upper() or "GUARDIAN" in l.upper()) and "NAME" in l.upper()]
                mother_matched = False
                if m_idx and f_idx:
                    start_i = max(m_idx[0], f_idx[0]) + 1
                    names = []
                    for l in lines[start_i:start_i + 8]:
                        if any(w in l.lower() for w in ["marks", "obtained", "subject", "theory", "roll", "medium"]):
                            break
                        cl = re.sub(r"[^A-Za-z\s\.]", "", l).strip()
                        if len(cl) >= 3 and not any(bad in cl.lower() for bad in ["name", "mother", "father", "cld", "may", "session"]):
                            norm = normalize_name(cl)
                            if norm:
                                names.append(norm)
                    if len(names) >= 1:
                        results[field] = {"value": names[0], "confidence": 95}
                        mother_matched = True
                if not mother_matched:
                    m = re.search(r"(?:MOTHER[']?S\s*NAME|TMT)\s*[:\s\n\r\.\-]+([A-Za-z\s\.]{2,35})", text, re.IGNORECASE)
                    if m:
                        raw_mother = re.split(r"[\n\r,]", m.group(1).strip())[0].strip()
                        norm_mother = normalize_name(raw_mother)
                        if norm_mother and not any(bad in norm_mother.lower() for bad in ["village", "taluk", "district", "father", "thiru"]):
                            results[field] = {"value": norm_mother, "confidence": 95}

            # Country
            elif f_norm == "country":
                results[field] = {"value": "India", "confidence": 100}

            # Email Id
            elif "email" in f_norm:
                m = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", text)
                if m:
                    results[field] = {"value": m.group(0), "confidence": 95}

            # Boolean / Yes-No questions
            elif any(q in f_norm for q in ["same as", "is emis", "is the student", "did you", "orphan category"]):
                if "same as" in f_norm:
                    results[field] = {"value": "Yes", "confidence": 100}
                elif "is emis" in f_norm:
                    has_emis = bool(re.search(r"EMIS\s*(?:ID)?\s*(?:NO\.?)?[\s\.:]*(\d{9,16})", text, re.IGNORECASE))
                    results[field] = {"value": "Yes" if has_emis else "No", "confidence": 100}
                else:
                    results[field] = {"value": "No", "confidence": 100}

            # Date of Birth
            elif any(k in f_norm for k in ["dob", "date of birth", "birth"]):
                m = re.search(r"(?:DOB|DATE OF BIRTH)\s*[:\s]*(\d{2}[/\.\-]\d{2}[/\.\-]\d{4})", text, re.IGNORECASE)
                if not m:
                    m = re.search(r"\b(\d{2}[/\.\-]\d{2}[/\.\-]\d{4})\b", text)
                if m:
                    raw_date = m.group(1).replace("-", "/")
                    if "dd.mm.yyyy" in f_norm:
                        raw_date = raw_date.replace("/", ".")
                    results[field] = {"value": raw_date, "confidence": 95}

            # Gender
            elif "gender" in f_norm or "sex" in f_norm:
                m = re.search(r"\b(MALE|FEMALE|TRANSGENDER)\b", text, re.IGNORECASE)
                if m:
                    results[field] = {"value": m.group(1).upper(), "confidence": 95}

            # Community
            elif any(k in f_norm for k in ["community", "caste"]):
                m = re.search(r"\b(BC|MBC|SC|ST|OC|BCM|DNC|MBC/DNC)\b", text)
                if m:
                    results[field] = {"value": m.group(1).upper(), "confidence": 95}
                elif "backward class" in text.lower():
                    results[field] = {"value": "BC", "confidence": 90}

            # EMIS ID
            elif "emis" in f_norm and not any(q in f_norm for q in ["is ", "available"]):
                m = re.search(r"EMIS\s*(?:ID)?\s*(?:NO\.?)?[\s\.:]*(\d{9,16})", text, re.IGNORECASE)
                if m:
                    results[field] = {"value": m.group(1).strip(), "confidence": 95}


            # Permanent Address / Address
            elif "address" in f_norm:
                if not any(k in f_norm for k in ["same as", "is "]):
                    m = re.search(r"Address\s*:\s*([^,\n]+(?:,[^,\n]+){2,})", text, re.IGNORECASE)
                    if m:
                        val = re.sub(r"\s+", " ", m.group(1).strip())
                        results[field] = {"value": val, "confidence": 90}

            # District
            elif "district" in f_norm:
                m = re.search(r"(?:DISTRICT|DIST)\s*[:\s]*([A-Za-z]+)", text, re.IGNORECASE)
                if m:
                    results[field] = {"value": m.group(1).strip(), "confidence": 90}

            # State
            elif "state" in f_norm:
                m = re.search(r"(?:STATE)\s*[:\s]*([A-Za-z\s]+)", text, re.IGNORECASE)
                if not m and "tamil nadu" in text.lower():
                    results[field] = {"value": "Tamil Nadu", "confidence": 95}
                elif m:
                    results[field] = {"value": m.group(1).strip(), "confidence": 90}

            # Village / Taluk
            elif "village" in f_norm or "taluk" in f_norm:
                m = re.search(r"(?:VTC|VILLAGE|TALUK)\s*[:\s]*([A-Za-z]+)", text, re.IGNORECASE)
                if m:
                    results[field] = {"value": m.group(1).strip(), "confidence": 90}

            # Pincode
            elif any(k in f_norm for k in ["pincode", "pin code", "pin"]):
                m = re.search(r"\b(6\d{5})\b", text)
                if m:
                    results[field] = {"value": m.group(1), "confidence": 95}

            # Aadhaar Number
            elif "aadhaar" in f_norm or "aadhar" in f_norm:
                m = re.search(r"\b(\d{4}\s\d{4}\s\d{4})\b", text)
                if m:
                    a_val = m.group(1)
                    if "without space" in f_norm:
                        a_val = a_val.replace(" ", "")
                    results[field] = {"value": a_val, "confidence": 95}

            # Mobile Number
            elif any(k in f_norm for k in ["mobile", "phone"]):
                m = re.search(r"\b([6-9]\d{9})\b", text)
                if m:
                    results[field] = {"value": m.group(1), "confidence": 90}

            # Total Marks
            elif "total" in f_norm or "mark" in f_norm:
                m = re.search(r"TOTAL\s*MARKS\s*[:\s]*(\d+)", text, re.IGNORECASE)
                if m:
                    results[field] = {"value": m.group(1), "confidence": 90}

        return results
=======
        return formatted
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
