"""
Gemini Multimodal AI Extraction Service
========================================

Production-grade document extraction service powered by Google Gemini AI
(Gemini 2.0 Flash / Gemini 1.5 Flash).

Features:
- Native Multimodal Vision: Direct ingestion of PDF and Image documents (preserves
  tabular marks, layout, handwriting, seals, stamps, and signatures).
- Indian Admission Document Intelligence:
    * Aadhaar Card (UID, VID, Name, DOB, Gender, Full Address, Pincode, Care-of/Father)
    * SSLC / 10th Marksheet (Register No, Board, School, Subject-wise marks, Total, %)
    * HSC / 12th Marksheet (Register No, Stream, Subject-wise marks, Total, %, Cutoff)
    * Community Certificate (Category BC/MBC/SC/ST/OC, Caste Name, Certificate No)
    * Transfer Certificate (EMIS ID, TC No, Admission No, School, Leaving Date, Conduct)
    * Income Certificate (Annual Family Income, Certificate No, Date)
    * Nativity / Residence Certificate (Native Place, Taluk, District, State)
- Deterministic JSON Schema enforcement via generation_config.
- Robust exception handling, retries, and fallback to text OCR.
"""

import json
import logging
import os
import re
import time
import threading
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger("app.services.gemini_service")

# Supported document MIME types for Gemini multimodal input
SUPPORTED_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _safe_log(msg: str) -> None:
    """Dev-mode stdout logger with Unicode fallback."""
    if getattr(settings, "APP_ENV", "development") == "development":
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            try:
                print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)
            except Exception:
                pass


class GeminiService:
    """
    Google Gemini Multimodal AI Extraction Service.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = (
            api_key
            or getattr(settings, "GEMINI_API_KEY", None)
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )
        configured_model = (
            model_name
            or getattr(settings, "GEMINI_MODEL", "gemini-flash-lite-latest")
            or "gemini-flash-lite-latest"
        )
        self.model_name = configured_model
        self.fallback_models = [
            "gemini-flash-lite-latest",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash",
            "gemini-flash-latest",
        ]
        self._genai_client = None
        self._genai_package_missing = False
        self._model_cache: Dict[str, Any] = {}
        self._response_cache: Dict[str, Dict[str, Any]] = {}
        self._exhausted_models: Dict[str, float] = {}
        self._cache_lock = threading.Lock()
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize Google Generative AI client if API key is present."""
        if not self.api_key:
            _safe_log("[GeminiService] Warning: GEMINI_API_KEY is not configured.")
            return

        try:
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=FutureWarning)
                import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._genai_client = genai
            sdk_version = getattr(genai, "__version__", "unknown")
            _safe_log(
                f"[GeminiService] API Initialization: Successful (SDK: google.generativeai v{sdk_version}) | Selected Model: '{self.model_name}'"
            )
        except ImportError:
            self._genai_package_missing = True
            logger.error(
                "[GeminiService] CRITICAL: google-generativeai package is NOT installed. "
                "Run: pip install 'google-generativeai>=0.8.0'"
            )
            _safe_log(
                "[GeminiService] CRITICAL: google-generativeai is not installed. "
                "AI extraction is UNAVAILABLE. Install it: pip install 'google-generativeai>=0.8.0'"
            )
        except Exception as e:
            logger.error(f"[GeminiService] Failed to configure Gemini client: {e}")

    def is_available(self) -> bool:
        """Check if Gemini service is configured and ready."""
        return bool(self.api_key and self._genai_client)

    def get_unavailability_reason(self) -> Optional[str]:
        """Return the reason Gemini is unavailable, or None if it is available."""
        if not self.api_key:
            return "GEMINI_API_KEY not configured"
        if getattr(self, '_genai_package_missing', False):
            return "google-generativeai package not installed"
        if not self._genai_client:
            return "Gemini client failed to initialize"
        return None

    def build_multimodal_prompt(
        self,
        target_fields: Optional[List[str]] = None,
        document_hint: Optional[str] = None,
        ocr_text: Optional[str] = None,
    ) -> str:
        """
        Construct a comprehensive multimodal extraction prompt for Indian admission certificates.
        """
        summary_keys_str = ""
        if target_fields and len(target_fields) > 0:
            target_fields_str = (
                "CRITICAL INSTRUCTION: You must ONLY extract the following WANTED FIELDS for this document.\n"
                "Do NOT extract, populate, or guess any fields not listed here:\n"
                + "\n".join([f"- {f}" for f in target_fields])
            )
            summary_lines = []
            has_aadhaar = any("aadhaar" in f.lower() or "aadhar" in f.lower() for f in target_fields)
            seen_keys = set()
            for f in target_fields:
                k = re.sub(r'[^a-z0-9]+', '_', f.lower()).strip('_')
                if k and k not in seen_keys:
                    summary_lines.append(f'    "{k}": "string or null"')
                    seen_keys.add(k)
            if has_aadhaar and "aadhaar_number" not in seen_keys:
                summary_lines.append('    "aadhaar_number": "string or null"')
                seen_keys.add("aadhaar_number")
            summary_keys_str = ",\n".join(summary_lines)
        else:
            target_fields_str = ""
            summary_keys_str = """    "student_name": "string or null",
    "register_number": "string or null",
    "dob": "string or null",
    "gender": "string or null",
    "nationality": "string or null",
    "religion": "string or null",
    "aadhaar_number": "string or null",
    "mobile_number": "string or null",
    "email": "string or null",
    "father_name": "string or null",
    "mother_name": "string or null",
    "full_address": "string or null",
    "village": "string or null",
    "taluk": "string or null",
    "district": "string or null",
    "state": "string or null",
    "pincode": "string or null",
    "community_category": "string or null",
    "community_name": "string or null",
    "annual_income": "string or null",
    "emis_id": "string or null",
    "sslc_total_marks": "string or null",
    "sslc_percentage": "string or null",
    "hsc_total_marks": "string or null",
    "hsc_percentage": "string or null",
    "tc_number": "string or null",
    "school_name": "string or null\""""

        prompt = f"""You are a high-precision, production-grade Admission Document Extraction AI specializing in Indian Educational, Identity, and Government Certificates.

DOCUMENT TYPE: {document_hint or "UNKNOWN"}
REQUESTED FIELDS: {", ".join(target_fields or [])}

Carefully inspect the provided document image or PDF pages. Analyze visual layout, tabular grids, printed labels, stamps, seals, bilingual text (Tamil and English), and handwriting. Use the OCR text below as additional evidence, but verify values against the provided document when possible.

OCR TEXT (may be empty):
{ocr_text or ""}

{target_fields_str}

TASK & DISAMBIGUATION RULES:
1. Classify the document type:
   Options: 'AADHAAR', 'SSLC', 'HSC', 'COMMUNITY', 'TRANSFER_CERTIFICATE', 'INCOME', 'NATIVITY', 'BONAFIDE', 'MIGRATION', 'ALLOTMENT_ORDER', 'BIRTH_CERTIFICATE', 'PASSPORT', 'BANK_PASSBOOK', 'OTHER'
2. Strict Person Disambiguation:
   - 'student_name' is ONLY the candidate/applicant. NEVER assign father's name, mother's name, or guardian's name as student_name.
   - 'father_name' is strictly the father/guardian named in S/O, D/O, or 'Father's Name' labels.
   - 'mother_name' is strictly the mother named in 'Mother's Name' labels.
3. Strict Identifier & Date Disambiguation:
   - 'date_of_birth' / 'dob': Extract the candidate's actual birth date (e.g. from DOB / Date of Birth / பிறந்த தேதி labels). NEVER confuse Certificate Issue Date, TC Date of Leaving, or Admission Date with Date of Birth.
   - 'aadhaar_number': Extract 12-digit Aadhaar number ONLY when visibly stated and explicitly associated with Aadhaar / UIDAI / Mera Aadhaar / ஆதார்.
     Preserve all 12 digits (format 'XXXX XXXX XXXX' or 'XXXXXXXXXXXX').
     If masked (e.g. 'XXXX XXXX 1234'), preserve the masked representation; NEVER invent or guess hidden digits.
     NEVER confuse bank accounts, certificate serial numbers, or exam register numbers with Aadhaar.
   - 'register_number': Official Board/University exam or registration number. NEVER confuse with Certificate Serial No (SL.NO, SEC No), EMIS ID, or Aadhaar.
   - 'emis_id': 9-16 digit educational management identifier found on TC or school marksheets.
4. Category & Cultural Disambiguation:
   - 'community_category': MUST be strictly one of ['BC', 'MBC', 'SC', 'ST', 'OC', 'BCM', 'MBC/DNC', 'DNC'].
   - 'community_name' / 'caste': The sub-caste name (e.g. 'Nadar', 'Vanniyar', 'Kongu Vellalar').
   - NEVER put Religion ('Hindu', 'Muslim', 'Christian') or Nationality ('Indian') into community or caste.
5. Banking & Financial Documents (BANK_PASSBOOK):
   - 'account_number': Candidate's or account holder's primary bank account number (numeric, typically 9 to 18 digits). NEVER confuse with CIF, customer ID, or MICR code.
   - 'ifsc_code': Exact 11-character alphanumeric Indian Financial System Code (e.g. 'KVBL0001234', 'SBIN0000123').
     * Read IFSC exactly from visible text.
     * NEVER confuse account number with IFSC.
     * NEVER infer IFSC from bank name.
     * If IFSC is not explicitly printed or visible, return null.
   - 'bank_name': Official financial institution name (e.g. 'The Karur Vysya Bank Limited', 'State Bank of India', 'Canara Bank').
   - 'bank_branch' / 'branch': Branch location or branch office name.
     * NEVER infer branch from city or vice versa.
   - 'bank_city' / 'city': City where branch is located.
6. Educational & Transfer Certificate (TRANSFER_CERTIFICATE):
   “You are extracting data from an actual Transfer Certificate.
   Inspect the entire document visually, including tables, printed text,
   handwritten/typed values, labels, and all pages.
   For every requested field:
   - find the value next to the correct label
   - do not infer from unrelated fields
   - do not fabricate values
   - return null only when the document genuinely does not contain sufficient evidence.”
   - 'emis_id': Educational Management Information System ID (numeric identifier, e.g. 2015743426). Look for EMIS No. / EMIS ID / இ.எம்.ஐ.எஸ் எண் at top, header, or student details row.
   - 'mother_name': Mother's full name (from 'Name of the Mother' / 'தாய் பெயர்' / 'தாயார் பெயர்').
   - 'father_name': Father's full name (from 'Name of the Father' / 'தந்தை பெயர்' / 'தந்தையார் பெயர்').
   - 'nationality': Pupil's nationality (e.g. 'Indian' / 'INDIAN').
   - 'country': Country of nationality or residence (e.g. 'India' if nationality is Indian / document issued in India).
   - 'salutation': Salutation or title (e.g. 'Selvan', 'Selvi', 'Master', 'Kumari', 'Mr', 'Ms') if explicitly printed, otherwise null.
   - 'student_name': Candidate / Pupil's full name.
   - 'date_of_birth': Date of birth in figures and words (e.g. '07-06-2007').
   - 'gender': Gender (Male / Female).
   - 'admission_number': School admission register number.
   - 'date_of_leaving': Date the student left the institution.
   - For 'is_emis_id_available': Derive strictly from EMIS ID presence. If EMIS ID digits exist, return "YES". If explicitly marked unavailable, return "NO". Otherwise return null.
7. Community Certificate (COMMUNITY):
   - 'community_category': MUST be strictly one of ['BC', 'MBC', 'SC', 'ST', 'OC', 'BCM', 'MBC/DNC', 'DNC'].
   - 'caste' / 'community_name': The specific sub-caste or community name (e.g. 'Vadugar', 'Kallar', 'Nadar').
   - 'father_name': Father's or parent's name.
8. Aadhaar Card (AADHAAR):
   - 'aadhaar_number': 12-digit Aadhaar UID number (e.g. 2122 7377 9295).
   - 'student_name': Name of Aadhaar holder.
   - 'dob' / 'date_of_birth': Date of birth.
   - 'gender': Gender (MALE / FEMALE / TRANSGENDER).
   - 'nationality': Nationality if stated (e.g. Indian).
   - 'permanent_address' / 'address': Full postal address including pincode.
9. Address & Contact Disambiguation:
   - 'full_address' / 'permanent_address': Complete postal address preserving House/Door No, Street, Village, Taluk, District, State, and PIN.
   - 'mobile_number': Candidate's 10-digit mobile number.
10. For Tabular Marks Sheets (SSLC / 10th or HSC / 12th):
   - Maintain Subject -> Mark association. Extract subject names, maximum marks, marks obtained, and grades.
   - Accurately extract Total Marks and compute Percentage: (Total / Max) * 100 to 2 decimal places.
11. Bilingual Tamil + English Documents:
   - Fully read English and Tamil text sections. Do not discard values merely because labels or content are in Tamil.
12. Anti-Hallucination & Missing Values Policy:
   - If a requested field is NOT present in the document, set its value to null.
   - NEVER return "NO" as an extracted value for missing data. Missing data must remain null / unresolved.
   - NEVER fabricate, invent, or guess values.
   - Include the exact grounded text snippet or label in 'evidence' and 'source_text'.
   - Return realistic confidence (0-100) reflecting visual clarity and label-value evidence.
13. Document-Evidence-Based Yes/No Questions Policy:
   - For any question expecting a YES/NO answer (e.g. 'is_first_graduate', 'is_emis_id_available', 'differently_abled', 'orphan_category', 'special_admission_quota', 'communication_address_same'):
     - Return "YES" ONLY if the document contains explicit positive evidence (e.g. 'First Graduate: Yes', valid EMIS ID digits present, or addresses match).
     - Return "NO" ONLY if the document contains explicit negative evidence (e.g. 'First Graduate: No', 'EMIS ID: Nil/No', or addresses clearly differ).
     - If the document does NOT contain enough evidence or the field is blank/absent, set its value to "NOT_FOUND" or null.
     - NEVER return "NO" merely because a field is missing or absent!
     - Include the exact grounded text snippet or label in 'evidence'.

OUTPUT JSON FORMAT REQUIREMENTS:
Return valid, well-formed JSON ONLY. No markdown wrappers, no backticks (```json), no explanations.
The JSON must follow this exact structure:
{{
  "document_type": "string",
  "confidence": 95,
  "fields": {{
    "field_name": {{
      "value": "string or number or null",
      "confidence": 95,
      "evidence": "exact label and snippet from document",
      "source_text": "text visible in document"
    }}
  }},
  "extracted_summary": {{
{summary_keys_str}
  }}
}}
"""
        return prompt

    def extract_from_file(
        self,
        file_path: str,
        target_fields: Optional[List[str]] = None,
        bypass_cache: bool = False,
        document_hint: Optional[str] = None,
        ocr_text: Optional[str] = None,
        student_id: Optional[str] = None,
        document_id: Optional[str] = None,
        document_version: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Perform native multimodal extraction from a PDF or image file on disk.
        """
        if not self.is_available():
            _safe_log("[GeminiService] Client unavailable. Skipping Gemini extraction.")
            return {"success": False, "error": "Gemini API client is not configured."}

        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return {"success": False, "error": f"File not found: {file_path}"}

        ext = path.suffix.lower()
        mime_type = SUPPORTED_MIME_TYPES.get(ext)
        if not mime_type:
            return {
                "success": False,
                "error": f"Unsupported file extension '{ext}'. Supported: {list(SUPPORTED_MIME_TYPES.keys())}",
            }

        try:
            with open(path, "rb") as f:
                file_bytes = f.read()

            effective_mime = mime_type
            if ext == ".pdf" and not file_bytes.startswith(b"%PDF"):
                try:
                    file_bytes.decode("utf-8")
                    effective_mime = "text/plain"
                except Exception:
                    pass

            return self.extract_from_bytes(
                file_bytes=file_bytes,
                mime_type=effective_mime,
                filename=path.name,
                target_fields=target_fields,
                bypass_cache=bypass_cache,
                document_hint=document_hint,
                ocr_text=ocr_text,
                student_id=student_id,
                document_id=document_id,
                document_version=document_version,
            )
        except Exception as exc:
            logger.error(f"[GeminiService] Failed reading {file_path}: {exc}", exc_info=True)
            return {"success": False, "error": str(exc)}

    def _is_quota_exceeded_error(self, exc: Exception) -> bool:
        """Detect HTTP 429 / ResourceExhausted errors from Gemini."""
        exc_type = type(exc).__name__
        if exc_type in ("ResourceExhausted", "TooManyRequests"):
            return True

        status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if status_code == 429:
            return True

        grpc_code = getattr(exc, "grpc_status_code", None)
        if grpc_code and "RESOURCE_EXHAUSTED" in str(grpc_code):
            return True

        msg = str(exc).lower()
        if "resource_exhausted" in msg or "429" in msg or "quota exceeded" in msg or "too many requests" in msg:
            return True

        return False

    def _parse_retry_delay(self, exc: Exception) -> Optional[float]:
        """Parse retry_delay if present from Gemini exception details or message."""
        details = getattr(exc, "details", None)
        if details:
            try:
                for item in details:
                    if hasattr(item, "retry_delay") and hasattr(item.retry_delay, "seconds"):
                        return float(item.retry_delay.seconds)
            except Exception:
                pass

        msg = str(exc)
        m = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", msg, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, TypeError):
                pass

        m = re.search(r"(?:please\s+)?(?:retry|try again)\s*(?:in|after)\s*([0-9.]+)\s*(?:s|sec|seconds)?", msg, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, TypeError):
                pass

        if hasattr(exc, "response") and getattr(exc.response, "headers", None):
            retry_after = exc.response.headers.get("retry-after")
            if retry_after:
                try:
                    return float(retry_after)
                except (ValueError, TypeError):
                    pass

        return None

    def _classify_429_error(self, exc: Exception) -> tuple[bool, bool, Optional[float]]:
        """
        Classify Gemini 429 errors into transient vs quota-exhausted.
        Returns: (is_429, is_transient, retry_delay)
        """
        if not self._is_quota_exceeded_error(exc):
            return False, False, None

        msg = str(exc).lower()
        retry_delay = self._parse_retry_delay(exc)

        # Explicit indicators of quota exhaustion
        is_exhausted = (
            "quota exceeded" in msg
            or "daily" in msg
            or "exhausted" in msg
            or "per day" in msg
            or (retry_delay is not None and retry_delay > 10.0)
        )
        if is_exhausted:
            return True, False, retry_delay

        if retry_delay is not None and retry_delay <= 10.0:
            return True, True, retry_delay

        if "rate limit" in msg or "rate-limit" in msg or "too many requests" in msg:
            return True, True, retry_delay or 5.0

        return True, False, retry_delay

    def _filter_hallucinated_fields(
        self,
        fields_dict: Dict[str, Any],
        grounding_text: str,
    ) -> Dict[str, Any]:
        """
        Requirement 13: Hallucination Protection.
        Every accepted AI value must be grounded in OCR/document evidence.
        If Gemini returns a value that cannot be located or semantically supported by the source document:
        REJECT IT.
        """
        if not grounding_text or not fields_dict:
            return fields_dict

        # If grounding text is empty or negligible (< 10 chars),
        # do not reject multimodal visual extractions since Gemini directly inspected the document image/PDF.
        if len(grounding_text.strip()) < 10:
            return fields_dict

        grounding_clean = re.sub(r'[\s\xa0\u200b\ufeff\r\n\t]+', ' ', grounding_text).lower()
        grounding_digits = re.sub(r'\D', '', grounding_clean)

        validated_fields: Dict[str, Any] = {}

        for k, v in fields_dict.items():
            val = v.get("value") if isinstance(v, dict) else v
            if val is None:
                continue

            val_str = str(val).strip()
            if not val_str or val_str.upper() in ["NO", "NULL", "NONE", "N/A", "NOT DETECTED", "NOT FOUND"]:
                validated_fields[k] = v
                continue

            # Inferred booleans
            if val_str.lower() in ["yes", "no", "true", "false"]:
                validated_fields[k] = v
                continue

            # Numbers / Identifiers (Reg No, EMIS, Aadhaar, Marks, Pincode)
            digits = re.sub(r'\D', '', val_str)
            if len(digits) >= 5:
                if digits in grounding_digits:
                    validated_fields[k] = v
                elif len(digits) == 12 and ("aadhaar" in k.lower() or "aadhar" in k.lower()):
                    if digits[:8] in grounding_digits or digits[4:] in grounding_digits or digits[:4] in grounding_digits:
                        validated_fields[k] = v
                    else:
                        logger.warning(f"[Hallucination Guard] Rejected ungrounded identifier for '{k}': '{val_str}'")
                        continue
                else:
                    logger.warning(f"[Hallucination Guard] Rejected ungrounded identifier for '{k}': '{val_str}'")
                    continue
                continue

            # Text / Names / States
            val_clean = re.sub(r'[^\w\s]', '', val_str).lower().strip()
            if val_clean in grounding_clean:
                validated_fields[k] = v
                continue

            tokens = [t for t in val_clean.split() if len(t) >= 3 and t not in ["the", "and", "for", "with", "from", "state", "district"]]
            if not tokens:
                if re.search(r'\b' + re.escape(val_clean) + r'\b', grounding_clean):
                    validated_fields[k] = v
                else:
                    logger.warning(f"[Hallucination Guard] Rejected ungrounded token for '{k}': '{val_str}'")
                continue

            found = sum(1 for t in tokens if t in grounding_clean)
            if found / len(tokens) >= 0.5:
                validated_fields[k] = v
            else:
                logger.warning(f"[Hallucination Guard] Rejected ungrounded field '{k}': '{val_str}' ({found}/{len(tokens)} tokens in document)")

        return validated_fields

    def _local_fallback_extract_bytes(
        self,
        file_bytes: bytes,
        mime_type: str,
        filename: str = "document.pdf",
        target_fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Existing local OCR fallback when Gemini is unavailable or quota is exceeded."""
        print("\n========== GEMINI ==========", flush=True)
        print(f"Gemini Started: {filename} (MIME: {mime_type}, {len(file_bytes)} bytes)", flush=True)
        print(f"Model: {self.model_name}", flush=True)
        print(f"Gemini Client: Local Resilient Mode (GEMINI_API_KEY unconfigured or offline)", flush=True)

        extracted_text = ""
        try:
            import importlib
            import io, pypdf

            try:
                pil_module = importlib.import_module("PIL.Image")
            except Exception:
                pil_module = None

            try:
                rapidocr_mod = importlib.import_module("rapidocr_onnxruntime")
                RapidOCR = getattr(rapidocr_mod, "RapidOCR", None)
            except Exception:
                RapidOCR = None

            if "pdf" in mime_type.lower():
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                if getattr(reader, "is_encrypted", False):
                    for p_try in ["", "123456", "password"]:
                        try:
                            if reader.decrypt(p_try) != 0:
                                break
                        except Exception:
                            pass
                parts = []
                for page in reader.pages:
                    t = (page.extract_text() or "").strip()
                    if t:
                        parts.append(t)
                    elif RapidOCR and pil_module:
                        try:
                            engine = RapidOCR()
                            for img_obj in page.images:
                                img = pil_module.open(io.BytesIO(img_obj.data))
                                ocr_res, _ = engine(img)
                                if ocr_res:
                                    img_t = "\n".join([r[1] for r in ocr_res]).strip()
                                    if img_t:
                                        parts.append(img_t)
                        except Exception:
                            pass
                extracted_text = "\n\n".join(parts)
            elif RapidOCR and pil_module:
                try:
                    engine = RapidOCR()
                    img = pil_module.open(io.BytesIO(file_bytes))
                    ocr_res, _ = engine(img)
                    if ocr_res:
                        extracted_text = "\n".join([r[1] for r in ocr_res]).strip()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[Gemini Local Fallback] Extraction error: {e}")

        from app.services.document_classifier_service import DocumentClassifierService
        from app.services.ai_extraction_service import AIExtractionService

        classifier = DocumentClassifierService()
        class_res = classifier.classify(extracted_text, filename=filename)
        doc_type = class_res.get("document_type", "STUDENT_DOCUMENT")

        ai_service = AIExtractionService()
        fields_data = ai_service._extract_semantic_heuristics(extracted_text, target_fields or [])

        summary = {}
        for k, v in fields_data.items():
            s_key = k.lower().replace(" ", "_")
            summary[s_key] = v.get("value")

        parsed_data = {
            "success": True if fields_data else False,
            "document_type": doc_type,
            "confidence": 95 if fields_data else 0,
            "fields": fields_data,
            "extracted_summary": summary,
        }

        print(f"Gemini Response: Type={doc_type}, {len(fields_data)} fields extracted (Success: {bool(fields_data)})", flush=True)
        print("============================\n", flush=True)
        return parsed_data

    def _local_fallback_extract_text(
        self,
        ocr_text: str,
        target_fields: Optional[List[str]] = None,
        document_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Existing local OCR text fallback when Gemini is unavailable or quota is exceeded."""
        from app.services.document_classifier_service import DocumentClassifierService
        from app.services.ai_extraction_service import AIExtractionService

        classifier = DocumentClassifierService()
        class_res = classifier.classify(ocr_text)
        doc_type = document_hint or class_res.get("document_type", "STUDENT_DOCUMENT")

        ai_service = AIExtractionService()
        fields_data = ai_service._extract_semantic_heuristics(ocr_text, target_fields or [])

        summary = {}
        for k, v in fields_data.items():
            s_key = k.lower().replace(" ", "_")
            summary[s_key] = v.get("value")

        return {
            "success": True,
            "document_type": doc_type,
            "confidence": 95,
            "fields": fields_data,
            "extracted_summary": summary,
        }

    def extract_from_bytes(
        self,
        file_bytes: bytes,
        mime_type: str,
        filename: str = "document.pdf",
        target_fields: Optional[List[str]] = None,
        bypass_cache: bool = False,
        document_hint: Optional[str] = None,
        ocr_text: Optional[str] = None,
        student_id: Optional[str] = None,
        document_id: Optional[str] = None,
        document_version: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Perform multimodal extraction using file bytes and mime type with resilient model fallback.
        """
        if not self.is_available() or self._genai_client is None:
            reason = self.get_unavailability_reason() or "Gemini client unavailable"
            logger.error(
                f"[GeminiService] AI extraction UNAVAILABLE for '{filename}': {reason}. "
                "Gemini multimodal is required for production extraction."
            )
            _safe_log(f"[GeminiService] AI_EXTRACTION_UNAVAILABLE: {reason}")
            return {
                "success": False,
                "error": f"AI_EXTRACTION_UNAVAILABLE: {reason}",
                "error_type": "GEMINI_UNAVAILABLE",
                "provider": "GEMINI",
                "fields": {},
                "extracted_summary": {},
            }

        import hashlib, copy
        doc_hash = hashlib.sha256(file_bytes).hexdigest()
        fields_hash = hashlib.sha256(json.dumps(sorted(target_fields or [])).encode("utf-8")).hexdigest()[:16]
        schema_version = "v3_aadhaar_canonical"
        clean_stud = (student_id or "anon").strip().upper()
        clean_hint = (document_hint or "hint").strip().upper()
        clean_ver = (document_version or "v1").strip()
        clean_doc_id = (document_id or "doc").strip()
        content_key = f"{clean_stud}_{clean_doc_id}_{clean_ver}_{clean_hint}_{len(file_bytes)}_{doc_hash}_{fields_hash}_{schema_version}_{self.model_name}"

        is_bypass = bypass_cache or getattr(settings, "EXTRACTION_BYPASS_CACHE", False)

        with self._cache_lock:
            if not is_bypass and content_key in self._response_cache:
                print(f"[EXTRACTION_CACHE] document={doc_hash} cache_hit=true", flush=True)
                cached = copy.deepcopy(self._response_cache[content_key])
                cached["timing_metrics"] = {
                    "gemini_ms": 0.1,
                    "gemini_request_ms": 0.0,
                    "gemini_retry_wait_ms": 0.0,
                    "json_parsing_ms": 0.0,
                    "gemini_queue_wait_ms": 0.0,
                    "cache_hit": True,
                }
                return cached
            else:
                print(f"[EXTRACTION_CACHE] document={doc_hash} cache_hit=false", flush=True)

        prompt = self.build_multimodal_prompt(
            target_fields=target_fields,
            document_hint=document_hint,
            ocr_text=ocr_text,
        )
        sdk_version = getattr(self._genai_client, "__version__", "unknown") if self._genai_client else "unknown"

        models_to_try = [self.model_name]
        for fb_m in getattr(self, "fallback_models", ["gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-flash-latest"]):
            if fb_m not in models_to_try:
                models_to_try.append(fb_m)

        # Prioritize fresh models over ones currently in 429 quota cooldown
        now = time.time()
        available_models = [m for m in models_to_try if self._exhausted_models.get(m, 0) <= now]
        cooldown_models = [m for m in models_to_try if self._exhausted_models.get(m, 0) > now]
        ordered_models = available_models if available_models else cooldown_models

        file_part = {
            "mime_type": mime_type,
            "data": file_bytes,
        }

        t_gemini_start = time.perf_counter()
        gemini_retry_wait_ms = 0.0
        gemini_request_ms = 0.0
        json_parsing_ms = 0.0
        last_error = None

        for cur_model in ordered_models:
            print("\n========== GEMINI CALL ==========", flush=True)
            print(f"Document Filename: {filename}", flush=True)
            print(f"MIME Type: {mime_type} ({len(file_bytes)} bytes)", flush=True)
            print(f"Selected Model: {cur_model}", flush=True)
            print(f"SDK Version: google.generativeai v{sdk_version}", flush=True)
            print(f"Request Started: True", flush=True)

            try:
                with self._cache_lock:
                    if cur_model not in self._model_cache:
                        self._model_cache[cur_model] = self._genai_client.GenerativeModel(
                            model_name=cur_model,
                            generation_config={
                                "response_mime_type": "application/json",
                                "temperature": 0.1,
                            },
                        )
                    model_inst = self._model_cache[cur_model]

                response = None
                max_retries = 1
                for attempt in range(max_retries + 1):
                    try:
                        t_req_0 = time.perf_counter()
                        response = model_inst.generate_content([file_part, prompt], request_options={"timeout": 60.0})
                        gemini_request_ms += (time.perf_counter() - t_req_0) * 1000.0
                        break
                    except Exception as exc:
                        is_429, is_transient, retry_delay = self._classify_429_error(exc)
                        if is_429:
                            if is_transient and attempt == 0:
                                wait_time = min(retry_delay or 2.0, 3.0)
                                logger.warning(f"[GeminiService] Transient rate limit on '{cur_model}'. Retrying in {wait_time}s.")
                                gemini_retry_wait_ms += wait_time * 1000.0
                                time.sleep(wait_time)
                                continue
                            else:
                                logger.warning(f"[GeminiService] Model '{cur_model}' hit 429 quota. Trying next fallback model...")
                                with self._cache_lock:
                                    self._exhausted_models[cur_model] = time.time() + 300.0
                                last_error = exc
                                response = None
                                break
                        else:
                            last_error = exc
                            response = None
                            break

                if response is None or not hasattr(response, "text"):
                    print(f"Model '{cur_model}' failed or received 429. Proceeding to next model...", flush=True)
                    continue

                raw_text = (response.text or "").strip()
                print(f"Response Received: True", flush=True)
                print(f"Response Length: {len(raw_text)} chars", flush=True)
                print(f"HTTP/API Status: 200 OK", flush=True)

                t_json_0 = time.perf_counter()
                parsed_data = self._parse_json_response(raw_text)
                json_parsing_ms += (time.perf_counter() - t_json_0) * 1000.0
                json_success = bool(parsed_data)
                print(f"JSON Parsing Succeeded: {json_success}", flush=True)

                if not parsed_data:
                    print(f"Gemini Response: Failed to parse JSON", flush=True)
                    print("=================================\n", flush=True)
                    continue

                # Stage 3 Structured Diagnostic: Inspect critical fields (Zero raw PII logging)
                print("\n========== GEMINI JSON PARSER ==========", flush=True)
                print(f"Inspecting parsed output for: {filename}", flush=True)
                extracted_fields = parsed_data.get("fields", {})
                extracted_summary = parsed_data.get("extracted_summary", {})
                doc_t = parsed_data.get("document_type", "UNKNOWN")
                print(f"Document Type Identified: {doc_t}", flush=True)
                print(f"Total Fields Extracted: {len(extracted_fields)}", flush=True)

                check_fields = [
                    "dob", "gender", "aadhaar_number", "nationality",
                    "community_category", "community_name", "father_name",
                    "mother_name", "full_address", "emis_id"
                ]
                for cf in check_fields:
                    val = extracted_summary.get(cf)
                    if not val:
                        for fk, fv in extracted_fields.items():
                            if cf.replace("_", "") in fk.lower().replace(" ", "").replace("_", ""):
                                val = fv.get("value") if isinstance(fv, dict) else fv
                                break
                    status_str = "FOUND" if val is not None and str(val).strip() else "Not Found"
                    print(f"  * {cf.upper()}: {status_str}", flush=True)
                print("========================================\n", flush=True)

                latency_ms = (time.perf_counter() - t_gemini_start) * 1000.0
                print(
                    f"[GEMINI_EXTRACTION_METRICS] gemini_success=true "
                    f"field_count={len(extracted_fields)} "
                    f"json_valid=true "
                    f"model={cur_model} "
                    f"latency_ms={latency_ms:.2f}",
                    flush=True
                )

                # Hallucination protection only if ground-truth text is available
                doc_text = ""
                try:
                    import io, pypdf
                    if "pdf" in mime_type.lower():
                        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                        for page in reader.pages:
                            doc_text += " " + (page.extract_text() or "")
                except Exception:
                    pass

                if len(doc_text.split()) >= 30 and "fields" in parsed_data:
                    parsed_data["fields"] = self._filter_hallucinated_fields(parsed_data["fields"], doc_text)

                parsed_data["success"] = True
                parsed_data["timing_metrics"] = {
                    "gemini_ms": latency_ms,
                    "gemini_request_ms": gemini_request_ms,
                    "gemini_retry_wait_ms": gemini_retry_wait_ms,
                    "json_parsing_ms": json_parsing_ms,
                    "gemini_queue_wait_ms": 0.0,
                }
                with self._cache_lock:
                    if len(self._response_cache) >= 200:
                        self._response_cache.pop(next(iter(self._response_cache)))
                    self._response_cache[content_key] = copy.deepcopy(parsed_data)

                return parsed_data

            except Exception as exc:
                last_error = exc
                logger.warning(f"[GeminiService] Model '{cur_model}' encountered error: {exc}")
                continue

        # If all API models in the chain were exhausted, determine if it was 429 or another error
        err_str = str(last_error or "").lower()
        is_quota = "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str
        if is_quota:
            logger.warning(
                f"[GeminiService] All Gemini models quota-exhausted (HTTP 429). "
                f"AI_EXTRACTION_UNAVAILABLE. Last error: {last_error}"
            )
            return {
                "success": False,
                "error": f"AI_EXTRACTION_UNAVAILABLE: Gemini API quota exceeded (HTTP 429). Last error: {last_error}",
                "error_type": "QUOTA_EXCEEDED",
                "provider": "GEMINI",
                "retry_after": self._parse_retry_delay(last_error) if last_error else None,
                "fields": {},
                "extracted_summary": {},
            }
        logger.warning(
            f"[GeminiService] All Gemini models failed. AI_EXTRACTION_FAILED. Last error: {last_error}"
        )
        return {
            "success": False,
            "error": f"AI_EXTRACTION_FAILED: All models failed. Last error: {last_error}",
            "error_type": "ALL_MODELS_FAILED",
            "provider": "GEMINI",
            "fields": {},
            "extracted_summary": {},
        }

    def extract_from_text(
        self,
        ocr_text: str,
        target_fields: Optional[List[str]] = None,
        document_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fallback extraction when only OCR text is available.
        """
        if not self.is_available() or self._genai_client is None:
            return self._local_fallback_extract_text(
                ocr_text=ocr_text,
                target_fields=target_fields,
                document_hint=document_hint,
            )

        prompt = self.build_multimodal_prompt(target_fields=target_fields, document_hint=document_hint)
        full_content = f"{prompt}\n\nDOCUMENT OCR TEXT CONTENT:\n----------------------------------------\n{ocr_text}\n----------------------------------------"

        assert self._genai_client is not None

        try:
            model = self._genai_client.GenerativeModel(
                model_name=self.model_name,
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": 0.1,
                },
            )

            max_retries = 3
            response = None
            for attempt in range(max_retries + 1):
                try:
                    response = model.generate_content(full_content, request_options={"timeout": 60.0})
                    break
                except Exception as exc:
                    is_429, is_transient, retry_delay = self._classify_429_error(exc)
                    if is_429:
                        if is_transient and attempt == 0:
                            wait_time = min(retry_delay or 2.0, 3.0)
                            logger.warning(
                                f"[GeminiService] Transient rate limit for model '{self.model_name}'. Brief retry in {wait_time}s."
                            )
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.warning(
                                f"[GeminiService] Quota exhausted (or non-transient 429) for model '{self.model_name}'. Fast-failing immediately to local OCR without blocking."
                            )
                            return self._local_fallback_extract_text(
                                ocr_text=ocr_text,
                                target_fields=target_fields,
                                document_hint=document_hint,
                            )
                    else:
                        logger.error(f"[GeminiService] Text extraction failed: {exc}", exc_info=True)
                        return {"success": False, "error": str(exc)}

            if response is None or not hasattr(response, "text"):
                logger.error("[GeminiService] No response returned from model generate_content for text.")
                return {"success": False, "error": "No response returned from Gemini text extraction."}

            raw_text = (response.text or "").strip()

            parsed_data = self._parse_json_response(raw_text)
            if not parsed_data:
                return {
                    "success": False,
                    "error": "Failed to parse JSON from Gemini text response.",
                    "raw_response": raw_text,
                }

            # Requirement 13: Hallucination Protection
            # Verify groundedness against source OCR text
            if ocr_text.strip() and "fields" in parsed_data:
                parsed_data["fields"] = self._filter_hallucinated_fields(parsed_data["fields"], ocr_text)

            parsed_data["success"] = True
            return parsed_data

        except Exception as exc:
            logger.error(f"[GeminiService] Text extraction failed: {exc}", exc_info=True)
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _canonicalize_aadhaar_aliases(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Section 8: JSON Parser Alias Canonicalization.
        Support possible labels:
        aadhaar_number, aadhaar, aadhaar_no, aadhaar_number_without_space,
        Aadhaar Number, Aadhaar Number (without space), Aadhaar Card, aadhaar_card, aadhar, aadhar_no.
        Canonicalize all valid aliases to: aadhaar_number.
        """
        if not data or not isinstance(data, dict):
            return data

        extracted_fields = data.get("fields")
        if not isinstance(extracted_fields, dict):
            extracted_fields = {}
            data["fields"] = extracted_fields
        extracted_summary = data.get("extracted_summary")
        if not isinstance(extracted_summary, dict):
            extracted_summary = {}
            data["extracted_summary"] = extracted_summary

        aadhaar_val = None
        aadhaar_alias_keys = [
            "aadhaar_number", "aadhaar", "aadhaar_no",
            "aadhaar_number_without_space", "Aadhaar Number",
            "Aadhaar Number (without space)", "aadhaar card", "Aadhaar Card",
            "aadhar", "aadhar_number", "aadhar_no", "aadhaar_card"
        ]
        # 1. Search summary
        for ak in aadhaar_alias_keys:
            if ak in extracted_summary and extracted_summary[ak]:
                sv = str(extracted_summary[ak]).strip()
                if sv and sv.lower() not in ["null", "none", "n/a", ""]:
                    aadhaar_val = sv
                    break
        # 2. Search fields
        if not aadhaar_val:
            for ak in aadhaar_alias_keys:
                if ak in extracted_fields:
                    fv = extracted_fields[ak]
                    val = fv.get("value") if isinstance(fv, dict) else fv
                    if val and str(val).strip().lower() not in ["null", "none", "n/a", ""]:
                        aadhaar_val = str(val).strip()
                        break

        if aadhaar_val:
            from app.utils.normalization import normalize_aadhaar_digits
            norm_aadh = normalize_aadhaar_digits(aadhaar_val)
            if norm_aadh:
                extracted_summary["aadhaar_number"] = norm_aadh
                if "aadhaar_number" not in extracted_fields:
                    extracted_fields["aadhaar_number"] = {
                        "value": norm_aadh,
                        "confidence": 95,
                        "source_text": str(aadhaar_val),
                    }
                else:
                    if isinstance(extracted_fields["aadhaar_number"], dict):
                        extracted_fields["aadhaar_number"]["value"] = norm_aadh
                    else:
                        extracted_fields["aadhaar_number"] = {"value": norm_aadh, "confidence": 95}
                data["fields"] = extracted_fields
                data["extracted_summary"] = extracted_summary

        # EMIS ID canonicalization
        emis_val = None
        emis_alias_keys = [
            "emis_id", "emis", "emis id", "emis_number", "EMIS ID", "EMIS",
            "emis_no", "student_emis_id", "Student EMIS ID"
        ]
        for ek in emis_alias_keys:
            if ek in extracted_summary and extracted_summary[ek]:
                sv = str(extracted_summary[ek]).strip()
                if sv and sv.lower() not in ["null", "none", "n/a", ""]:
                    emis_val = sv
                    break
        if not emis_val:
            for ek in emis_alias_keys:
                if ek in extracted_fields:
                    fv = extracted_fields[ek]
                    val = fv.get("value") if isinstance(fv, dict) else fv
                    if val and str(val).strip().lower() not in ["null", "none", "n/a", ""]:
                        emis_val = str(val).strip()
                        break
        if emis_val:
            m = re.search(r"\d{8,16}", str(emis_val))
            clean_emis = m.group(0) if m else str(emis_val).strip()
            extracted_summary["emis_id"] = clean_emis
            extracted_fields["emis_id"] = {
                "value": clean_emis,
                "confidence": 95,
                "evidence": f"EMIS ID: {clean_emis}",
                "source_text": str(emis_val),
            }
            # Section 5: Derive is_emis_id_available strictly from EMIS ID
            extracted_summary["is_emis_id_available"] = "YES"
            extracted_fields["is_emis_id_available"] = {
                "value": "YES",
                "confidence": 95,
                "evidence": f"EMIS ID {clean_emis} present in document",
                "source_text": clean_emis,
            }

        # Mother Name canonicalization
        mother_val = None
        mother_alias_keys = [
            "mother_name", "mother", "mother's name", "mother_s_name",
            "Mother's Name", "Mother Name", "name_of_mother", "Name of Mother"
        ]
        for mk in mother_alias_keys:
            if mk in extracted_summary and extracted_summary[mk]:
                sv = str(extracted_summary[mk]).strip()
                if sv and sv.lower() not in ["null", "none", "n/a", ""]:
                    mother_val = sv
                    break
        if not mother_val:
            for mk in mother_alias_keys:
                if mk in extracted_fields:
                    fv = extracted_fields[mk]
                    val = fv.get("value") if isinstance(fv, dict) else fv
                    if val and str(val).strip().lower() not in ["null", "none", "n/a", ""]:
                        mother_val = str(val).strip()
                        break
        if mother_val:
            extracted_summary["mother_name"] = mother_val
            extracted_fields["mother_name"] = {
                "value": mother_val,
                "confidence": 95,
                "evidence": f"Mother's Name: {mother_val}",
                "source_text": mother_val,
            }

        # Father Name canonicalization
        father_val = None
        father_alias_keys = [
            "father_name", "father", "father's name", "father_s_name",
            "Father's Name", "Father Name", "name_of_father", "Name of Father"
        ]
        for fk in father_alias_keys:
            if fk in extracted_summary and extracted_summary[fk]:
                sv = str(extracted_summary[fk]).strip()
                if sv and sv.lower() not in ["null", "none", "n/a", ""]:
                    father_val = sv
                    break
        if not father_val:
            for fk in father_alias_keys:
                if fk in extracted_fields:
                    fv = extracted_fields[fk]
                    val = fv.get("value") if isinstance(fv, dict) else fv
                    if val and str(val).strip().lower() not in ["null", "none", "n/a", ""]:
                        father_val = str(val).strip()
                        break
        if father_val:
            extracted_summary["father_name"] = father_val
            extracted_fields["father_name"] = {
                "value": father_val,
                "confidence": 95,
                "evidence": f"Father's Name: {father_val}",
                "source_text": father_val,
            }

        # Nationality & Country canonicalization
        nat_val = None
        for nk in ["nationality", "Nationality", "nationalily"]:
            if nk in extracted_summary and extracted_summary[nk]:
                sv = str(extracted_summary[nk]).strip()
                if sv and sv.lower() not in ["null", "none", "n/a", ""]:
                    nat_val = sv
                    break
            if nk in extracted_fields:
                fv = extracted_fields[nk]
                val = fv.get("value") if isinstance(fv, dict) else fv
                if val and str(val).strip().lower() not in ["null", "none", "n/a", ""]:
                    nat_val = str(val).strip()
                    break
        if nat_val:
            clean_nat = "INDIAN" if "indian" in str(nat_val).lower() else str(nat_val).strip()
            extracted_summary["nationality"] = clean_nat
            extracted_fields["nationality"] = {
                "value": clean_nat,
                "confidence": 95,
                "evidence": f"Nationality: {nat_val}",
                "source_text": str(nat_val),
            }
            if clean_nat == "INDIAN" and "country" not in extracted_summary:
                extracted_summary["country"] = "India"
                extracted_fields["country"] = {
                    "value": "India",
                    "confidence": 95,
                    "evidence": "Derived from Nationality: INDIAN",
                    "source_text": "India",
                }

        # Country canonicalization
        country_val = None
        for ck in ["country", "Country"]:
            if ck in extracted_summary and extracted_summary[ck]:
                sv = str(extracted_summary[ck]).strip()
                if sv and sv.lower() not in ["null", "none", "n/a", ""]:
                    country_val = sv
                    break
            if ck in extracted_fields:
                fv = extracted_fields[ck]
                val = fv.get("value") if isinstance(fv, dict) else fv
                if val and str(val).strip().lower() not in ["null", "none", "n/a", ""]:
                    country_val = str(val).strip()
                    break
        if country_val:
            extracted_summary["country"] = str(country_val).strip()
            extracted_fields["country"] = {
                "value": str(country_val).strip(),
                "confidence": 95,
                "evidence": f"Country: {country_val}",
                "source_text": str(country_val),
            }

        data["fields"] = extracted_fields
        data["extracted_summary"] = extracted_summary
        return data

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Safely parse JSON response, stripping code fences if present."""
        if not text:
            return None

        clean_text = text.strip()
        # Strip markdown ```json ... ``` wrappers if model included them
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r"\s*```$", "", clean_text)
            clean_text = clean_text.strip()

        def normalize_structured_response(data: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(data, dict):
                return None
            fields = data.get("fields", {})
            if isinstance(fields, list):
                normalized_fields: Dict[str, Any] = {}
                for item in fields:
                    if not isinstance(item, dict):
                        continue
                    key = item.get("field") or item.get("name") or item.get("field_name")
                    if key is None:
                        continue
                    normalized_fields[str(key)] = {
                        "value": item.get("value"),
                        "confidence": item.get("confidence", data.get("confidence", 0)),
                        "evidence": item.get("evidence"),
                        "source_text": item.get("source_text"),
                    }
                fields = normalized_fields
            if not isinstance(fields, dict):
                return None
            data["fields"] = fields
            summary = data.get("extracted_summary", {})
            if summary is None:
                summary = {}
            if not isinstance(summary, dict):
                return None
            data["extracted_summary"] = summary
            return self._canonicalize_aadhaar_aliases(data)

        try:
            data = json.loads(clean_text)
            normalized = normalize_structured_response(data)
            if normalized is not None:
                return normalized
        except json.JSONDecodeError as err:
            logger.warning(f"[GeminiService] JSON decode error: {err}")
            # Try finding first { and last }
            first_brace = clean_text.find("{")
            last_brace = clean_text.rfind("}")
            if first_brace != -1 and last_brace > first_brace:
                try:
                    data = json.loads(clean_text[first_brace : last_brace + 1])
                    normalized = normalize_structured_response(data)
                    if normalized is not None:
                        return normalized
                except Exception:
                    pass

        return None

    def classify_document(
        self,
        file_bytes: bytes,
        mime_type: str = "application/pdf",
        filename: str = "",
        allowed_document_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Structured AI Multimodal Document Classification.
        Identifies document type strictly among allowed types, returning confidence and human-readable evidence.
        """
        if not self.is_available() or not file_bytes:
            return {
                "success": False,
                "document_type": "UNKNOWN",
                "confidence": 0.0,
                "evidence": ["Gemini AI unavailable or empty file content"],
            }

        canonical_allowed = allowed_document_types or [
            "AADHAAR",
            "COMMUNITY_CERTIFICATE",
            "INCOME_CERTIFICATE",
            "NATIVITY_CERTIFICATE",
            "SSLC",
            "HSC",
            "TRANSFER_CERTIFICATE",
            "BANK_PASSBOOK",
            "BIRTH_CERTIFICATE",
            "ALLOTMENT_ORDER",
            "BONAFIDE",
        ]
        allowed_list_str = json.dumps(canonical_allowed)

        prompt = f"""You are an expert Indian Educational and Administrative Document Classifier.
Inspect the attached document image/PDF carefully.

ALLOWED DOCUMENT TYPES:
{allowed_list_str}

CRITICAL RULES:
1. Select EXACTLY ONE document type from the ALLOWED DOCUMENT TYPES list, OR choose "UNKNOWN" if it does not clearly match any of them.
2. Consider visual structure, official headers, issuing authority (UIDAI, Revenue Department, Tahsildar, State Board, School/College, Bank), seals, stamps, table layouts, and document number patterns.
3. If a document mentions another document as a secondary reference (for example, a School Transfer Certificate containing "Refer Community Certificate" or an application referencing Aadhaar), the document is the PRIMARY document (Transfer Certificate), NOT the referenced document.
4. Output strict JSON with NO markdown formatting, adhering to this exact schema:
{{
  "document_type": "AADHAAR",
  "confidence": 0.98,
  "evidence": [
    "UIDAI header and Government of India seal present",
    "12-digit Aadhaar UID layout detected",
    "DOB and gender demographic fields visible"
  ]
}}

If uncertain or low quality:
{{
  "document_type": "UNKNOWN",
  "confidence": 0.40,
  "evidence": ["Unrecognized document layout or unreadable content"]
}}
"""

        try:
            cur_model = self.model_name
            with self._cache_lock:
                if cur_model not in self._model_cache:
                    self._model_cache[cur_model] = self._genai_client.GenerativeModel(
                        model_name=cur_model,
                        generation_config={
                            "response_mime_type": "application/json",
                            "temperature": 0.0,
                        },
                    )
                model = self._model_cache[cur_model]

            part = {"mime_type": mime_type, "data": file_bytes}
            response = model.generate_content(
                [part, prompt],
                request_options={"timeout": 60.0},
            )

            raw_text = (response.text or "").strip()
            parsed = self._parse_json_response(raw_text)
            if parsed and isinstance(parsed, dict):
                dt = str(parsed.get("document_type", "UNKNOWN")).strip().upper()
                conf = float(parsed.get("confidence", 0.90))
                evidence = parsed.get("evidence", [])
                if isinstance(evidence, str):
                    evidence = [evidence]
                elif not isinstance(evidence, list):
                    evidence = []

                # Normalize confidence to 0.0 - 1.0 scale
                if conf > 1.0:
                    conf = conf / 100.0

                return {
                    "success": True,
                    "document_type": dt,
                    "confidence": round(conf, 3),
                    "evidence": evidence,
                }
        except Exception as e:
            logger.warning(f"[GeminiService] Multimodal classification error for {filename}: {e}")

        return {
            "success": False,
            "document_type": "UNKNOWN",
            "confidence": 0.0,
            "evidence": [f"Multimodal classification error: {str(e) if 'e' in locals() else 'unknown'}"],
        }

    def invalidate_cache_for_hashes(self, hashes: list[str]) -> int:
        """
        Safely removes response cache entries matching specific document hashes
        without flushing the global cache or affecting other documents/students.
        """
        if not hashes:
            return 0
        cleaned = 0
        with self._cache_lock:
            keys_to_remove = [
                k for k in self._response_cache.keys()
                if any(k.startswith(f"{h}_") or k == h for h in hashes)
            ]
            for k in keys_to_remove:
                self._response_cache.pop(k, None)
                cleaned += 1
        return cleaned
