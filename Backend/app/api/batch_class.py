from fastapi import APIRouter, Depends, HTTPException, status
from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.models.batch_class import BatchClass
from app.models.student_submission import StudentSubmission
from app.schemas.batch_class import ClassCreate, ClassUpdate, ClassResponse, ClassStats
from app.services.batch_class_service import BatchClassService, ClassNotFoundException
from app.services.batch_service import BatchService, BatchNotFoundException

router = APIRouter(
    tags=["Batch Classes"],
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))],
)

def get_class_service() -> BatchClassService:
    return BatchClassService()

def get_batch_service() -> BatchService:
    return BatchService()

async def _verify_batch_department_access(batch_id: str, user: User, batch_service: BatchService):
    """Helper to verify department permissions on a batch."""
    if user.role == UserRole.DEPARTMENT_ADMIN:
        try:
            batch = await batch_service.get_batch_by_id(batch_id)
            if batch.department_id != user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to access another department's batch.",
                )
        except BatchNotFoundException:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Admission Batch with ID '{batch_id}' not found.",
            )


from app.models.student_document import StudentDocument
from app.models.upload_link import UploadLink


async def sync_batch_section_students(batch_id: str) -> list[BatchClass]:
    """
    Ensures authoritative student-to-section relationship for a batch:
    If a batch has exactly one section, any students in that batch without section_id
    are automatically assigned to that single section.
    """
    classes = await BatchClass.find(BatchClass.batch_id == batch_id).to_list()
    if len(classes) == 1:
        single_cls = classes[0]
        # Heal StudentSubmission
        all_subs = await StudentSubmission.find(StudentSubmission.batch_id == batch_id).to_list()
        for s in all_subs:
            if not s.class_id or s.class_id != single_cls.id or not s.class_name:
                s.class_id = single_cls.id
                s.class_name = single_cls.class_name
                await s.save()

        # Heal StudentDocument
        all_docs = await StudentDocument.find(StudentDocument.batch_id == batch_id).to_list()
        for d in all_docs:
            if not d.class_id or d.class_id != single_cls.id or not d.section_id:
                d.class_id = single_cls.id
                d.section_id = single_cls.id
                await d.save()

        # Heal UploadLink
        all_links = await UploadLink.find(UploadLink.batch_id == batch_id).to_list()
        for l in all_links:
            if not l.class_id or l.class_id != single_cls.id:
                l.class_id = single_cls.id
                await l.save()
    return classes


async def _get_canonical_class_submissions(cls: BatchClass) -> list[StudentSubmission]:
    """Retrieve distinct canonical student submissions belonging to this section."""
    all_classes = await sync_batch_section_students(cls.batch_id)
    if len(all_classes) == 1 and all_classes[0].id == cls.id:
        submissions = await StudentSubmission.find(StudentSubmission.batch_id == cls.batch_id).to_list()
    else:
        submissions = await StudentSubmission.find(
            StudentSubmission.batch_id == cls.batch_id,
            {"$or": [
                {"class_id": cls.id},
                {"class_name": cls.class_name},
            ]},
        ).to_list()

    # Deduplicate canonical students by register number (or id)
    distinct_students: dict[str, StudentSubmission] = {}
    for s in submissions:
        canon_key = (s.register_number or str(s.id)).strip().upper()
        if canon_key not in distinct_students:
            distinct_students[canon_key] = s
        else:
            if s.submission_status == "Verified" or len(s.documents or []) > len(distinct_students[canon_key].documents or []):
                distinct_students[canon_key] = s

    return list(distinct_students.values())


async def _build_class_response(cls: BatchClass) -> ClassResponse:
    """Build ClassResponse with section-isolated student statistics strictly from MongoDB."""
    canonical_subs = await _get_canonical_class_submissions(cls)
    total = len(canonical_subs)
    verified = sum(1 for s in canonical_subs if s.submission_status == "Verified")
    rejected = sum(1 for s in canonical_subs if s.submission_status == "Rejected")
    pending = total - verified - rejected
    return ClassResponse(
        id=cls.id,
        batch_id=cls.batch_id,
        class_name=cls.class_name,
        department=cls.department,
        section=cls.section,
        academic_year=cls.academic_year,
        stats=ClassStats(
            students=total,
            pending=max(0, pending),
            verified=verified,
            rejected=rejected,
        ),
        created_at=cls.created_at,
        updated_at=cls.updated_at,
    )


@router.post("/batches/{batch_id}/classes", response_model=ClassResponse, status_code=status.HTTP_201_CREATED)
async def create_class(
    batch_id: str,
    data: ClassCreate,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Create a new class inside a batch.
    """
    await _verify_batch_department_access(batch_id, current_user, batch_service)
    try:
        new_class = await service.create_class(batch_id, data)
        return await _build_class_response(new_class)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/batches/{batch_id}/classes", response_model=list[ClassResponse])
async def list_classes_by_batch(
    batch_id: str,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    List all classes for the selected batch with section-isolated student statistics.
    """
    await _verify_batch_department_access(batch_id, current_user, batch_service)
    classes = await service.get_classes_by_batch(batch_id)
    return [await _build_class_response(c) for c in classes]


@router.get("/classes/{class_id}", response_model=ClassResponse)
async def get_class_by_id(
    class_id: str,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Get class details with section-isolated student statistics.
    """
    try:
        class_doc = await service.get_class_by_id(class_id)
        await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)
        return await _build_class_response(class_doc)
    except ClassNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)


@router.get("/classes/{class_id}/stats", response_model=ClassStats)
async def get_class_stats(
    class_id: str,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Get statistics for a specific class (strictly filtered by batch_id and class_id).
    """
    class_doc = await service.get_class_by_id(class_id)
    await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)
    canonical_subs = await _get_canonical_class_submissions(class_doc)
    total = len(canonical_subs)
    verified = sum(1 for s in canonical_subs if s.submission_status == "Verified")
    rejected = sum(1 for s in canonical_subs if s.submission_status == "Rejected")
    pending = total - verified - rejected
    return ClassStats(
        students=total,
        pending=max(0, pending),
        verified=verified,
        rejected=rejected,
    )


@router.put("/classes/{class_id}", response_model=ClassResponse)
async def update_class(
    class_id: str,
    data: ClassUpdate,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Update class details.
    """
    try:
        class_doc = await service.get_class_by_id(class_id)
        await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)
        updated = await service.update_class(class_id, data)
        return await _build_class_response(updated)
    except ClassNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/classes/{class_id}")
async def delete_class(
    class_id: str,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Delete a class.
    """
    try:
        class_doc = await service.get_class_by_id(class_id)
        await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)
        await service.delete_class(class_id)
        return {"message": f"Class '{class_doc.class_name}' deleted successfully"}
    except ClassNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ==========================================
# CLASS-LEVEL ISOLATED SUB-RESOURCE ENDPOINTS
# ==========================================

from app.models.student_submission import StudentSubmission
from app.models.upload_link import UploadLink
from app.schemas.upload_link import UploadLinkCreate, UploadLinkResponse
from app.schemas.student_submission import StudentSubmissionResponse
from app.api.student_submission import _to_response
from app.services.doc_config_version_service import DocConfigVersionService
from fastapi import UploadFile, File, Form

doc_config_service = DocConfigVersionService()


@router.get("/classes/{class_id}/students", response_model=list[StudentSubmissionResponse])
async def get_class_students(
    class_id: str,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Get all students belonging to a specific class.
    """
    class_doc = await service.get_class_by_id(class_id)
    await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)
    canonical_subs = await _get_canonical_class_submissions(class_doc)
    return [_to_response(s) for s in canonical_subs]


@router.get("/classes/{class_id}/verification", response_model=list[StudentSubmissionResponse])
async def get_class_verification_queue(
    class_id: str,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Get verification queue for a specific class.
    """
    class_doc = await service.get_class_by_id(class_id)
    await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)
    canonical_subs = await _get_canonical_class_submissions(class_doc)
    return [_to_response(s) for s in canonical_subs]


@router.get("/classes/{class_id}/export")
async def get_class_export_data(
    class_id: str,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Get export metrics and data for a specific class.
    """
    class_doc = await service.get_class_by_id(class_id)
    await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)
    canonical_subs = await _get_canonical_class_submissions(class_doc)
    return {
        "class_id": class_id,
        "class_name": class_doc.class_name,
        "batch_id": class_doc.batch_id,
        "total_students": len(canonical_subs),
        "verified_students": len([s for s in canonical_subs if s.submission_status == "Verified"]),
    }


@router.post("/classes/{class_id}/upload-link", response_model=UploadLinkResponse, status_code=status.HTTP_201_CREATED)
async def create_class_upload_link(
    class_id: str,
    data: UploadLinkCreate,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Create a student upload portal link scoped to a specific class.
    """
    class_doc = await service.get_class_by_id(class_id)
    await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)

    import secrets
    token = secrets.token_urlsafe(8)
    slug = token

    link = UploadLink(
        department_id=data.department_id,
        batch_id=class_doc.batch_id,
        class_id=class_id,
        token=token,
        slug=slug,
        title=data.title,
        description=data.description,
        is_active=True,
        expires_at=data.expires_at,
        max_submissions=data.max_submissions,
        created_by=current_user.username,
    )
    await link.insert()
    return link


@router.get("/classes/{class_id}/upload-links", response_model=list[UploadLinkResponse])
async def list_class_upload_links(
    class_id: str,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    List all upload portal links created for a specific class.
    """
    class_doc = await service.get_class_by_id(class_id)
    await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)
    return await UploadLink.find(UploadLink.class_id == class_id).to_list()


@router.post("/classes/{class_id}/document-config")
async def create_class_document_config(
    class_id: str,
    documents: list[dict],
    change_summary: str | None = None,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Section-level document configuration is disabled.
    Document Configuration is managed at the Batch level.
    """
    class_doc = await service.get_class_by_id(class_id)
    await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Document Configuration is managed at the Batch level. All sections in batch '{class_doc.batch_id}' share the same document requirements. Please update document requirements at the Batch dashboard.",
    )


@router.get("/classes/{class_id}/document-config")
async def get_class_document_config(
    class_id: str,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Get the active shared batch document configuration version for a specific class/section.
    """
    class_doc = await service.get_class_by_id(class_id)
    await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)
    ver = await doc_config_service.get_or_create_current_version(class_doc.batch_id)
    return ver
