from fastapi import APIRouter, Depends, HTTPException, status
from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.schemas.batch import BatchCreate, BatchUpdate, BatchResponse
from app.services.batch_service import BatchService, BatchNotFoundException

router = APIRouter(
    prefix="/batches",
    tags=["Admission Batches"],
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))],
)


def get_batch_service() -> BatchService:
    return BatchService()


@router.post("", response_model=BatchResponse, status_code=status.HTTP_201_CREATED)
async def create_batch(
    data: BatchCreate,
    current_user: User = Depends(get_current_user),
    service: BatchService = Depends(get_batch_service),
):
    # Department Admin can only create batches for their own department
    if current_user.role == UserRole.DEPARTMENT_ADMIN:
        if not current_user.department_code or data.department_id != current_user.department_code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You can only create admission batches for your assigned department.",
            )

    try:
        return await service.create_batch(data, created_by=current_user.username)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("", response_model=list[BatchResponse])
async def list_batches(
    current_user: User = Depends(get_current_user),
    service: BatchService = Depends(get_batch_service),
):
    # Department Admin can only see their department's batches
    if current_user.role == UserRole.DEPARTMENT_ADMIN:
        if not current_user.department_code:
            return []
        return await service.get_batches_by_department(current_user.department_code)
    
    # Super Admin can see all batches
    return await service.get_all_batches()


@router.get("/{batchId}", response_model=BatchResponse)
async def get_batch_by_id(
    batchId: str,
    current_user: User = Depends(get_current_user),
    service: BatchService = Depends(get_batch_service),
):
    try:
        batch = await service.get_batch_by_id(batchId)
        # Check department access
        if current_user.role == UserRole.DEPARTMENT_ADMIN:
            if batch.department_id != current_user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to access another department's batch.",
                )
        return batch
    except BatchNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)


@router.put("/{batchId}", response_model=BatchResponse)
async def update_batch(
    batchId: str,
    data: BatchUpdate,
    current_user: User = Depends(get_current_user),
    service: BatchService = Depends(get_batch_service),
):
    try:
        batch = await service.get_batch_by_id(batchId)
        # Check department access
        if current_user.role == UserRole.DEPARTMENT_ADMIN:
            if batch.department_id != current_user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to update another department's batch.",
                )
        
        update_dict = data.model_dump(exclude_unset=True)
        return await service.update_batch(batchId, update_dict)
    except BatchNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/{batchId}")
async def delete_batch(
    batchId: str,
    current_user: User = Depends(get_current_user),
    service: BatchService = Depends(get_batch_service),
):
    try:
        batch = await service.get_batch_by_id(batchId)
        # Check department access
        if current_user.role == UserRole.DEPARTMENT_ADMIN:
            if batch.department_id != current_user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to delete another department's batch.",
                )
        
        await service.delete_batch(batchId)
        return {"message": "Batch deleted successfully"}
    except BatchNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


public_router = APIRouter(
    prefix="/public/batches",
    tags=["Public Admission Batches"],
)


@public_router.get("/{batchId}", response_model=BatchResponse)
async def get_public_batch(
    batchId: str,
    service: BatchService = Depends(get_batch_service),
):
    """
    Public lookup for batch cohort info (e.g. used by the Student Document Upload portal).
    """
    try:
        return await service.get_batch_by_id(batchId)
    except BatchNotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


from app.schemas.doc_config_version import DocConfigVersionResponse, DocRequirementSchema

@public_router.get("/{batchId}/doc-versions/current", response_model=DocConfigVersionResponse)
async def get_public_current_doc_version(batchId: str):
    """
    Public lookup for a batch's active document configuration requirements version.
    """
    try:
        from app.services.doc_config_version_service import DocConfigVersionService
        doc_config_service = DocConfigVersionService()
        v = await doc_config_service.get_or_create_current_version(batchId)
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
                )
                for d in v.documents
            ],
            is_current=v.is_current,
            change_summary=v.change_summary,
            created_by=v.created_by,
            created_at=v.created_at,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No document configuration found for batch '{batchId}': {str(e)}",
        )

