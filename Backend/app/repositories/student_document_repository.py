import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from beanie import PydanticObjectId


from app.models.student_document import (
    StudentDocument,
    DocumentVersion,
    DocumentStatus,
    DocumentValidationStatus,
)

logger = logging.getLogger("app.repositories.student_document_repository")

_doc_locks: Dict[str, asyncio.Lock] = {}


def _get_doc_lock(doc_id: str) -> asyncio.Lock:
    if doc_id not in _doc_locks:
        _doc_locks[doc_id] = asyncio.Lock()
    return _doc_locks[doc_id]


class StudentDocumentRepository:
    """
    Data-access repository for StudentDocument and its immutable versions.
    Enforces strict uniqueness per (student/submission + document_type) and provides
    safe consolidation of any legacy duplicate records.
    """

    async def create_document(self, doc: StudentDocument) -> StudentDocument:
        """
        Insert a new StudentDocument record, or safely replace the document file
        if a document of the same logical type already exists for this student/submission.
        """
        from app.services.document_extraction_service import normalize_doc_type
        norm_type = normalize_doc_type(doc.document_type)
        doc.document_type = norm_type
        clean_student = str(doc.student_id).strip()

        # Check if document already exists
        existing = await self.get_by_student_and_type(clean_student, norm_type)
        if not existing and doc.submission_id:
            existing = await self.get_by_submission_and_type(doc.submission_id, norm_type)

        if existing:
            # If doc has initial version to add/replace, replace in-place safely
            if doc.versions:
                latest_v = doc.versions[-1]
                await self.replace_document_file(
                    doc_id=existing.id,
                    file_path=latest_v.file_path,
                    original_filename=latest_v.original_filename,
                    file_size_bytes=latest_v.file_size_bytes,
                    mime_type=latest_v.mime_type,
                    uploaded_by=latest_v.uploaded_by,
                    validation_status=latest_v.validation_status,
                    validation_reason=latest_v.validation_reason,
                    extraction_reference=latest_v.extraction_reference,
                )
                refreshed = await self.get_by_id(existing.id)
                return refreshed or existing
            return existing

        return await doc.insert()

    async def replace_document_file(
        self,
        doc_id: str | PydanticObjectId,
        file_path: str,
        original_filename: str,
        file_size_bytes: int = 0,
        mime_type: str = "application/pdf",
        uploaded_by: Optional[str] = None,
        validation_status: str = DocumentValidationStatus.PENDING.value,
        validation_reason: Optional[str] = None,
        expected_document_type: Optional[str] = None,
        detected_document_type: Optional[str] = None,
        classification_confidence: float = 0.0,
        classification_evidence: Optional[List[str]] = None,
        classifier_version: Optional[str] = "v2.0-ai-hybrid",
        classified_at: Optional[datetime] = None,
        extraction_reference: Optional[Any] = None,
    ) -> Optional[StudentDocument]:
        """
        Replace the document file on the existing StudentDocument record in-place.
        Updates the single DocumentVersion rather than creating a new version record.
        Maintains the same StudentDocument ID and updates file reference,
        size, mime_type, classification metadata, and timestamp.
        """
        from datetime import datetime, timezone
        import uuid
        from app.models.student_document import DocumentStatus

        clean_id = str(doc_id)
        async with _get_doc_lock(clean_id):
            doc = await self.get_by_id(doc_id)
            if not doc:
                return None

            old_file_path = None
            evidence_list = classification_evidence or []
            class_dt = classified_at or (datetime.now(timezone.utc) if detected_document_type else None)

            if doc.versions:
                v = doc.versions[0]
                old_file_path = v.file_path
                v.file_path = file_path
                v.original_filename = original_filename
                v.file_size_bytes = file_size_bytes
                v.mime_type = mime_type
                v.uploaded_at = datetime.now(timezone.utc)
                v.uploaded_by = uploaded_by or "system"
                v.validation_status = validation_status
                v.validation_reason = validation_reason
                v.expected_document_type = expected_document_type or doc.expected_document_type or doc.document_type
                v.detected_document_type = detected_document_type
                v.classification_confidence = classification_confidence
                v.classification_evidence = evidence_list
                v.classifier_version = classifier_version
                v.classified_at = class_dt
                v.is_active = True
                v.extraction_reference = extraction_reference
                doc.versions = [v]
                doc.active_version_id = v.version_id
            else:
                new_v = DocumentVersion(
                    version_id=uuid.uuid4().hex,
                    version_number=1,
                    file_path=file_path,
                    original_filename=original_filename,
                    file_size_bytes=file_size_bytes,
                    mime_type=mime_type,
                    uploaded_at=datetime.now(timezone.utc),
                    uploaded_by=uploaded_by or "system",
                    validation_status=validation_status,
                    validation_reason=validation_reason,
                    expected_document_type=expected_document_type or doc.expected_document_type or doc.document_type,
                    detected_document_type=detected_document_type,
                    classification_confidence=classification_confidence,
                    classification_evidence=evidence_list,
                    classifier_version=classifier_version,
                    classified_at=class_dt,
                    is_active=True,
                    extraction_reference=extraction_reference,
                )
                doc.versions = [new_v]
                doc.active_version_id = new_v.version_id

            if expected_document_type:
                doc.expected_document_type = expected_document_type
            if detected_document_type:
                doc.detected_document_type = detected_document_type
            if classification_confidence:
                doc.classification_confidence = classification_confidence
            if evidence_list:
                doc.classification_evidence = evidence_list

            doc.current_version = 1
            doc.status = DocumentStatus.UPLOADED.value
            await doc.save()

            # Safe cleanup of old physical file if different
            if old_file_path and old_file_path != file_path:
                try:
                    import os
                    from pathlib import Path
                    old_p = Path(old_file_path)
                    if old_p.exists() and old_p.is_file():
                        os.remove(old_p)
                except Exception as ex:
                    logger.warning(f"Failed to clean up replaced old file {old_file_path}: {ex}")

            return doc

    async def get_by_id(self, doc_id: str | PydanticObjectId) -> Optional[StudentDocument]:
        """Fetch StudentDocument by its MongoDB ObjectId string or instance."""
        try:
            pyd_id = PydanticObjectId(doc_id) if isinstance(doc_id, str) else doc_id
        except Exception:
            return None
        return await StudentDocument.get(pyd_id)

    async def get_by_student_id(self, student_id: str) -> List[StudentDocument]:
        """Fetch all managed documents for a specific student, running defensive consolidation."""
        clean_id = str(student_id).strip()
        await self.consolidate_duplicate_documents(clean_id)
        return await StudentDocument.find(StudentDocument.student_id == clean_id).to_list()

    async def get_by_student_and_type(
        self, student_id: str, document_type: str
    ) -> Optional[StudentDocument]:
        """
        Fetch document for a student by canonical document type (e.g., AADHAAR).
        Uses normalized type matching and fallback aliases.
        """
        from app.services.document_extraction_service import normalize_doc_type
        clean_student = str(student_id).strip()
        norm_type = normalize_doc_type(document_type)

        # 1. Exact match on normalized type
        doc = await StudentDocument.find_one(
            StudentDocument.student_id == clean_student,
            StudentDocument.document_type == norm_type,
        )
        if doc:
            return doc

        # 2. Case-insensitive / alias scan across all docs for this student
        student_docs = await StudentDocument.find(StudentDocument.student_id == clean_student).to_list()
        for d in student_docs:
            if (
                d.document_type == norm_type
                or normalize_doc_type(d.document_type) == norm_type
                or normalize_doc_type(d.document_name) == norm_type
            ):
                return d
        return None

    async def get_by_submission_and_type(
        self, submission_id: str, document_type: str
    ) -> Optional[StudentDocument]:
        """Fetch document by submission_id and canonical document type."""
        from app.services.document_extraction_service import normalize_doc_type
        clean_sub = str(submission_id).strip()
        norm_type = normalize_doc_type(document_type)

        doc = await StudentDocument.find_one(
            StudentDocument.submission_id == clean_sub,
            StudentDocument.document_type == norm_type,
        )
        if doc:
            return doc

        sub_docs = await StudentDocument.find(StudentDocument.submission_id == clean_sub).to_list()
        for d in sub_docs:
            if (
                d.document_type == norm_type
                or normalize_doc_type(d.document_type) == norm_type
                or normalize_doc_type(d.document_name) == norm_type
            ):
                return d
        return None

    async def add_version(
        self,
        doc_id: str | PydanticObjectId,
        version: DocumentVersion,
        set_active: bool = True,
    ) -> Optional[StudentDocument]:
        """
        Append a new immutable version to the StudentDocument.
        If set_active is True, marks all previous versions as is_active=False
        and sets active_version_id and current_version.
        Guarantees serial execution under concurrency per document ID.
        """
        clean_id = str(doc_id)
        async with _get_doc_lock(clean_id):
            doc = await self.get_by_id(doc_id)
            if not doc:
                return None

            existing_versions = [v.version_number for v in doc.versions]
            next_ver = (max(existing_versions) + 1) if existing_versions else 1
            version.version_number = next_ver

            if set_active:
                for v in doc.versions:
                    v.is_active = False
                version.is_active = True
                doc.active_version_id = version.version_id

            doc.versions.append(version)
            doc.current_version = max(doc.current_version, next_ver)
            await doc.save()
            return doc

    async def activate_version(
        self, doc_id: str | PydanticObjectId, version_id: str
    ) -> Optional[StudentDocument]:
        """
        Set a specific existing version as the active version.
        Ensures strictly one version is active at any time under concurrency.
        """
        clean_id = str(doc_id)
        async with _get_doc_lock(clean_id):
            doc = await self.get_by_id(doc_id)
            if not doc:
                return None

            found = False
            for v in doc.versions:
                if v.version_id == version_id:
                    v.is_active = True
                    doc.active_version_id = version_id
                    found = True
                else:
                    v.is_active = False

            if not found:
                return None

            await doc.save()
            return doc

    async def update_status(
        self, doc_id: str | PydanticObjectId, status: str
    ) -> Optional[StudentDocument]:
        """Update high-level lifecycle status of the document."""
        doc = await self.get_by_id(doc_id)
        if not doc:
            return None

        doc.status = status
        await doc.save()
        return doc

    async def list_documents(
        self,
        batch_id: Optional[str] = None,
        class_id: Optional[str] = None,
        department_id: Optional[str] = None,
    ) -> List[StudentDocument]:
        """List documents with optional tenancy filtering."""
        query = {}
        if batch_id:
            query["batch_id"] = batch_id
        if class_id:
            query["class_id"] = class_id
        if department_id:
            query["department_id"] = department_id
        return await StudentDocument.find(query).to_list()

    async def consolidate_duplicate_documents(
        self, student_id: Optional[str] = None
    ) -> int:
        """
        Identify and safely consolidate any duplicate StudentDocument records for the same
        student/submission and logical document type.

        Preserves the latest valid uploaded file, ensures exactly ONE active version (v1),
        updates foreign extraction/verification references, and safely removes redundant duplicate
        document records from the database.

        Returns the number of duplicate document containers removed.
        """
        from app.services.document_extraction_service import normalize_doc_type
        from app.models.document_extraction_request import DocumentExtractionRequest
        from app.models.document_verification import DocumentFieldVerification

        query = {}
        if student_id:
            query["student_id"] = str(student_id).strip()

        all_docs = await StudentDocument.find(query).to_list()
        if not all_docs:
            return 0

        # Group by (student_id or submission_id, normalized_type)
        grouped: Dict[tuple, List[StudentDocument]] = {}
        for d in all_docs:
            norm_type = normalize_doc_type(d.document_type or d.document_name)
            key = (str(d.student_id or d.submission_id or "").strip(), norm_type)
            grouped.setdefault(key, []).append(d)

        consolidated_count = 0

        for (stud_key, norm_type), doc_list in grouped.items():
            if len(doc_list) <= 1:
                continue

            # Pick primary document: prefer one with latest created_at or highest current_version
            primary_doc = max(
                doc_list,
                key=lambda d: (
                    d.created_at.timestamp() if d.created_at else 0,
                    len(d.versions or []),
                    d.current_version or 0,
                ),
            )
            duplicate_docs = [d for d in doc_list if d.id != primary_doc.id]

            # Find the latest active version across primary and all duplicates
            all_versions: List[DocumentVersion] = []
            for d in doc_list:
                for v in d.versions or []:
                    all_versions.append(v)

            # Sort versions by uploaded_at / created_at
            all_versions_sorted = sorted(
                all_versions,
                key=lambda v: (
                    v.uploaded_at.timestamp() if v.uploaded_at else (v.created_at.timestamp() if v.created_at else 0),
                    v.version_number or 0,
                ),
            )

            # Find the latest valid/active version
            latest_version = None
            for v in reversed(all_versions_sorted):
                if v.file_path:
                    latest_version = v
                    break
            if not latest_version and all_versions_sorted:
                latest_version = all_versions_sorted[-1]

            if latest_version:
                latest_version.version_number = 1
                latest_version.is_active = True
                primary_doc.versions = [latest_version]
                primary_doc.active_version_id = latest_version.version_id
            else:
                primary_doc.versions = []
                primary_doc.active_version_id = None

            primary_doc.document_type = norm_type
            primary_doc.current_version = 1
            await primary_doc.save()

            # Re-point references from duplicates to primary_doc
            for dup in duplicate_docs:
                try:
                    await DocumentExtractionRequest.find(
                        DocumentExtractionRequest.student_document_id == str(dup.id)
                    ).update_many(
                        {"$set": {"student_document_id": str(primary_doc.id)}}
                    )
                except Exception as ex:
                    logger.warning(f"Error updating extraction request references for duplicate {dup.id}: {ex}")

                try:
                    await DocumentFieldVerification.find(
                        DocumentFieldVerification.document_id == str(dup.id)
                    ).update_many(
                        {"$set": {"document_id": str(primary_doc.id)}}
                    )
                except Exception as ex:
                    logger.warning(f"Error updating verification references for duplicate {dup.id}: {ex}")

                await dup.delete()
                consolidated_count += 1

            logger.info(
                f"[Consolidate] Merged {len(duplicate_docs)} duplicate(s) for student '{stud_key}' / '{norm_type}' into primary '{primary_doc.id}'."
            )

        return consolidated_count
