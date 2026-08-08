from fastapi import APIRouter, HTTPException, status, Depends
from app.schemas.doc_config_version import (
    DocConfigVersionCreate,
    DocConfigVersionResponse,
    DocRequirementSchema,
)
from app.services.doc_config_version_service import DocConfigVersionService
from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.services.batch_service import BatchService

router = APIRouter(
    prefix="/batches",
    tags=["Document Versioning"],
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))],
)
service = DocConfigVersionService()
batch_service = BatchService()


async def _verify_batch_access(batch_id: str, user: User):
    """Helper to verify department access for doc configurations."""
    if user.role == UserRole.DEPARTMENT_ADMIN:
        try:
            batch = await batch_service.get_batch_by_id(batch_id)
            if batch.department_id != user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to access this department's configuration.",
                )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch with ID '{batch_id}' not found.",
            )


@router.get("/{batchId}/doc-versions/current", response_model=DocConfigVersionResponse)
async def get_current_doc_version(
    batchId: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve current active document configuration version for an Admission Batch.
    """
    await _verify_batch_access(batchId, current_user)
    
    v = await service.get_or_create_current_version(batchId)
    return DocConfigVersionResponse(
        id=str(v.id),
        batch_id=v.batch_id,
        version=v.version,
        documents=[
            DocRequirementSchema(
                id=d.id,
                name=d.name,
                required=d.required,
                allowed_types=d.allowed_types,
                max_size_mb=d.max_size_mb,
                description=d.description,
                type=d.type,
                extraction_fields=d.extraction_fields,
            )
            for d in v.documents
        ],
        is_current=v.is_current,
        change_summary=v.change_summary,
        created_by=v.created_by,
        created_at=v.created_at,
    )


@router.get("/{batchId}/doc-versions", response_model=list[DocConfigVersionResponse])
async def get_doc_version_history(
    batchId: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve version history (Version 1, Version 2...) for an Admission Batch.
    """
    await _verify_batch_access(batchId, current_user)

    history = await service.get_version_history(batchId)
    return [
        DocConfigVersionResponse(
            id=str(v.id),
            batch_id=v.batch_id,
            version=v.version,
            documents=[
                DocRequirementSchema(
                    id=d.id,
                    name=d.name,
                    required=d.required,
                    allowed_types=d.allowed_types,
                    max_size_mb=d.max_size_mb,
                    description=d.description,
                    type=d.type,
                    extraction_fields=d.extraction_fields,
                )
                for d in v.documents
            ],
            is_current=v.is_current,
            change_summary=v.change_summary,
            created_by=v.created_by,
            created_at=v.created_at,
        )
        for v in history
    ]


@router.post("/{batchId}/doc-versions", response_model=DocConfigVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_new_doc_version(
    batchId: str,
    payload: DocConfigVersionCreate,
    current_user: User = Depends(get_current_user),
):
    """
    Staff update: Create a new document configuration version (e.g. Version 2).
    Does NOT modify existing student submissions or snapshots.
    """
    await _verify_batch_access(batchId, current_user)

    try:
        new_v = await service.create_new_version(
            batch_id=batchId,
            documents=payload.documents,
            change_summary=payload.change_summary,
            created_by=current_user.username,
        )
        return DocConfigVersionResponse(
            id=str(new_v.id),
            batch_id=new_v.batch_id,
            version=new_v.version,
            documents=[
                DocRequirementSchema(
                    id=d.id,
                    name=d.name,
                    required=d.required,
                    allowed_types=d.allowed_types,
                    max_size_mb=d.max_size_mb,
                    description=d.description,
                    type=d.type,
                    extraction_fields=d.extraction_fields,
                )
                for d in new_v.documents
            ],
            is_current=new_v.is_current,
            change_summary=new_v.change_summary,
            created_by=new_v.created_by,
            created_at=new_v.created_at,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create document configuration version: {str(e)}",
        )


@router.get("/{batchId}/extraction-fields")
async def get_batch_extraction_fields_route(batchId: str):
    """
    Retrieve unique document extraction fields derived from active document configuration for a batch.
    """
    fields = await service.get_batch_extraction_fields(batchId)
    return {
        "batch_id": batchId,
        "extraction_fields": fields,
    }


