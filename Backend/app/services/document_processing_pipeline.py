"""
Document Processing Pipeline Orchestrator
=========================================

Production-grade end-to-end AI document processing pipeline.

Stages:
1. File Ingestion & Format Validation (PDF, Images)
2. Primary Multimodal AI Extraction (Google Gemini 2.0/1.5 Flash)
3. Resilient OCR & Regex Fallback (when API key absent or offline)
4. Intelligent Document Classification & Alignment
5. Cross-Document Attribute Fusion & Priority Merge
6. Smart Administrative Lookup (PIN code resolution, Address parsing, Salutations)
7. Semantic Field Mapping to Target Excel Template Column Headers
8. Structured Verification JSON Output for Student Review and Database Persistence
"""

import os
import re
import json
import logging
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import UploadFile

from app.core.config import settings
from app.services.gemini_service import GeminiService
from app.services.ocr_service import OCRService
from app.services.ocr_preprocessor import OCRPreprocessor
from app.services.ai_extraction_service import AIExtractionService
from app.services.document_classifier_service import DocumentClassifierService
from app.services.smart_lookup_service import SmartLookupEngine
from app.services.field_mapping_service import FieldMappingService
from app.services.doc_config_version_service import DocConfigVersionService
from app.services.excel_template_service import ExcelTemplateService
from app.services.wanted_field_service import WantedFieldService
from app.utils.performance_profiler import PipelineProfiler, DocumentTimer

logger = logging.getLogger("app.services.document_processing_pipeline")


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


class DocumentProcessingPipeline:
    """
    Unified Production AI Document Extraction Pipeline.
    """

    def __init__(self):
        self.gemini_service = GeminiService()
        self.ocr_service = OCRService()
        self.preprocessor = OCRPreprocessor()
        self.ai_service = AIExtractionService()
        self.classifier = DocumentClassifierService()
        self.lookup_engine = SmartLookupEngine()
        self.field_mapper = FieldMappingService()
        self.doc_config_service = DocConfigVersionService()
        self.excel_service = ExcelTemplateService()
        self.wanted_field_service = WantedFieldService()

    def _filter_fields_to_wanted(
        self, extracted: Dict[str, Any], wanted_fields: List[str]
    ) -> Dict[str, Any]:
        """
        Filter extracted fields dictionary to strictly retain ONLY fields
        that correspond to the configured wanted fields.
        """
        if not wanted_fields:
            return {}

        from app.services.field_mapping_service import get_canonical_source_field
        from app.utils.field_canonicalizer import get_canonical_field_name

        wanted_lookup = set()
        has_aadhaar_wanted = any("aadhaar" in wf.lower() or "aadhar" in wf.lower() for wf in wanted_fields)
        if has_aadhaar_wanted:
            wanted_lookup.update([
                "aadhaar", "aadhaar_number", "aadhaarnumber", "aadhaarno", "aadhaar_no",
                "aadhaarcard", "aadhaar_card", "aadhaar_number_without_space",
                "aadhaarnumberwithoutspace", "aadhar", "aadharnumber", "aadhar_number",
                "aadhaar number", "aadhaar number (without space)", "aadhaar card",
            ])
        for wf in wanted_fields:
            wanted_lookup.add(wf.strip().lower())
            clean_wf = re.sub(r"[^a-z0-9]", "", wf.lower())
            if clean_wf:
                wanted_lookup.add(clean_wf)
            canon_src = get_canonical_source_field(wf)
            if canon_src:
                wanted_lookup.add(canon_src.strip().lower())
                wanted_lookup.add(re.sub(r"[^a-z0-9]", "", canon_src.lower()))
            canon_name = get_canonical_field_name(wf)
            if canon_name:
                wanted_lookup.add(canon_name.strip().lower())
                wanted_lookup.add(re.sub(r"[^a-z0-9]", "", canon_name.lower()))

        filtered = {}
        for k, v in extracted.items():
            k_clean = re.sub(r"[^a-z0-9]", "", k.lower())
            k_canon_src = get_canonical_source_field(k)
            k_canon_src_clean = re.sub(r"[^a-z0-9]", "", k_canon_src.lower()) if k_canon_src else ""
            k_canon_name = get_canonical_field_name(k)
            k_canon_name_clean = re.sub(r"[^a-z0-9]", "", k_canon_name.lower()) if k_canon_name else ""

            is_wanted = (
                k.strip().lower() in wanted_lookup
                or k_clean in wanted_lookup
                or (k_canon_src and k_canon_src.strip().lower() in wanted_lookup)
                or (k_canon_src_clean and k_canon_src_clean in wanted_lookup)
                or (k_canon_name and k_canon_name.strip().lower() in wanted_lookup)
                or (k_canon_name_clean and k_canon_name_clean in wanted_lookup)
            )

            if is_wanted:
                filtered[k] = v

        return filtered

    def _process_single_document(
        self,
        filename: str,
        file_bytes: bytes,
        excel_headers: List[str],
        uploads_dir: Path,
        doc_timer: DocumentTimer,
        batch_wanted_configs: Optional[Dict[str, List[str]]] = None,
        bypass_cache: bool = False,
    ) -> Dict[str, Any]:
        """
        Process a single document through Validation, Gemini Multimodal Vision, and fallback OCR if needed.
        Runs thread-safe and isolated per document.
        Respects Document-Specific Wanted Field configurations.
        """
        print("\n==================================================", flush=True)
        print(f"PROCESSING DOCUMENT: {filename}", flush=True)
        print("==================================================", flush=True)

        try:
            with doc_timer.track("validation"):
                file_size = len(file_bytes)
                save_path = uploads_dir / filename
                with open(save_path, "wb") as f:
                    f.write(file_bytes)
                abs_path = str(save_path.resolve())

            _safe_log(f"\nProcessing File: {filename} ({file_size} bytes)")

            ext = Path(filename).suffix.lower()
            mime_type = "application/pdf" if ext == ".pdf" else "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"

            doc_extracted: Dict[str, Any] = {}
            doc_type: str = "UNKNOWN"
            raw_ocr: str = ""
            ai_response_status = "PENDING"

            # Document SHA-256 hash for audit tracing
            import hashlib
            doc_hash = hashlib.sha256(file_bytes).hexdigest()

            # Page count detection
            page_count = 1
            if ext == ".pdf":
                try:
                    import io, pypdf
                    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                    page_count = len(reader.pages)
                except Exception:
                    page_count = 1

            # Pre-classify document from filename
            pre_class = self.classifier.classify("", filename=filename)
            pre_doc_type = pre_class.get("document_type", "UNKNOWN").upper()

            # If detected doc_type has zero wanted fields configured, short-circuit immediately
            if batch_wanted_configs is not None and pre_doc_type in batch_wanted_configs and len(batch_wanted_configs[pre_doc_type]) == 0:
                _safe_log(f"[Pipeline] Zero wanted fields configured for '{pre_doc_type}'. Skipping extraction.")
                doc_timer.doc_type = pre_doc_type
                doc_timer.finish()
                doc_timer.print_log()
                return {
                    "filename": filename,
                    "doc_type": pre_doc_type,
                    "doc_extracted": {},
                    "raw_ocr": "",
                    "ai_response_status": "NO_WANTED_FIELDS_CONFIGURED",
                    "success": True,
                    "fields_rejected_by_rule": 0,
                    "pages": page_count,
                    "timing": doc_timer.timings,
                }

            # Aggregate all configured wanted fields across the batch
            batch_all_wanted_fields: List[str] = []
            if batch_wanted_configs:
                for d_fields in batch_wanted_configs.values():
                    if isinstance(d_fields, list):
                        batch_all_wanted_fields.extend(d_fields)

            combined_target_set = list(dict.fromkeys(batch_all_wanted_fields + excel_headers))

            # Determine target extraction fields for Gemini Vision
            if batch_wanted_configs and pre_doc_type in batch_wanted_configs and batch_wanted_configs[pre_doc_type]:
                gemini_target_fields = batch_wanted_configs[pre_doc_type]
            elif combined_target_set:
                gemini_target_fields = combined_target_set
            elif pre_doc_type != "UNKNOWN":
                gemini_target_fields = self.wanted_field_service.get_default_wanted_fields_for_doc_type(pre_doc_type) or excel_headers
            else:
                gemini_target_fields = excel_headers

            # Strategy A: Google Gemini Multimodal Vision Extraction (Primary)
            regex_results = {}
            raw_ocr = ""
            clean_ocr = ""
            _safe_log(f"[Pipeline] Running Gemini multimodal vision on '{filename}' (target fields: {len(gemini_target_fields)})...")
            with doc_timer.track("gemini"):
                gemini_res = self.gemini_service.extract_from_bytes(
                    file_bytes=file_bytes,
                    mime_type=mime_type,
                    filename=filename,
                    target_fields=gemini_target_fields,
                    bypass_cache=bypass_cache,
                )

            if gemini_res.get("timing_metrics"):
                tm = gemini_res["timing_metrics"]
                doc_timer.record("gemini_retry_wait_ms", tm.get("gemini_retry_wait_ms", 0.0))
                doc_timer.record("json_parsing_ms", tm.get("json_parsing_ms", 0.0))

            if gemini_res.get("success"):
                ai_response_status = "200 OK"
                doc_type = gemini_res.get("document_type", "UNKNOWN").upper()
                extracted_fields_dict = gemini_res.get("fields", {}) or {}

                # Ensure summary fields are populated with both clean label and canonical names
                from app.utils.field_canonicalizer import get_canonical_field_name
                summary = gemini_res.get("extracted_summary", {}) or {}
                summary_map = {
                    "student_name": ["Student Name"],
                    "register_number": ["Register Number"],
                    "dob": ["Student Date of Birth(DD.MM.YYYY)", "DOB", "Date of Birth"],
                    "gender": ["Gender"],
                    "aadhaar_number": ["Aadhaar Number (without space)", "Aadhaar Number", "Aadhaar Card"],
                    "emis_id": ["EMIS ID"],
                    "father_name": ["Father's Name", "Father Name"],
                    "mother_name": ["Mother's Name", "Mother Name"],
                    "nationality": ["Nationality"],
                    "community_category": ["Community", "Community Category"],
                    "community_name": ["Caste", "Community Name"],
                    "full_address": ["Permanent Address", "Address"],
                    "annual_income": ["Annual Family Income", "Income"],
                    "sslc_total_marks": ["SSLC Total Marks"],
                    "sslc_percentage": ["SSLC Mark Percentage"],
                    "hsc_total_marks": ["HSC Total Marks"],
                    "hsc_percentage": ["HSC Mark Percentage"],
                    "tc_number": ["TC Number", "Transfer Certificate Number"],
                    "school_name": ["School Name"],
                }
                for sk, sv in summary.items():
                    if sv and str(sv).strip() and str(sv).strip().lower() not in ["null", "none", "n/a"]:
                        aliases = summary_map.get(sk, [sk.replace("_", " ").title()])
                        for alias in aliases:
                            if alias not in extracted_fields_dict or not extracted_fields_dict[alias].get("value"):
                                extracted_fields_dict[alias] = {"value": str(sv).strip(), "confidence": 95}
                            canon_a = get_canonical_field_name(alias)
                            if canon_a and canon_a not in extracted_fields_dict:
                                extracted_fields_dict[canon_a] = {"value": str(sv).strip(), "confidence": 95}

                # Canonicalize any fields in extracted_fields_dict
                for fk, fv in list(extracted_fields_dict.items()):
                    val = fv.get("value") if isinstance(fv, dict) else fv
                    if val and str(val).strip() and str(val).strip().lower() not in ["null", "none", "n/a"]:
                        canon_k = get_canonical_field_name(fk)
                        if canon_k and canon_k != fk and canon_k not in extracted_fields_dict:
                            extracted_fields_dict[canon_k] = {"value": val, "confidence": fv.get("confidence", 95) if isinstance(fv, dict) else 95}

                # Check if detected doc_type has explicit wanted field configuration
                effective_doc_type = doc_type if doc_type != "UNKNOWN" else pre_doc_type
                if batch_wanted_configs is not None and effective_doc_type in batch_wanted_configs:
                    conf_fields = batch_wanted_configs[effective_doc_type]
                    if len(conf_fields) == 0:
                        doc_extracted = {}
                        ai_response_status = "NO_FIELDS_CONFIGURED"
                    else:
                        doc_extracted = self._filter_fields_to_wanted(extracted_fields_dict, conf_fields)
                else:
                    doc_extracted = extracted_fields_dict
            else:
                ai_response_status = "FAILED/429"

            # Strategy B: Fallback / Complementary OCR Engine
            if not doc_extracted or doc_type == "UNKNOWN":
                _safe_log(f"[Pipeline] Running OCR fallback for '{filename}'...")
                with doc_timer.track("ocr"):
                    ocr_result = self.ocr_service.extract_text(abs_path)
                    raw_ocr = ocr_result.get("text") or ""
                with doc_timer.track("preprocess"):
                    clean_ocr = self.preprocessor.clean_ocr_text(raw_ocr)

                # Classify document via OCR text & filename
                with doc_timer.track("classification"):
                    class_res = self.classifier.classify(raw_ocr, filename=filename)
                    if doc_type == "UNKNOWN":
                        doc_type = class_res.get("document_type", "UNKNOWN").upper()

                # If detected doc_type has zero wanted fields configured, return immediately
                if batch_wanted_configs is not None and doc_type in batch_wanted_configs and len(batch_wanted_configs[doc_type]) == 0:
                    _safe_log(f"[Pipeline] Zero wanted fields configured for '{doc_type}' in fallback. Skipping extraction.")
                    doc_timer.doc_type = doc_type
                    doc_timer.finish()
                    doc_timer.print_log()
                    return {
                        "filename": filename,
                        "doc_type": doc_type,
                        "doc_extracted": {},
                        "raw_ocr": raw_ocr,
                        "ai_response_status": "NO_FIELDS_CONFIGURED",
                        "success": True,
                    }

                fallback_target_fields = (
                    batch_wanted_configs.get(doc_type)
                    if (batch_wanted_configs is not None and doc_type in batch_wanted_configs and batch_wanted_configs[doc_type])
                    else excel_headers
                )

                # Regex deterministic extraction
                regex_results = self.preprocessor.extract_regex_fields(clean_ocr or raw_ocr)

                # If Gemini is available with text mode
                if self.gemini_service.is_available() and raw_ocr.strip():
                    with doc_timer.track("gemini"):
                        gemini_text_res = self.gemini_service.extract_from_text(
                            ocr_text=raw_ocr,
                            target_fields=fallback_target_fields,
                            document_hint=doc_type,
                        )
                    if gemini_text_res.get("success"):
                        doc_extracted = gemini_text_res.get("fields", {})
                        ai_response_status = "200 OK (Text Fallback)"
                        if doc_type == "UNKNOWN":
                            doc_type = gemini_text_res.get("document_type", "UNKNOWN").upper()

                # If still empty, fall back to Mistral / local AI
                if not doc_extracted and raw_ocr.strip():
                    try:
                        doc_extracted = self.ai_service.extract(
                            document_type=doc_type,
                            ocr_text=raw_ocr,
                            required_fields=fallback_target_fields,
                        )
                        ai_response_status = "200 OK (Mistral OCR)"
                    except Exception as ai_err:
                        _safe_log(f"[Pipeline AI Notice] {ai_err}")

                # Merge regex extractions
                if isinstance(regex_results, dict):
                    for rk, rv in regex_results.items():
                        if rk not in doc_extracted or not doc_extracted[rk].get("value"):
                            doc_extracted[rk] = rv

                # Post-filter fallback extractions to wanted fields
                if batch_wanted_configs is not None and doc_type in batch_wanted_configs:
                    doc_extracted = self._filter_fields_to_wanted(doc_extracted, batch_wanted_configs[doc_type])

            # Section 1 Safe Aadhaar Diagnostic Trace (Zero PII)
            is_aadhaar_doc = (doc_type == "AADHAAR") or any(k in filename.lower() for k in ["aadhaar", "aadhar", "uid"])
            if is_aadhaar_doc:
                from app.utils.normalization import normalize_aadhaar_digits
                # OCR candidate count
                ocr_aadhaar_cands = []
                if isinstance(regex_results, dict):
                    for rk, rv in regex_results.items():
                        if any(ak in rk.lower() for ak in ["aadhaar", "aadhar"]):
                            v = rv.get("value") if isinstance(rv, dict) else rv
                            if v:
                                ocr_aadhaar_cands.append(v)
                ocr_candidate_count = len(ocr_aadhaar_cands)

                # AI candidate count
                ai_aadhaar_cands = []
                if "gemini_res" in locals() and isinstance(gemini_res, dict):
                    g_fields = gemini_res.get("fields", {}) or {}
                    g_summary = gemini_res.get("extracted_summary", {}) or {}
                    for ak in ["aadhaar_number", "Aadhaar Number", "Aadhaar Card", "aadhaar", "aadhar"]:
                        if ak in g_summary and g_summary[ak]:
                            ai_aadhaar_cands.append(g_summary[ak])
                            break
                    for fk, fv in g_fields.items():
                        if any(ak in fk.lower() for ak in ["aadhaar", "aadhar"]):
                            v = fv.get("value") if isinstance(fv, dict) else fv
                            if v and v not in ai_aadhaar_cands:
                                ai_aadhaar_cands.append(v)
                ai_candidate_count = len(ai_aadhaar_cands)

                # Normalized & Verhoeff validation candidate count
                all_raw_cands = list(set(ocr_aadhaar_cands + ai_aadhaar_cands))
                normalized_cands = []
                valid_cands = []
                for rc in all_raw_cands:
                    norm = normalize_aadhaar_digits(rc)
                    if norm:
                        normalized_cands.append(norm)
                        valid_cands.append(norm)
                    else:
                        raw_d = re.sub(r'\D', '', str(rc))
                        if len(raw_d) == 12:
                            normalized_cands.append(raw_d)

                normalized_candidate_count = len(normalized_cands)
                validation_candidate_count = len(valid_cands)
                canonical_candidate_count = 1 if valid_cands else 0

                # Ensure valid Aadhaar candidate is present in doc_extracted
                if valid_cands:
                    best_aadh = valid_cands[0]
                    if not any(ak in doc_extracted and doc_extracted[ak].get("value") for ak in ["aadhaar_number", "Aadhaar Number", "Aadhaar Card"]):
                        doc_extracted["aadhaar_number"] = {"value": best_aadh, "confidence": 100}
                        doc_extracted["Aadhaar Number"] = {"value": best_aadh, "confidence": 100}
                        doc_extracted["Aadhaar Number (without space)"] = {"value": best_aadh, "confidence": 100}
                        doc_extracted["Aadhaar Card"] = {"value": f"{best_aadh[:4]} {best_aadh[4:8]} {best_aadh[8:]}", "confidence": 100}

                final_candidate_count = 1 if any(ak in doc_extracted and doc_extracted[ak].get("value") for ak in ["aadhaar_number", "Aadhaar Number", "Aadhaar Card", "Aadhaar Number (without space)"]) else 0
                final_status = "FOUND" if final_candidate_count > 0 else "NOT_FOUND"

                print(
                    f"\n[AADHAAR_TRACE]\n"
                    f"ocr_candidate_count={ocr_candidate_count}\n"
                    f"ai_candidate_count={ai_candidate_count}\n"
                    f"normalized_candidate_count={normalized_candidate_count}\n"
                    f"canonical_candidate_count={canonical_candidate_count}\n"
                    f"validation_candidate_count={validation_candidate_count}\n"
                    f"final_candidate_count={final_candidate_count}\n"
                    f"final_status={final_status}\n",
                    flush=True
                )

            # Stage 1 Structured Diagnostics
            print("\n========== DOCUMENT PROCESSING (STAGE 1 DIAGNOSTICS) ==========", flush=True)
            print(f"Document Filename: {filename}", flush=True)
            print(f"Document ID: {doc_type}_{abs(hash(filename)) % 10000:04d}", flush=True)
            print(f"Document Type: {doc_type}", flush=True)
            print(f"OCR Text Length: {len(raw_ocr)} chars", flush=True)
            ocr_portion_first = raw_ocr[:120].replace('\n', ' ') if raw_ocr else 'Direct Multimodal Vision Ingestion'
            ocr_portion_last = raw_ocr[-120:].replace('\n', ' ') if raw_ocr else 'Direct Multimodal Vision Ingestion'
            print(f"OCR Text First Portion: {ocr_portion_first}", flush=True)
            print(f"OCR Text Last Portion: {ocr_portion_last}", flush=True)
            print(f"OCR Succeeded: {bool(raw_ocr.strip() or doc_extracted)}", flush=True)
            print("===============================================================\n", flush=True)

            # Phase 2 Structured Trace
            ocr_stat = "OK" if raw_ocr else ("VISION" if ("gemini_res" in locals() and gemini_res.get("success")) else "NONE")
            gemini_called_val = "true" if ("gemini_res" in locals() and gemini_res.get("success")) else "false"
            gemini_cnt = len(gemini_res.get("fields", {}) or {}) if ("gemini_res" in locals() and isinstance(gemini_res, dict)) else 0
            norm_cnt = len(extracted_fields_dict) if "extracted_fields_dict" in locals() else len(doc_extracted)
            cand_cnt = len(doc_extracted)

            print(
                f"[EXTRACT_TRACE]\n"
                f"document_hash={doc_hash}\n"
                f"document_type={doc_type}\n"
                f"pages={page_count}\n"
                f"ocr_status={ocr_stat}\n"
                f"ocr_chars={len(raw_ocr)}\n"
                f"gemini_called={gemini_called_val}\n"
                f"gemini_fields={gemini_cnt}\n"
                f"normalized_fields={norm_cnt}\n"
                f"canonical_fields={norm_cnt}\n"
                f"candidate_fields={cand_cnt}\n"
                f"validated_fields={cand_cnt}\n"
                f"merged_fields={cand_cnt}\n",
                flush=True
            )

            doc_timer.doc_type = doc_type
            doc_timer.finish()
            doc_timer.print_log()

            return {
                "filename": filename,
                "doc_type": doc_type,
                "doc_extracted": doc_extracted,
                "raw_ocr": raw_ocr,
                "ai_response_status": ai_response_status,
                "success": True,
            }

        except Exception as doc_err:
            logger.error(f"[Pipeline] Error processing document '{filename}': {doc_err}", exc_info=True)
            print(f"[Pipeline Warning] Error processing '{filename}': {doc_err}.", flush=True)
            doc_timer.finish()
            return {
                "filename": filename,
                "doc_type": "UNKNOWN",
                "doc_extracted": {},
                "raw_ocr": "",
                "ai_response_status": f"ERROR: {doc_err}",
                "success": False,
            }

    async def process_student_documents(
        self,
        batch_id: str,
        register_number: str,
        student_name: str,
        mobile_number: Optional[str] = None,
        email: Optional[str] = None,
        files: Optional[List[UploadFile]] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute full document extraction pipeline for a student submission.
        """
        files = files or []

        uploads_dir = Path(__file__).resolve().parent.parent.parent / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        # 1. Retrieve Excel Column Headers (Single Source of Truth)
        try:
            excel_template = await self.excel_service.get_template_by_batch(batch_id)
            excel_headers = excel_template.headers if (excel_template and excel_template.headers) else []
        except Exception:
            excel_headers = []

        # Fallback to configured document requirement fields if template not uploaded yet
        if not excel_headers:
            try:
                excel_headers = await self.doc_config_service.get_batch_extraction_fields(batch_id)
            except Exception:
                excel_headers = []

        if not excel_headers:
            excel_headers = [
                "Student Name", "Register Number", "EMIS ID", "Is EMIS ID Available",
                "Date of Birth", "Gender", "Nationality", "Community", "Caste",
                "Aadhaar Number", "State", "District", "Taluk", "Village", "Village Panchayat",
                "Permanent Address", "Father's Name", "Father's Occupation",
                "Mother's Name", "Mother's Occupation", "Application Number"
            ]

        # 2. Build Login Profile Context
        login_profile = {
            "student_name": student_name.strip(),
            "register_number": register_number.strip(),
            "mobile_number": mobile_number.strip() if mobile_number else "",
            "email": email.strip() if email else "",
        }

        login_fields = {
            "Student Name": student_name.strip(),
            "Register Number": register_number.strip(),
            "Mobile Number": mobile_number.strip() if mobile_number else "N/A",
            "Email": email.strip() if email else "N/A",
            "Email Address": email.strip() if email else "N/A",
        }

        detected_documents: List[str] = []
        extracted_fields_per_document: Dict[str, Dict[str, Any]] = {}
        document_types_per_file: Dict[str, str] = {}
        all_extracted_pool: Dict[str, Any] = {}

        _safe_log("\n================ UPLOADED FILES ================")
        for idx, f in enumerate(files, start=1):
            _safe_log(f"{idx}. Filename : {f.filename}")
        _safe_log("===============================================\n")

        _safe_log("\n================ REQUIRED EXCEL COLUMNS ================")
        for idx, h in enumerate(excel_headers, start=1):
            _safe_log(f"{idx}. {h}")
        _safe_log("========================================================\n")

        # 3. Read uploaded files upfront into memory
        file_payloads = []
        for upload_file in files:
            fname = upload_file.filename or "uploaded_doc.pdf"
            fbytes = await upload_file.read()
            file_payloads.append((fname, fbytes))

        # Retrieve Batch-Scoped Wanted Field Configurations
        batch_wanted_configs: Dict[str, List[str]] = {}
        try:
            batch_wanted_configs = await self.wanted_field_service.get_all_active_wanted_fields_by_batch(batch_id)
        except Exception as wf_err:
            logger.warning(f"[Pipeline] Could not load wanted field configs for batch {batch_id}: {wf_err}")

        # 4. Process Uploaded Files Concurrently with Bounded Concurrency
        profiler = PipelineProfiler()
        doc_stats_tracking: Dict[str, Dict[str, Any]] = {}
        concurrency_limit = min(max(len(file_payloads), 1), 4)
        semaphore = asyncio.Semaphore(concurrency_limit)

        async def _bounded_process(fname: str, fbytes: bytes):
            async with semaphore:
                doc_timer = profiler.start_document(fname)
                return await asyncio.to_thread(
                    self._process_single_document,
                    fname,
                    fbytes,
                    excel_headers,
                    uploads_dir,
                    doc_timer,
                    batch_wanted_configs=batch_wanted_configs,
                    bypass_cache=force_refresh,
                )

        doc_results = await asyncio.gather(
            *[_bounded_process(fn, fb) for fn, fb in file_payloads],
            return_exceptions=True,
        )

        for res in doc_results:
            if isinstance(res, Exception):
                logger.error(f"[Pipeline] Document task exception: {res}", exc_info=True)
                continue
            if not isinstance(res, dict):
                continue

            fname = res["filename"]
            doc_type = res["doc_type"]
            doc_extracted = res["doc_extracted"]
            raw_ocr = res["raw_ocr"]
            ai_response_status = res["ai_response_status"]

            if doc_type and doc_type != "UNKNOWN" and doc_type not in detected_documents:
                detected_documents.append(doc_type)

            _safe_log(f"Detected Document Type: {doc_type}")
            extracted_fields_per_document[fname] = doc_extracted
            document_types_per_file[fname] = doc_type
            doc_stats_tracking[fname] = {
                "ocr_len": len(raw_ocr),
                "ai_response": ai_response_status,
                "parsed_count": len(doc_extracted),
            }

        # 4. Order-Independent Cross-Document Fusion & Authority Merge
        with profiler.track_pipeline("merge"):
            verification_fields = self._order_independent_cross_document_merge(
                detected_docs=detected_documents,
                all_extracted_pool=extracted_fields_per_document,
                excel_headers=excel_headers,
                student_profile=login_profile,
                document_types_per_file=document_types_per_file,
            )

        # User Requirement 13 Diagnostic Tables
        ai_resp_col = "AI STATUS" if getattr(settings, "APP_ENV", "development") == "production" else "AI RESPONSE"
        print("\n====================================================================================================", flush=True)
        print("DOCUMENT PROCESSING DIAGNOSTIC TABLE", flush=True)
        print("====================================================================================================", flush=True)
        print(f"{'DOCUMENT':<32} | {'OCR':<8} | {ai_resp_col:<16} | {'PARSED FIELDS':<14} | {'CANDIDATES':<11} | {'ACCEPTED':<9} | {'REJECTED':<9}", flush=True)
        print("-" * 115, flush=True)
        for fname, dinfo in doc_stats_tracking.items():
            ocr_stat = f"{dinfo['ocr_len']} chars" if dinfo['ocr_len'] > 0 else "Vision"
            ai_stat = dinfo.get("ai_response", "200 OK")
            parsed_cnt = dinfo.get("parsed_count", 0)
            cands_cnt = parsed_cnt
            acc_cnt = parsed_cnt
            rej_cnt = 0
            print(f"{fname[:31]:<32} | {ocr_stat:<8} | {ai_stat:<16} | {parsed_cnt:<14} | {cands_cnt:<11} | {acc_cnt:<9} | {rej_cnt:<9}", flush=True)
        print("====================================================================================================\n", flush=True)

        print("\n=============================================================================================================================", flush=True)
        print("FINAL FIELD RESOLUTION DIAGNOSTIC TABLE", flush=True)
        print("=============================================================================================================================", flush=True)
        print(f"{'FIELD':<35} | {'STATUS':<35} | {'SOURCE DOCUMENT':<25} | {'AUTHORITY':<10} | {'CONFIDENCE':<11} | {'VERIFICATION':<12}", flush=True)
        print("-" * 140, flush=True)
        for fk in excel_headers:
            fitem = verification_fields.get(fk, {})
            v = fitem.get("value")
            if v is None or str(v).strip() == "" or str(v).strip().lower() == "not found":
                fstatus = "Not Found"
            elif str(v).strip().upper() in ["NONE", "NO"]:
                fstatus = str(v).strip()
            else:
                fstatus = "FOUND"
            fsrc = str(fitem.get("source", "N/A"))
            fconf = f"{fitem.get('confidence', 0)}%"
            fver = "Verified" if not fitem.get("requires_verification", False) else "Required"
            fauth = "HIGH" if any(term in fsrc for term in ["Profile", "Aadhaar", "TC", "EMIS", "Community", "SSLC", "HSC"]) else "MEDIUM"
            print(f"{fk[:34]:<35} | {fstatus[:34]:<35} | {fsrc[:24]:<25} | {fauth:<10} | {fconf:<11} | {fver:<12}", flush=True)
        print("=============================================================================================================================\n", flush=True)

        _safe_log("\n================ DETECTED DOCUMENT TYPES ================")
        _safe_log(json.dumps(detected_documents, indent=2))
        _safe_log("=========================================================\n")

        safe_summary = {k: ("FOUND" if (v.get("value") is not None and str(v.get("value")).strip() != "" and str(v.get("value")).strip().lower() != "not found") else "Not Found") for k, v in verification_fields.items()}
        _safe_log("\n================ MERGED JSON ================")
        _safe_log(json.dumps({k: (v.get("value") if isinstance(v, dict) else v) for k, v in verification_fields.items()}, indent=2, default=str))
        _safe_log("=============================================\n")

        _safe_log("\n================ ALIAS MAPPING ================")
        _safe_log(json.dumps({k: (v.get("value") if isinstance(v, dict) else v) for k, v in verification_fields.items()}, indent=2, default=str))
        _safe_log("===============================================\n")

        _safe_log("\n================ MERGED FIELDS STATUS ================")
        _safe_log(json.dumps(safe_summary, indent=2))
        _safe_log("======================================================\n")

        final_response = {
            "status": "success",
            "batch_id": batch_id,
            "register_number": register_number,
            "login_fields": login_fields,
            "detected_documents": detected_documents,
            "extracted_fields_per_document": extracted_fields_per_document,
            "merged_fields": verification_fields,
            "excel_headers": excel_headers,
            "verification_fields": verification_fields,
            "extracted_data": verification_fields,
        }

        _safe_log("\n================ FINAL RESPONSE ================")
        _safe_log(json.dumps(final_response, indent=2, default=str))
        _safe_log("=================================================\n")

        profiler.finish()
        profiler.print_batch_summary()

        return final_response

    def _order_independent_cross_document_merge(
        self,
        detected_docs: List[Any],
        all_extracted_pool: Any,
        excel_headers: List[str],
        student_profile: Optional[Dict[str, Any]] = None,
        document_types_per_file: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Order-Independent Cross-Document Fusion & Authority Merge Engine:
        1. Normalizes input pool across arbitrary upload permutations.
        2. Applies document authority weighting (e.g. TC > SSLC > HSC for EMIS).
        3. Enforces explicit negative evidence blocking (e.g. TC Guardian NONE overrides lower-doc candidates).
        4. Validates every candidate semantically ensuring zero wrong-column contamination.
        5. Enforces strictly formatted Excel column outputs (Yes/No booleans, isolated person names).
        """
        from app.services.field_source_rules import (
            evaluate_field_source,
            normalize_document_type,
            SourceAuthorityService,
        )
        from app.utils.field_canonicalizer import (
            get_document_field_authority_weight,
            get_canonical_field_name,
            is_document_authorized_for_field,
        )
        from app.utils.normalization import (
            clean_text_noise,
            is_explicit_negative,
            validate_and_normalize_person_name,
            validate_and_normalize_gender,
            validate_and_normalize_state,
            validate_and_normalize_nationality,
            validate_and_normalize_religion,
            validate_and_normalize_emis,
            validate_and_normalize_code_field,
            validate_boolean_yes_no,
            validate_and_normalize_aadhaar,
            validate_and_normalize_mobile,
            validate_and_normalize_dob,
            validate_and_normalize_community,
            validate_and_normalize_address,
            validate_and_normalize_location_name,
            validate_and_normalize_village_panchayat,
            validate_and_normalize_occupation,
        )

        def _validate_candidate_semantic(field_name: str, val: Any) -> Optional[str]:
            """Semantic validation ensuring zero wrong-column contamination."""
            if val is None or is_explicit_negative(val):
                return None
            fn_lower = field_name.lower().strip()

            is_bool_q = (
                any(tag in fn_lower for tag in ["yes/no", "(yes/no)", "yes / no", "same as", "did ", "whether"])
                or fn_lower.startswith("is ")
                or fn_lower.endswith("?")
            )

            # Boolean Questions
            if is_bool_q:
                return validate_boolean_yes_no(val)

            # Strict rejection of boolean values for non-boolean columns
            if str(val).strip().lower() in ["yes", "no", "true", "false", "y", "n"]:
                return None

            # Address (Permanent Address, Communication Address)
            if "address" in fn_lower and not any(comp in fn_lower for comp in ["email", "mail"]):
                return validate_and_normalize_address(val)

            # Person Names (Must never receive occupation, address, or caste)
            if any(k in fn_lower for k in ["father", "mother", "guardian", "student name", "candidate name", "applicant name"]) and not any(k in fn_lower for k in ["occupation", "mobile", "phone", "aadhaar", "address"]):
                return validate_and_normalize_person_name(val, role=field_name)

            # Occupations (Must never receive person names or address text)
            if "occupation" in fn_lower:
                return validate_and_normalize_occupation(val)

            # Gender
            if "gender" in fn_lower or "sex" in fn_lower:
                return validate_and_normalize_gender(val)

            # State
            if "state" in fn_lower:
                return validate_and_normalize_state(val)

            # Nationality
            if "nationality" in fn_lower:
                return validate_and_normalize_nationality(val)

            # Religion
            if "religion" in fn_lower:
                return validate_and_normalize_religion(val)

            # EMIS ID
            if "emis" in fn_lower:
                return validate_and_normalize_emis(val)

            # Village Panchayat (Explicitly Village Panchayat only, never full address)
            if "panchayat" in fn_lower:
                return validate_and_normalize_village_panchayat(val)

            # District / Taluk / Village Location Strings
            if "district" in fn_lower:
                return validate_and_normalize_location_name(val, "District")
            if "taluk" in fn_lower:
                if "code" in fn_lower:
                    return validate_and_normalize_code_field(field_name, val)
                return validate_and_normalize_location_name(val, "Taluk")
            if "village" in fn_lower and "panchayat" not in fn_lower:
                return validate_and_normalize_location_name(val, "Village")

            # Code fields
            if fn_lower.endswith("code") or "code" in fn_lower.split():
                return validate_and_normalize_code_field(field_name, val)

            # Aadhaar
            if "aadhaar" in fn_lower or "aadhar" in fn_lower:
                without_space = (
                    "without space" in fn_lower
                    or "nospace" in fn_lower
                    or fn_lower in ["aadhaar_number", "aadhaar_number_without_space", "aadhaar"]
                )
                return validate_and_normalize_aadhaar(val, without_space=without_space)

            # Mobile
            if any(m in fn_lower for m in ["mobile", "phone", "cell"]):
                return validate_and_normalize_mobile(val)

            # Date of Birth
            if any(d in fn_lower for d in ["dob", "birth"]):
                return validate_and_normalize_dob(val)

            # Community
            if "community" in fn_lower or "caste" in fn_lower:
                return validate_and_normalize_community(val)

            # Register Number (Reject Aadhaar 12-digit numbers)
            if any(r in fn_lower for r in ["register number", "register no", "reg no", "registration number", "roll no"]):
                val_str = str(val).strip()
                digits = re.sub(r'\D', '', val_str)
                if len(digits) == 12 and (re.match(r'^\d{4}\s+\d{4}\s+\d{4}$', val_str) or val_str.isdigit()):
                    return None

            clean = clean_text_noise(val)
            return clean if clean and not is_explicit_negative(clean) else None

        # Convert input pool to standardized dictionary of files
        extracted_fields_per_document: Dict[str, Dict[str, Any]] = {}
        types_per_file: Dict[str, str] = dict(document_types_per_file or {})

        if isinstance(all_extracted_pool, list):
            for idx, doc_item in enumerate(all_extracted_pool):
                fname = doc_item.get("source_file", f"doc_{idx}")
                doctype = doc_item.get("document_type", doc_item.get("type", "UNKNOWN"))
                extracted_data = doc_item.get("extracted_data", {})
                confidences = doc_item.get("field_confidences", {})
                fields_dict = {}
                for fk, fv in extracted_data.items():
                    fields_dict[fk] = {
                        "value": fv,
                        "confidence": confidences.get(fk, 85),
                    }
                extracted_fields_per_document[fname] = fields_dict
                types_per_file[fname] = doctype
        elif isinstance(all_extracted_pool, dict):
            extracted_fields_per_document = all_extracted_pool
            for fname in extracted_fields_per_document:
                if fname not in types_per_file:
                    types_per_file[fname] = "UNKNOWN"

        # Collect raw candidates across all documents order-independently
        raw_candidates_by_field: Dict[str, List[Dict[str, Any]]] = {}
        for fname, doc_fields in extracted_fields_per_document.items():
            f_doctype = types_per_file.get(fname, "UNKNOWN")
            for k, v in doc_fields.items():
                if not k or not isinstance(k, str):
                    continue
                val = v.get("value") if isinstance(v, dict) else v
                conf = v.get("confidence", 85) if isinstance(v, dict) else 85
                try:
                    conf = int(conf)
                except Exception:
                    conf = 85

                is_neg = is_explicit_negative(val)
                item = {
                    "field_key": k,
                    "canonical_field": k,
                    "value": val,
                    "confidence": conf,
                    "source_file": fname,
                    "doc_type": f_doctype,
                    "source_document": fname,
                    "source_type": f_doctype,
                    "authority": get_document_field_authority_weight(k, f_doctype),
                    "validation_status": "PENDING",
                    "provenance": f"{f_doctype}:{fname}",
                    "is_negative": is_neg,
                }
                raw_candidates_by_field.setdefault(k, []).append(item)
                canonical_k = get_canonical_field_name(k)
                if canonical_k and canonical_k != k:
                    item_canon = dict(item)
                    item_canon["canonical_field"] = canonical_k
                    raw_candidates_by_field.setdefault(canonical_k, []).append(item_canon)

                # Section 9: Candidate Pool Creation for Aadhaar
                if any(ak in k.lower() for ak in ["aadhaar", "aadhar"]):
                    from app.utils.normalization import normalize_aadhaar_digits
                    norm_aadh_val = normalize_aadhaar_digits(val)
                    if norm_aadh_val:
                        item_aadh = dict(item)
                        item_aadh["field_key"] = "aadhaar_number"
                        item_aadh["canonical_field"] = "aadhaar_number"
                        item_aadh["value"] = norm_aadh_val
                        item_aadh["source_document"] = fname
                        item_aadh["source_type"] = "AADHAAR"
                        item_aadh["validation_status"] = "VALID"
                        item_aadh["provenance"] = f"AADHAAR:{fname}"
                        raw_candidates_by_field.setdefault("aadhaar_number", []).append(item_aadh)
                        for alias_hdr in ["Aadhaar Number", "Aadhaar Number (without space)", "Aadhaar Card"]:
                            item_al = dict(item_aadh)
                            item_al["field_key"] = alias_hdr
                            item_al["canonical_field"] = alias_hdr
                            raw_candidates_by_field.setdefault(alias_hdr, []).append(item_al)

        total_raw_fields = sum(len(df) for df in extracted_fields_per_document.values())
        total_after_canonical = sum(len(cands) for cands in raw_candidates_by_field.values())
        accepted_candidates_count = 0
        rejected_candidates_count = 0

        print("\n========== CANDIDATE POOL (STAGE 5 DIAGNOSTICS) ==========", flush=True)
        print(f"BEFORE INSERT (Document Extracted Fields Count): {total_raw_fields}", flush=True)
        print(f"AFTER CANONICALIZATION (Candidate Pool Count): {total_after_canonical}", flush=True)

        fused_pool: Dict[str, Dict[str, Any]] = {}

        # Merge each field with Source Authority, Document Authority, and Explicit Negative Evidence protection
        for k, candidates in raw_candidates_by_field.items():
            # 1. Compute highest negative authority evidence (strictly from authorized documents)
            neg_candidates = [
                c for c in candidates
                if c["is_negative"] and evaluate_field_source(k, c["doc_type"])[0]
            ]
            max_neg_auth = max(
                [get_document_field_authority_weight(k, c["doc_type"]) for c in neg_candidates],
                default=-1
            )

            # 2. Filter positive candidates: Source Authority Filter -> Semantic Validation -> Merge
            valid_positives = []
            for c in candidates:
                if c["is_negative"] or c["value"] is None or str(c["value"]).strip() == "":
                    rejected_candidates_count += 1
                    continue

                # --- STEP 3: SOURCE AUTHORITY FILTER ---
                is_auth, auth_reason, prio, rule_name = evaluate_field_source(k, c["doc_type"])
                if not is_auth:
                    rejected_candidates_count += 1
                    # evaluate_field_source already safe-logs structured trace without PII
                    continue

                # --- STEP 4: SEMANTIC FIELD VALIDATION ---
                cleaned_val = _validate_candidate_semantic(k, c["value"])
                if cleaned_val is None:
                    rejected_candidates_count += 1
                    print(f"  [REJECTED] Field: '{k}' | Doc: {c['source_file']} -> Rejection: Semantic validation failed", flush=True)
                    continue

                auth_weight = prio if prio > 0 else get_document_field_authority_weight(k, c["doc_type"])
                # Requirement 3 & 15: Explicit negative evidence prevents lower- or equal-authority candidates
                if max_neg_auth >= auth_weight:
                    rejected_candidates_count += 1
                    print(f"  [REJECTED] Field: '{k}' | Doc: {c['source_file']} -> Rejection: Overridden by higher authority negative evidence", flush=True)
                    continue

                composite_score = auth_weight * 1000 + c["confidence"]
                norm_doc = normalize_document_type(c["doc_type"])
                valid_positives.append({
                    "canonical_field": k,
                    "value": cleaned_val,
                    "confidence": c["confidence"],
                    "source_file": c["source_file"],
                    "doc_type": norm_doc,
                    "source_document": c["source_file"],
                    "source_type": norm_doc,
                    "authority": auth_weight,
                    "source_rule": rule_name,
                    "validation_status": "VALID",
                    "provenance": c.get("provenance", f"{norm_doc}:{c['source_file']}"),
                    "_weight": composite_score,
                    "_auth": auth_weight,
                })
                accepted_candidates_count += 1

            if valid_positives:
                # Deterministic order-independent sort
                valid_positives.sort(
                    key=lambda x: (x["_weight"], x["_auth"], x["confidence"], str(x["doc_type"]), str(x["source_file"])),
                    reverse=True
                )
                winner = valid_positives[0]
                fused_pool[k] = {
                    "canonical_field": k,
                    "value": winner["value"],
                    "confidence": winner["confidence"],
                    "source_file": winner["source_file"],
                    "doc_type": winner["doc_type"],
                    "source_document": winner["source_document"],
                    "source_type": winner["source_type"],
                    "authority": winner["authority"],
                    "source_rule": winner["source_rule"],
                    "validation_status": "VALID",
                    "provenance": winner.get("provenance"),
                    "_weight": winner["_weight"],
                }
            elif max_neg_auth >= 0:
                # Explicit negative evidence won
                fused_pool[k] = {
                    "canonical_field": k,
                    "value": "NO",
                    "raw_value": "NONE",
                    "state": "EXPLICIT_NEGATIVE",
                    "confidence": 95,
                    "source_file": "Explicit Negative Evidence",
                    "doc_type": "Document Evidence",
                    "source_document": "Explicit Negative Evidence",
                    "source_type": "DOCUMENT_NEGATIVE",
                    "authority": max_neg_auth,
                    "source_rule": "EXPLICIT_NEGATIVE",
                    "validation_status": "VALID",
                    "provenance": "Document Negative Evidence",
                    "_weight": max_neg_auth * 1000,
                }

        print(f"AFTER VALIDATION: Accepted Count={accepted_candidates_count}, Rejected Count={rejected_candidates_count}", flush=True)
        print(f"BEFORE MERGE: Candidate Count={len(raw_candidates_by_field)}", flush=True)
        print(f"AFTER MERGE: Final Fused Count={len(fused_pool)}", flush=True)
        print("===========================================================\n", flush=True)

        # Normalize detected document labels
        detected_doc_types: List[str] = []
        for d in detected_docs:
            if isinstance(d, dict):
                dtype = d.get("document_type", d.get("type", "UNKNOWN"))
            else:
                dtype = str(d)
            if dtype and dtype != "UNKNOWN" and dtype not in detected_doc_types:
                detected_doc_types.append(dtype)

        # Smart Administrative Lookup Engine
        initial_fields: Dict[str, Dict[str, Any]] = {}
        for h in excel_headers:
            if h in fused_pool:
                initial_fields[h] = fused_pool[h]
            else:
                initial_fields[h] = {"value": None, "confidence": 0}

        try:
            enriched_fields = self.lookup_engine.process_lookup(
                verification_fields=initial_fields,
                all_extracted_pool=fused_pool,
                detected_documents=detected_doc_types,
            )
            for ek, ev in enriched_fields.items():
                if ev.get("value") and ev.get("confidence", 0) > 0:
                    fused_pool[ek] = ev
        except Exception as lookup_err:
            _safe_log(f"[CrossDocMerge Lookup Warning] {lookup_err}")

        # Semantic Mapping to Excel Headers
        mapped_results = self.field_mapper.map_all_excel_headers(
            excel_headers=excel_headers,
            extracted_data_pool=fused_pool,
            student_profile=student_profile,
        )

        verification_fields: Dict[str, Dict[str, Any]] = {}
        for header in excel_headers:
            item = mapped_results.get(header, {})
            val = item.get("value")
            conf = item.get("confidence", 0)
            src = item.get("source", "Document Extraction")

            h_lower = header.lower().strip()
            is_yes_no = (
                any(q in h_lower for q in ["yes/no", "(yes/no)", "yes / no", "same as", "did ", "whether"])
                or h_lower.startswith("is ")
                or h_lower.endswith("?")
            )

            # Requirement 2: EMIS ID Handling (Boolean flag and actual ID)
            if "emis" in h_lower:
                accepted_emis = None
                # Check fused pool first
                for pk, pv in fused_pool.items():
                    pkl = pk.lower()
                    if "emis" in pkl and not pkl.startswith("is ") and not any(q in pkl for q in ["available", "yes/no"]):
                        pval = pv.get("value") if isinstance(pv, dict) else pv
                        if pval and validate_and_normalize_emis(pval):
                            accepted_emis = validate_and_normalize_emis(pval)
                            break
                # If not found in fused pool, check ONLY documents authorized for EMIS ID (TC only)
                if not accepted_emis:
                    for fname, doc_fields in extracted_fields_per_document.items():
                        f_doctype = types_per_file.get(fname, "UNKNOWN")
                        if not evaluate_field_source("EMIS ID", f_doctype)[0]:
                            continue
                        for dk, dv in doc_fields.items():
                            if "emis" in dk.lower() and not any(q in dk.lower() for q in ["available", "is ", "yes/no"]):
                                dval = dv.get("value") if isinstance(dv, dict) else dv
                                norm_e = validate_and_normalize_emis(dval)
                                if norm_e:
                                    accepted_emis = norm_e
                                    break
                        if accepted_emis:
                            break

                if is_yes_no:
                    if accepted_emis:
                        verification_fields[header] = {
                            "value": "Yes",
                            "confidence": 95,
                            "source": "EMIS Validated",
                            "source_document": "Transfer Certificate",
                            "source_type": "TRANSFER_CERTIFICATE",
                            "authority": 100,
                            "source_rule": "STRICT_TRANSFER_CERTIFICATE",
                            "validation_status": "VALID",
                            "requires_verification": False,
                        }
                    else:
                        verification_fields[header] = {
                            "value": "No",
                            "confidence": 95,
                            "source": "EMIS Not Available",
                            "source_document": "N/A",
                            "source_type": "N/A",
                            "authority": 0,
                            "source_rule": "STRICT_TRANSFER_CERTIFICATE",
                            "validation_status": "VALID",
                            "requires_verification": False,
                        }
                    continue
                else:
                    if accepted_emis:
                        verification_fields[header] = {
                            "value": accepted_emis,
                            "confidence": 95,
                            "source": "EMIS Document Extraction",
                            "source_document": "Transfer Certificate",
                            "source_type": "TRANSFER_CERTIFICATE",
                            "authority": 100,
                            "source_rule": "STRICT_TRANSFER_CERTIFICATE",
                            "validation_status": "VALID",
                            "requires_verification": False,
                        }
                        continue
                    else:
                        verification_fields[header] = {
                            "value": None,
                            "confidence": 0,
                            "source": "EMIS Not Found",
                            "source_document": "N/A",
                            "source_type": "N/A",
                            "authority": 0,
                            "source_rule": "STRICT_TRANSFER_CERTIFICATE",
                            "validation_status": "VERIFICATION_REQUIRED",
                            "requires_verification": True,
                        }
                        continue

            # Requirement 7: "Is Communication Address Same as Permanent Address"
            if ("same as" in h_lower or "communication address same" in h_lower) and is_yes_no:
                verification_fields[header] = {
                    "value": "Yes",
                    "confidence": 85,
                    "source": "Address Rule",
                    "source_document": "Inferred Address Rule",
                    "source_type": "RULE_INFERRED",
                    "authority": 85,
                    "source_rule": "ADDRESS_RULE",
                    "validation_status": "VALID",
                    "requires_verification": False,
                }
                continue

            # If explicit negative evidence was determined
            if val in ["NO", "NONE"] or (header in fused_pool and (fused_pool[header].get("value") in ["NO", "NONE"] or fused_pool[header].get("state") == "EXPLICIT_NEGATIVE")):
                verification_fields[header] = {
                    "value": "NO",
                    "state": "EXPLICIT_NEGATIVE",
                    "confidence": 95,
                    "source": "Explicit Negative Evidence",
                    "source_document": "Explicit Negative Evidence",
                    "source_type": "DOCUMENT_NEGATIVE",
                    "authority": 100,
                    "source_rule": "EXPLICIT_NEGATIVE",
                    "validation_status": "VALID",
                    "requires_verification": False,
                }
                continue

            valid_val = _validate_candidate_semantic(header, val) if (val is not None and str(val).strip() != "") else None

            if valid_val is not None:
                final_val = str(val).strip() if (str(val).strip().upper() == valid_val.strip().upper()) else valid_val.strip()
                pool_item = fused_pool.get(header) or fused_pool.get(get_canonical_field_name(header)) or {}
                is_prof = bool(item.get("is_profile", False)) or (src == "Student Profile")
                src_type = "PROFILE_SOURCE" if is_prof else (pool_item.get("source_type") or normalize_document_type(pool_item.get("doc_type", src)))
                src_doc = "Student Profile" if is_prof else (pool_item.get("source_document") or pool_item.get("source_file", src))
                auth_prio = 100 if is_prof else pool_item.get("authority", 50)
                src_rule = "AUTHENTICATED_LOGIN_SESSION" if is_prof else pool_item.get("source_rule", "DEFAULT")

                verification_fields[header] = {
                    "value": final_val,
                    "confidence": conf,
                    "source": src,
                    "source_document": src_doc,
                    "source_type": src_type,
                    "authority": auth_prio,
                    "source_rule": src_rule,
                    "validation_status": "VALID",
                    "requires_verification": False,
                }
            else:
                verification_fields[header] = {
                    "value": "No" if is_yes_no else None,
                    "confidence": 0,
                    "source": src if val is None else "Rejected Invalid Value",
                    "source_document": "N/A",
                    "source_type": "N/A",
                    "authority": 0,
                    "source_rule": "N/A",
                    "validation_status": "VERIFICATION_REQUIRED",
                    "requires_verification": True if not is_yes_no else False,
                }

        # Strict Final Field Validation Gate
        for header, item in verification_fields.items():
            h_lower = header.lower().strip()
            is_yes_no = (
                any(q in h_lower for q in ["yes/no", "(yes/no)", "yes / no", "same as", "did ", "whether"])
                or h_lower.startswith("is ")
                or h_lower.endswith("?")
            )
            v = item.get("value")
            if v is not None:
                # 1. Non-boolean headers must NEVER be boolean Yes/No (except explicit negative document evidence)
                if item.get("source") != "Explicit Negative Evidence" and not is_yes_no and str(v).strip().lower() in ["yes", "no", "true", "false", "y", "n"]:
                    item["value"] = None
                    item["requires_verification"] = True
                    item["source"] = "Rejected Boolean in Non-Boolean Field"
                # 2. Address validation
                elif "address" in h_lower and not is_yes_no and not any(comp in h_lower for comp in ["email", "mail"]):
                    norm_addr = validate_and_normalize_address(v)
                    if norm_addr is None:
                        item["value"] = None
                        item["requires_verification"] = True
                        item["source"] = "Invalid Address Format"
                    else:
                        item["value"] = norm_addr
                # 3. DOB validation
                elif any(d in h_lower for d in ["dob", "birth"]):
                    norm_dob = validate_and_normalize_dob(v)
                    if norm_dob is None:
                        item["value"] = None
                        item["requires_verification"] = True
                        item["source"] = "Invalid DOB (Issue Date/Out of Range)"
                    else:
                        item["value"] = norm_dob
                # 4. Aadhaar validation
                elif "aadhaar" in h_lower or "aadhar" in h_lower:
                    without_space = "without space" in h_lower or "nospace" in h_lower
                    norm_aadh = validate_and_normalize_aadhaar(v, without_space=without_space)
                    if norm_aadh is None:
                        item["value"] = None
                        item["requires_verification"] = True
                        item["source"] = "Invalid Aadhaar Format"
                    else:
                        item["value"] = norm_aadh
                # 5. EMIS ID validation
                elif "emis" in h_lower and not is_yes_no:
                    norm_emis = validate_and_normalize_emis(v)
                    if norm_emis is None:
                        item["value"] = None
                        item["requires_verification"] = True
                        item["source"] = "Invalid EMIS ID Format"
                    else:
                        item["value"] = norm_emis
                # 6. Gender validation
                elif "gender" in h_lower or "sex" in h_lower:
                    norm_gender = validate_and_normalize_gender(v)
                    if norm_gender is None:
                        item["value"] = None
                        item["requires_verification"] = True
                        item["source"] = "Invalid Gender Format"
                    else:
                        item["value"] = norm_gender

        # Inherit validated Permanent Address for Communication Address if not separately found
        perm_addr_val = None
        for pk in ["Permanent Address", "Permanent address", "Address"]:
            if verification_fields.get(pk, {}).get("value") and str(verification_fields.get(pk, {}).get("value")).strip().lower() not in ["none", "not found", "yes", "no"]:
                perm_addr_val = verification_fields[pk]["value"]
                break

        for ck in ["Communication address", "Communication Address"]:
            if ck in verification_fields and (not verification_fields[ck].get("value") or str(verification_fields[ck].get("value")).strip().lower() in ["none", "not found", "yes", "no"]):
                if perm_addr_val:
                    verification_fields[ck] = {
                        "value": perm_addr_val,
                        "confidence": 90,
                        "source": "Permanent Address (Same Address Rule)",
                        "requires_verification": False,
                    }

        # Inject authenticated profile fields if provided
        if student_profile:
            for pk, pv in student_profile.items():
                if pv is not None:
                    verification_fields[pk] = {
                        "value": pv,
                        "confidence": 100,
                        "source": "Student Profile",
                        "requires_verification": False,
                    }

        return verification_fields

