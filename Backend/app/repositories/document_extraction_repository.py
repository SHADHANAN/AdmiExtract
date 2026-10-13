from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from beanie import PydanticObjectId

from app.models.document_extraction_request import (
    DocumentExtractionRequest,
    ExtractionRequestStatus,
)
from app.models.document_extraction_result import DocumentExtractionResult


class DocumentExtractionRepository:
    """Repository for DocumentExtractionRequest and DocumentExtractionResult persistence."""

    async def create_request(
        self, request: DocumentExtractionRequest
    ) -> DocumentExtractionRequest:
        await request.insert()
        return request

    async def get_request_by_id(
        self, request_id: str
    ) -> Optional[DocumentExtractionRequest]:
        try:
            obj_id = PydanticObjectId(request_id)
            return await DocumentExtractionRequest.get(obj_id)
        except Exception:
            return None

    async def get_requests_by_document_id(
        self, student_document_id: str
    ) -> List[DocumentExtractionRequest]:
        return await DocumentExtractionRequest.find(
            DocumentExtractionRequest.student_document_id == student_document_id
        ).sort("-requested_at").to_list()

    async def update_request_status(
        self,
        request_id: str,
        status: ExtractionRequestStatus,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        failed_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        extraction_result_id: Optional[str] = None,
    ) -> Optional[DocumentExtractionRequest]:
        req = await self.get_request_by_id(request_id)
        if not req:
            return None

        req.status = status
        req.updated_at = datetime.now(timezone.utc)
        if started_at is not None:
            req.started_at = started_at
        if completed_at is not None:
            req.completed_at = completed_at
        if failed_at is not None:
            req.failed_at = failed_at
        if error_message is not None:
            req.error_message = error_message
        if extraction_result_id is not None:
            req.extraction_result_id = extraction_result_id

        await req.save()
        return req

    async def create_result(
        self, result: DocumentExtractionResult
    ) -> DocumentExtractionResult:
        await result.insert()
        return result

    async def get_result_by_id(
        self, result_id: str
    ) -> Optional[DocumentExtractionResult]:
        try:
            obj_id = PydanticObjectId(result_id)
            return await DocumentExtractionResult.get(obj_id)
        except Exception:
            return None

    async def get_result_by_request_id(
        self, request_id: str
    ) -> Optional[DocumentExtractionResult]:
        return await DocumentExtractionResult.find_one(
            DocumentExtractionResult.extraction_request_id == request_id
        )

    async def find_existing_result(
        self,
        student_document_id: str,
        document_version_id: str,
        requested_fields: List[str],
    ) -> Optional[DocumentExtractionResult]:
        """
        Find an existing completed extraction result for the exact same document version
        and identical set of requested canonical fields.
        """
        results = await DocumentExtractionResult.find(
            DocumentExtractionResult.student_document_id == student_document_id,
            DocumentExtractionResult.document_version_id == document_version_id,
        ).sort("-created_at").to_list()

        target_set = set(requested_fields)
        for res in results:
            if set(res.requested_fields) == target_set:
                # Do not reuse stale/empty results where all extracted fields failed or are NOT_AVAILABLE
                data = res.extracted_data or {}
                has_meaningful_data = any(
                    val not in (None, "", "NOT_AVAILABLE", "NOT FOUND", "None", "null")
                    for val in data.values()
                )
                if has_meaningful_data:
                    return res
        return None
