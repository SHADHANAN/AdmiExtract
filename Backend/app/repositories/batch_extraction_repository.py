from datetime import datetime, timezone
from typing import Dict, List, Optional
from beanie import PydanticObjectId

from app.models.batch_extraction import BatchExtractionRequest


class BatchExtractionRepository:
    """
    Data-access repository for BatchExtractionRequest entity.
    """

    async def create(self, request: BatchExtractionRequest) -> BatchExtractionRequest:
        """Insert and return a new BatchExtractionRequest."""
        return await request.insert()

    async def get_by_id(self, doc_id: str | PydanticObjectId) -> Optional[BatchExtractionRequest]:
        """Fetch by MongoDB ObjectId or extraction_request_id string."""
        if isinstance(doc_id, str) and doc_id.startswith("ext_"):
            return await self.get_by_request_id(doc_id)
        try:
            pyd_id = PydanticObjectId(doc_id) if isinstance(doc_id, str) else doc_id
            return await BatchExtractionRequest.get(pyd_id)
        except Exception:
            return await self.get_by_request_id(str(doc_id))

    async def get_by_request_id(self, extraction_request_id: str) -> Optional[BatchExtractionRequest]:
        """Fetch by business extraction_request_id or mongo _id."""
        req = await BatchExtractionRequest.find_one(
            BatchExtractionRequest.extraction_request_id == extraction_request_id
        )
        if not req:
            try:
                pyd_id = PydanticObjectId(extraction_request_id)
                req = await BatchExtractionRequest.get(pyd_id)
            except Exception:
                pass
        return req

    async def list_by_batch(
        self,
        batch_id: str | PydanticObjectId,
        department_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[BatchExtractionRequest]:
        """List extraction requests for a batch in reverse chronological order."""
        b_str = str(batch_id)
        batch_ids = [b_str]
        if isinstance(batch_id, PydanticObjectId):
            batch_ids.append(batch_id)
        query: Dict[str, Any] = {"batch_id": {"$in": batch_ids}}
        if department_id:
            query["department_id"] = department_id
        return (
            await BatchExtractionRequest.find(query)
            .sort([("created_at", -1)])
            .limit(limit)
            .to_list()
        )

    async def list_all(
        self,
        department_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[BatchExtractionRequest]:
        """List extraction requests across batches."""
        query: Dict[str, Any] = {}
        if department_id:
            query["department_id"] = department_id
        return (
            await BatchExtractionRequest.find(query)
            .sort([("created_at", -1)])
            .limit(limit)
            .to_list()
        )

    async def save(self, request: BatchExtractionRequest) -> BatchExtractionRequest:
        """Save updates to extraction request."""
        return await request.save()

    async def update_status(
        self,
        extraction_request_id: str,
        status: str,
        result_count: Optional[int] = None,
        verification_status: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[BatchExtractionRequest]:
        """Update request status and timestamps."""
        req = await self.get_by_request_id(extraction_request_id)
        if not req:
            return None

        req.status = status
        now = datetime.now(timezone.utc)
        if status in ("COMPLETED", "VERIFICATION_PENDING", "VERIFIED"):
            req.completed_at = now
        elif status == "FAILED":
            req.failed_at = now
            req.error_message = error_message
        elif status == "PROCESSING" and not req.started_at:
            req.started_at = now

        if result_count is not None:
            req.result_count = result_count
        if verification_status is not None:
            req.verification_status = verification_status

        return await req.save()
