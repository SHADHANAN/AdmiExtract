from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from beanie import PydanticObjectId

from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
)


class DocumentVerificationRepository:
    """Repository for managing DocumentFieldVerification documents in MongoDB."""

    async def create_record(
        self, record: DocumentFieldVerification
    ) -> DocumentFieldVerification:
        await record.insert()
        return record

    async def bulk_create(
        self, records: List[DocumentFieldVerification]
    ) -> List[DocumentFieldVerification]:
        if records:
            await DocumentFieldVerification.insert_many(records)
        return records

    async def get_by_id(
        self, record_id: str
    ) -> Optional[DocumentFieldVerification]:
        try:
            obj_id = PydanticObjectId(record_id)
            return await DocumentFieldVerification.get(obj_id)
        except Exception:
            return None

    async def get_by_extraction_result(
        self, result_id: str
    ) -> List[DocumentFieldVerification]:
        return await DocumentFieldVerification.find(
            DocumentFieldVerification.extraction_result_id == result_id
        ).to_list()

    async def get_by_student_id(
        self, student_id: str
    ) -> List[DocumentFieldVerification]:
        return await DocumentFieldVerification.find(
            DocumentFieldVerification.student_id == student_id
        ).sort("-created_at").to_list()

    async def get_by_document_id(
        self, document_id: str
    ) -> List[DocumentFieldVerification]:
        return await DocumentFieldVerification.find(
            DocumentFieldVerification.document_id == document_id
        ).sort("-created_at").to_list()

    async def get_pending_corrections(
        self,
        department_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        class_id: Optional[str] = None,
    ) -> List[DocumentFieldVerification]:
        """Query all fields with status CORRECTION_REQUESTED filtered by tenancy."""
        filters = [
            DocumentFieldVerification.status
            == VerificationFieldStatus.CORRECTION_REQUESTED
        ]
        if department_id:
            filters.append(DocumentFieldVerification.department_id == department_id)
        if batch_id:
            filters.append(DocumentFieldVerification.batch_id == batch_id)
        if class_id:
            filters.append(DocumentFieldVerification.class_id == class_id)

        return await DocumentFieldVerification.find(*filters).sort("-student_updated_at").to_list()

    async def save_record(
        self, record: DocumentFieldVerification
    ) -> DocumentFieldVerification:
        record.updated_at = datetime.now(timezone.utc)
        await record.save()
        return record

    async def get_verified_fields_for_student(
        self, student_id: str
    ) -> List[DocumentFieldVerification]:
        """Retrieve all resolved verified fields for a student."""
        return await DocumentFieldVerification.find(
            DocumentFieldVerification.student_id == student_id,
            {"status": {"$in": [
                VerificationFieldStatus.STAFF_APPROVED.value,
                VerificationFieldStatus.STUDENT_CONFIRMED.value,
                VerificationFieldStatus.STUDENT_VERIFIED.value,
                VerificationFieldStatus.STAFF_REJECTED.value,
            ]}},
        ).sort("-updated_at").to_list()
