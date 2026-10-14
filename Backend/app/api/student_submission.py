from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query, Request
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
from app.core.dependencies import get_current_user, get_optional_current_user, RoleChecker
from app.core.rate_limiter import rate_limit
from app.models.user import User, UserRole
from app.schemas.user import StudentProfileResponse
from app.services.batch_service import BatchService
from app.services.student_document_service import StudentDocumentService
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

from app.services.excel_template_service import ExcelTemplateService

router = APIRouter(prefix="/student-submissions", tags=["Student Submissions"])
service = StudentSubmissionService()
batch_service = BatchService()
_upload_link_service = UploadLinkService()
_excel_service = ExcelTemplateService()

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
                "document_type": getattr(d, "document_type", None),
                "status": d.status,
                "file_path": d.file_path,
                "file_size_mb": d.file_size_mb,
                "file_type": d.file_type,
                "version": getattr(d, "version", 1) or 1,
                "uploaded_at": d.uploaded_at,
            }
            for d in s.documents
        ],
    )


def _to_public_response(s) -> StudentSubmissionResponse:
    """
    Sanitized submission response for public student portal resumption:
    - Never leaks internal server filesystem paths in document metadata.
    - Never exposes sensitive AI-extracted PII (Aadhaar, bank account details).
    """
    safe_docs = [
        {
            "document_name": d.document_name,
            "document_type": getattr(d, "document_type", None),
            "status": d.status,
            "file_path": None,  # Strictly omit internal server disk path
            "file_size_mb": d.file_size_mb,
            "file_type": d.file_type,
            "version": getattr(d, "version", 1) or 1,
            "uploaded_at": d.uploaded_at,
        }
        for d in s.documents
    ]
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
        extracted_data={},  # Do not leak extracted PII on unauthenticated public endpoint
        submitted_at=s.submitted_at,
        updated_at=s.updated_at,
        documents=safe_docs,
    )



@router.post("/verify-identity", response_model=StudentIdentityVerifyResponse)
async def verify_student_identity(data: StudentIdentityVerifyRequest):
    """
    Public endpoint — NO authentication required.

    Verifies that:
      1. The upload link token is valid and active.
      2. The register number has not already been submitted for this batch (no roster or pre-configured student lookup is performed).
      3. The student has not already completed a submission for this batch.

    On success, returns batch_id and batch_name so the frontend can create a
    temporary sessionStorage submission session. No JWT or auth cookie is issued.
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

    # 6. Get or create student submission (resumes existing submission if already present)
    class_id = getattr(link, "class_id", None)
    class_name = None
    from app.models.batch_class import BatchClass
    if not class_id:
        classes = await BatchClass.find(BatchClass.batch_id == batch_id).to_list()
        if len(classes) == 1:
            class_id = classes[0].id
            class_name = classes[0].class_name
    elif not class_name:
        class_doc = await BatchClass.get(class_id)
        if class_doc:
            class_name = class_doc.class_name

    submission = await service.get_or_create_student_submission(
        batch_id=batch_id,
        student_name=data.student_name,
        register_number=data.register_number,
        mobile_number=data.mobile_number,
        email=data.email,
        class_id=class_id,
        class_name=class_name,
        upload_link_id=str(link.id) if hasattr(link, "id") and link.id else None,
    )

    uploaded_docs = []
    if submission and submission.documents:
        from app.services.document_extraction_service import normalize_doc_type
        doc_service = StudentDocumentService()
        for d in submission.documents:
            norm_type = getattr(d, "document_type", None) or normalize_doc_type(d.document_name)
            std_doc = await doc_service.get_student_document_by_type(data.register_number.strip(), norm_type)

            ver_num = getattr(d, "version", 1) or 1
            cur_file = d.file_path
            cur_size = d.file_size_mb
            cur_name = None
            if std_doc and std_doc.active_version:
                ver_num = std_doc.active_version.version_number
                cur_file = std_doc.active_version.file_path
                cur_name = std_doc.active_version.original_filename
                if std_doc.active_version.file_size_bytes:
                    cur_size = round(std_doc.active_version.file_size_bytes / (1024 * 1024), 2)

            uploaded_docs.append(
                {
                    "id": str(std_doc.id) if std_doc else None,
                    "student_document_id": str(std_doc.id) if std_doc else None,
                    "document_name": d.document_name,
                    "document_type": norm_type,
                    "status": d.status,
                    "file_path": cur_file,
                    "filename": cur_name or (cur_file.replace("\\", "/").split("/")[-1] if cur_file else None),
                    "file_size_mb": cur_size,
                    "file_type": d.file_type,
                    "version": ver_num,
                    "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                }
            )

    return StudentIdentityVerifyResponse(
        batch_id=batch_id,
        batch_name=batch.name,
        class_id=class_id,
        class_name=class_name,
        upload_link_id=str(link.id) if hasattr(link, "id") and link.id else None,
        token=data.token,
        submission_id=str(submission.id),
        submission_status=submission.submission_status,
        uploaded_documents=uploaded_docs,
    )




@router.post("/upload", response_model=StudentSubmissionResponse, status_code=status.HTTP_201_CREATED)
async def upload_student_submission_documents(
    batch_id: str = Form(...),
    register_number: str = Form(...),
    student_name: str = Form(...),
    mobile_number: str | None = Form(None),
    email: str | None = Form(None),
    class_id: str | None = Form(None),
    class_name: str | None = Form(None),
    upload_link_id: str | None = Form(None),
    token: str | None = Form(None),
    documents_metadata: str | None = Form(None),
    files: list[UploadFile] = File([]),
):
    """
    Public endpoint: Receives and securely stores student admission documents.

    PRODUCT RULE (STORE ONCE, EXTRACT ONLY WHEN NEEDED):
    - Receives and persists uploaded document files to storage.
    - Creates/updates StudentSubmission, StudentDocument, and DocumentVersion (v1) records.
    - Status is marked as 'Submitted' / 'UPLOADED' / 'PENDING' validation.
    - STRICTLY NO AI processing, OCR, Gemini vision, extraction, or verification at upload time.
    """
    import json
    from pathlib import Path
    from app.utils.file_security import sanitize_filename, validate_uploaded_document
    from app.services.student_document_service import StudentDocumentService
    from app.services.document_extraction_service import normalize_doc_type
    from app.models.student_submission import StudentDocumentMeta

    clean_batch_id = batch_id.strip()
    clean_reg = register_number.strip()
    clean_name = student_name.strip()
    clean_mobile = mobile_number.strip() if mobile_number else ""
    clean_email = email.strip() if email else None
    eff_class_id = class_id.strip() if class_id else None
    eff_class_name = class_name.strip() if class_name else None

    # 1. Resolve and validate link token / link ID if provided
    if token or upload_link_id:
        link = None
        if token:
            link = await _upload_link_service.get_link_by_slug_or_token(token)
        elif upload_link_id:
            from bson import ObjectId
            from app.models.upload_link import UploadLink
            try:
                link = await UploadLink.get(ObjectId(upload_link_id))
            except Exception:
                link = None

        if link:
            if not link.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Upload link has been disabled.",
                )
            if link.expires_at is not None:
                now = datetime.now(timezone.utc)
                expires_at = link.expires_at.replace(tzinfo=timezone.utc) if link.expires_at.tzinfo is None else link.expires_at
                if expires_at < now:
                    raise HTTPException(
                        status_code=status.HTTP_410_GONE,
                        detail="Upload link has expired.",
                    )

            if link.batch_id:
                clean_batch_id = link.batch_id
            if link.class_id:
                eff_class_id = link.class_id
            if link.class_id and not eff_class_name:
                from app.models.batch_class import BatchClass
                c_doc = await BatchClass.get(link.class_id)
                if c_doc:
                    eff_class_name = c_doc.class_name
            upload_link_id = str(link.id)
            link.submission_count = (link.submission_count or 0) + 1
            await link.save()

    # 2. Validate batch exists
    batch = await batch_service.get_batch_by_id(clean_batch_id)
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admission batch not found.")

    if not eff_class_id:
        from app.models.batch_class import BatchClass
        classes = await BatchClass.find(BatchClass.batch_id == clean_batch_id).to_list()
        if len(classes) == 1:
            eff_class_id = classes[0].id
            eff_class_name = classes[0].class_name

    department_id = batch.department_id

    # 2.5 Global uniqueness and identity check: Verify student cannot overwrite or claim another student's register number
    from app.models.student_submission import StudentSubmission
    from app.utils.normalization import normalize_register_number, normalize_name
    norm_reg = normalize_register_number(clean_reg)
    existing_sub = await service.repository.get_by_normalized_register_number(norm_reg)
    if not existing_sub:
        existing_sub = await service.repository.get_by_register_number_global(clean_reg)

    if existing_sub:
        if existing_sub.batch_id != clean_batch_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Register number '{clean_reg}' is already assigned to a student.",
            )
        if existing_sub.student_name and clean_name:
            norm_existing_name = normalize_name(existing_sub.student_name) or existing_sub.student_name.strip().upper()
            norm_incoming_name = normalize_name(clean_name) or clean_name.strip().upper()
            if norm_existing_name != norm_incoming_name and existing_sub.student_name.strip().lower() != clean_name.lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Register number '{clean_reg}' is already assigned to a student.",
                )

    # 3. Parse document metadata list if provided
    meta_list = []
    if documents_metadata:
        try:
            parsed = json.loads(documents_metadata)
            if isinstance(parsed, list):
                meta_list = parsed
        except Exception:
            pass

    doc_service = StudentDocumentService()
    doc_metas: list[StudentDocumentMeta] = []

    # Filter meta_list for items representing new file uploads
    new_upload_metas = [m for m in meta_list if m.get("is_new_file") is True or m.get("file_index") is not None]
    if not new_upload_metas:
        new_upload_metas = [m for m in meta_list if m.get("status") == "Uploaded"]

    # Map each physical file strictly to its corresponding metadata item
    file_meta_map = {}
    for idx, f in enumerate(files):
        clean_fn = sanitize_filename(f.filename or f"document_{idx}.pdf")
        matched_meta = None

        # 1. Match by explicit file_index
        for m in meta_list:
            if m.get("file_index") == idx:
                matched_meta = m
                break

        # 2. Match by exact filename
        if not matched_meta:
            for m in meta_list:
                if m.get("filename") == f.filename or m.get("filename") == clean_fn:
                    matched_meta = m
                    break

        # 3. Match by index within new_upload_metas
        if not matched_meta and idx < len(new_upload_metas):
            matched_meta = new_upload_metas[idx]

        file_meta_map[idx] = matched_meta or {}

    # 4. Persist physical files and create/update StudentDocument + DocumentVersion
    for idx, f in enumerate(files):
        content = await f.read()
        clean_filename, mime_type = validate_uploaded_document(f.filename or f"doc_{idx}.pdf", content)

        m_info = file_meta_map.get(idx, {})
        doc_display_name = m_info.get("document_name") or Path(clean_filename).stem.replace("_", " ").title()
        raw_doc_type = m_info.get("document_type")
        if not raw_doc_type or raw_doc_type.upper() in ("MANDATORY", "OPTIONAL", "REQUIRED", "DISABLED"):
            raw_doc_type = doc_display_name

        doc_type = normalize_doc_type(raw_doc_type)
        if doc_type in ("MANDATORY", "OPTIONAL", "REQUIRED", "DISABLED", "OTHER") and doc_display_name:
            fallback_type = normalize_doc_type(doc_display_name)
            if fallback_type != "OTHER":
                doc_type = fallback_type

        doc_id_from_meta = m_info.get("document_id") or m_info.get("id")
        existing_doc = None
        if doc_id_from_meta:
            try:
                existing_doc = await doc_service.repository.get_by_id(str(doc_id_from_meta))
            except Exception:
                existing_doc = None

        if not existing_doc:
            existing_doc = await doc_service.get_student_document_by_type(clean_reg, doc_type)
        if not existing_doc and existing_sub:
            existing_doc = await doc_service.repository.get_by_submission_and_type(str(existing_sub.id), doc_type)

        target_dir = doc_service.get_document_storage_dir(clean_reg, doc_type, 1)
        target_path = target_dir / clean_filename
        with open(target_path, "wb") as out_f:
            out_f.write(content)

        file_size_mb = round(len(content) / (1024 * 1024), 2)

        # Replace existing StudentDocument or create initial record
        if existing_doc:
            updated_doc = await doc_service.replace_document_file(
                student_document_id=str(existing_doc.id),
                file_path=str(target_path),
                original_filename=clean_filename,
                file_size_bytes=len(content),
                mime_type=mime_type,
                uploaded_by=clean_reg,
                validation_status="PENDING",
            )
            version_num = 1
        else:
            created_doc = await doc_service.create_student_document(
                student_id=clean_reg,
                batch_id=clean_batch_id,
                document_type=doc_type,
                document_name=doc_display_name,
                class_id=eff_class_id,
                section_id=eff_class_id,
                department_id=department_id,
                submission_id=str(existing_sub.id) if existing_sub else None,
                initial_file_path=str(target_path),
                original_filename=clean_filename,
                file_size_bytes=len(content),
                mime_type=mime_type,
                status_value="UPLOADED",
                validation_status="PENDING",
            )
            version_num = 1

        doc_metas.append(
            StudentDocumentMeta(
                document_name=doc_display_name,
                document_type=doc_type,
                status="Uploaded",
                file_path=str(target_path),
                file_size_mb=file_size_mb,
                file_type=clean_filename.split(".")[-1].upper(),
                version=version_num,
                uploaded_at=datetime.now(timezone.utc),
            )
        )

    # 5. Add any waived / Not Available or preserved documents from metadata
    uploaded_doc_names = {d.document_name.strip().lower() for d in doc_metas}
    uploaded_doc_types = {d.document_type for d in doc_metas if d.document_type}

    for m in meta_list:
        doc_name = m.get("document_name")
        raw_type = m.get("document_type") or doc_name
        if not raw_type or raw_type.upper() in ("MANDATORY", "OPTIONAL", "REQUIRED", "DISABLED"):
            raw_type = doc_name
        m_doc_type = normalize_doc_type(raw_type) if raw_type else "OTHER"

        doc_name_key = (doc_name or "").strip().lower()
        if doc_name and doc_name_key not in uploaded_doc_names and m_doc_type not in uploaded_doc_types:
            if m.get("status") == "Not Available":
                doc_metas.append(
                    StudentDocumentMeta(
                        document_name=doc_name,
                        document_type=m_doc_type,
                        status="Not Available",
                        file_path=None,
                        file_size_mb=None,
                        file_type=None,
                        version=m.get("version", 1) or 1,
                        uploaded_at=datetime.now(timezone.utc),
                    )
                )
            elif m.get("status") == "Uploaded":
                existing_doc = await doc_service.get_student_document_by_type(clean_reg, m_doc_type)
                if not existing_doc and existing_sub:
                    existing_doc = await doc_service.repository.get_by_submission_and_type(str(existing_sub.id), m_doc_type)

                active_v = existing_doc.active_version if existing_doc else None
                f_path = active_v.file_path if active_v else m.get("file_path")
                f_name = active_v.original_filename if active_v else (m.get("filename") or f"{doc_name}.pdf")
                v_num = existing_doc.current_version if existing_doc else (m.get("version") or 1)

                doc_metas.append(
                    StudentDocumentMeta(
                        document_name=doc_name,
                        document_type=m_doc_type,
                        status="Uploaded",
                        file_path=str(f_path) if f_path else None,
                        file_size_mb=m.get("file_size_mb"),
                        file_type=f_name.split(".")[-1].upper() if f_name else "PDF",
                        version=v_num,
                        uploaded_at=active_v.uploaded_at if active_v else datetime.now(timezone.utc),
                    )
                )



    # 7. Create or update StudentSubmission (NO AI extraction called!)
    sub_data = StudentSubmissionCreate(
        batch_id=clean_batch_id,
        batch_name=batch.name,
        class_id=eff_class_id,
        class_name=eff_class_name,
        upload_link_id=upload_link_id,
        token=token,
        student_name=clean_name,
        register_number=clean_reg,
        mobile_number=clean_mobile,
        email=clean_email,
        submission_status="Submitted",
        documents=[
            {
                "document_name": d.document_name,
                "document_type": d.document_type,
                "status": d.status,
                "file_path": d.file_path,
                "file_size_mb": d.file_size_mb,
                "file_type": d.file_type,
                "version": d.version,
                "uploaded_at": d.uploaded_at,
            }
            for d in doc_metas
        ],
        extracted_data={},
    )

    submission = await service.create_submission(sub_data)
    return _to_response(submission)


@router.post("", response_model=StudentSubmissionResponse, status_code=status.HTTP_201_CREATED)
async def create_student_submission(data: StudentSubmissionCreate):
    """
    Submit student admission documents from public upload link.
    This endpoint remains public so students can upload documents without logging in.
    Persists submission to database and populates Excel workbook.
    """
    try:
        submission = await service.create_submission(data)
        return _to_response(submission)
    except HTTPException:
        raise
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

        from app.api.batch_class import sync_batch_section_students
        await sync_batch_section_students(batchId)

        submissions = await service.get_submissions_by_batch_id(batchId)
        return [_to_response(s) for s in submissions]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


from app.schemas.student_submission import StudentSectionAssignRequest

@router.put(
    "/{submission_id}/assign-section",
    response_model=StudentSubmissionResponse,
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))],
)
async def assign_student_section(
    submission_id: str,
    data: StudentSectionAssignRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Assign or reassign a student submission to a specific section/class in the batch.
    Synchronizes StudentSubmission and all corresponding StudentDocument records.
    """
    from app.models.batch_class import BatchClass
    from app.models.student_document import StudentDocument

    sub = await service.get_submission_by_id(submission_id)
    if current_user.role == UserRole.DEPARTMENT_ADMIN and sub.department_id != current_user.department_code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You do not have permission to modify another department's student.",
        )

    class_doc = await BatchClass.get(data.class_id.strip())
    if not class_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Class/Section '{data.class_id}' not found.")

    if class_doc.batch_id != sub.batch_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Class '{class_doc.class_name}' belongs to batch '{class_doc.batch_id}', not student's batch '{sub.batch_id}'.",
        )

    sub.class_id = class_doc.id
    sub.class_name = class_doc.class_name
    await sub.save()

    # Sync student documents
    docs = await StudentDocument.find(
        {"$or": [
            {"submission_id": str(sub.id)},
            {"student_id": sub.register_number, "batch_id": sub.batch_id},
        ]}
    ).to_list()
    for d in docs:
        d.class_id = class_doc.id
        d.section_id = class_doc.id
        await d.save()

    return _to_response(sub)


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

    # 9. Record audit log for preview/download
    try:
        from app.models.audit_log import AuditLog
        await AuditLog(
            action="DOCUMENT_PREVIEW",
            actor_user_id=str(current_user.id),
            actor_username=current_user.username,
            actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            submission_id=str(s.id),
            student_name=s.student_name,
            register_number=s.register_number,
            batch_id=s.batch_id,
            class_id=s.class_id,
            documents_count=1,
            result="SUCCESS",
            failure_info=f"Document: {doc.document_name}",
        ).insert()
    except Exception as log_err:
        pass

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


@router.get(
    "/{submission_id}/documents/download-all",
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))],
)
async def download_all_submission_documents(
    submission_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Download all available uploaded documents for a student submission combined into a single PDF.

    Security & Scope Chain:
      1. JWT required (401 if missing/invalid).
      2. RBAC: Restricted to staff (SUPER_ADMIN and DEPARTMENT_ADMIN). Students cannot access (403).
      3. Validates submission ownership from DB.
      4. Department isolation: DEPARTMENT_ADMIN can ONLY access their department's submissions (403).
      5. Skips unuploaded/unavailable/missing documents without creating empty pages.
      6. Raises 404 if no valid documents exist.
      7. Records an audit trail log entry for the action.
    """
    from fastapi.responses import Response
    from app.services.document_merge_service import DocumentMergeService, NoDocumentsAvailableException

    # 1. Load submission from DB
    try:
        s = await service.get_submission_by_id(submission_id)
    except StudentSubmissionNotFoundException:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found.")

    # 2. Scope check: DEPARTMENT_ADMIN can only access their department's submissions
    if current_user.role == UserRole.DEPARTMENT_ADMIN:
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

    # 3. Generate combined PDF
    try:
        pdf_bytes, filename, included_count = DocumentMergeService.generate_all_documents_pdf(s)
    except NoDocumentsAvailableException:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No documents available for download.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to process documents: {str(e)}",
        )

    # 4. Record audit log
    try:
        from app.models.audit_log import AuditLog
        await AuditLog(
            action="DOWNLOAD_ALL_DOCUMENTS",
            actor_user_id=str(current_user.id),
            actor_username=current_user.username,
            actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            submission_id=str(s.id),
            student_name=s.student_name,
            register_number=s.register_number,
            batch_id=s.batch_id,
            class_id=s.class_id,
            documents_count=included_count,
            result="SUCCESS",
        ).insert()
    except Exception as log_err:
        import logging
        logging.getLogger(__name__).warning(f"[download_all_submission_documents] Audit log error: {log_err}")

    # 5. Return PDF file response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Type": "application/pdf",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


# Alias router for /submissions prefix compatibility
submissions_alias_router = APIRouter(prefix="/submissions", tags=["Student Submissions (Alias)"])


@submissions_alias_router.get(
    "/{submission_id}/documents/download-all",
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))],
)
async def download_all_submission_documents_alias(
    submission_id: str,
    current_user: User = Depends(get_current_user),
):
    return await download_all_submission_documents(submission_id, current_user)


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

document_pipeline = DocumentProcessingPipeline()


@router.post(
    "/extract",
    dependencies=[Depends(rate_limit(max_requests=10, window_seconds=60))],
)
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
    Protected by sliding-window rate limiting to prevent automated quota abuse.
    """
    from app.utils.file_security import is_executable_content, MAX_DOCUMENT_FILE_SIZE_BYTES
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided for extraction.")
    for f in files:
        if f.filename and is_executable_content(f.filename, b""):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Executable file type forbidden: {f.filename}")

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


@router.post(
    "/extract-async",
    dependencies=[Depends(rate_limit(max_requests=10, window_seconds=60))],
)
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
    Protected by sliding-window rate limiting to prevent resource exhaustion.
    """
    from app.utils.file_security import is_executable_content
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided for extraction.")
    for f in files:
        if f.filename and is_executable_content(f.filename, b""):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Executable file type forbidden: {f.filename}")

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

    # 4. Get or create student submission (resumes existing submission if already present)
    safe_print("Student Verification Succeeded 🎉")

    class_id = getattr(link, "class_id", None)
    class_name = None
    if class_id:
        from app.models.batch_class import BatchClass
        class_doc = await BatchClass.get(class_id)
        if class_doc:
            class_name = class_doc.class_name

    submission = await service.get_or_create_student_submission(
        batch_id=batch_id,
        student_name=data.student_name,
        register_number=data.register_number,
        mobile_number=data.mobile_number,
        email=data.email,
        class_id=class_id,
        class_name=class_name,
        upload_link_id=str(link.id) if hasattr(link, "id") and link.id else None,
    )

    uploaded_docs = []
    if submission and submission.documents:
        from app.services.document_extraction_service import normalize_doc_type
        doc_service = StudentDocumentService()
        for d in submission.documents:
            norm_type = getattr(d, "document_type", None) or normalize_doc_type(d.document_name)
            std_doc = await doc_service.get_student_document_by_type(data.register_number.strip(), norm_type)

            ver_num = getattr(d, "version", 1) or 1
            cur_file = d.file_path
            cur_size = d.file_size_mb
            cur_name = None
            if std_doc and std_doc.active_version:
                ver_num = std_doc.active_version.version_number
                cur_file = std_doc.active_version.file_path
                cur_name = std_doc.active_version.original_filename
                if std_doc.active_version.file_size_bytes:
                    cur_size = round(std_doc.active_version.file_size_bytes / (1024 * 1024), 2)

            uploaded_docs.append(
                {
                    "document_name": d.document_name,
                    "document_type": norm_type,
                    "status": d.status,
                    "file_path": cur_file,
                    "filename": cur_name or (cur_file.replace("\\", "/").split("/")[-1] if cur_file else None),
                    "file_size_mb": cur_size,
                    "file_type": d.file_type,
                    "version": ver_num,
                    "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                }
            )

    return StudentIdentityVerifyResponse(
        batch_id=batch_id,
        batch_name=batch.name,
        class_id=class_id,
        class_name=class_name,
        upload_link_id=str(link.id) if hasattr(link, "id") and link.id else None,
        token=data.token,
        submission_id=str(submission.id),
        submission_status=submission.submission_status,
        uploaded_documents=uploaded_docs,
    )



@router.get(
    "/public/{submission_id}",
    response_model=StudentSubmissionResponse,
    dependencies=[Depends(rate_limit(max_requests=30, window_seconds=60))],
)
@submissions_alias_router.get(
    "/public/{submission_id}",
    response_model=StudentSubmissionResponse,
    dependencies=[Depends(rate_limit(max_requests=30, window_seconds=60))],
)
@student_router.get(
    "/submissions/{submission_id}",
    response_model=StudentSubmissionResponse,
    dependencies=[Depends(rate_limit(max_requests=30, window_seconds=60))],
)
async def get_public_student_submission(
    submission_id: str,
    request: Request,
    token: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """
    Secure lookup for a student's submission to allow resuming their document session on the frontend.
    Enforces staff authorization or a valid scoped student verification/upload session.
    Returns sanitized data without internal filesystem paths or raw extracted PII.
    """
    try:
        s = await service.get_submission_by_id(submission_id)
        if not s:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found.")
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found.")

    is_authorized = False

    # 1. Staff authorization check
    if current_user:
        if current_user.role == UserRole.SUPER_ADMIN:
            is_authorized = True
        elif current_user.role == UserRole.DEPARTMENT_ADMIN:
            if (
                current_user.department_code
                and s.department_id
                and str(s.department_id).strip().upper() == str(current_user.department_code).strip().upper()
            ):
                is_authorized = True
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to access another department's student submission.",
                )
        elif current_user.role == UserRole.STUDENT:
            user_reg = current_user.register_number or current_user.username
            if user_reg and (
                user_reg.strip().upper() == (s.register_number or "").strip().upper()
                or str(current_user.id) == s.student_id
            ):
                is_authorized = True

    # 2. Scoped student session validation (via token query param or headers)
    if not is_authorized:
        req_token = (
            token
            or request.headers.get("x-verification-token")
            or request.headers.get("x-upload-token")
            or request.query_params.get("session_token")
        )
        if req_token:
            clean_tok = req_token.strip()
            # a) Check active VerificationToken
            from app.models.verification_token import VerificationToken
            v_token = await VerificationToken.find_one(VerificationToken.token == clean_tok)
            if v_token and v_token.is_valid:
                if v_token.submission_id == str(s.id) or (
                    v_token.student_id
                    and s.register_number
                    and v_token.student_id.strip().upper() == s.register_number.strip().upper()
                    and v_token.batch_id == s.batch_id
                ):
                    is_authorized = True

            # b) Check active UploadLink
            if not is_authorized:
                from app.models.upload_link import UploadLink
                u_link = await UploadLink.find_one(
                    {"$or": [{"token": clean_tok}, {"slug": clean_tok}]}
                )
                if u_link and u_link.is_active:
                    if u_link.batch_id == s.batch_id:
                        is_authorized = True

    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Access to this student submission requires staff authentication or a valid scoped session token.",
        )

    return _to_public_response(s)



@student_router.get("/{slug}", response_model=UploadLinkResponse)
async def get_student_upload_link_endpoint(slug: str):
    """
    Resolve upload portal link details for student by token or slug.
    Delegates to the verified upload link lookup logic in app.api.upload_link.
    """
    from app.api.upload_link import get_upload_link_by_slug
    return await get_upload_link_by_slug(slug, _upload_link_service)
