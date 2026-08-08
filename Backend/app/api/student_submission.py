from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.student_submission import (
    StudentSubmissionCreate,
    StudentSubmissionResponse,
    StudentSubmissionStatusUpdate,
)
from app.schemas.student_identity import (
    StudentIdentityVerifyRequest,
    StudentIdentityVerifyResponse,
)
from app.services.student_submission_service import (
    StudentSubmissionService,
    StudentSubmissionNotFoundException,
)
from app.services.upload_link_service import UploadLinkService, UploadLinkNotFoundException
from app.services.excel_template_service import ExcelTemplateService
from app.repositories.excel_template_repository import ExcelTemplateRepository
from app.core.dependencies import get_current_user, get_optional_current_user, RoleChecker
from app.models.user import User, UserRole
from app.schemas.user import StudentProfileResponse
from app.services.batch_service import BatchService
from app.utils.field_canonicalizer import (
    get_aliases_for_header,
    is_address_field,
    is_profile_field,
    get_canonical_field_name,
    is_document_authorized_for_field,
    get_allowed_sources_for_field,
)

router = APIRouter(prefix="/student-submissions", tags=["Student Submissions"])
service = StudentSubmissionService()
batch_service = BatchService()
_upload_link_service = UploadLinkService()
_excel_service = ExcelTemplateService()
_excel_repo = ExcelTemplateRepository()


def _to_response(s) -> StudentSubmissionResponse:
    return StudentSubmissionResponse(
        id=str(s.id),
        batch_id=s.batch_id,
        batch_name=s.batch_name,
        student_name=s.student_name,
        register_number=s.register_number,
        mobile_number=s.mobile_number,
        email=s.email,
        submission_status=s.submission_status,
        ai_status=s.ai_status,
        document_version=getattr(s, "document_version", 1),
        document_version_id=getattr(s, "document_version_id", None),
        document_requirements_snapshot=getattr(s, "document_requirements_snapshot", []),
        extracted_data=getattr(s, "extracted_data", {}),
        submitted_at=s.submitted_at,
        updated_at=s.updated_at,
        documents=[
            {
                "document_name": d.document_name,
                "status": d.status,
                "file_path": d.file_path,
                "file_size_mb": d.file_size_mb,
                "file_type": d.file_type,
                "uploaded_at": d.uploaded_at,
            }
            for d in s.documents
        ],
    )


@router.post("/verify-identity", response_model=StudentIdentityVerifyResponse)
async def verify_student_identity(data: StudentIdentityVerifyRequest):
    """
    Public endpoint — NO authentication required.

    Verifies that:
      1. The upload link token is valid and active.
      2. The register number exists in the uploaded Excel student list for the linked batch.
      3. The student has not already completed a submission for this batch.

    On success, returns batch_id and batch_name so the frontend can create a
    temporary sessionStorage submission session.  No JWT or auth cookie is issued.
    """
    # 1. Resolve and validate the upload link
    print(f"[Verify Identity] Requested token/slug: {data.token}")
    try:
        link = await _upload_link_service.get_link_by_slug_or_token(data.token)
    except UploadLinkNotFoundException:
        print(f"[Verify Identity] Failed: slug '{data.token}' not found in DB. Result: 404")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid upload link.",
        )

    # 2. Validate batch exists
    if not link.batch_id:
        print(f"[Verify Identity] Failed: batch_id is missing on link document. Result: 404")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid upload link.",
        )

    batch_id: str = link.batch_id

    try:
        batch = await batch_service.get_batch_by_id(batch_id)
    except Exception:
        print(f"[Verify Identity] Failed: batch '{batch_id}' does not exist in DB. Result: 404")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid upload link.",
        )

    # 3. Validate department exists
    from app.services.department_service import DepartmentService
    dept_service = DepartmentService()
    try:
        await dept_service.get_department_by_id(link.department_id)
    except Exception:
        print(f"[Verify Identity] Failed: department '{link.department_id}' does not exist in DB. Result: 404")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid upload link.",
        )

    # 4. Check active status
    if not link.is_active:
        print(f"[Verify Identity] Failed: link is deactivated. Result: 403")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Upload link has been disabled.",
        )

    # 5. Check expiry (if configured)
    if link.expires_at is not None:
        now = datetime.now(timezone.utc)
        expires_at = link.expires_at.replace(tzinfo=timezone.utc) if link.expires_at.tzinfo is None else link.expires_at
        if expires_at < now:
            print(f"[Verify Identity] Failed: link has expired at {expires_at}. Result: 410")
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Upload link has expired.",
            )

    # 3. Check whether an Excel template has been uploaded for this batch
    template_exists = await _excel_service.register_number_exists(batch_id, data.register_number)

    # Determine if an Excel has been uploaded at all (different from register not found)
    template_meta = await _excel_repo.get_by_batch_id(batch_id)

    if template_meta is None:
        # No Excel uploaded — block with a configuration error
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Student list has not been configured for this batch. Please contact your admissions office.",
        )

    if not template_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Register Number not found. Please verify your admission number and try again.",
        )

    # 4. Check for duplicate submission
    already_submitted = await service.check_duplicate_submission(batch_id, data.register_number)
    if already_submitted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already submitted your documents for this admission batch.",
        )

    return StudentIdentityVerifyResponse(
        batch_id=batch_id,
        batch_name=batch.name,
    )


@router.post("", response_model=StudentSubmissionResponse, status_code=status.HTTP_201_CREATED)
async def create_student_submission(data: StudentSubmissionCreate):
    """
    Submit student admission documents from public upload link.
    This endpoint remains public so students can upload documents without logging in.
    """
    try:
        submission = await service.create_submission(data)
        return _to_response(submission)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=list[StudentSubmissionResponse], dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))])
async def get_all_student_submissions(current_user: User = Depends(get_current_user)):
    """
    Retrieve all student submissions.
    Department Admin can only retrieve submissions belonging to their assigned department.
    """
    dept_code = current_user.department_code if current_user.role == UserRole.DEPARTMENT_ADMIN else None
    submissions = await service.get_all_submissions(department_id=dept_code)
    return [_to_response(s) for s in submissions]


@router.get("/batch/{batchId}", response_model=list[StudentSubmissionResponse], dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))])
async def get_submissions_by_batch(
    batchId: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve student submissions for a specific admission batch ID.
    Department Admin can only access submissions of a batch that belongs to their assigned department.
    """
    try:
        # Check batch department access
        batch = await batch_service.get_batch_by_id(batchId)
        if current_user.role == UserRole.DEPARTMENT_ADMIN:
            if batch.department_id != current_user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to access another department's resources.",
                )

        submissions = await service.get_submissions_by_batch_id(batchId)
        return [_to_response(s) for s in submissions]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{id}", response_model=StudentSubmissionResponse, dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))])
async def get_student_submission_by_id(
    id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve a specific student submission by ID.
    """
    try:
        s = await service.get_submission_by_id(id)
        if current_user.role == UserRole.DEPARTMENT_ADMIN:
            if s.department_id != current_user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to access another department's resources.",
                )
        return _to_response(s)
    except HTTPException:
        raise
    except StudentSubmissionNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.patch("/{id}/status", response_model=StudentSubmissionResponse, dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))])
async def update_student_submission_status(
    id: str,
    data: StudentSubmissionStatusUpdate,
    current_user: User = Depends(get_current_user),
):
    """
    Update submission status for a student record.
    """
    try:
        s = await service.get_submission_by_id(id)
        if current_user.role == UserRole.DEPARTMENT_ADMIN:
            if s.department_id != current_user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to modify another department's resources.",
                )

        updated_s = await service.update_status(id, data.submission_status)
        return _to_response(updated_s)
    except HTTPException:
        raise
    except StudentSubmissionNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


from fastapi import UploadFile, File, Form
from app.services.excel_template_service import ExcelTemplateService

excel_template_service = ExcelTemplateService()


@router.post("/extract")
async def extract_student_documents(
    batch_id: str = Form(...),
    register_number: str = Form(...),
    student_name: str = Form(...),
    mobile_number: str | None = Form(None),
    files: list[UploadFile] = File(...)
):
    """
    Production AI Document Extraction endpoint.
    Saves uploaded files, performs Mistral OCR, OCR Preprocessing, Regex Extraction,
    and Mistral AI Extraction based on active batch document requirements.
    """
    import os
    import re
    import json
    from pathlib import Path
    from app.core.config import settings
    from app.services.doc_config_version_service import DocConfigVersionService
    from app.services.ocr_service import OCRService
    from app.services.ocr_preprocessor import OCRPreprocessor
    from app.services.ai_extraction_service import AIExtractionService

    def safe_log(msg: str):
        if getattr(settings, "APP_ENV", "development") == "development":
            try:
                print(msg, flush=True)
            except Exception:
                try:
                    print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)
                except Exception:
                    pass

    try:
        doc_config_service = DocConfigVersionService()
        active_version = await doc_config_service.get_or_create_current_version(batch_id)
        required_fields = await doc_config_service.get_batch_extraction_fields(batch_id)

        uploads_dir = Path(__file__).resolve().parent.parent.parent / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        ocr_service = OCRService()
        preprocessor = OCRPreprocessor()
        ai_service = AIExtractionService()
        from app.utils.field_canonicalizer import is_profile_field

        # STEP 1: Fetch Excel column headers (Single Source of Truth)
        try:
            excel_template = await _excel_service.get_template_by_batch(batch_id)
            excel_headers = excel_template.headers if (excel_template and excel_template.headers) else []
        except Exception:
            excel_headers = []

        # STEP 3: Login Profile Injection (sourced strictly from authenticated session/payload)
        login_fields = {
            "Student Name": student_name,
            "Register Number": register_number,
            "Mobile Number": mobile_number or "N/A",
        }

        # Target extraction fields derived from Excel headers (excluding profile fields)
        # Target extraction fields derived from Excel headers (excluding profile fields)
        if excel_headers:
            target_fields = [h for h in excel_headers if not is_profile_field(h)]
        else:
            target_fields = [f for f in required_fields if not is_profile_field(f)]

        detected_documents: list[str] = []
        extracted_fields_per_document: Dict[str, Dict[str, Any]] = {}
        all_extracted_pool: Dict[str, Any] = {}

        # Candidate pool across ALL uploaded documents: { header: [ { "source_file": fn, "value": val, "confidence": conf } ] }
        candidate_pool: Dict[str, list] = {tf: [] for tf in target_fields}

        # UPLOADED FILES SUMMARY LOG
        safe_log("\n================ UPLOADED FILES ================")
        for idx, f in enumerate(files, start=1):
            fn = f.filename or f"uploaded_doc_{idx}.pdf"
            safe_log(f"{idx}. Filename : {fn}")
        safe_log("===============================================\n")

        # Requirement 12 Log 1 & Test Assertions: Excel Headers / Required Excel Columns
        safe_log("\n==================== EXCEL HEADERS ====================")
        safe_log(json.dumps(excel_headers if excel_headers else target_fields, indent=2))
        safe_log("======================================================\n")

        safe_log("\n================ REQUIRED EXCEL COLUMNS ================")
        safe_log(json.dumps(excel_headers if excel_headers else target_fields, indent=2))
        safe_log("=======================================================\n")

        # Process EVERY uploaded file independently
        for upload_file in files:
            file_bytes = await upload_file.read()
            file_size = len(file_bytes)
            filename = upload_file.filename or "uploaded_doc.pdf"
            save_path = uploads_dir / filename

            with open(save_path, "wb") as f:
                f.write(file_bytes)

            abs_path = str(save_path.resolve())

            safe_log(f"\nProcessing File: {filename} ({file_size} bytes)")

            # OCR Extraction
            ocr_result = ocr_service.extract_text(abs_path)
            if not ocr_result.get("success") or not (ocr_result.get("text") or "").strip():
                safe_log(f"OCR failed or empty for file: {filename}")
                continue

            raw_ocr = ocr_result.get("text", "") or ""
            clean_ocr = preprocessor.clean_ocr_text(raw_ocr)

            # Requirement 12 Log 2: OCR Text Per Document
            safe_log(f"\n==================== OCR TEXT PER DOCUMENT ({filename}) ====================")
            safe_log(clean_ocr if clean_ocr.strip() else "[EMPTY OCR TEXT]")
            safe_log("=========================================================================\n")

            # Document Classification for Audit Logging
            from app.services.document_classifier_service import DocumentClassifierService
            doc_classifier = DocumentClassifierService()
            class_res = doc_classifier.classify(raw_ocr, filename=filename)
            doc_type = class_res.get("document_type", "UNKNOWN")

            if doc_type not in detected_documents:
                detected_documents.append(doc_type)

            safe_log(f"\n================ DOCUMENT TYPE ({filename}) ================")
            safe_log(f"Filename              : {filename}")
            safe_log(f"Detected Document Type: {doc_type}")
            safe_log("============================================================\n")

            # Expand target_fields with semantic aliases for this document extraction
            expanded_doc_fields: list[str] = []
            for tf in target_fields:
                aliases = get_aliases_for_header(tf)
                for a in aliases[:4]:
                    if a not in expanded_doc_fields:
                        expanded_doc_fields.append(a)

            if not expanded_doc_fields:
                expanded_doc_fields = ["Document Details"]

            # Perform Regex Extraction
            regex_results = preprocessor.extract_regex_fields(clean_ocr)
            ocr_addr_obj = preprocessor.extract_address_from_ocr(clean_ocr) or preprocessor.extract_address_from_ocr(raw_ocr)

            aadhaar_matches = re.findall(r"\b([2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4})\b", clean_ocr)
            valid_aadhaar = None
            for match in aadhaar_matches:
                clean_digits = re.sub(r"\D", "", match)
                if len(clean_digits) == 12:
                    valid_aadhaar = f"{clean_digits[:4]} {clean_digits[4:8]} {clean_digits[8:]}"
                    break

            # Perform AI Extraction for all target fields across this document
            doc_extracted = ai_service.extract(
                document_type=doc_type,
                ocr_text=raw_ocr,
                required_fields=expanded_doc_fields,
            )

            # Integrate Regex & Aadhaar Numbers if found
            if valid_aadhaar:
                doc_extracted["Aadhaar Card"] = {"value": valid_aadhaar, "confidence": 100}
                doc_extracted["Aadhaar Number"] = {"value": valid_aadhaar, "confidence": 100}

            if isinstance(regex_results, dict):
                for k, v in regex_results.items():
                    if k not in doc_extracted or not doc_extracted[k].get("value"):
                        doc_extracted[k] = v

            # Address Fallback & Integration
            ai_addr_val = None
            for ak in ["Address", "Full Address", "Permanent Address", "Postal Address", "Residential Address", "Communication Address"]:
                if ak in doc_extracted and isinstance(doc_extracted[ak], dict) and doc_extracted[ak].get("value"):
                    ai_addr_val = doc_extracted[ak].get("value")
                    break

            if ai_addr_val and str(ai_addr_val).strip():
                final_addr_obj = {"value": str(ai_addr_val).strip(), "confidence": 100}
            elif ocr_addr_obj and ocr_addr_obj.get("value"):
                final_addr_obj = ocr_addr_obj
            else:
                final_addr_obj = {"value": None, "confidence": 0}

            if final_addr_obj.get("value"):
                doc_extracted["Address"] = final_addr_obj
                doc_extracted["Full Address"] = final_addr_obj
                doc_extracted["Permanent Address"] = final_addr_obj
                doc_extracted["Residential Address"] = final_addr_obj

            doc_extracted_filtered = {k: v for k, v in (doc_extracted or {}).items() if not is_profile_field(k)}
            extracted_fields_per_document[filename] = doc_extracted_filtered

            # Collect Candidates into candidate_pool for each target Excel field
            for tf in target_fields:
                if tf not in candidate_pool:
                    candidate_pool[tf] = []

                aliases = get_aliases_for_header(tf)
                matched_val = None
                matched_conf = 100

                for alias in aliases:
                    alias_lower = alias.lower()
                    for ek, ev in doc_extracted_filtered.items():
                        if ek.strip().lower() == alias_lower:
                            val = ev.get("value") if isinstance(ev, dict) else ev
                            conf = ev.get("confidence", 100) if isinstance(ev, dict) else 100
                            if val is not None and str(val).strip() != "":
                                matched_val = val
                                matched_conf = conf
                                break
                    if matched_val is not None:
                        break

                if matched_val is not None:
                    if is_document_authorized_for_field(doc_type, tf):
                        candidate_pool[tf].append({
                            "source_file": filename,
                            "doc_type": doc_type,
                            "value": matched_val,
                            "confidence": matched_conf,
                        })
                    else:
                        safe_log(f"[Document Authority Guard] Ignored '{tf}' candidate from {filename} ({doc_type}) because {doc_type} is not authorized for {tf}.")

            # Also merge into all_extracted_pool keeping non-null / highest confidence values
            for k, v in doc_extracted_filtered.items():
                if k not in all_extracted_pool:
                    all_extracted_pool[k] = v
                else:
                    existing = all_extracted_pool[k]
                    existing_val = existing.get("value") if isinstance(existing, dict) else existing
                    new_val = v.get("value") if isinstance(v, dict) else v
                    existing_conf = existing.get("confidence", 0) if isinstance(existing, dict) else 100
                    new_conf = v.get("confidence", 0) if isinstance(v, dict) else 100

                    if (existing_val is None or str(existing_val).strip() == "") and (new_val is not None and str(new_val).strip() != ""):
                        all_extracted_pool[k] = v
                    elif existing_val is not None and str(existing_val).strip() != "" and (new_val is None or str(new_val).strip() == ""):
                        pass
                    elif new_conf > existing_conf:
                        all_extracted_pool[k] = v

        # Requirement 12 Log 3: Candidate Matches
        safe_log("\n==================== CANDIDATE MATCHES ====================")
        for tf, candidates in candidate_pool.items():
            safe_log(f"Field '{tf}':")
            if candidates:
                for c in candidates:
                    safe_log(f"  - [{c['source_file']}] Value: {c['value']} (confidence={c['confidence']})")
            else:
                safe_log("  - [No candidate matches found across uploaded documents]")
        safe_log("===========================================================\n")

        # Per-Field Extraction Source Validation Debug Logs & Final Selection
        safe_log("\n==================== FIELD EXTRACTION SOURCE VALIDATION ====================")
        verification_fields: Dict[str, Dict[str, Any]] = {}

        # First populate Profile/Login fields strictly from authenticated session
        for pk, pv in login_fields.items():
            verification_fields[pk] = {"value": pv, "confidence": 100}

        headers_to_process = excel_headers if excel_headers else target_fields
        for header in headers_to_process:
            if is_profile_field(header):
                val = login_fields.get(header)
                safe_log(f"\nField : {header}")
                safe_log("Allowed Documents : Student Profile")
                safe_log(f"Searching : Profile Session")
                safe_log(f"Value Found : {val}")
                safe_log(f"Final : {val}")
                continue

            allowed_sources = get_allowed_sources_for_field(header)
            allowed_str = ", ".join(allowed_sources) if "ALL" not in allowed_sources else "Any Uploaded Document"

            safe_log(f"\nField : {header}")
            safe_log(f"Allowed Documents : {allowed_str}")

            candidates = candidate_pool.get(header, [])

            # Filter candidates strictly by allowed document types
            valid_candidates = []
            for c in candidates:
                c_doc_type = c.get("doc_type", "UNKNOWN")
                if "ALL" in allowed_sources or c_doc_type in allowed_sources or c_doc_type == "UNKNOWN":
                    valid_candidates.append(c)

            best_candidate = None
            if valid_candidates:
                sorted_candidates = sorted(valid_candidates, key=lambda x: x["confidence"], reverse=True)
                best_candidate = sorted_candidates[0]
                safe_log(f"Searching : {best_candidate['source_file']} ({best_candidate.get('doc_type', 'UNKNOWN')})")
                safe_log(f"Value Found : {best_candidate['value']}")
                safe_log(f"Final : {best_candidate['value']}")
                verification_fields[header] = {
                    "value": best_candidate["value"],
                    "confidence": best_candidate["confidence"],
                }
            else:
                safe_log(f"Searching : {allowed_str}")
                safe_log("Result : Not Found")
                safe_log("Final : null")
                verification_fields[header] = {"value": None, "confidence": 0}

        safe_log("=========================================================================\n")

        safe_log("\n================ DETECTED DOCUMENT TYPES ================")
        safe_log(json.dumps(detected_documents, indent=2))
        safe_log("=========================================================\n")

        safe_log("\n================ MERGED JSON ================")
        safe_log(json.dumps({k: (v.get("value") if isinstance(v, dict) else v) for k, v in verification_fields.items()}, indent=2))
        safe_log("=============================================\n")

        safe_log("\n================ ALIAS MAPPING ================")
        safe_log(json.dumps({k: (v.get("value") if isinstance(v, dict) else v) for k, v in verification_fields.items()}, indent=2))
        safe_log("===============================================\n")

        # Requirement 12 Log 5: Final JSON
        safe_log("\n==================== FINAL JSON ====================")
        safe_log(json.dumps(verification_fields, indent=2))
        safe_log("====================================================\n")

        final_parsed_json_dict = {
            "status": "success",
            "batch_id": batch_id,
            "register_number": register_number,
            "login_fields": login_fields,
            "detected_documents": detected_documents,
            "extracted_fields_per_document": extracted_fields_per_document,
            "merged_fields": verification_fields,
            "excel_headers": excel_headers,
            "verification_fields": verification_fields,
            "extracted_data": verification_fields, # For backwards compatibility
        }

        safe_log("\n================ FINAL RESPONSE ================")
        safe_log(json.dumps(final_parsed_json_dict, indent=2))
        safe_log("===============================================\n")

        return final_parsed_json_dict

    except HTTPException:
        raise
    except Exception as e:
        safe_log(f"[ERROR] Extraction endpoint error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/batch/{batch_id}/excel-headers")
async def get_batch_excel_headers(batch_id: str):
    """
    Public endpoint - retrieve Excel column headers for an Admission Batch.
    Used by student verification page to dynamically adapt field inputs.
    """
    template = await _excel_service.get_template_by_batch(batch_id)
    headers = template.headers if (template and template.headers) else []
    return {
        "batch_id": batch_id,
        "headers": headers,
    }



@router.post("/confirm", response_model=StudentSubmissionResponse)
async def confirm_student_submission(
    data: StudentSubmissionCreate,
    current_user: User | None = Depends(get_optional_current_user),
):
    """
    Finalize student submission, save to MongoDB, and update matched candidate columns in Excel workbook.
    """
    try:
        import json
        from app.core.config import settings

        # Security check: Only override with authenticated student's profile (NEVER admin/staff profiles)
        if current_user and current_user.role == UserRole.STUDENT:
            data.student_name = current_user.name
            data.register_number = current_user.register_number or current_user.username
            if current_user.mobile_number:
                data.mobile_number = current_user.mobile_number
            if current_user.email:
                data.email = current_user.email

        # --- STAGE 9: DATA SAVED TO DATABASE ---
        if getattr(settings, "APP_ENV", "development") == "development":
            print("\n" + "=" * 24, flush=True)
            print("DATA SAVED TO DATABASE", flush=True)
            print("=" * 24, flush=True)
            print(json.dumps(data.model_dump(), indent=2, default=str), flush=True)
            print("=" * 24 + "\n", flush=True)

        submission = await service.create_submission(data)

        # Try updating Excel sheet dynamically using student's profile values directly from StudentSubmission
        try:
            excel_updates = {k: v for k, v in data.extracted_data.items() if v is not None}
            excel_updates["Student Name"] = submission.student_name
            excel_updates["Name"] = submission.student_name
            excel_updates["Register Number"] = submission.register_number
            excel_updates["Mobile Number"] = submission.mobile_number
            excel_updates["Mobile"] = submission.mobile_number
            if submission.email:
                excel_updates["Email"] = submission.email
                excel_updates["Email Address"] = submission.email

            if getattr(settings, "APP_ENV", "development") == "development":
                print("\n================ EXCEL WRITE VALUES ================", flush=True)
                print(json.dumps(excel_updates, indent=2, default=str), flush=True)
                print("===================================================\n", flush=True)

            await excel_template_service.append_or_update_student_row_in_excel(
                batch_id=data.batch_id,
                register_number=data.register_number,
                student_data=excel_updates,
            )
        except Exception as excel_err:
            print(f"Warning: Failed to update Excel workbook: {str(excel_err)}")

        return _to_response(submission)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


students_me_router = APIRouter(prefix="/students", tags=["Students"])


@students_me_router.get("/me", response_model=StudentProfileResponse)
async def get_students_me(current_user: User = Depends(get_current_user)):
    """
    Retrieve authenticated student profile derived from JWT token.
    Populates student_name, register_number, mobile_number, and email.
    Only allows users with role 'student'.
    """
    if current_user.role != UserRole.STUDENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current logged in user is not a student account.",
        )

    reg_num = current_user.register_number or current_user.username
    mob_num = current_user.mobile_number or ""
    return StudentProfileResponse(
        student_name=current_user.name,
        register_number=reg_num,
        mobile_number=mob_num,
        email=current_user.email,
    )


student_router = APIRouter(prefix="/student", tags=["Student"])

@student_router.get("/me", response_model=StudentProfileResponse)
async def get_student_me_alias(current_user: User = Depends(get_current_user)):
    """Alias for /students/me endpoint."""
    return await get_students_me(current_user)


@student_router.post("/verify", response_model=StudentIdentityVerifyResponse)
async def verify_student_identity(data: StudentIdentityVerifyRequest):
    import os, sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    def safe_print(msg: str):
        try:
            print(msg, flush=True)
        except Exception:
            try:
                ascii_msg = msg.encode('ascii', 'replace').decode('ascii')
                print(ascii_msg, flush=True)
            except Exception:
                pass

    # 1. Log Register Received
    safe_print("\n========================")
    safe_print("REGISTER RECEIVED")
    safe_print(data.register_number)
    safe_print("========================\n")

    safe_print(f"[Student Verification] Starting verification for token/slug: {data.token}")
    
    # 2. Upload link check
    try:
        link = await _upload_link_service.get_link_by_slug_or_token(data.token)
        safe_print("Upload Link Found ✅")
    except UploadLinkNotFoundException:
        safe_print("Upload Link Not Found ❌")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid upload link.",
        )

    # Validate active/expired for upload link
    if not link.is_active:
        safe_print("Upload Link Disabled ❌")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admission portal has been disabled.",
        )
        
    if link.expires_at is not None:
        now = datetime.now(timezone.utc)
        expires_at = link.expires_at.replace(tzinfo=timezone.utc) if link.expires_at.tzinfo is None else link.expires_at
        if expires_at < now:
            safe_print("Upload Link Expired ❌")
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Admission portal has expired.",
            )

    # 3. Batch check
    batch_id: str = link.batch_id
    if not batch_id:
        safe_print("Batch ID Missing on Link ❌")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid upload link.",
        )

    try:
        batch = await batch_service.get_batch_by_id(batch_id)
        safe_print("Batch Found ✅")
    except Exception:
        safe_print("Batch Not Found ❌")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid upload link.",
        )

    # Log Batch Info
    safe_print("\n========================")
    safe_print("BATCH")
    safe_print(f"ID     : {batch.id}")
    safe_print(f"Name   : {batch.name}")
    safe_print(f"Status : {batch.status}")
    safe_print("========================\n")

    # Check batch active status
    if batch.status != "active":
        safe_print(f"Batch Inactive ({batch.status}) ❌")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admission portal has been disabled.",
        )
    safe_print("Batch Active ✅")

    # 4. Excel Loaded check
    template_meta = await _excel_repo.get_by_batch_id(batch_id)
    if template_meta is None or not os.path.exists(template_meta.file_path):
        safe_print("Excel Template Missing ❌")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Student list has not been configured for this batch.",
        )
    safe_print("Excel Loaded ✅")

    # 5. Check for duplicate submission
    already_submitted = await service.check_duplicate_submission(batch_id, data.register_number)
    if already_submitted:
        safe_print("Duplicate Submission Detected ❌")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Documents have already been submitted for this Register Number.",
        )
    safe_print("Duplicate Check Passed ✅")
    safe_print("Student Verification Succeeded 🎉")

    return StudentIdentityVerifyResponse(
        batch_id=batch_id,
        batch_name=batch.name,
    )



