from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, status, Depends
from app.models.user import User, UserRole
from app.core.dependencies import get_current_user, RoleChecker
from app.services.batch_service import BatchService
from app.services.wanted_field_service import WantedFieldService
from app.services.excel_template_service import ExcelTemplateService
from app.models.wanted_field_config import DocumentFieldConfiguration, WantedFieldItem
from app.schemas.wanted_field import (
    CreateDocumentTypePayload,
    AddFieldPayload,
    SaveDocumentWantedFieldsPayload,
    DocumentFieldConfigurationResponse,
    DocumentTypeOverviewItem,
)

router = APIRouter(
    prefix="/wanted-fields",
    tags=["Wanted Fields"],
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))],
)

wanted_field_service = WantedFieldService()
batch_service = BatchService()
excel_service = ExcelTemplateService()


async def _verify_batch_access(batch_id: str, user: User):
    """Verify Department Admin access to the given batch."""
    if user.role == UserRole.DEPARTMENT_ADMIN:
        try:
            batch = await batch_service.get_batch_by_id(batch_id)
            if batch.department_id != user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to access this batch's configurations.",
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch with ID '{batch_id}' not found.",
            )


@router.get("/{batchId}/overview", response_model=List[DocumentTypeOverviewItem])
async def get_batch_wanted_fields_overview(
    batchId: str,
    classId: Optional[str] = None,
    class_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve overview summary of wanted fields and mapping status across all configured document types for a batch.
    If no document types have been configured, returns an empty list.
    """
    await _verify_batch_access(batchId, current_user)
    target_class = classId or class_id
    return await wanted_field_service.get_batch_overview(batchId, class_id=target_class)


def _to_config_response(config: DocumentFieldConfiguration) -> DocumentFieldConfigurationResponse:
    return DocumentFieldConfigurationResponse(
        id=str(config.id) if config.id else None,
        batch_id=config.batch_id,
        class_id=config.class_id,
        document_type=config.document_type,
        display_name=config.display_name,
        description=config.description,
        requirement_status=getattr(config, "requirement_status", "REQUIRED") or "REQUIRED",
        allowed_types=getattr(config, "allowed_types", None) or ["PDF", "JPG", "PNG"],
        max_size_mb=getattr(config, "max_size_mb", None) or 5.0,
        fields=[
            {"field": f.field, "enabled": f.enabled, "excel_header": f.excel_header}
            for f in config.fields
        ],
        available_fields=getattr(config, "available_fields", None) or [f.field for f in config.fields],
        is_archived=getattr(config, "is_archived", False),
        version=config.version,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.post("/{batchId}/document-type", response_model=DocumentFieldConfigurationResponse)
async def create_document_type(
    batchId: str,
    payload: CreateDocumentTypePayload,
    classId: Optional[str] = None,
    class_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Staff/Admin manually creates a new document type for this batch.
    Validates name and code uniqueness, normalizes code, and starts with zero wanted fields.
    """
    await _verify_batch_access(batchId, current_user)
    target_class = classId or class_id
    try:
        config = await wanted_field_service.create_document_type(
            batch_id=batchId,
            name=payload.name,
            code=payload.code,
            description=payload.description,
            class_id=target_class,
            initial_fields=payload.initial_fields,
            requirement_status=payload.requirement_status,
            allowed_types=payload.allowed_types,
            max_size_mb=payload.max_size_mb,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )

    return _to_config_response(config)


@router.get("/{batchId}/{documentType}", response_model=DocumentFieldConfigurationResponse)
async def get_document_wanted_fields(
    batchId: str,
    documentType: str,
    classId: Optional[str] = None,
    class_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve wanted fields configuration for a specific document type.
    """
    await _verify_batch_access(batchId, current_user)
    target_class = classId or class_id
    config = await wanted_field_service.get_document_configuration(batchId, documentType, class_id=target_class)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document type '{documentType}' is not configured for this batch.",
        )
    return _to_config_response(config)


@router.post("/{batchId}/{documentType}/fields", response_model=DocumentFieldConfigurationResponse)
async def add_field_to_document_type(
    batchId: str,
    documentType: str,
    payload: AddFieldPayload,
    classId: Optional[str] = None,
    class_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Add a custom field to the document type's available fields list.
    """
    await _verify_batch_access(batchId, current_user)
    target_class = classId or class_id
    try:
        updated = await wanted_field_service.add_field_to_document(
            batch_id=batchId,
            doc_type=documentType,
            field_name=payload.field_name,
            class_id=target_class,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )

    return _to_config_response(updated)


@router.put("/{batchId}/{documentType}", response_model=DocumentFieldConfigurationResponse)
async def save_document_wanted_fields(
    batchId: str,
    documentType: str,
    payload: SaveDocumentWantedFieldsPayload,
    classId: Optional[str] = None,
    class_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Save or update wanted fields and Excel column mappings for a specific document type.
    Enforces semantic compatibility, allowed template headers, and duplicate target conflict detection.
    """
    await _verify_batch_access(batchId, current_user)
    target_class = classId or class_id

    # Get allowed headers from template if template exists
    template = await excel_service.get_template_by_batch(batchId, class_id=target_class)
    allowed_headers = template.headers if (template and template.headers) else None

    # Convert payload items to model items
    field_items = [
        WantedFieldItem(
            field=item.field.strip(),
            enabled=item.enabled,
            excel_header=item.excel_header.strip() if item.excel_header else None,
        )
        for item in payload.fields
    ]

    try:
        saved = await wanted_field_service.save_document_configuration(
            batch_id=batchId,
            doc_type=documentType,
            fields=field_items,
            allowed_headers=allowed_headers,
            class_id=target_class,
            display_name=payload.display_name,
            description=payload.description,
            requirement_status=payload.requirement_status,
            allowed_types=payload.allowed_types,
            max_size_mb=payload.max_size_mb,
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )

    return _to_config_response(saved)


@router.delete("/{batchId}/{documentType}")
async def delete_document_type(
    batchId: str,
    documentType: str,
    classId: Optional[str] = None,
    class_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Safely delete or soft-archive a document configuration for a batch.
    Preserves auditability for existing uploaded student submissions.
    """
    await _verify_batch_access(batchId, current_user)
    target_class = classId or class_id
    try:
        result = await wanted_field_service.delete_or_archive_document_type(
            batch_id=batchId,
            doc_type=documentType,
            class_id=target_class,
        )
        return result
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        )

