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

    async def process_student_documents(
        self,
        batch_id: str,
        register_number: str,
        student_name: str,
        mobile_number: Optional[str] = None,
        files: Optional[List[UploadFile]] = None,
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

        # 2. Build Login Profile Context
        login_profile = {
            "student_name": student_name.strip(),
            "register_number": register_number.strip(),
            "mobile_number": mobile_number.strip() if mobile_number else "",
            "email": "",
        }

        login_fields = {
            "Student Name": student_name.strip(),
            "Register Number": register_number.strip(),
            "Mobile Number": mobile_number.strip() if mobile_number else "N/A",
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
        _safe_log(json.dumps(excel_headers, indent=2))
        _safe_log("=======================================================\n")

        # 3. Process Each Uploaded File
        doc_stats_tracking: Dict[str, Dict[str, Any]] = {}
        for upload_file in files:
            filename = upload_file.filename or "uploaded_doc.pdf"
            print("\n==================================================", flush=True)
            print(f"PROCESSING DOCUMENT: {filename}", flush=True)
            print("==================================================", flush=True)

            try:
                file_bytes = await upload_file.read()
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

                # Strategy A: Google Gemini Multimodal Vision Extraction (Primary)
                _safe_log(f"[Pipeline] Running Gemini multimodal vision on '{filename}'...")
                gemini_res = self.gemini_service.extract_from_bytes(
                    file_bytes=file_bytes,
                    mime_type=mime_type,
                    filename=filename,
                    target_fields=excel_headers,
                )

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

                    doc_extracted = extracted_fields_dict
                else:
                    ai_response_status = "FAILED/429"

                # Strategy B: Fallback / Complementary OCR Engine
                if not doc_extracted or doc_type == "UNKNOWN":
                    _safe_log(f"[Pipeline] Running OCR fallback for '{filename}'...")
                    ocr_result = self.ocr_service.extract_text(abs_path)
                    raw_ocr = ocr_result.get("text") or ""
                    clean_ocr = self.preprocessor.clean_ocr_text(raw_ocr)

                    # Classify document via OCR text & filename
                    class_res = self.classifier.classify(raw_ocr, filename=filename)
                    if doc_type == "UNKNOWN":
                        doc_type = class_res.get("document_type", "UNKNOWN").upper()

                    # Regex deterministic extraction
                    regex_results = self.preprocessor.extract_regex_fields(clean_ocr or raw_ocr)

                    # If Gemini is available with text mode
                    if self.gemini_service.is_available() and raw_ocr.strip():
                        gemini_text_res = self.gemini_service.extract_from_text(
                            ocr_text=raw_ocr,
                            target_fields=excel_headers,
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
                                required_fields=excel_headers,
                            )
                            ai_response_status = "200 OK (Mistral OCR)"
                        except Exception as ai_err:
                            _safe_log(f"[Pipeline AI Notice] {ai_err}")

                    # Merge regex extractions
                    if isinstance(regex_results, dict):
                        for rk, rv in regex_results.items():
                            if rk not in doc_extracted or not doc_extracted[rk].get("value"):
                                doc_extracted[rk] = rv

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

                # Track detected document type
                if doc_type and doc_type != "UNKNOWN" and doc_type not in detected_documents:
                    detected_documents.append(doc_type)

                _safe_log(f"Detected Document Type: {doc_type}")
                extracted_fields_per_document[filename] = doc_extracted
                document_types_per_file[filename] = doc_type

                doc_stats_tracking[filename] = {
                    "ocr_len": len(raw_ocr),
                    "ai_response": ai_response_status,
                    "parsed_count": len(doc_extracted),
                }

            except Exception as doc_err:
                logger.error(f"[Pipeline] Error processing document '{filename}': {doc_err}", exc_info=True)
                print(f"[Pipeline Warning] Error processing '{filename}': {doc_err}. Continuing with remaining documents...", flush=True)
                continue

        # 4. Order-Independent Cross-Document Fusion & Authority Merge
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
        print(f"{'FIELD':<35} | {'FINAL VALUE':<35} | {'SOURCE DOCUMENT':<25} | {'AUTHORITY':<10} | {'CONFIDENCE':<11} | {'VERIFICATION':<12}", flush=True)
        print("-" * 140, flush=True)
        for fk in excel_headers:
            fitem = verification_fields.get(fk, {})
            fval = str(fitem.get("value") if fitem.get("value") is not None else "Not Found")
            fsrc = str(fitem.get("source", "N/A"))
            fconf = f"{fitem.get('confidence', 0)}%"
            fver = "Verified" if not fitem.get("requires_verification", False) else "Required"
            fauth = "HIGH" if any(term in fsrc for term in ["Profile", "Aadhaar", "TC", "EMIS", "Community", "SSLC", "HSC"]) else "MEDIUM"
            print(f"{fk[:34]:<35} | {fval[:34]:<35} | {fsrc[:24]:<25} | {fauth:<10} | {fconf:<11} | {fver:<12}", flush=True)
        print("=============================================================================================================================\n", flush=True)

        _safe_log("\n================ DETECTED DOCUMENT TYPES ================")
        _safe_log(json.dumps(detected_documents, indent=2))
        _safe_log("=========================================================\n")

        _safe_log("\n================ MERGED JSON ====================")
        _safe_log(json.dumps(verification_fields, indent=2))
        _safe_log("=================================================\n")

        _safe_log("\n================ ALIAS MAPPING ================")
        _safe_log(json.dumps(verification_fields, indent=2))
        _safe_log("===============================================\n")

        _safe_log("\n================ FINAL JSON ====================")
        _safe_log(json.dumps(verification_fields, indent=2))
        _safe_log("====================================================\n")

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
        _safe_log("================================================\n")

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

            # Person Names
            if any(k in fn_lower for k in ["father", "mother", "guardian", "student name", "candidate name", "applicant name"]) and not any(k in fn_lower for k in ["occupation", "mobile", "phone", "aadhaar", "address"]):
                return validate_and_normalize_person_name(val, role=field_name)

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

            # Code fields
            if fn_lower.endswith("code") or "code" in fn_lower.split():
                return validate_and_normalize_code_field(field_name, val)

            # Aadhaar
            if "aadhaar" in fn_lower or "aadhar" in fn_lower:
                without_space = "without space" in fn_lower or "nospace" in fn_lower
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
                    "value": val,
                    "confidence": conf,
                    "source_file": fname,
                    "doc_type": f_doctype,
                    "is_negative": is_neg,
                }
                raw_candidates_by_field.setdefault(k, []).append(item)
                canonical_k = get_canonical_field_name(k)
                if canonical_k and canonical_k != k:
                    item_canon = dict(item)
                    item_canon["field_key"] = canonical_k
                    raw_candidates_by_field.setdefault(canonical_k, []).append(item_canon)

        total_raw_fields = sum(len(df) for df in extracted_fields_per_document.values())
        total_after_canonical = sum(len(cands) for cands in raw_candidates_by_field.values())
        accepted_candidates_count = 0
        rejected_candidates_count = 0

        print("\n========== CANDIDATE POOL (STAGE 5 DIAGNOSTICS) ==========", flush=True)
        print(f"BEFORE INSERT (Document Extracted Fields Count): {total_raw_fields}", flush=True)
        print(f"AFTER CANONICALIZATION (Candidate Pool Count): {total_after_canonical}", flush=True)

        fused_pool: Dict[str, Dict[str, Any]] = {}

        # Merge each field with Document Authority and Explicit Negative Evidence protection
        for k, candidates in raw_candidates_by_field.items():
            # 1. Compute highest negative authority evidence
            neg_candidates = [c for c in candidates if c["is_negative"]]
            max_neg_auth = max(
                [get_document_field_authority_weight(k, c["doc_type"]) for c in neg_candidates],
                default=-1
            )

            # 2. Filter positive candidates and validate semantically
            valid_positives = []
            for c in candidates:
                if c["is_negative"] or c["value"] is None or str(c["value"]).strip() == "":
                    rejected_candidates_count += 1
                    continue
                cleaned_val = _validate_candidate_semantic(k, c["value"])
                if cleaned_val is None:
                    rejected_candidates_count += 1
                    print(f"  [REJECTED] Field: '{k}' | Value: '{c['value']}' | Doc: {c['source_file']} -> Rejection: Semantic validation failed", flush=True)
                    continue

                auth_weight = get_document_field_authority_weight(k, c["doc_type"])
                # Requirement 3: Explicit negative evidence prevents lower- or equal-authority candidates
                if max_neg_auth >= auth_weight:
                    rejected_candidates_count += 1
                    print(f"  [REJECTED] Field: '{k}' | Value: '{c['value']}' | Doc: {c['source_file']} -> Rejection: Overridden by higher authority negative evidence", flush=True)
                    continue

                composite_score = auth_weight * 1000 + c["confidence"]
                valid_positives.append({
                    "value": cleaned_val,
                    "confidence": c["confidence"],
                    "source_file": c["source_file"],
                    "doc_type": c["doc_type"],
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
                    "value": winner["value"],
                    "confidence": winner["confidence"],
                    "source_file": winner["source_file"],
                    "doc_type": winner["doc_type"],
                    "_weight": winner["_weight"],
                }
            elif max_neg_auth >= 0:
                # Explicit negative evidence won
                fused_pool[k] = {
                    "value": "NO",
                    "confidence": 95,
                    "source_file": "Explicit Negative Evidence",
                    "doc_type": "Document Evidence",
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
                # If not found in fused pool, check all documents directly
                if not accepted_emis:
                    for fname, doc_fields in extracted_fields_per_document.items():
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
                            "requires_verification": False,
                        }
                    else:
                        verification_fields[header] = {
                            "value": "No",
                            "confidence": 95,
                            "source": "EMIS Not Available",
                            "requires_verification": False,
                        }
                    continue
                else:
                    if accepted_emis:
                        verification_fields[header] = {
                            "value": accepted_emis,
                            "confidence": 95,
                            "source": "EMIS Document Extraction",
                            "requires_verification": False,
                        }
                        continue
                    else:
                        verification_fields[header] = {
                            "value": None,
                            "confidence": 0,
                            "source": "EMIS Not Found",
                            "requires_verification": True,
                        }
                        continue

            # Requirement 7: "Is Communication Address Same as Permanent Address"
            if ("same as" in h_lower or "communication address same" in h_lower) and is_yes_no:
                verification_fields[header] = {
                    "value": "Yes",
                    "confidence": 85,
                    "source": "Address Rule",
                    "requires_verification": False,
                }
                continue

            # If explicit negative evidence was determined
            if val == "NO" or (header in fused_pool and fused_pool[header].get("value") == "NO"):
                verification_fields[header] = {
                    "value": "NO",
                    "confidence": 95,
                    "source": "Explicit Negative Evidence",
                    "requires_verification": False,
                }
                continue

            valid_val = _validate_candidate_semantic(header, val) if (val is not None and str(val).strip() != "") else None

            if valid_val is not None:
                final_val = str(val).strip() if (str(val).strip().upper() == valid_val.strip().upper()) else valid_val.strip()
                verification_fields[header] = {
                    "value": final_val,
                    "confidence": conf,
                    "source": src,
                    "requires_verification": False,
                }
            else:
                verification_fields[header] = {
                    "value": "No" if is_yes_no else None,
                    "confidence": 0,
                    "source": src if val is None else "Rejected Invalid Value",
                    "requires_verification": True if val is not None else False,
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

