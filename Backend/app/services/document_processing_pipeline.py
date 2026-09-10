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
        all_extracted_pool: Dict[str, Any] = {}

        _safe_log("\n================ UPLOADED FILES ================")
        for idx, f in enumerate(files, start=1):
            _safe_log(f"{idx}. Filename : {f.filename}")
        _safe_log("===============================================\n")

        _safe_log("\n================ REQUIRED EXCEL COLUMNS ================")
        _safe_log(json.dumps(excel_headers, indent=2))
        _safe_log("=======================================================\n")

        # 3. Process Each Uploaded File
        for upload_file in files:
            filename = upload_file.filename or "uploaded_doc.pdf"
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

            # Strategy A: Google Gemini Multimodal Vision Extraction (Primary)
            _safe_log(f"[Pipeline] Running Gemini multimodal vision on '{filename}'...")
            gemini_res = self.gemini_service.extract_from_bytes(
                file_bytes=file_bytes,
                mime_type=mime_type,
                filename=filename,
                target_fields=excel_headers,
            )

            if gemini_res.get("success"):
                doc_type = gemini_res.get("document_type", "UNKNOWN").upper()
                extracted_fields_dict = gemini_res.get("fields", {})

                # Flatten summary fields into extracted_fields_dict if missing
                summary = gemini_res.get("extracted_summary", {})
                for sk, sv in summary.items():
                    if sv and sk not in extracted_fields_dict:
                        clean_label = sk.replace("_", " ").title()
                        extracted_fields_dict[clean_label] = {"value": sv, "confidence": 95}

                doc_extracted = extracted_fields_dict

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
                    except Exception as ai_err:
                        _safe_log(f"[Pipeline AI Notice] {ai_err}")

                # Merge regex extractions
                if isinstance(regex_results, dict):
                    for rk, rv in regex_results.items():
                        if rk not in doc_extracted or not doc_extracted[rk].get("value"):
                            doc_extracted[rk] = rv

            # Track detected document type
            if doc_type and doc_type != "UNKNOWN" and doc_type not in detected_documents:
                detected_documents.append(doc_type)

            _safe_log(f"Detected Document Type: {doc_type}")
            extracted_fields_per_document[filename] = doc_extracted

            # Merge into cross-document pool with Document-Aware Authority & Conflict Resolution
            from app.utils.field_canonicalizer import is_document_authorized_for_field
            from app.utils.normalization import (
                clean_text_noise,
                validate_and_normalize_aadhaar,
                validate_and_normalize_mobile,
                validate_and_normalize_dob,
                validate_and_normalize_community,
            )

            for k, v in doc_extracted.items():
                val = v.get("value") if isinstance(v, dict) else v
                conf = v.get("confidence", 85) if isinstance(v, dict) else 85

                if val is not None and str(val).strip() != "" and str(val).strip().upper() not in ["NO", "NULL", "NONE", "N/A"]:
                    clean_val = clean_text_noise(val) if isinstance(val, str) else val
                    is_auth = is_document_authorized_for_field(doc_type, k)
                    candidate_weight = conf + (25 if is_auth else 0)

                    # Validation quality boost
                    k_lower = k.lower()
                    if "aadhaar" in k_lower and validate_and_normalize_aadhaar(clean_val):
                        candidate_weight += 10
                    elif "mobile" in k_lower and validate_and_normalize_mobile(clean_val):
                        candidate_weight += 10
                    elif ("dob" in k_lower or "birth" in k_lower) and validate_and_normalize_dob(clean_val):
                        candidate_weight += 10
                    elif "community" in k_lower and validate_and_normalize_community(clean_val):
                        candidate_weight += 10

                    existing = all_extracted_pool.get(k)
                    if not existing:
                        all_extracted_pool[k] = {
                            "value": clean_val,
                            "confidence": conf,
                            "source_file": filename,
                            "doc_type": doc_type,
                            "_weight": candidate_weight,
                        }
                    else:
                        exist_weight = existing.get("_weight", existing.get("confidence", 0))
                        if candidate_weight > exist_weight:
                            all_extracted_pool[k] = {
                                "value": clean_val,
                                "confidence": conf,
                                "source_file": filename,
                                "doc_type": doc_type,
                                "_weight": candidate_weight,
                            }

        # 4. Execute Smart Administrative Lookup Engine (Address, PIN code, Salutation)
        initial_fields: Dict[str, Dict[str, Any]] = {}
        for h in excel_headers:
            if h in all_extracted_pool:
                initial_fields[h] = all_extracted_pool[h]
            else:
                initial_fields[h] = {"value": None, "confidence": 0}

        enriched_fields = self.lookup_engine.process_lookup(
            verification_fields=initial_fields,
            all_extracted_pool=all_extracted_pool,
            detected_documents=detected_documents,
        )

        # Merge lookup results back into pool
        for ek, ev in enriched_fields.items():
            if ev.get("value") and ev.get("confidence", 0) > 0:
                all_extracted_pool[ek] = ev

        print("\n========== EXTRACTION ==========", flush=True)
        print(f"Extracted Fields Pool ({len(all_extracted_pool)} total):", flush=True)
        for fk, fv in all_extracted_pool.items():
            fval = fv.get("value") if isinstance(fv, dict) else fv
            fsrc = fv.get("source_file", fv.get("doc_type", "Document")) if isinstance(fv, dict) else "Extraction"
            fcnf = fv.get("confidence", 90) if isinstance(fv, dict) else 90
            print(f"  - {fk}: {fval} (source: {fsrc}, conf: {fcnf})", flush=True)
        print("================================\n", flush=True)

        # 5. Semantic Mapping to Excel Column Headers
        mapped_results = self.field_mapper.map_all_excel_headers(
            excel_headers=excel_headers,
            extracted_data_pool=all_extracted_pool,
            student_profile=login_profile,
        )

        # Prepare Verification Fields for Frontend UI & backward compatibility
        verification_fields: Dict[str, Dict[str, Any]] = {}
        for header, item in mapped_results.items():
            val = item.get("value")
            conf = item.get("confidence", 0)
            src = item.get("source", "Document Extraction")

            if val is not None and str(val).strip() != "":
                verification_fields[header] = {
                    "value": str(val).strip(),
                    "confidence": conf,
                    "source": src,
                }
            else:
                is_yes_no = (
                    any(q in header.lower() for q in ["yes/no", "(yes/no)", "yes / no", "same as", "did ", "whether"])
                    or header.lower().startswith("is ")
                )
                verification_fields[header] = {
                    "value": "No" if is_yes_no else None,
                    "confidence": 0,
                    "source": "Not Found",
                }

        # Profile fields injection guarantee
        for pk, pv in login_fields.items():
            verification_fields[pk] = {"value": pv, "confidence": 100, "source": "Student Profile"}

        print("\n========== MAPPING ==========", flush=True)
        print(f"Mapped Fields to Excel Headers ({len(verification_fields)}):", flush=True)
        for mk, mv in verification_fields.items():
            mval = mv.get("value")
            msrc = mv.get("source", "N/A")
            mcnf = mv.get("confidence", 0)
            print(f"  - {mk} = {mval} (conf: {mcnf}, source: {msrc})", flush=True)
        print("=============================\n", flush=True)

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
