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
        No hardcoded field rules or hardcoded field names.
        """
        fields_bullet_list = "\n".join([f"- {field}" for field in required_fields])

        # Build dynamic example JSON structure from the actual required fields
        example_json_dict = {}
        for f in required_fields[:3]:
            example_json_dict[f] = {"value": "Sample Value", "confidence": 100}
        example_json_str = json.dumps(example_json_dict, indent=2)

        address_hint = ""
        if document_type == "AADHAAR" or any("address" in f.lower() for f in required_fields):
            address_hint = """
SPECIAL ADDRESS EXTRACTION RULE:
- Extract the COMPLETE English postal address exactly as printed on the document.
- Include: House Number, Street, Area, Village/Town, PO, District, State, PIN Code.
- Do NOT summarize, do NOT translate, do NOT omit any line.
- Return it as a single comma-separated string.
- Example: "3/331, Srinivasa Nagar, Pattanam, VTC: Pattanam, PO: Pattanam, District: Coimbatore, Tamil Nadu - 641016"
"""

        prompt = f"""You are an Admission Document Extraction AI.

Document Type:
{document_type}

Requested Target Fields:
{fields_bullet_list}
{address_hint}
RULES:
1. Extract ONLY the requested target fields listed above.
2. Never return extra fields outside the requested target list.
3. Never guess, assume, or hallucinate values not present in the document.
4. If a requested target field is not present or unavailable in the OCR text, set "value" to null and "confidence" to 0.
5. Return valid JSON ONLY. No markdown wrappers, no extra explanation text.
6. The JSON structure MUST map each requested target field name to an object containing "value" and "confidence" (integer between 0 and 100).

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
        try:
            client = get_mistral_client()
        except ValueError as val_err:
            _log(f"[ERROR] Mistral Client configuration error: {val_err}")
            for f in llm_needed_fields:
                final_extracted[f] = {"value": None, "confidence": 0}
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
                                "You are an Admission Document Extraction AI. "
                                "Return valid JSON containing ONLY requested fields."
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
            _log("[ERROR] LLM Extraction failed after retries. Using fallback null values.")
            for f in llm_needed_fields:
                final_extracted[f] = {"value": None, "confidence": 0}
        else:
            # CRITICAL: Merge LLM-extracted fields into final result
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
        """
        try:
            data = json.loads(raw_json_str)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            return None

        formatted: Dict[str, Any] = {}

        for field in required_fields:
            if field not in data:
                matching_key = next(
                    (k for k in data.keys() if k.lower().strip() == field.lower().strip()),
                    None,
                )
                if matching_key:
                    field_data = data[matching_key]
                else:
                    return None
            else:
                field_data = data[field]

            if isinstance(field_data, dict):
                val = field_data.get("value")
                conf = field_data.get("confidence")

                if val == "null" or val == "None" or val == "":
                    val = None

                try:
                    conf = int(conf) if conf is not None else 0
                    conf = max(0, min(100, conf))
                except (ValueError, TypeError):
                    conf = 0 if val is None else 80

                formatted[field] = {
                    "value": val,
                    "confidence": conf,
                }
            elif field_data is None:
                formatted[field] = {
                    "value": None,
                    "confidence": 0,
                }
            else:
                val_str = str(field_data).strip()
                formatted[field] = {
                    "value": val_str if val_str else None,
                    "confidence": 80 if val_str else 0,
                }

        return formatted