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
    ) -> Optional[DocumentFieldConfiguration]:
        """
        Retrieve document field configuration for a specific batch/class and document type.
        """
        doc_type_upper = document_type.upper().strip()
        config: Optional[DocumentFieldConfiguration] = None
        if class_id:
            config = await DocumentFieldConfiguration.find_one(
                DocumentFieldConfiguration.batch_id == batch_id,
                DocumentFieldConfiguration.class_id == class_id,
                DocumentFieldConfiguration.document_type == doc_type_upper,
            )

        if not config:
            config = await DocumentFieldConfiguration.find_one(
                DocumentFieldConfiguration.batch_id == batch_id,
                DocumentFieldConfiguration.class_id == None,  # noqa: E711
                DocumentFieldConfiguration.document_type == doc_type_upper,
            ) or await DocumentFieldConfiguration.find_one(
                DocumentFieldConfiguration.batch_id == batch_id,
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
        Only returns non-archived configurations unless include_archived is True.
        """
        configs: List[DocumentFieldConfiguration] = []
        if class_id:
            class_configs = await DocumentFieldConfiguration.find(
                DocumentFieldConfiguration.batch_id == batch_id,
                DocumentFieldConfiguration.class_id == class_id,
            ).to_list()
            if class_configs:
                configs = class_configs

        if not configs:
            configs = await DocumentFieldConfiguration.find(
                DocumentFieldConfiguration.batch_id == batch_id
            ).to_list()

        if not include_archived:
            configs = [c for c in configs if not getattr(c, "is_archived", False)]

        return configs

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
        Create a new document configuration entry for a batch.
        Initially contains zero wanted fields (enabled=False).
        """
        doc_type_upper = document_type.upper().strip()
        now = datetime.now(timezone.utc)
        av_fields = available_fields or []
        f_items = fields or [WantedFieldItem(field=f, enabled=False, excel_header=None) for f in av_fields]

        new_config = DocumentFieldConfiguration(
            batch_id=batch_id,
            class_id=class_id,
            document_type=doc_type_upper,
            display_name=display_name.strip(),
            description=description.strip() if description else None,
            requirement_status=requirement_status.strip().upper() if requirement_status else "REQUIRED",
            allowed_types=allowed_types if allowed_types is not None else ["PDF", "JPG", "PNG"],
            max_size_mb=max_size_mb if max_size_mb is not None else 5.0,
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
        existing = await self.get_by_batch_and_doc_type(batch_id, doc_type_upper, class_id=class_id, include_archived=True)

        now = datetime.now(timezone.utc)
        if existing and (existing.class_id == class_id or (class_id is None and existing.class_id is None)):
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
        config = await self.get_by_batch_and_doc_type(batch_id, doc_type_upper, class_id=class_id, include_archived=True)
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
        config = await self.get_by_batch_and_doc_type(batch_id, doc_type_upper, class_id=class_id, include_archived=True)
        if not config:
            return False
        await config.delete()
        return True
