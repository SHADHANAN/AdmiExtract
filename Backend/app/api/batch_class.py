from fastapi import APIRouter, Depends, HTTPException, status
from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.schemas.batch_class import ClassCreate, ClassUpdate, ClassResponse
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
        return await service.create_class(batch_id, data)
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
    List all classes for the selected batch.
    """
    await _verify_batch_department_access(batch_id, current_user, batch_service)
    return await service.get_classes_by_batch(batch_id)


@router.get("/classes/{class_id}", response_model=ClassResponse)
async def get_class_by_id(
    class_id: str,
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Get class details.
    """
    try:
        class_doc = await service.get_class_by_id(class_id)
        await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)
        return class_doc
    except ClassNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)


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
        return await service.update_class(class_id, data)
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
from app.services.excel_template_service import ExcelTemplateService
from app.services.doc_config_version_service import DocConfigVersionService
from fastapi import UploadFile, File, Form

excel_template_service = ExcelTemplateService()
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
    submissions = await StudentSubmission.find(StudentSubmission.class_id == class_id).to_list()
    if not submissions:
        submissions = await StudentSubmission.find(
            StudentSubmission.batch_id == class_doc.batch_id,
            StudentSubmission.class_name == class_doc.class_name
        ).to_list()
    return [_to_response(s) for s in submissions]


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
    submissions = await StudentSubmission.find(StudentSubmission.class_id == class_id).to_list()
    return [_to_response(s) for s in submissions]


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
    submissions = await StudentSubmission.find(StudentSubmission.class_id == class_id).to_list()
    template = await excel_template_service.get_template_by_batch(class_doc.batch_id, class_id=class_id)
    return {
        "class_id": class_id,
        "class_name": class_doc.class_name,
        "batch_id": class_doc.batch_id,
        "total_students": len(submissions),
        "verified_students": len([s for s in submissions if s.submission_status == "Verified"]),
        "excel_template": {
            "id": str(template.id),
            "batch_id": template.batch_id,
            "class_id": template.class_id,
            "template_filename": template.template_filename,
            "total_rows": template.total_rows,
            "updated_count": template.updated_count,
            "headers": template.headers,
            "field_mappings": template.field_mappings,
        } if template else None,
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


@router.post("/classes/{class_id}/excel-template")
async def upload_class_excel_template(
    class_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    service: BatchClassService = Depends(get_class_service),
    batch_service: BatchService = Depends(get_batch_service),
):
    """
    Upload and register an Excel template scoped to a specific class.
    """
    class_doc = await service.get_class_by_id(class_id)
    await _verify_batch_department_access(class_doc.batch_id, current_user, batch_service)
    return await excel_template_service.upload_template(class_doc.batch_id, file, class_id=class_id)

