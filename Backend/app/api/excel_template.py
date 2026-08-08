import os
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends
from fastapi.responses import FileResponse
from app.schemas.excel_template import (
    ExcelMappingUpdate,
    ExcelTemplateResponse,
    StudentRowUpdatePayload,
)
from app.services.excel_template_service import ExcelTemplateService
from app.core.dependencies import get_current_user, RoleChecker
from app.models.user import User, UserRole
from app.services.batch_service import BatchService

router = APIRouter(
    prefix="/excel-templates",
    tags=["Excel Templates"],
    dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN, UserRole.DEPARTMENT_ADMIN]))],
)
service = ExcelTemplateService()
batch_service = BatchService()


async def _verify_batch_access(batch_id: str, user: User):
    """Helper to verify that a Department Admin is accessing a batch belonging to their department."""
    if user.role == UserRole.DEPARTMENT_ADMIN:
        try:
            batch = await batch_service.get_batch_by_id(batch_id)
            if batch.department_id != user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to access this department's Excel templates.",
                )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch with ID '{batch_id}' not found.",
            )


@router.post("/upload/{batchId}", response_model=ExcelTemplateResponse)
async def upload_excel_template(
    batchId: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Upload an Excel template (.xlsx) for an Admission Batch.
    """
    await _verify_batch_access(batchId, current_user)
    
    template = await service.upload_template(batchId, file)
    remaining = max(0, template.total_rows - template.updated_count)
    return ExcelTemplateResponse(
        id=str(template.id),
        batch_id=template.batch_id,
        template_filename=template.template_filename,
        file_path=template.file_path,
        headers=template.headers,
        field_mappings=template.field_mappings,
        lookup_column=template.lookup_column,
        total_rows=template.total_rows,
        updated_count=template.updated_count,
        remaining_students=remaining,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.get("/batch/{batchId}", response_model=ExcelTemplateResponse)
async def get_excel_template(
    batchId: str,
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve Excel template metadata and headers for an Admission Batch.
    """
    await _verify_batch_access(batchId, current_user)

    template = await service.get_template_by_batch(batchId)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Excel template found for batch '{batchId}'.",
        )
    remaining = max(0, template.total_rows - template.updated_count)
    return ExcelTemplateResponse(
        id=str(template.id),
        batch_id=template.batch_id,
        template_filename=template.template_filename,
        file_path=template.file_path,
        headers=template.headers,
        field_mappings=template.field_mappings,
        lookup_column=template.lookup_column,
        total_rows=template.total_rows,
        updated_count=template.updated_count,
        remaining_students=remaining,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.put("/mappings/{batchId}", response_model=ExcelTemplateResponse)
async def update_excel_mappings(
    batchId: str,
    data: ExcelMappingUpdate,
    current_user: User = Depends(get_current_user),
):
    """
    Update field mappings (AI Extracted Field -> Excel Column) and primary lookup key column.
    """
    await _verify_batch_access(batchId, current_user)

    template = await service.update_mappings(batchId, data.field_mappings, data.lookup_column)
    remaining = max(0, template.total_rows - template.updated_count)
    return ExcelTemplateResponse(
        id=str(template.id),
        batch_id=template.batch_id,
        template_filename=template.template_filename,
        file_path=template.file_path,
        headers=template.headers,
        field_mappings=template.field_mappings,
        lookup_column=template.lookup_column,
        total_rows=template.total_rows,
        updated_count=template.updated_count,
        remaining_students=remaining,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.post("/update-row/{batchId}")
async def update_student_excel_row(
    batchId: str,
    payload: StudentRowUpdatePayload,
    current_user: User = Depends(get_current_user),
):
    """
    Find student row by Register Number in Excel template and update mapped column cells.
    """
    await _verify_batch_access(batchId, current_user)

    success = await service.update_student_row_in_excel(
        batchId, payload.register_number, payload.extracted_fields
    )
    return {
        "status": "success",
        "message": f"Successfully updated Excel row for candidate {payload.register_number}",
        "updated": success,
    }


@router.get("/download/{batchId}")
async def download_excel_workbook(
    batchId: str,
    current_user: User = Depends(get_current_user),
):
    """
    Download the latest updated Excel workbook (.xlsx) for an Admission Batch.
    """
    await _verify_batch_access(batchId, current_user)

    template = await service.get_template_by_batch(batchId)
    if not template or not os.path.exists(template.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Excel workbook for batch '{batchId}' not found.",
        )

    return FileResponse(
        path=template.file_path,
        filename=f"{batchId}_updated_{template.template_filename}",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

