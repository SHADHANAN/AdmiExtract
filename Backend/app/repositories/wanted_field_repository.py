from datetime import datetime, timezone
from typing import List, Optional
from app.models.wanted_field_config import DocumentFieldConfiguration, WantedFieldItem


class WantedFieldRepository:
    """
    Repository for managing DocumentFieldConfiguration documents in MongoDB.
    Provides batch/class and document-type scoped operations.
    """

    async def get_by_batch_and_doc_type(
        self,
        batch_id: str,
        document_type: str,
        class_id: Optional[str] = None,
        include_archived: bool = False,
        exact_scope_only: bool = False,
    ) -> Optional[DocumentFieldConfiguration]:
        """
        Retrieve document field configuration for a specific batch/class and document type.
        If exact_scope_only is False and class_id is provided, falls back to batch-level config.
        """
        doc_type_upper = document_type.upper().strip()
        config: Optional[DocumentFieldConfiguration] = None
        if class_id:
            config = await DocumentFieldConfiguration.find_one(
                DocumentFieldConfiguration.batch_id == batch_id,
                DocumentFieldConfiguration.class_id == class_id,
                DocumentFieldConfiguration.document_type == doc_type_upper,
            )

        if not config and not exact_scope_only:
            config = await DocumentFieldConfiguration.find_one(
                DocumentFieldConfiguration.batch_id == batch_id,
                DocumentFieldConfiguration.class_id == None,  # noqa: E711
                DocumentFieldConfiguration.document_type == doc_type_upper,
            )

        if not config and not class_id and exact_scope_only:
            config = await DocumentFieldConfiguration.find_one(
                DocumentFieldConfiguration.batch_id == batch_id,
                DocumentFieldConfiguration.class_id == None,  # noqa: E711
                DocumentFieldConfiguration.document_type == doc_type_upper,
            )

        if config and not include_archived and config.is_archived:
            return None

        return config

    async def list_by_batch(
        self,
        batch_id: str,
        class_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> List[DocumentFieldConfiguration]:
        """
        List all document field configurations for an Admission Batch.
        Ensures strict scope isolation: when class_id is None, returns only batch-level documents.
        When class_id is provided, returns class-level documents (or empty if none configured).
        Only returns non-archived configurations unless include_archived is True.
        Defensively deduplicates by document_type.
        """
        configs: List[DocumentFieldConfiguration] = []
        if class_id:
            configs = await DocumentFieldConfiguration.find(
                DocumentFieldConfiguration.batch_id == batch_id,
                DocumentFieldConfiguration.class_id == class_id,
            ).to_list()
        else:
            configs = await DocumentFieldConfiguration.find(
                DocumentFieldConfiguration.batch_id == batch_id,
                DocumentFieldConfiguration.class_id == None,  # noqa: E711
            ).to_list()

        if not include_archived:
            configs = [c for c in configs if not getattr(c, "is_archived", False)]

        # Defensive deduplication by document_type within the returned list
        deduped: dict[str, DocumentFieldConfiguration] = {}
        for c in configs:
            dt = c.document_type.upper().strip()
            if dt not in deduped:
                deduped[dt] = c
            else:
                existing = deduped[dt]
                if (c.version or 1) > (existing.version or 1) or (c.updated_at or c.created_at) > (existing.updated_at or existing.created_at):
                    deduped[dt] = c

        return list(deduped.values())

    async def create_document_type(
        self,
        batch_id: str,
        document_type: str,
        display_name: str,
        description: Optional[str] = None,
        class_id: Optional[str] = None,
        available_fields: Optional[List[str]] = None,
        fields: Optional[List[WantedFieldItem]] = None,
        requirement_status: str = "REQUIRED",
        allowed_types: Optional[List[str]] = None,
        max_size_mb: Optional[float] = None,
    ) -> DocumentFieldConfiguration:
        """
        Create or idempotently update a document configuration entry for a batch.
        Guarantees that a document type exists only once in the given scope.
        """
        doc_type_upper = document_type.upper().strip()
        now = datetime.now(timezone.utc)
        av_fields = available_fields or []
        f_items = fields or [WantedFieldItem(field=f, enabled=False, excel_header=None) for f in av_fields]

        req_status = requirement_status.strip().upper() if requirement_status else "REQUIRED"
        types = allowed_types if allowed_types is not None else ["PDF", "JPG", "PNG"]
        size_limit = max_size_mb if max_size_mb is not None else 5.0

        existing = await self.get_by_batch_and_doc_type(
            batch_id, doc_type_upper, class_id=class_id, include_archived=True, exact_scope_only=True
        )
        if existing:
            existing.display_name = display_name.strip() if display_name else existing.display_name
            if description is not None:
                existing.description = description.strip() if description else None
            existing.requirement_status = req_status
            existing.allowed_types = types
            existing.max_size_mb = size_limit
            if available_fields:
                merged_av = list(dict.fromkeys((existing.available_fields or []) + available_fields))
                existing.available_fields = merged_av
            if fields:
                existing.fields = f_items
            existing.is_archived = False
            existing.version += 1
            existing.updated_at = now
            await existing.save()
            return existing

        new_config = DocumentFieldConfiguration(
            batch_id=batch_id,
            class_id=class_id,
            document_type=doc_type_upper,
            display_name=display_name.strip(),
            description=description.strip() if description else None,
            requirement_status=req_status,
            allowed_types=types,
            max_size_mb=size_limit,
            fields=f_items,
            available_fields=av_fields,
            is_archived=False,
            version=1,
            created_at=now,
            updated_at=now,
        )
        return await new_config.insert()

    async def save_or_update(
        self,
        batch_id: str,
        document_type: str,
        fields: List[WantedFieldItem],
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        available_fields: Optional[List[str]] = None,
        class_id: Optional[str] = None,
        requirement_status: Optional[str] = None,
        allowed_types: Optional[List[str]] = None,
        max_size_mb: Optional[float] = None,
    ) -> DocumentFieldConfiguration:
        """
        Create or update a document field configuration.
        Preserves isolation: updating Aadhaar never alters TC or Community configurations.
        """
        doc_type_upper = document_type.upper().strip()
        existing = await self.get_by_batch_and_doc_type(
            batch_id, doc_type_upper, class_id=class_id, include_archived=True, exact_scope_only=True
        )

        now = datetime.now(timezone.utc)
        if existing:
            existing.fields = fields
            existing.is_archived = False
            if display_name:
                existing.display_name = display_name.strip()
            if description is not None:
                existing.description = description.strip() if description else None
            if available_fields is not None:
                existing.available_fields = available_fields
            if requirement_status is not None:
                existing.requirement_status = requirement_status.strip().upper()
            if allowed_types is not None:
                existing.allowed_types = allowed_types
            if max_size_mb is not None:
                existing.max_size_mb = max_size_mb
            existing.version += 1
            existing.updated_at = now
            await existing.save()
            return existing
        else:
            av_fields = available_fields or [f.field for f in fields]
            new_config = DocumentFieldConfiguration(
                batch_id=batch_id,
                class_id=class_id,
                document_type=doc_type_upper,
                display_name=display_name.strip() if display_name else doc_type_upper,
                description=description.strip() if description else None,
                requirement_status=requirement_status.strip().upper() if requirement_status else "REQUIRED",
                allowed_types=allowed_types if allowed_types is not None else ["PDF", "JPG", "PNG"],
                max_size_mb=max_size_mb if max_size_mb is not None else 5.0,
                fields=fields,
                available_fields=av_fields,
                is_archived=False,
                version=1,
                created_at=now,
                updated_at=now,
            )
            return await new_config.insert()

    async def archive_document_type(
        self,
        batch_id: str,
        document_type: str,
        class_id: Optional[str] = None,
    ) -> bool:
        """
        Soft-archive a document configuration so that uploaded student documents remain readable.
        """
        doc_type_upper = document_type.upper().strip()
        config = await self.get_by_batch_and_doc_type(
            batch_id, doc_type_upper, class_id=class_id, include_archived=True, exact_scope_only=True
        )
        if not config:
            return False
        config.is_archived = True
        config.updated_at = datetime.now(timezone.utc)
        await config.save()
        return True

    async def delete_document_type(
        self,
        batch_id: str,
        document_type: str,
        class_id: Optional[str] = None,
    ) -> bool:
        """
        Hard-delete document configuration if safe.
        """
        doc_type_upper = document_type.upper().strip()
        config = await self.get_by_batch_and_doc_type(
            batch_id, doc_type_upper, class_id=class_id, include_archived=True, exact_scope_only=True
        )
        if not config:
            return False
        await config.delete()
        return True

