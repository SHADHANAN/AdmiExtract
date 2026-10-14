from typing import Optional
from datetime import datetime, timezone
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


from app.schemas.student_document import (
    BatchDocumentValidationResponse,
    BatchDocumentValidationSummary,
    BatchDocumentValidationItem,
)


@router.get("/{batchId}/document-validation", response_model=BatchDocumentValidationResponse)
async def get_batch_document_validation(
    batchId: str,
    classId: Optional[str] = None,
    class_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    service: BatchService = Depends(get_batch_service),
):
    """
    Retrieve document classification diagnostic information, validation statuses,
    evidence, and batch-level summary counts for staff verification.
    """
    batch = await service.get_batch_by_id(batchId)
    if current_user.role == UserRole.DEPARTMENT_ADMIN:
        if batch.department_id != current_user.department_code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You do not have permission to access another department's batch.",
            )

    target_class = classId or class_id

    # Query all StudentDocuments for this batch
    from app.models.student_document import StudentDocument
    from app.models.student_submission import StudentSubmission
    from beanie.operators import In, Eq

    batch_ids = [str(batch.id)]
    if hasattr(batch, "name") and batch.name:
        batch_ids.append(batch.name)
    if str(batchId) not in batch_ids:
        batch_ids.append(str(batchId))

    query_filter = In(StudentDocument.batch_id, batch_ids)
    if target_class:
        query_filter = query_filter & (Eq(StudentDocument.class_id, target_class) | Eq(StudentDocument.section_id, target_class))

    docs = await StudentDocument.find(query_filter).to_list()

    # Build student metadata lookup map
    student_ids = list({d.student_id for d in docs if d.student_id})
    subs = await StudentSubmission.find(In(StudentSubmission.register_number, student_ids)).to_list()
    sub_map = {s.register_number: s for s in subs}

    doc_items: List[BatchDocumentValidationItem] = []
    summary = BatchDocumentValidationSummary()

    for doc in docs:
        active_v = doc.active_version or (doc.versions[-1] if doc.versions else None)
        sub = sub_map.get(doc.student_id)

        stu_name = sub.student_name if sub else None
        reg_num = sub.register_number if sub else doc.student_id

        expected_type = active_v.expected_document_type if active_v else doc.expected_document_type
        detected_type = active_v.detected_document_type if active_v else doc.detected_document_type
        conf = float(active_v.classification_confidence if active_v else (doc.classification_confidence or 0.0))
        val_status = active_v.validation_status if active_v else "PENDING"
        val_reason = active_v.validation_reason if active_v else None
        evidence = (active_v.classification_evidence if active_v else doc.classification_evidence) or []
        hist = (active_v.reclassification_history if active_v else doc.reclassification_history) or []
        ver_num = active_v.version_number if active_v else doc.current_version
        v_id = active_v.version_id if active_v else doc.active_version_id
        orig_fn = active_v.original_filename if active_v else None
        fp = active_v.file_path if active_v else None
        up_at = active_v.uploaded_at if active_v else doc.created_at

        summary.total_documents += 1
        if val_status == "VALID":
            summary.valid += 1
        elif val_status == "WRONG_DOCUMENT":
            summary.wrong_documents += 1
        elif val_status in ("NEEDS_REVIEW", "PENDING"):
            summary.needs_review += 1
        elif val_status == "CLASSIFICATION_FAILED":
            summary.classification_failed += 1
        elif val_status == "UNKNOWN":
            summary.unknown += 1
            summary.needs_review += 1

        doc_items.append(
            BatchDocumentValidationItem(
                document_id=str(doc.id),
                student_id=doc.student_id,
                student_name=stu_name,
                register_number=reg_num,
                batch_id=doc.batch_id,
                class_id=doc.class_id,
                department_id=doc.department_id,
                document_type=doc.document_type,
                document_name=doc.document_name,
                expected_document_type=expected_type,
                detected_document_type=detected_type,
                classification_confidence=conf,
                validation_status=val_status,
                validation_reason=val_reason,
                classification_evidence=evidence,
                reclassification_history=hist,
                version_number=ver_num,
                active_version_id=v_id,
                original_filename=orig_fn,
                file_path=fp,
                uploaded_at=up_at,
            )
        )

    return BatchDocumentValidationResponse(
        batch_id=str(batch.id),
        summary=summary,
        documents=doc_items,
    )



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
@public_router.get("/{batchId}/classes/{classId}/doc-versions/current", response_model=DocConfigVersionResponse)
@public_router.get("/{batchId}/sections/{sectionId}/doc-versions/current", response_model=DocConfigVersionResponse)
async def get_public_current_doc_version(
    batchId: str,
    classId: Optional[str] = None,
    class_id: Optional[str] = None,
    sectionId: Optional[str] = None,
    section_id: Optional[str] = None,
):
    """
    Public lookup for a batch's active document configuration requirements version.
    Single source of truth is DocumentFieldConfiguration with fallback to DocumentConfigurationVersion.
    """
    try:
        from app.services.wanted_field_service import WantedFieldService
        wanted_service = WantedFieldService()
        target_class = classId or class_id or sectionId or section_id
        reqs = await wanted_service.get_student_document_requirements(batchId, class_id=target_class)
        return DocConfigVersionResponse(
            id=batchId,
            batch_id=batchId,
            version=1,
            documents=[
                DocRequirementSchema(
                    id=d["id"],
                    name=d["name"],
                    required=d["required"],
                    allowed_types=d["allowed_types"],
                    max_size_mb=d["max_size_mb"],
                    description=d.get("description"),
                    type=d["type"],
                    extraction_fields=d.get("wanted_fields", []),
                )
                for d in reqs
            ],
            is_current=True,
            change_summary="Admin Document Configuration",
            created_by="Admin",
            created_at=datetime.now(timezone.utc),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No document configuration found for batch '{batchId}': {str(e)}",
        )


@public_router.get("/{batchId}/document-configurations")
@public_router.get("/{batchId}/classes/{classId}/document-configurations")
@public_router.get("/{batchId}/sections/{sectionId}/document-configurations")
async def get_public_document_configurations(
    batchId: str,
    classId: Optional[str] = None,
    class_id: Optional[str] = None,
    sectionId: Optional[str] = None,
    section_id: Optional[str] = None,
):
    """
    Public clean endpoint returning active configured document types for Student Portal.
    """
    try:
        from app.services.wanted_field_service import WantedFieldService
        wanted_service = WantedFieldService()
        target_class = classId or class_id or sectionId or section_id
        reqs = await wanted_service.get_student_document_requirements(batchId, class_id=target_class)
        return {
            "batch_id": batchId,
            "class_id": target_class,
            "count": len(reqs),
            "documents": reqs,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failed to load document configurations for batch '{batchId}': {str(e)}",
        )
