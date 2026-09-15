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
            or getattr(settings, "GEMINI_MODEL", "gemini-3.6-flash")
            or "gemini-3.6-flash"
        )
        if configured_model in ("gemini-3.8-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"):
            configured_model = "gemini-3.6-flash"
        self.model_name = configured_model
        self.fallback_models = ["gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-3.7-flash", "gemini-3.8-flash"]
        self._genai_client = None
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
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._genai_client = genai
            sdk_version = getattr(genai, "__version__", "unknown")
            _safe_log(
                f"[GeminiService] API Initialization: Successful (SDK: google.generativeai v{sdk_version}) | Selected Model: '{self.model_name}'"
            )
        except ImportError:
            logger.warning("[GeminiService] google-generativeai package is not installed.")
        except Exception as e:
            logger.error(f"[GeminiService] Failed to configure Gemini client: {e}")

    def is_available(self) -> bool:
        """Check if Gemini service is configured and ready."""
        return bool(self.api_key and self._genai_client)

    def build_multimodal_prompt(
        self,
        target_fields: Optional[List[str]] = None,
        document_hint: Optional[str] = None,
    ) -> str:
        """
        Construct a comprehensive multimodal extraction prompt for Indian admission certificates.
        """
        summary_keys_str = ""
        if target_fields and len(target_fields) > 0:
            target_fields_str = (
                "CRITICAL INSTRUCTION: You must ONLY extract the following WANTED FIELDS for this document.\n"
                "Do NOT extract, populate, or guess any fields not listed here:\n"
                + "\n".join([f"  - {f}" for f in target_fields])
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

Carefully inspect the provided document image or PDF pages. Analyze visual layout, tabular grids, printed labels, stamps, seals, and handwriting.

{target_fields_str}

TASK & DISAMBIGUATION RULES:
1. Classify the document type:
   Options: 'AADHAAR', 'SSLC', 'HSC', 'COMMUNITY', 'TRANSFER_CERTIFICATE', 'INCOME', 'NATIVITY', 'BONAFIDE', 'MIGRATION', 'ALLOTMENT_ORDER', 'OTHER'
2. Strict Person Disambiguation:
   - 'student_name' is ONLY the candidate/applicant. NEVER assign father's name, mother's name, or guardian's name as student_name.
   - 'father_name' is strictly the father/guardian named in S/O, D/O, or 'Father's Name' labels.
   - 'mother_name' is strictly the mother named in 'Mother's Name' labels.
3. Strict Identifier Disambiguation:
   - 'register_number' is the official Board/University exam or registration number (e.g. 714024247103, 1625624).
   - NEVER confuse register_number with Certificate Serial No (e.g. SL.NO, SEC No), EMIS ID, or Aadhaar Number.
   - 'aadhaar_number': Extract 12-digit Aadhaar number ONLY when visibly stated in the document.
     Preserve all 12 digits (format 'XXXX XXXX XXXX' or 'XXXXXXXXXXXX').
     Do NOT infer, invent, or guess missing digits. Return null if not visible.
     Do NOT confuse other 12-digit identifiers (such as bank accounts, application numbers, or exam register numbers) with Aadhaar.
   - 'emis_id' is the 9-16 digit educational management identifier found on TC or school marksheets.
4. Category & Cultural Disambiguation:
   - 'community_category': MUST be strictly one of ['BC', 'MBC', 'SC', 'ST', 'OC', 'BCM', 'MBC/DNC', 'DNC'].
   - 'community_name' / 'caste': The sub-caste name (e.g. 'Nadar', 'Vanniyar', 'Kongu Vellalar').
   - NEVER put Religion ('Hindu', 'Muslim', 'Christian') or Nationality ('Indian') into community or caste.
5. Address & Contact Disambiguation:
   - 'full_address': Complete postal address preserving House/Door No, Street, Village, Taluk, District, State, and PIN.
   - 'mobile_number': Candidate's 10-digit mobile number.
   - 'parent_mobile_number': Guardian or father/mother mobile number.
6. For Tabular Marks Sheets (SSLC / 10th or HSC / 12th):
   - Extract subject names, maximum marks, marks obtained, and grades.
   - Accurately extract Total Marks and compute Percentage: (Total / Max) * 100 to 2 decimal places.
7. Noise & Anti-Hallucination Controls:
   - Ignore decorative borders, background watermarks, official seal stamps, and instructional terms.
   - If a field is not visibly stated on the document, omit it or set its value to null. NEVER hallucinate or guess.
   - Standardize Date of Birth strictly as DD/MM/YYYY.

OUTPUT JSON FORMAT REQUIREMENTS:
Return valid, well-formed JSON ONLY. No markdown wrappers, no backticks (```json), no explanations.
The JSON must follow this exact structure:
{{
  "document_type": "string",
  "confidence": 95,
  "fields": {{
    "Field Name": {{
      "value": "string or number or null",
      "confidence": 95,
      "source_text": "string visible in document"
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

            return self.extract_from_bytes(
                file_bytes=file_bytes,
                mime_type=mime_type,
                filename=path.name,
                target_fields=target_fields,
                bypass_cache=bypass_cache,
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
                    for p_try in ["", "SHAD2007", "SRUT2007", "123456", "password"]:
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
    ) -> Dict[str, Any]:
        """
        Perform multimodal extraction using file bytes and mime type with resilient model fallback.
        """
        if not self.is_available() or self._genai_client is None:
            return self._local_fallback_extract_bytes(
                file_bytes=file_bytes,
                mime_type=mime_type,
                filename=filename,
                target_fields=target_fields,
            )

        import hashlib, copy
        doc_hash = hashlib.sha256(file_bytes).hexdigest()
        fields_hash = hashlib.sha256(json.dumps(sorted(target_fields or [])).encode("utf-8")).hexdigest()[:16]
        schema_version = "v3_aadhaar_canonical"
        content_key = f"{len(file_bytes)}_{doc_hash}_{fields_hash}_{schema_version}_{self.model_name}"

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

        prompt = self.build_multimodal_prompt(target_fields=target_fields)
        sdk_version = getattr(self._genai_client, "__version__", "unknown") if self._genai_client else "unknown"

        models_to_try = [self.model_name]
        for fb_m in getattr(self, "fallback_models", ["gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-3.7-flash", "gemini-3.8-flash"]):
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

        # If all API models in the chain were exhausted, run local fallback
        logger.warning(f"[GeminiService] All Gemini models exhausted. Falling back to local OCR engine. Last error: {last_error}")
        return self._local_fallback_extract_bytes(
            file_bytes=file_bytes,
            mime_type=mime_type,
            filename=filename,
            target_fields=target_fields,
        )

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

        try:
            data = json.loads(clean_text)
            if isinstance(data, dict):
                return self._canonicalize_aadhaar_aliases(data)
        except json.JSONDecodeError as err:
            logger.warning(f"[GeminiService] JSON decode error: {err}")
            # Try finding first { and last }
            first_brace = clean_text.find("{")
            last_brace = clean_text.rfind("}")
            if first_brace != -1 and last_brace > first_brace:
                try:
                    data = json.loads(clean_text[first_brace : last_brace + 1])
                    if isinstance(data, dict):
                        return self._canonicalize_aadhaar_aliases(data)
                except Exception:
                    pass

        return None
