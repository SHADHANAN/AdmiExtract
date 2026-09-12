from datetime import datetime, timezone
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
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


from app.services.document_processing_pipeline import DocumentProcessingPipeline

excel_template_service = ExcelTemplateService()
document_pipeline = DocumentProcessingPipeline()


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
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
        except Exception as excel_err:
            print(f"[confirm_student_submission Excel Error] Warning: Failed to update Excel workbook: {excel_err}", flush=True)

        return _to_response(submission)
    except HTTPException:
        raise
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



