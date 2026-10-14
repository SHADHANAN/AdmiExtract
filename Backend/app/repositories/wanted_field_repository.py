import re
from datetime import datetime, timezone
from typing import List, Optional
from app.models.wanted_field_config import DocumentFieldConfiguration, WantedFieldItem

CANONICAL_DOC_CODE_MAP = {
    "AADHAAR": "AADHAAR",
    "AADHAAR_CARD": "AADHAAR",
    "AADHAR": "AADHAAR",
    "AADHAR_CARD": "AADHAAR",
    "BANK_PASSBOOK": "BANK_PASSBOOK",
    "PASSBOOK": "BANK_PASSBOOK",
    "BANK_STATEMENT": "BANK_PASSBOOK",
    "BANK_ACCOUNT": "BANK_PASSBOOK",
    "COMMUNITY": "COMMUNITY",
    "COMMUNITY_CERTIFICATE": "COMMUNITY",
    "CASTE": "COMMUNITY",
    "CASTE_CERTIFICATE": "COMMUNITY",
    "INCOME": "INCOME",
    "INCOME_CERTIFICATE": "INCOME",
    "TRANSFER_CERTIFICATE": "TRANSFER_CERTIFICATE",
    "TRANSFER_CERTIFICATE_TC": "TRANSFER_CERTIFICATE",
    "SSLC": "SSLC",
    "SSLC_MARKSHEET": "SSLC",
    "10TH": "SSLC",
    "10TH_MARKSHEET": "SSLC",
    "HSC": "HSC",
    "HSC_MARKSHEET": "HSC",
    "12TH": "HSC",
    "12TH_MARKSHEET": "HSC",
    "BIRTH_CERTIFICATE": "BIRTH_CERTIFICATE",
    "BIRTH": "BIRTH_CERTIFICATE",
    "NATIVITY": "NATIVITY",
    "NATIVITY_CERTIFICATE": "NATIVITY",
    "PASSPORT": "PASSPORT",
    "ALLOTMENT_ORDER": "ALLOTMENT_ORDER",
}


def _normalize_doc_code(code: str) -> str:
    cleaned = re.sub(r'[\s\-]+', '_', str(code).strip().upper())
    cleaned = re.sub(r'[^A-Z0-9_]', '', cleaned)
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')
    return CANONICAL_DOC_CODE_MAP.get(cleaned, cleaned)


async def _get_matching_batch_ids(batch_id: str) -> List[str]:
    """Resolve batch_id aliases (id, name, _id) for robust MongoDB lookups."""
    b_ids = [str(batch_id)]
    try:
        from app.models.batch import AdmissionBatch
        batch = await AdmissionBatch.get(batch_id)
        if not batch:
            batch = await AdmissionBatch.find_one({"$or": [{"id": batch_id}, {"_id": batch_id}, {"name": batch_id}]})
        if batch:
            if batch.id and str(batch.id) not in b_ids:
                b_ids.append(str(batch.id))
            if batch.name and str(batch.name) not in b_ids:
                b_ids.append(str(batch.name))
    except Exception:
        pass
    return b_ids


class WantedFieldRepository:
    """
    Repository for managing DocumentFieldConfiguration documents in MongoDB.
    Provides batch/class and document-type scoped operations with automatic inheritance.
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
        doc_type_upper = _normalize_doc_code(document_type)

        b_ids = await _get_matching_batch_ids(batch_id)
        config: Optional[DocumentFieldConfiguration] = None

        if class_id:
            config = await DocumentFieldConfiguration.find_one(
                {"batch_id": {"$in": b_ids}, "class_id": class_id, "document_type": doc_type_upper}
            )

        if not config and not exact_scope_only:
            config = await DocumentFieldConfiguration.find_one(
                {"batch_id": {"$in": b_ids}, "class_id": None, "document_type": doc_type_upper}
            )

        if not config and not class_id and exact_scope_only:
            config = await DocumentFieldConfiguration.find_one(
                {"batch_id": {"$in": b_ids}, "class_id": None, "document_type": doc_type_upper}
            )

        if config and not include_archived and getattr(config, "is_archived", False):
            return None

        return config

    async def list_by_batch(
        self,
        batch_id: str,
        class_id: Optional[str] = None,
        include_archived: bool = False,
        exact_scope_only: bool = False,
    ) -> List[DocumentFieldConfiguration]:
        """
        List all document field configurations for an Admission Batch.
        If class_id is provided and exact_scope_only is False:
          - Starts with Batch-level configurations
          - Overrides with Section-specific configurations
          - Any document type configured only at Batch level is inherited
        If exact_scope_only is True:
          - Returns strictly the configurations saved at that exact scope.
        """
        b_ids = await _get_matching_batch_ids(batch_id)

        batch_configs = await DocumentFieldConfiguration.find(
            {"batch_id": {"$in": b_ids}, "class_id": None}
        ).to_list()

        class_configs = []
        if class_id:
            class_configs = await DocumentFieldConfiguration.find(
                {"batch_id": {"$in": b_ids}, "class_id": class_id}
            ).to_list()

        if exact_scope_only:
            configs = class_configs if class_id else batch_configs
        else:
            merged_dict: dict[str, DocumentFieldConfiguration] = {}
            for c in batch_configs:
                canon_dt = _normalize_doc_code(c.document_type)
                merged_dict[canon_dt] = c

            for c in class_configs:
                canon_dt = _normalize_doc_code(c.document_type)
                # Section-specific configuration overrides Batch-level configuration
                merged_dict[canon_dt] = c

            configs = list(merged_dict.values())

        if not include_archived:
            configs = [c for c in configs if not getattr(c, "is_archived", False)]

        # Defensive deduplication by document_type within the returned list
        deduped: dict[str, DocumentFieldConfiguration] = {}
        for c in configs:
            dt = _normalize_doc_code(c.document_type)
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
        doc_type_upper = _normalize_doc_code(document_type)

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
        doc_type_upper = _normalize_doc_code(document_type)

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
        doc_type_upper = _normalize_doc_code(document_type)

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
        doc_type_upper = _normalize_doc_code(document_type)

        config = await self.get_by_batch_and_doc_type(
            batch_id, doc_type_upper, class_id=class_id, include_archived=True, exact_scope_only=True
        )
        if not config:
            return False
        await config.delete()
        return True
