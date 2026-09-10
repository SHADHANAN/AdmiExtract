from datetime import datetime, timezone
from typing import Any, Dict
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
        class_id=getattr(s, "class_id", None),
        class_name=getattr(s, "class_name", None),
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

    class_id = getattr(link, "class_id", None)
    class_name = None
    if class_id:
        from app.models.batch_class import BatchClass
        class_doc = await BatchClass.get(class_id)
        if class_doc:
            class_name = class_doc.class_name

    return StudentIdentityVerifyResponse(
        batch_id=batch_id,
        batch_name=batch.name,
        class_id=class_id,
        class_name=class_name,
    )


@router.post("", response_model=StudentSubmissionResponse, status_code=status.HTTP_201_CREATED)
async def create_student_submission(data: StudentSubmissionCreate):
    """
    Submit student admission documents from public upload link.
    This endpoint remains public so students can upload documents without logging in.
<<<<<<< HEAD
    Persists submission to database and populates Excel workbook.
    """
    try:
        submission = await service.create_submission(data)

        # Update Excel workbook dynamically
        try:
            excel_updates = {k: v for k, v in (data.extracted_data or {}).items() if v is not None}
            excel_updates["Student Name"] = submission.student_name
            excel_updates["Name"] = submission.student_name
            excel_updates["Register Number"] = submission.register_number
            excel_updates["Mobile Number"] = submission.mobile_number
            excel_updates["Mobile"] = submission.mobile_number
            if submission.email:
                excel_updates["Email"] = submission.email
                excel_updates["Email Address"] = submission.email

            await excel_template_service.append_or_update_student_row_in_excel(
                batch_id=data.batch_id,
                register_number=data.register_number,
                student_data=excel_updates,
                class_id=data.class_id,
            )
        except Exception as excel_err:
            print(f"[create_student_submission Excel Error] {excel_err}", flush=True)

=======
    """
    try:
        submission = await service.create_submission(data)
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
        return _to_response(submission)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


<<<<<<< HEAD

=======
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
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
<<<<<<< HEAD
from app.services.document_processing_pipeline import DocumentProcessingPipeline

excel_template_service = ExcelTemplateService()
document_pipeline = DocumentProcessingPipeline()
=======

excel_template_service = ExcelTemplateService()
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4


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
<<<<<<< HEAD
    Orchestrates Google Gemini multimodal AI vision extraction, resilient OCR,
    cross-document attribute fusion, administrative lookups, and adaptive Excel field mapping.
    """
    try:
        return await document_pipeline.process_student_documents(
            batch_id=batch_id,
            register_number=register_number,
            student_name=student_name,
            mobile_number=mobile_number,
            files=files,
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Extraction Endpoint Error] {e}", flush=True)
=======
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

            if doc_type == "UNKNOWN":
                safe_log(f"[Document Classifier] Document type for '{filename}' is UNKNOWN. Skipping target field extraction.")
                extracted_fields_per_document[filename] = {}
                continue

            # Determine target fields authorized for this specific document type
            authorized_doc_fields = [tf for tf in target_fields if is_document_authorized_for_field(doc_type, tf)]

            if not authorized_doc_fields:
                safe_log(f"[Document Authority Guard] No target fields authorized for document type {doc_type} in {filename}. Skipping AI extraction.")
                extracted_fields_per_document[filename] = {}
                continue

            # Expand authorized target fields with semantic aliases for this document extraction
            expanded_doc_fields: list[str] = []
            for tf in authorized_doc_fields:
                aliases = get_aliases_for_header(tf)
                for a in aliases[:4]:
                    if a not in expanded_doc_fields:
                        expanded_doc_fields.append(a)

            # Perform Regex Extraction
            regex_results = preprocessor.extract_regex_fields(clean_ocr)
            ocr_addr_obj = preprocessor.extract_address_from_ocr(clean_ocr) or preprocessor.extract_address_from_ocr(raw_ocr)

            # Perform AI Extraction strictly for target fields authorized for this document
            doc_extracted = ai_service.extract(
                document_type=doc_type,
                ocr_text=raw_ocr,
                required_fields=expanded_doc_fields,
            )

            # Integrate Regex & Aadhaar Numbers ONLY if document is AADHAAR
            if doc_type == "AADHAAR":
                aadhaar_matches = re.findall(r"\b([2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4})\b", clean_ocr)
                valid_aadhaar = None
                for match in aadhaar_matches:
                    clean_digits = re.sub(r"\D", "", match)
                    if len(clean_digits) == 12:
                        valid_aadhaar = f"{clean_digits[:4]} {clean_digits[4:8]} {clean_digits[8:]}"
                        break

                if valid_aadhaar:
                    doc_extracted["Aadhaar Card"] = {"value": valid_aadhaar, "confidence": 100}
                    doc_extracted["Aadhaar Number"] = {"value": valid_aadhaar, "confidence": 100}

                # Address Fallback & Integration for Aadhaar
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
                    final_addr_obj = {"value": "NO", "confidence": 0}

                if final_addr_obj.get("value"):
                    doc_extracted["Address"] = final_addr_obj
                    doc_extracted["Full Address"] = final_addr_obj
                    doc_extracted["Permanent Address"] = final_addr_obj
                    doc_extracted["Residential Address"] = final_addr_obj

            if isinstance(regex_results, dict):
                for k, v in regex_results.items():
                    if is_document_authorized_for_field(doc_type, k):
                        if k not in doc_extracted or not doc_extracted[k].get("value"):
                            doc_extracted[k] = v

            doc_extracted_filtered = {k: v for k, v in (doc_extracted or {}).items() if not is_profile_field(k)}
            extracted_fields_per_document[filename] = doc_extracted_filtered

            # Collect Candidates into candidate_pool for authorized target Excel fields ONLY
            for tf in authorized_doc_fields:
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
                            if val is not None and str(val).strip() != "" and str(val).strip().lower() not in ["null", "none", "n/a", "not detected"]:
                                matched_val = val
                                matched_conf = conf
                                break
                    if matched_val is not None:
                        break

                if matched_val is not None:
                    candidate_pool[tf].append({
                        "source_file": filename,
                        "doc_type": doc_type,
                        "value": matched_val,
                        "confidence": matched_conf,
                    })

            # Merge into all_extracted_pool keeping non-null / highest confidence values
            for k, v in doc_extracted_filtered.items():
                if is_document_authorized_for_field(doc_type, k):
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

        from app.utils.field_canonicalizer import (
            is_profile_field,
            is_field_belonging_to_optional_doc,
            is_optional_requirement,
            get_doc_type_for_requirement,
            is_yes_no_question_field,
            normalize_yes_no_value,
            parse_location_components_from_address,
            is_address_field,
            infer_gender_from_salutation,
        )

        doc_reqs = active_version.documents if (active_version and active_version.documents) else []

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

            # Check if field belongs to an OPTIONAL document requirement
            is_opt_field, opt_doc_type = is_field_belonging_to_optional_doc(header, doc_reqs)

            if is_opt_field and opt_doc_type:
                # Rule 2 & Rule 6: If an OPTIONAL document is not uploaded by the student:
                # Do not attempt OCR/LLM. Return every field belonging to that document as {"value": "No", "confidence": 0}
                if opt_doc_type not in detected_documents:
                    safe_log(f"\nField : {header}")
                    safe_log(f"Allowed Documents : {opt_doc_type} (OPTIONAL)")
                    safe_log(f"Searching : Optional document ({opt_doc_type}) NOT uploaded by student")
                    safe_log("Result : Optional Document Not Uploaded")
                    safe_log("Final : No (confidence=0)")
                    verification_fields[header] = {"value": "No", "confidence": 0}
                    continue

            allowed_sources = get_allowed_sources_for_field(header)
            allowed_str = ", ".join(allowed_sources) if allowed_sources else "None"

            safe_log(f"\nField : {header}")
            safe_log(f"Allowed Documents : {allowed_str}")

            # Check if an uploaded document matching allowed_sources exists
            matching_doc_uploaded = any(dt in allowed_sources for dt in detected_documents)

            if not matching_doc_uploaded:
                safe_log(f"Searching : Allowed document type(s) ({allowed_str}) NOT uploaded by student")
                safe_log("Result : Missing Document")
                if is_opt_field:
                    safe_log("Final : No (confidence=0)")
                    verification_fields[header] = {"value": "No", "confidence": 0}
                else:
                    safe_log("Final : NO (confidence=0)")
                    verification_fields[header] = {"value": "NO", "confidence": 0}
                continue

            candidates = candidate_pool.get(header, [])

            # Filter candidates strictly by allowed document types
            valid_candidates = [
                c for c in candidates
                if c.get("doc_type") in allowed_sources
            ]

            # Rule 6 Guard: If field belongs to an optional document, only allow candidates from that specific optional doc
            if is_opt_field and opt_doc_type:
                valid_candidates = [c for c in valid_candidates if c.get("doc_type") == opt_doc_type]

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
                safe_log(f"Searching : {allowed_str} (Uploaded)")
                safe_log("Result : Field Absent in Source Document")
                # Rule 3: Document uploaded but field absent inside it -> NO, confidence 0
                safe_log("Final : NO (confidence=0)")
                verification_fields[header] = {"value": "NO", "confidence": 0}

        from app.utils.field_canonicalizer import (
            ADDRESS_SOURCE_PRIORITY,
            is_profile_field,
            is_field_belonging_to_optional_doc,
            is_optional_requirement,
            get_doc_type_for_requirement,
            is_yes_no_question_field,
            normalize_yes_no_value,
            parse_location_components_from_address,
            is_address_field,
        )

        DOC_TYPE_LABELS: Dict[str, str] = {
            "AADHAAR": "Aadhaar Card",
            "RESIDENCE": "Residence Certificate",
            "RESIDENCE_CERTIFICATE": "Residence Certificate",
            "NATIVITY": "Nativity Certificate",
            "COMMUNITY": "Community Certificate",
            "TRANSFER_CERTIFICATE": "Transfer Certificate",
            "INCOME": "Income Certificate",
            "PASSPORT": "Passport",
            "DRIVING_LICENCE": "Driving Licence",
            "DRIVING_LICENSE": "Driving Licence",
            "VOTER_ID": "Voter ID",
            "BONAFIDE": "Bonafide Certificate",
            "MIGRATION": "Migration Certificate",
        }

        # 1. Priority-Based Address Source Document Selection
        selected_address_doc = None
        selected_address_str = None

        for priority_doc_type in ADDRESS_SOURCE_PRIORITY:
            if priority_doc_type in detected_documents:
                # Search candidate pool for candidates from this document type
                for cand_field in ["Address", "Full Address", "Permanent Address", "Communication Address", "Postal Address", "Residential Address"]:
                    cands = candidate_pool.get(cand_field, [])
                    match = next((c for c in cands if c.get("doc_type") == priority_doc_type and c.get("value")), None)
                    if match:
                        selected_address_doc = priority_doc_type
                        selected_address_str = match.get("value")
                        break

                if not selected_address_str:
                    # Fallback search inside extracted_fields_per_document
                    for fname, doc_ext in extracted_fields_per_document.items():
                        for k_addr, v_item in (doc_ext or {}).items():
                            if is_address_field(k_addr) and isinstance(v_item, dict) and v_item.get("value"):
                                selected_address_doc = priority_doc_type
                                selected_address_str = v_item.get("value")
                                break
                        if selected_address_str:
                            break

            if selected_address_str:
                break

        # 2. Debug Logging according to Requirement 7
        doc_label = "None"
        if selected_address_doc == "AADHAAR":
            doc_label = "Aadhaar Card"
        elif selected_address_doc:
            label = DOC_TYPE_LABELS.get(selected_address_doc, selected_address_doc.title().replace("_", " "))
            if "AADHAAR" in detected_documents:
                doc_label = label
            else:
                doc_label = f"{label} (Aadhaar not uploaded)"

        derived_loc = parse_location_components_from_address(str(selected_address_str)) if selected_address_str else {}

        v_val = derived_loc.get("Village", {}).get("value")
        t_val = derived_loc.get("Taluk", {}).get("value")
        d_val = derived_loc.get("District", {}).get("value")
        s_val = derived_loc.get("State", {}).get("value")
        p_val = derived_loc.get("Pincode", {}).get("value")

        safe_log("\n==================== ADDRESS PARSING & DERIVATION ====================")
        safe_log(f"Address Source: {doc_label}")
        safe_log(f"Parsed Address: {selected_address_str}")
        safe_log(f"Village: {v_val}")
        safe_log(f"Taluk: {t_val}")
        safe_log(f"District: {d_val}")
        safe_log(f"State: {s_val}")
        safe_log(f"Pincode: {p_val}")
        safe_log("======================================================================\n")

        # 3. Derive location components and populate address & location fields ONLY from selected_address_doc
        address_location_fields = [
            h for h in list(verification_fields.keys())
            if is_address_field(h) or any(c in h.lower() for c in ["village", "vtc", "town", "taluk", "tehsil", "tk", "district", "dist", "dt", "state", "pincode", "pin code", "postal code", "pin"])
        ]

        if selected_address_str:
            for header in address_location_fields:
                if is_profile_field(header):
                    continue

                h_lower = header.strip().lower()

                if is_address_field(header):
                    verification_fields[header] = {"value": str(selected_address_str), "confidence": 100}

                elif any(k in h_lower for k in ["village", "vtc", "town"]):
                    verification_fields[header] = derived_loc.get("Village", {"value": "NO", "confidence": 0})

                elif any(k in h_lower for k in ["taluk", "tehsil", "tk"]):
                    verification_fields[header] = derived_loc.get("Taluk", {"value": "NO", "confidence": 0})

                elif any(k in h_lower for k in ["district", "dist", "dt"]):
                    verification_fields[header] = derived_loc.get("District", {"value": "NO", "confidence": 0})

                elif any(k in h_lower for k in ["state"]):
                    verification_fields[header] = derived_loc.get("State", {"value": "NO", "confidence": 0})

                elif any(k in h_lower for k in ["pincode", "pin code", "postal code", "pin"]):
                    verification_fields[header] = derived_loc.get("Pincode", {"value": "NO", "confidence": 0})

        else:
            # No uploaded document contains a valid address
            for header in address_location_fields:
                if not is_profile_field(header):
                    verification_fields[header] = {"value": "NO", "confidence": 0}




        # Post-processing normalization for Aadhaar Number (without space)
        for k in list(verification_fields.keys()):
            if "aadhaar" in k.lower() and "without space" in k.lower():
                val = verification_fields[k].get("value")
                if val:
                    clean_val = re.sub(r"\D", "", str(val))
                    verification_fields[k]["value"] = clean_val

        # Post-processing normalization for Communication Address Same As Permanent Address
        comm_same_key = next((k for k in verification_fields.keys() if "communication address same as" in k.lower()), None)
        if comm_same_key:
            perm_val = None
            for pk in ["Permanent Address", "Address", "Full Address", "Communication address"]:
                if pk in verification_fields and isinstance(verification_fields[pk], dict) and verification_fields[pk].get("value"):
                    perm_val = verification_fields[pk].get("value")
                    break

            raw_val = verification_fields[comm_same_key].get("value")
            if perm_val or (raw_val and len(str(raw_val)) > 10):
                verification_fields[comm_same_key] = {"value": "Yes", "confidence": 100}

        # Post-processing normalization for EMIS ID Available flag
        emis_avail_key = next((k for k in verification_fields.keys() if "emis" in k.lower() and ("available" in k.lower() or "is " in k.lower())), None)
        emis_val_key = next((k for k in verification_fields.keys() if k.strip().lower() in ["emis id", "emis_id", "emis no"]), None)
        if emis_avail_key and emis_val_key:
            if verification_fields[emis_val_key].get("value"):
                verification_fields[emis_avail_key] = {"value": "Yes", "confidence": 100}

        # Normalize ALL Yes/No question fields strictly to 'Yes', 'No', or 'NO' if missing
        for header, item in list(verification_fields.items()):
            if is_yes_no_question_field(header):
                current_val = item.get("value") if isinstance(item, dict) else item
                current_conf = item.get("confidence", 0) if isinstance(item, dict) else 0
                norm_val = normalize_yes_no_value(current_val)
                if norm_val:
                    verification_fields[header] = {"value": norm_val, "confidence": current_conf if current_conf == 0 else 100}
                else:
                    verification_fields[header] = {"value": "NO", "confidence": 0}

        # Execute Smart Lookup Engine Layer (OCR -> AI Extraction -> Smart Lookup Engine -> Verification)
        from app.services.smart_lookup_service import SmartLookupEngine
        lookup_engine = SmartLookupEngine()
        verification_fields = lookup_engine.process_lookup(
            verification_fields=verification_fields,
            all_extracted_pool=all_extracted_pool,
            detected_documents=detected_documents,
        )

        # Structured Field Extraction & Inference Audit Logs
        safe_log("\n==================== FIELD INFERENCE & EXTRACTION AUDIT ====================")
        for header, item in verification_fields.items():
            val = item.get("value") if isinstance(item, dict) else item
            conf = item.get("confidence", 0) if isinstance(item, dict) else 0
            src = item.get("source") if isinstance(item, dict) else None
            rule = item.get("rule_applied") if isinstance(item, dict) else None

            safe_log(f"Field: {header}")
            if val and str(val).upper() not in ["NO", "NULL"] and conf > 0:
                if src:
                    safe_log(f"Source: {src}")
                elif any(k in header.lower() for k in ["village", "vtc", "town", "taluk", "tehsil", "tk", "district", "dist", "dt", "state", "pincode", "pin code", "postal code", "pin"]) or is_address_field(header):
                    addr_src = f"{doc_label} Address" if doc_label != "None" else "Address Proof"
                    safe_log(f"Source: {addr_src}")
                else:
                    allowed_sources = get_allowed_sources_for_field(header)
                    doc_str = ", ".join(allowed_sources) if allowed_sources else "Document Extraction"
                    safe_log(f"Source: {doc_str}")

                if rule:
                    safe_log(f"Rule Applied: {rule}")
                elif any(k in header.lower() for k in ["village", "vtc", "town", "taluk", "tehsil", "tk", "district", "dist", "dt", "state", "pincode", "pin code", "postal code", "pin"]) or is_address_field(header):
                    safe_log("Rule Applied: Address Parsing")
                else:
                    safe_log("Rule Applied: Direct Extraction")
            else:
                safe_log("Source: Not Found")
                safe_log("Returned: NO")
            safe_log("")
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
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
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
                class_id=data.class_id,
            )
<<<<<<< HEAD
        except HTTPException as http_exc:
            print(f"[confirm_student_submission Excel Error] HTTPException: {http_exc.detail}", flush=True)
            raise http_exc
        except Exception as excel_err:
            print(f"[confirm_student_submission Excel Error] Unexpected error updating workbook: {excel_err}", flush=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Submission created, but failed to write to Excel workbook: {str(excel_err)}",
            )

        return _to_response(submission)
    except HTTPException:
        raise
=======
        except Exception as excel_err:
            print(f"Warning: Failed to update Excel workbook: {str(excel_err)}")

        return _to_response(submission)
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
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
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
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
    if not link.batch_id:
        safe_print("Batch ID Missing on Link ❌")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid upload link.",
        )
    batch_id: str = link.batch_id

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

    class_id = getattr(link, "class_id", None)
    class_name = None
    if class_id:
        from app.models.batch_class import BatchClass
        class_doc = await BatchClass.get(class_id)
        if class_doc:
            class_name = class_doc.class_name

    return StudentIdentityVerifyResponse(
        batch_id=batch_id,
        batch_name=batch.name,
        class_id=class_id,
        class_name=class_name,
    )



