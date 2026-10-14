from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, File, Form, UploadFile
from beanie import PydanticObjectId

from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.models.student_document import StudentDocument, DocumentVersion
from app.models.document_extraction_request import (
    DocumentExtractionRequest,
    ExtractionRequestStatus,
)
from app.schemas.student_document import (
    StudentDocumentResponse,
    DocumentVersionResponse,
    CreateDocumentVersionRequest,
    ReclassifyDocumentRequest,
    DocumentClassificationResponse,
)
from app.schemas.document_extraction import (
    ExtractDocumentRequest,
    DocumentExtractionRequestResponse,
)
from app.services.student_document_service import StudentDocumentService
from app.services.document_extraction_service import DocumentExtractionService

router = APIRouter(prefix="/student-documents", tags=["Student Documents"])
service = StudentDocumentService()
extraction_service = DocumentExtractionService()


def _to_version_response(v: DocumentVersion) -> DocumentVersionResponse:
    return DocumentVersionResponse(
        version_id=v.version_id,
        version_number=v.version_number,
        file_path=v.file_path,
        original_filename=v.original_filename,
        file_size_bytes=v.file_size_bytes,
        mime_type=v.mime_type,
        uploaded_at=v.uploaded_at,
        uploaded_by=v.uploaded_by,
        validation_status=v.validation_status,
        validation_reason=v.validation_reason,
        expected_document_type=v.expected_document_type,
        detected_document_type=v.detected_document_type,
        classification_confidence=v.classification_confidence,
        classification_evidence=v.classification_evidence or [],
        classifier_version=v.classifier_version,
        classified_at=v.classified_at,
        reclassification_history=v.reclassification_history or [],
        is_active=v.is_active,
        extraction_reference=v.extraction_reference,
        created_at=v.created_at,
    )


def _to_doc_response(doc: StudentDocument) -> StudentDocumentResponse:
    versions_resp = [_to_version_response(v) for v in doc.versions]
    active_v = doc.active_version
    active_resp = _to_version_response(active_v) if active_v else None
    return StudentDocumentResponse(
        id=str(doc.id),
        student_id=doc.student_id,
        batch_id=doc.batch_id,
        class_id=doc.class_id,
        section_id=doc.section_id,
        department_id=doc.department_id,
        document_type=doc.document_type,
        document_name=doc.document_name,
        expected_document_type=doc.expected_document_type,
        detected_document_type=doc.detected_document_type,
        classification_confidence=doc.classification_confidence,
        classification_evidence=doc.classification_evidence or [],
        reclassification_history=doc.reclassification_history or [],
        current_version=doc.current_version,
        active_version_id=doc.active_version_id,
        status=doc.status,
        active_version=active_resp,
        versions=versions_resp,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )



# Specific subpaths before generic {student_id} / {document_type} paths


@router.get(
    "/{student_document_id}/versions",
    response_model=List[DocumentVersionResponse],
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                    UserRole.STUDENT,
                ]
            )
        )
    ],
)
async def get_document_versions(
    student_document_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve the immutable version history of a StudentDocument.
    """
    versions = await service.get_version_history(
        student_document_id=student_document_id,
        current_user=current_user,
    )
    return [_to_version_response(v) for v in versions]


@router.get(
    "/{student_document_id}/versions/{version_id}/file",
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                    UserRole.STUDENT,
                ]
            )
        )
    ],
)
async def serve_student_document_version_file(
    student_document_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Securely serve a specific version of a StudentDocument.
    Enforces RBAC, Student Ownership, and Department Isolation.
    """
    import mimetypes
    import re
    from fastapi.responses import FileResponse
    from app.utils.storage_resolver import resolve_document_file_path
    from app.models.audit_log import AuditLog

    doc = await service.repository.get_by_id(student_document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student document not found.")

    service._verify_user_access(doc, current_user)

    target_version = None
    for v in doc.versions:
        if v.version_id == version_id:
            target_version = v
            break

    if not target_version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found.")

    resolved_path = resolve_document_file_path(
        raw_path=target_version.file_path,
        batch_id=doc.batch_id,
        register_number=doc.student_id,
        document_name=doc.document_name,
    )
    if not resolved_path or not resolved_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found on server.")

    try:
        if resolved_path.stat().st_size == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file is empty (0 bytes).")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file is unreadable.")

    file_ext = resolved_path.suffix.lower()
    media_type_map = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(file_ext) or mimetypes.guess_type(str(resolved_path))[0] or "application/octet-stream"

    # Look up actual student name from StudentSubmission or User record
    student_name = None
    if getattr(doc, "submission_id", None):
        try:
            from app.models.student_submission import StudentSubmission
            sub = await StudentSubmission.get(doc.submission_id)
            if sub and sub.student_name:
                student_name = sub.student_name
        except Exception:
            pass

    if not student_name and doc.student_id:
        try:
            from app.models.student_submission import StudentSubmission
            sub = await StudentSubmission.find_one(
                StudentSubmission.register_number == doc.student_id,
                StudentSubmission.batch_id == doc.batch_id,
            )
            if sub and sub.student_name:
                student_name = sub.student_name
        except Exception:
            pass

    if not student_name and doc.student_id:
        try:
            from app.models.user import User
            u = await User.find_one(User.register_number == doc.student_id)
            if not u:
                u = await User.find_one(User.username == doc.student_id)
            if u and u.name:
                student_name = u.name
        except Exception:
            pass

    from app.utils.file_security import format_document_download_filename, build_content_disposition_header
    safe_filename = format_document_download_filename(
        register_number=doc.student_id,
        student_name=student_name,
        document_name=doc.document_name,
        original_filename_or_ext=resolved_path.name or file_ext,
    )
    content_disp = build_content_disposition_header(safe_filename, disposition_type="inline")

    try:
        await AuditLog(
            action="STUDENT_DOCUMENT_VERSION_PREVIEW",
            actor_user_id=str(current_user.id),
            actor_username=current_user.username,
            actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            submission_id=str(doc.id),
            student_name=student_name or f"Student_{doc.student_id}",
            register_number=str(doc.student_id),
            batch_id=doc.batch_id,
            class_id=doc.class_id,
            documents_count=1,
            result="SUCCESS",
            failure_info=f"Version: {target_version.version_number} | Doc: {doc.document_name} | File: {safe_filename}",
        ).insert()
    except Exception:
        pass

    return FileResponse(
        path=str(resolved_path),
        media_type=media_type,
        filename=safe_filename,
        headers={
            "Content-Disposition": content_disp,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/{student_document_id}/file",
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                    UserRole.STUDENT,
                ]
            )
        )
    ],
)
async def serve_student_document_active_file(
    student_document_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Securely serve the active version file of a StudentDocument.
    """
    doc = await service.repository.get_by_id(student_document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student document not found.")

    active_v = doc.active_version
    if not active_v:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active version found for document.")

    return await serve_student_document_version_file(
        student_document_id=student_document_id,
        version_id=active_v.version_id,
        current_user=current_user,
    )


@router.post(
    "/{student_document_id}/upload-version",
    response_model=StudentDocumentResponse,
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                ]
            )
        )
    ],
)
async def upload_document_version_file(
    student_document_id: str,
    file: UploadFile = File(...),
    validation_status: Optional[str] = Form("PENDING"),
    validation_reason: Optional[str] = Form(None),
    set_active: bool = Form(True),
    current_user: User = Depends(get_current_user),
):
    """
    Direct multipart file upload to replace the file for an existing StudentDocument in-place.
    """
    from app.utils.file_security import sanitize_filename, is_executable_content, MAX_DOCUMENT_FILE_SIZE_BYTES

    doc = await service.repository.get_by_id(student_document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student document not found.")

    service._verify_user_access(doc, current_user)

    clean_filename = sanitize_filename(file.filename or "uploaded_document.pdf")
    content = await file.read()
    if len(content) > MAX_DOCUMENT_FILE_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File exceeds 25MB maximum size limit.")
    if is_executable_content(clean_filename, content):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Executable files are forbidden.")

    target_dir = service.get_document_storage_dir(doc.student_id, doc.document_type, 1)
    target_path = target_dir / clean_filename
    with open(target_path, "wb") as f:
        f.write(content)

    updated_doc = await service.replace_document_file(
        student_document_id=student_document_id,
        file_path=str(target_path),
        original_filename=clean_filename,
        file_size_bytes=len(content),
        mime_type=file.content_type or "application/octet-stream",
        uploaded_by=current_user.username,
        validation_status=validation_status or "PENDING",
        validation_reason=validation_reason,
        actor=current_user,
    )
    return _to_doc_response(updated_doc)


@router.post(
    "/upload",
    response_model=StudentDocumentResponse,
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                ]
            )
        )
    ],
)
async def upload_initial_or_new_document(
    student_id: str = Form(...),
    batch_id: str = Form(...),
    document_type: str = Form(...),
    document_name: str = Form(...),
    class_id: Optional[str] = Form(None),
    section_id: Optional[str] = Form(None),
    department_id: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Direct multipart file upload to create a new StudentDocument or replace the file if one already exists.
    """
    from app.utils.file_security import sanitize_filename, is_executable_content, MAX_DOCUMENT_FILE_SIZE_BYTES

    clean_filename = sanitize_filename(file.filename or "uploaded_document.pdf")
    content = await file.read()
    if len(content) > MAX_DOCUMENT_FILE_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File exceeds 25MB maximum size limit.")
    if is_executable_content(clean_filename, content):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Executable files are forbidden.")

    from app.services.document_extraction_service import normalize_doc_type
    norm_doc_type = normalize_doc_type(document_type)

    existing_doc = await service.get_student_document_by_type(student_id, norm_doc_type, current_user)
    if existing_doc:
        target_dir = service.get_document_storage_dir(student_id, norm_doc_type, 1)
        target_path = target_dir / clean_filename
        with open(target_path, "wb") as f:
            f.write(content)

        updated_doc = await service.replace_document_file(
            student_document_id=str(existing_doc.id),
            file_path=str(target_path),
            original_filename=clean_filename,
            file_size_bytes=len(content),
            mime_type=file.content_type or "application/octet-stream",
            uploaded_by=current_user.username,
            validation_status="VALID",
            actor=current_user,
        )
        return _to_doc_response(updated_doc)

    target_dir = service.get_document_storage_dir(student_id, norm_doc_type, 1)
    target_path = target_dir / clean_filename
    with open(target_path, "wb") as f:
        f.write(content)

    new_doc = await service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        document_type=norm_doc_type,
        document_name=document_name,
        class_id=class_id,
        section_id=section_id,
        department_id=department_id,
        initial_file_path=str(target_path),
        original_filename=clean_filename,
        file_size_bytes=len(content),
        mime_type=file.content_type or "application/octet-stream",
        validation_status="VALID",
        status="UPLOADED",
        actor=current_user,
    )
    return _to_doc_response(new_doc)


@router.post(
    "/{student_document_id}/versions",
    response_model=StudentDocumentResponse,
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                ]
            )
        )
    ],
)
async def create_document_version(
    student_document_id: str,
    req: CreateDocumentVersionRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Create a new immutable version for an existing StudentDocument.
    Appends the new version with incremented version number, preserving previous versions.
    """
    doc = await service.add_new_version(
        student_document_id=student_document_id,
        file_path=req.file_path,
        original_filename=req.original_filename,
        file_size_bytes=req.file_size_bytes,
        mime_type=req.mime_type,
        uploaded_by=current_user.username,
        validation_status=req.validation_status or "PENDING",
        validation_reason=req.validation_reason,
        set_active=req.set_active,
        extraction_reference=req.extraction_reference,
        actor=current_user,
    )
    return _to_doc_response(doc)


@router.post(
    "/{student_document_id}/reclassify",
    response_model=StudentDocumentResponse,
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                ]
            )
        )
    ],
)
async def reclassify_student_document(
    student_document_id: str,
    req: ReclassifyDocumentRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Staff-only reclassification operation.
    Updates the document canonical classification type while preserving immutable audit logs & history.
    """
    doc = await service.reclassify_document(
        student_document_id=student_document_id,
        new_document_type=req.document_type,
        reason=req.reason,
        actor=current_user,
        version_id=req.version_id,
    )
    return _to_doc_response(doc)



@router.post(
    "/{student_document_id}/extract",
    response_model=DocumentExtractionRequestResponse,
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                ]
            )
        )
    ],
)
async def extract_student_document_fields(
    student_document_id: str,
    req: ExtractDocumentRequest,
    current_user: User = Depends(get_current_user),
):
    """
    On-demand requested-field extraction for a stored student document version.
    Extracts ONLY the requested fields without re-uploading the file.
    """
    request_rec, result_rec = await extraction_service.request_and_extract_fields(
        student_document_id=student_document_id,
        requested_fields=req.requested_fields,
        actor=current_user,
        version_id=req.version_id,
    )

    extracted_data = result_rec.extracted_data if result_rec else None
    return DocumentExtractionRequestResponse(
        extraction_request_id=str(request_rec.id),
        student_document_id=request_rec.student_document_id,
        document_version_id=request_rec.document_version_id,
        student_id=request_rec.student_id,
        document_type=request_rec.document_type,
        requested_fields=request_rec.requested_fields,
        status=request_rec.status.value if isinstance(request_rec.status, ExtractionRequestStatus) else str(request_rec.status),
        requested_by=request_rec.requested_by,
        requested_at=request_rec.requested_at,
        started_at=request_rec.started_at,
        completed_at=request_rec.completed_at,
        failed_at=request_rec.failed_at,
        error_message=request_rec.error_message,
        extraction_result_id=request_rec.extraction_result_id,
        extracted_data=extracted_data,
    )


@router.get(
    "/{student_document_id}/classification",
    response_model=DocumentClassificationResponse,
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                ]
            )
        )
    ],
)
async def get_document_classification(
    student_document_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve document classification diagnostic details, evidence, and validation status.
    """
    doc = await service.repository.get_by_id(student_document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student document '{student_document_id}' not found.",
        )
    service._verify_user_access(doc, current_user)

    # Resolve student metadata
    student_name = None
    register_number = str(doc.student_id)
    try:
        from app.models.student_submission import StudentSubmission
        sub = await StudentSubmission.find_one(StudentSubmission.register_number == doc.student_id)
        if sub:
            student_name = sub.student_name
            register_number = sub.register_number
    except Exception:
        pass

    active_v = doc.active_version or (doc.versions[-1] if doc.versions else None)

    return DocumentClassificationResponse(
        document_id=str(doc.id),
        student_id=doc.student_id,
        student_name=student_name,
        register_number=register_number,
        batch_id=doc.batch_id,
        class_id=doc.class_id,
        department_id=doc.department_id,
        document_type=doc.document_type,
        document_name=doc.document_name,
        expected_document_type=active_v.expected_document_type if active_v else doc.expected_document_type,
        detected_document_type=active_v.detected_document_type if active_v else doc.detected_document_type,
        classification_confidence=active_v.classification_confidence if active_v else doc.classification_confidence,
        validation_status=active_v.validation_status if active_v else "PENDING",
        validation_reason=active_v.validation_reason if active_v else None,
        classification_evidence=(active_v.classification_evidence if active_v else doc.classification_evidence) or [],
        classifier_version=active_v.classifier_version if active_v else "v2.0-ai-hybrid",
        classified_at=active_v.classified_at if active_v else None,
        reclassification_history=(active_v.reclassification_history if active_v else doc.reclassification_history) or [],
        current_version=doc.current_version,
        active_version_id=doc.active_version_id,
        original_filename=active_v.original_filename if active_v else None,
        file_path=active_v.file_path if active_v else None,
        file_size_bytes=active_v.file_size_bytes if active_v else 0,
        uploaded_at=active_v.uploaded_at if active_v else None,
    )


@router.post(
    "/{student_document_id}/reclassify",
    response_model=StudentDocumentResponse,
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                ]
            )
        )
    ],
)
async def reclassify_student_document(
    student_document_id: str,
    req: ReclassifyDocumentRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Staff-only reclassification of a student document.
    Updates classification metadata, preserves audit history with reviewer and timestamp.
    """
    if not req.document_type or not req.document_type.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_type is required for reclassification.",
        )

    updated_doc = await service.reclassify_document(
        student_document_id=student_document_id,
        new_document_type=req.document_type.strip(),
        reason=req.reason or "Manual staff reclassification",
        version_id=req.version_id,
        actor=current_user,
    )
    return _to_doc_response(updated_doc)


@router.get(
    "/{student_document_id}/extractions",
    response_model=List[DocumentExtractionRequestResponse],
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                ]
            )
        )
    ],
)
async def get_document_extractions(
    student_document_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve historical extraction requests for a given student document.
    """
    requests = await extraction_service.get_document_extractions(
        student_document_id=student_document_id,
        actor=current_user,
    )
    return [
        DocumentExtractionRequestResponse(
            extraction_request_id=str(r.id),
            student_document_id=r.student_document_id,
            document_version_id=r.document_version_id,
            student_id=r.student_id,
            document_type=r.document_type,
            requested_fields=r.requested_fields,
            status=r.status.value if isinstance(r.status, ExtractionRequestStatus) else str(r.status),
            requested_by=r.requested_by,
            requested_at=r.requested_at,
            started_at=r.started_at,
            completed_at=r.completed_at,
            failed_at=r.failed_at,
            error_message=r.error_message,
            extraction_result_id=r.extraction_result_id,
            extracted_data=None,
        )
        for r in requests
    ]


@router.get(
    "/{student_id}",
    response_model=List[StudentDocumentResponse],
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                    UserRole.STUDENT,
                ]
            )
        )
    ],
)
async def get_student_documents(
    student_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve all managed StudentDocuments for a given student ID.
    Enforces student isolation and department tenancy.
    """
    docs = await service.get_student_documents(student_id=student_id, current_user=current_user)
    return [_to_doc_response(d) for d in docs]


@router.get(
    "/{student_id}/{document_type}",
    response_model=StudentDocumentResponse,
    dependencies=[
        Depends(
            RoleChecker(
                [
                    UserRole.SUPER_ADMIN,
                    UserRole.DEPARTMENT_ADMIN,
                    UserRole.STUDENT,
                ]
            )
        )
    ],
)
async def get_student_document_by_type(
    student_id: str,
    document_type: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve a specific document for a student by canonical document type (e.g. AADHAAR).
    """
    doc = await service.get_student_document_by_type(
        student_id=student_id,
        document_type=document_type,
        current_user=current_user,
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document of type '{document_type}' not found for student '{student_id}'.",
        )
    return _to_doc_response(doc)
