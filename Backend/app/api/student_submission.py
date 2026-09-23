from datetime import datetime, timezone
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
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
from app.schemas.upload_link import UploadLinkResponse
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

import asyncio
from app.models.document_job import (
    DocumentProcessingJob,
    JobStatus,
    SubmissionSession,
    SubmissionProcessingStatus,
)
from app.services.document_worker_pool import DocumentWorkerPool

router = APIRouter(prefix="/student-submissions", tags=["Student Submissions"])
service = StudentSubmissionService()
batch_service = BatchService()
_upload_link_service = UploadLinkService()
_excel_service = ExcelTemplateService()
_excel_repo = ExcelTemplateRepository()

# Per-batch lock guaranteeing safe serialized Excel workbook updates under high concurrency
_excel_write_locks: dict[str, tuple[asyncio.Lock, Any]] = {}

def _get_batch_excel_lock(batch_id: str) -> asyncio.Lock:
    clean_id = (batch_id or "").strip()
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    entry = _excel_write_locks.get(clean_id)
    if entry is None or entry[1] != current_loop:
        lock = asyncio.Lock()
        _excel_write_locks[clean_id] = (lock, current_loop)
        return lock
    return entry[0]


def _to_response(s) -> StudentSubmissionResponse:
    return StudentSubmissionResponse(
        id=str(s.id),
        batch_id=s.batch_id,
        batch_name=s.batch_name,
        class_id=getattr(s, "class_id", None),
        class_name=getattr(s, "class_name", None),
        upload_link_id=getattr(s, "upload_link_id", None),
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
        upload_link_id=str(link.id) if hasattr(link, "id") and link.id else None,
        token=data.token,
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


@router.get(
    "/{submission_id}/documents/{document_index}/file",
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN, UserRole.STUDENT]))],
)
async def serve_submission_document(
    submission_id: str,
    document_index: int,
    current_user: User = Depends(get_current_user),
):
    """
    Securely serve an uploaded student document file for authenticated staff or the student owner.

    Authorization chain:
      1. JWT required (401 if missing/invalid).
      2. RBAC: SUPER_ADMIN, DEPARTMENT_ADMIN, or student owner.
      3. Submission ownership: loads the submission from DB — never client-trusted.
      4. Student isolation: Students can ONLY access their own submissions.
      5. Department isolation: DEPARTMENT_ADMIN can ONLY access their department's submissions.
      6. Document bounds check: document_index must be within range.
      7. File existence & readability check: verified physical file on disk (non-zero bytes).

    Never exposes raw filesystem paths, MongoDB IDs, or internal storage details to the client.
    """
    import mimetypes
    import re
    from fastapi.responses import FileResponse
    from app.utils.storage_resolver import resolve_document_file_path

    # 1. Load submission from DB (trust DB, not client-supplied path)
    try:
        s = await service.get_submission_by_id(submission_id)
    except StudentSubmissionNotFoundException:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found.")

    # 2. RBAC isolation
    if current_user.role == UserRole.STUDENT:
        user_reg = current_user.register_number or current_user.username
        if not user_reg or (s.register_number != user_reg):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not have permission to view another student's documents.",
            )
    elif current_user.role == UserRole.DEPARTMENT_ADMIN:
        dept_id = s.department_id
        if not dept_id and s.batch_id:
            try:
                from app.models.batch import AdmissionBatch
                b = await AdmissionBatch.get(s.batch_id)
                if b:
                    dept_id = b.department_id
            except Exception:
                pass
        if dept_id and dept_id != current_user.department_code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not have permission to access another department's resources.",
            )

    # 3. Validate document index
    if document_index < 0 or document_index >= len(s.documents):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    doc = s.documents[document_index]

    # 4. Ensure document was actually uploaded
    if doc.status != "Uploaded" or not doc.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file not available.",
        )

    # 5. Resolve verified physical file on disk
    resolved_path = resolve_document_file_path(
        raw_path=doc.file_path,
        batch_id=s.batch_id,
        register_number=s.register_number,
        document_name=doc.document_name,
    )
    if not resolved_path or not resolved_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file not found on server.",
        )

    # 6. Verify file is readable and not zero bytes
    try:
        file_size = resolved_path.stat().st_size
        if file_size == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document file is empty (0 bytes).",
            )
        # Check readability
        with open(resolved_path, "rb") as f:
            f.read(1024)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file is unreadable.",
        )

    # 7. Determine media type from file extension
    file_ext = resolved_path.suffix.lower()
    media_type_map = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(file_ext) or mimetypes.guess_type(str(resolved_path))[0] or "application/octet-stream"

    # 8. Safe filename for Content-Disposition (no path exposure)
    clean_name = re.sub(r'[^a-zA-Z0-9_-]', '_', doc.document_name)
    safe_filename = f"{clean_name}{file_ext}"

    return FileResponse(
        path=str(resolved_path),
        media_type=media_type,
        filename=safe_filename,
        headers={
            "Content-Disposition": f'inline; filename="{safe_filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


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


@router.delete(
    "/{id}",
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))],
)
async def delete_student_submission(
    id: str,
    batch_id: str | None = Query(None),
    class_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
):
    """
    Permanently and safely delete a student submission and linked data.
    Enforces staff authorization, active processing checks, file reference counting, and audit logging.
    Students cannot delete records.
    """
    try:
        result = await service.delete_student_submission(
            id, current_user, batch_id=batch_id, class_id=class_id
        )
        if not result.get("success", True):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("message", "Student deletion requires cleanup retry. Please contact an administrator."),
            )
        return result
    except HTTPException:
        raise
    except StudentSubmissionNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unable to delete this student: {str(e)}")


from app.services.document_processing_pipeline import DocumentProcessingPipeline

excel_template_service = ExcelTemplateService()
document_pipeline = DocumentProcessingPipeline()


@router.post("/extract")
async def extract_student_documents(
    batch_id: str = Form(...),
    register_number: str = Form(...),
    student_name: str = Form(...),
    mobile_number: str | None = Form(None),
    email: str | None = Form(None),
    files: list[UploadFile] = File(...),
    force_refresh: bool = Form(False),
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
            email=email,
            files=files,
            force_refresh=force_refresh,
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Extraction Endpoint Error] {e}", flush=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/extract-async")
async def extract_student_documents_async(
    batch_id: str = Form(...),
    register_number: str = Form(...),
    student_name: str = Form(...),
    mobile_number: str | None = Form(None),
    email: str | None = Form(None),
    files: list[UploadFile] = File(...),
    force_refresh: bool = Form(False),
):
    """
    Asynchronous Multi-Student Document Extraction endpoint.
    Absorbs spikes by saving isolated uploads and queuing jobs into MongoDB.
    Returns immediately with submission_id for frontend polling.
    """
    try:
        worker_pool = DocumentWorkerPool.get_instance()
        submission_id = await worker_pool.enqueue_submission(
            batch_id=batch_id,
            register_number=register_number,
            student_name=student_name,
            mobile_number=mobile_number,
            email=email,
            files=files,
            force_refresh=force_refresh,
        )
        return {
            "status": "QUEUED",
            "submission_id": submission_id,
            "message": "Documents enqueued for concurrent extraction.",
        }
    except Exception as e:
        print(f"[Extract Async Error] {e}", flush=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{submission_id}/status")
async def get_submission_processing_status(submission_id: str):
    """
    Poll processing status of a multi-document submission session.
    Provides live overall status, completion counters, and per-document breakdown.
    """
    session = await SubmissionSession.find_one(SubmissionSession.submission_id == submission_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission session not found.")

    jobs = await DocumentProcessingJob.find(
        DocumentProcessingJob.submission_id == submission_id
    ).sort("+created_at").to_list()

    docs_status = [
        {
            "job_id": j.job_id,
            "document_name": j.document_name,
            "document_type": j.document_type or "UNKNOWN",
            "status": j.status.value if hasattr(j.status, "value") else str(j.status),
            "error": j.error_info,
        }
        for j in jobs
    ]

    status_str = session.status.value if hasattr(session.status, "value") else str(session.status)

    return {
        "submission_id": session.submission_id,
        "status": status_str,
        "total_documents": session.total_documents,
        "completed_documents": session.completed_documents,
        "failed_documents": session.failed_documents,
        "documents": docs_status,
        "verification_fields": session.verification_fields,
        "extracted_data": session.verification_fields,
        "detected_documents": session.detected_documents,
    }


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

        # Resolve section and batch strictly on the server from upload link token / ID
        if data.token or data.upload_link_id:
            try:
                link = None
                if data.token:
                    link = await _upload_link_service.get_link_by_slug_or_token(data.token)
                elif data.upload_link_id:
                    from bson import ObjectId
                    try:
                        from app.models.upload_link import UploadLink
                        link = await UploadLink.get(ObjectId(data.upload_link_id))
                    except Exception:
                        link = None

                if link:
                    if link.batch_id:
                        data.batch_id = link.batch_id
                    if link.class_id:
                        data.class_id = link.class_id
                    data.upload_link_id = str(link.id)
                    if link.class_id and not data.class_name:
                        from app.models.batch_class import BatchClass
                        class_doc = await BatchClass.get(link.class_id)
                        if class_doc:
                            data.class_name = class_doc.class_name

                    link.submission_count = (link.submission_count or 0) + 1
                    await link.save()
            except Exception as link_resolve_err:
                print(f"[confirm_student_submission] Warning resolving link: {link_resolve_err}", flush=True)

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

            batch_excel_lock = _get_batch_excel_lock(data.batch_id)
            async with batch_excel_lock:
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
        import traceback
        traceback.print_exc()
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
        upload_link_id=str(link.id) if hasattr(link, "id") and link.id else None,
        token=data.token,
    )


@student_router.get("/{slug}", response_model=UploadLinkResponse)
async def get_student_upload_link_endpoint(slug: str):
    """
    Resolve upload portal link details for student by token or slug.
    Delegates to the verified upload link lookup logic in app.api.upload_link.
    """
    from app.api.upload_link import get_upload_link_by_slug
    return await get_upload_link_by_slug(slug, _upload_link_service)




