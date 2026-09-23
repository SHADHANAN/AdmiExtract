import re
from typing import Any, Dict, List, Optional, Tuple
from app.models.wanted_field_config import DocumentFieldConfiguration, WantedFieldItem
from app.repositories.wanted_field_repository import WantedFieldRepository
from app.services.field_mapping_service import is_mapping_compatible, get_canonical_source_field
from app.services.field_source_rules import normalize_document_type
from app.models.excel_template import ExcelBatchTemplate
from app.models.student_submission import StudentSubmission


def normalize_document_code(code: str) -> str:
    """
    Normalize document code to a clean uppercase alphanumeric string with underscores.
    e.g. 'Aadhaar Card' -> 'AADHAAR_CARD', 'TC-1' -> 'TC_1', '  emis id ' -> 'EMIS_ID'.
    """
    cleaned = re.sub(r'[\s\-]+', '_', code.strip().upper())
    cleaned = re.sub(r'[^A-Z0-9_]', '', cleaned)
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')
    return cleaned


# Standard Available Fields Catalog per Document Type
DOCUMENT_AVAILABLE_FIELDS_CATALOG: Dict[str, List[str]] = {
    "AADHAAR": [
        "Aadhaar Number",
        "Date of Birth",
        "Student Name",
        "Gender",
        "Permanent Address",
        "District",
        "Taluk",
        "State",
        "Pincode",
        "Mobile Number",
        "Father's Name",
    ],
    "TRANSFER_CERTIFICATE": [
        "EMIS ID",
        "Student Name",
        "Father's Name",
        "Mother's Name",
        "Admission Number",
        "Issue Date",
        "Date of Leaving",
        "School Name",
        "Date of Birth",
        "Community Category",
        "Caste",
        "Transfer Certificate Number",
    ],
    "COMMUNITY": [
        "Community Category",
        "Caste",
        "Community Certificate Number",
        "Student Name",
        "Father's Name",
        "Issue Date",
        "District",
        "Taluk",
    ],
    "INCOME": [
        "Annual Family Income",
        "Student Name",
        "Father's Name",
        "Income Certificate Number",
        "Issue Date",
    ],
    "SSLC": [
        "Student Name",
        "SSLC Register Number",
        "SSLC Total Marks",
        "SSLC Mark Percentage",
        "SSLC Year of Passing",
        "Date of Birth",
        "School Name",
    ],
    "HSC": [
        "Student Name",
        "HSC Register Number",
        "HSC Total Marks",
        "HSC Mark Percentage",
        "HSC Cutoff",
        "HSC Year of Passing",
        "School Name",
    ],
    "NATIVITY": [
        "Student Name",
        "Father's Name",
        "State",
        "District",
        "Taluk",
        "Nativity",
    ],
    "BONAFIDE": [
        "Student Name",
        "School Name",
        "Admission Number",
    ],
    "MIGRATION": [
        "Migration Number",
        "University",
        "Year",
        "Student Name",
    ],
}

# Backward-compatible defaults reference (only used if explicitly requested)
DEFAULT_DOCUMENT_WANTED_FIELDS: Dict[str, List[str]] = {
    "AADHAAR": ["Aadhaar Number"],
    "TRANSFER_CERTIFICATE": ["Transfer Certificate Number", "School Name", "Admission Number", "Issue Date", "Date of Leaving"],
    "COMMUNITY": ["Community Category"],
    "INCOME": ["Annual Family Income"],
    "SSLC": ["SSLC Mark Percentage"],
    "HSC": ["HSC Mark Percentage"],
    "NATIVITY": ["Nativity"],
    "BONAFIDE": ["School Name"],
    "MIGRATION": ["Migration Number", "University", "Year"],
}

DOCUMENT_DISPLAY_NAMES: Dict[str, str] = {
    "AADHAAR": "Aadhaar Card",
    "TRANSFER_CERTIFICATE": "Transfer Certificate (TC)",
    "COMMUNITY": "Community Certificate",
    "INCOME": "Income Certificate",
    "SSLC": "SSLC Marksheet (10th)",
    "HSC": "HSC Marksheet (12th)",
    "NATIVITY": "Nativity Certificate",
    "BONAFIDE": "Bonafide Certificate",
    "MIGRATION": "Migration Certificate",
}


class WantedFieldService:
    """
    Business service layer orchestrating Document-Specific Wanted Field configurations,
    validation against Excel templates, and synchronization with extraction/persistence engines.
    Staff manually creates document types and selects wanted fields.
    """

    def __init__(self, repository: Optional[WantedFieldRepository] = None):
        self.repository = repository or WantedFieldRepository()

    def get_available_fields_for_doc_type(self, doc_type: str) -> List[str]:
        """Return catalog of available fields for a canonical document type."""
        norm_type = normalize_document_code(doc_type) or normalize_document_type(doc_type)
        return DOCUMENT_AVAILABLE_FIELDS_CATALOG.get(norm_type, [norm_type])

    def get_default_wanted_fields_for_doc_type(self, doc_type: str) -> List[str]:
        """Return default enabled wanted fields for backward compatibility."""
        norm_type = normalize_document_code(doc_type) or normalize_document_type(doc_type)
        return DEFAULT_DOCUMENT_WANTED_FIELDS.get(norm_type, [norm_type])

    async def get_active_wanted_fields(
        self, batch_id: str, doc_type: str, class_id: Optional[str] = None
    ) -> Optional[List[str]]:
        """
        Get the currently active (enabled) wanted fields for a document type.
        Returns:
            - list[str]: explicit list of enabled fields (can be [] if staff disabled all fields).
            - None: if no configuration exists for this batch, indicating backward-compatible default fallback.
        """
        norm_type = normalize_document_code(doc_type) or normalize_document_type(doc_type)
        config = await self.repository.get_by_batch_and_doc_type(batch_id, norm_type, class_id=class_id)
        if not config:
            return None
        return [f.field for f in config.fields if f.enabled]

    async def get_all_active_wanted_fields_by_batch(
        self, batch_id: str, class_id: Optional[str] = None
    ) -> Dict[str, List[str]]:
        """
        Returns a dict mapping doc_type -> list of enabled field names for this batch.
        Only doc_types that have an explicit DocumentFieldConfiguration saved are included.
        If a doc_type IS in the dict with [], it means staff explicitly selected 0 wanted fields for it.
        """
        configs = await self.repository.list_by_batch(batch_id, class_id=class_id)
        return {c.document_type: [f.field for f in c.fields if f.enabled] for c in configs}

    async def create_document_type(
        self,
        batch_id: str,
        name: str,
        code: str,
        description: Optional[str] = None,
        class_id: Optional[str] = None,
        initial_fields: Optional[List[str]] = None,
        requirement_status: str = "REQUIRED",
        allowed_types: Optional[List[str]] = None,
        max_size_mb: Optional[float] = None,
    ) -> DocumentFieldConfiguration:
        """
        Staff/Admin creates a new document type for a specific batch.
        Validates non-empty name and code, ensures code uniqueness, normalizes code,
        and initializes the document with ZERO wanted fields.
        """
        name_clean = name.strip()
        code_clean = code.strip()
        if not name_clean:
            raise ValueError("Document Name is required.")
        if not code_clean:
            raise ValueError("Document Code is required.")

        norm_code = normalize_document_code(code_clean)
        if not norm_code:
            raise ValueError("Document Code must contain alphanumeric characters.")

        req_status_clean = requirement_status.strip().upper() if requirement_status else "REQUIRED"
        if req_status_clean not in ["REQUIRED", "OPTIONAL", "DISABLED"]:
            req_status_clean = "REQUIRED"

        types = allowed_types if allowed_types else ["PDF", "JPG", "PNG"]
        size_limit = max_size_mb if max_size_mb and max_size_mb > 0 else 5.0

        # Check existing code within batch/class scope (including archived)
        existing = await self.repository.get_by_batch_and_doc_type(
            batch_id, norm_code, class_id=class_id, include_archived=True, exact_scope_only=True
        )
        if existing:
            # If same display name or archived or updating requirements, update idempotently
            if existing.is_archived or existing.display_name.strip().lower() == name_clean.lower():
                existing.display_name = name_clean
                if description is not None:
                    existing.description = description.strip() if description else None
                existing.requirement_status = req_status_clean
                existing.allowed_types = types
                existing.max_size_mb = size_limit
                existing.is_archived = False
                existing.version += 1
                if initial_fields:
                    merged = list(dict.fromkeys((existing.available_fields or []) + [f.strip() for f in initial_fields if f.strip()]))
                    existing.available_fields = merged
                return await existing.save()
            else:
                raise ValueError(f"Document type with code '{norm_code}' already exists for this batch.")

        # Check unique display name within batch
        existing_list = await self.repository.list_by_batch(batch_id, class_id=class_id)
        for c in existing_list:
            if c.display_name and c.display_name.strip().lower() == name_clean.lower():
                raise ValueError(f"Document type with name '{name_clean}' already exists for this batch.")

        # Resolve available fields
        if initial_fields and len(initial_fields) > 0:
            available = [f.strip() for f in initial_fields if f.strip()]
        else:
            catalog_match = DOCUMENT_AVAILABLE_FIELDS_CATALOG.get(norm_code)
            if not catalog_match and norm_code in [
                "AADHAAR", "TC", "TRANSFER_CERTIFICATE", "COMMUNITY", "INCOME",
                "SSLC", "HSC", "NATIVITY", "BONAFIDE", "MIGRATION"
            ]:
                catalog_match = DOCUMENT_AVAILABLE_FIELDS_CATALOG.get(normalize_document_type(norm_code))
            available = list(catalog_match) if catalog_match else []

        # Deduplicate available fields
        available = list(dict.fromkeys(available))

        # Initialize all available fields as disabled (ZERO wanted fields)
        field_items = [
            WantedFieldItem(field=f, enabled=False, excel_header=None)
            for f in available
        ]

        return await self.repository.create_document_type(
            batch_id=batch_id,
            document_type=norm_code,
            display_name=name_clean,
            description=description.strip() if description else None,
            class_id=class_id,
            available_fields=available,
            fields=field_items,
            requirement_status=req_status_clean,
            allowed_types=types,
            max_size_mb=size_limit,
        )

    async def add_field_to_document(
        self,
        batch_id: str,
        doc_type: str,
        field_name: str,
        class_id: Optional[str] = None,
    ) -> DocumentFieldConfiguration:
        """
        Add a custom field to a document configuration's available fields list.
        """
        field_clean = field_name.strip()
        if not field_clean:
            raise ValueError("Field name cannot be empty.")

        norm_type = normalize_document_code(doc_type) or normalize_document_type(doc_type)
        config = await self.repository.get_by_batch_and_doc_type(batch_id, norm_type, class_id=class_id)
        if not config:
            raise ValueError(f"Document type '{doc_type}' not found for this batch.")

        # Add to fields if not already present
        existing_field_names = [f.field for f in config.fields]
        if field_clean not in existing_field_names:
            config.fields.append(WantedFieldItem(field=field_clean, enabled=False, excel_header=None))

        # Add to available_fields
        if not hasattr(config, "available_fields") or config.available_fields is None:
            config.available_fields = []
        if field_clean not in config.available_fields:
            config.available_fields.append(field_clean)

        return await self.repository.save_or_update(
            batch_id=batch_id,
            document_type=norm_type,
            fields=config.fields,
            display_name=config.display_name,
            description=config.description,
            available_fields=config.available_fields,
            class_id=class_id,
        )

    async def delete_or_archive_document_type(
        self,
        batch_id: str,
        doc_type: str,
        class_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Safely remove a document type. If existing uploaded student submissions reference it,
        soft-archives it to ensure uploaded student documents remain readable.
        """
        norm_type = normalize_document_code(doc_type) or normalize_document_type(doc_type)
        config = await self.repository.get_by_batch_and_doc_type(batch_id, norm_type, class_id=class_id)
        if not config:
            raise ValueError(f"Document type '{doc_type}' not found for this batch.")

        # Check dependency in student submissions
        has_submissions = False
        try:
            has_submissions = (
                await StudentSubmission.find(
                    StudentSubmission.batch_id == batch_id,
                    {"documents.document_name": {"$regex": norm_type, "$options": "i"}},
                ).count()
                > 0
            )
        except Exception:
            has_submissions = False

        if has_submissions:
            # Soft-archive
            await self.repository.archive_document_type(batch_id, norm_type, class_id=class_id)
            is_archived = True
        else:
            # Hard delete if safe
            await self.repository.delete_document_type(batch_id, norm_type, class_id=class_id)
            is_archived = False

        # Synchronize ExcelBatchTemplate by removing mappings from this document
        template = await ExcelBatchTemplate.find_one(
            ExcelBatchTemplate.batch_id == batch_id,
            ExcelBatchTemplate.class_id == class_id,
        ) or await ExcelBatchTemplate.find_one(ExcelBatchTemplate.batch_id == batch_id)

        if template and template.field_mappings:
            mappings = dict(template.field_mappings)
            for f in config.fields:
                mappings.pop(f.field, None)
            template.field_mappings = mappings
            await template.save()

        return {
            "success": True,
            "archived": is_archived,
            "message": (
                f"Document type '{config.display_name or norm_type}' has been archived because student documents reference it."
                if is_archived
                else f"Document type '{config.display_name or norm_type}' has been deleted."
            ),
        }

    def validate_document_fields(
        self,
        doc_type: str,
        fields: List[WantedFieldItem],
        allowed_headers: Optional[List[str]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate wanted fields configuration:
        1. Enabled fields must have a valid, non-empty Excel target column.
        2. Excel target column must exist in template headers (if provided).
        3. Semantic compatibility check: AI field and Excel target must be semantically compatible.
        4. Duplicate target ownership: two enabled fields cannot claim the same Excel column.
        """
        allowed_set = set(allowed_headers) if allowed_headers else None
        target_to_field: Dict[str, str] = {}

        for item in fields:
            if not item.enabled:
                continue

            target = item.excel_header.strip() if item.excel_header else ""
            if not target:
                return (
                    False,
                    f"Enabled wanted field '{item.field}' must have a valid Excel target column selected.",
                )

            if allowed_set is not None and target not in allowed_set:
                return (
                    False,
                    f"Unknown Excel header '{target}' for field '{item.field}'. Must be one of the template headers.",
                )

            # Duplicate target ownership check
            if target in target_to_field:
                existing_src = target_to_field[target]
                if existing_src != item.field:
                    return (
                        False,
                        f"Conflict: Excel column '{target}' is already mapped to '{existing_src}'. One target column cannot have multiple distinct source fields ('{existing_src}' and '{item.field}').",
                    )
            else:
                target_to_field[target] = item.field

            # Semantic compatibility check
            is_compat, msg = is_mapping_compatible(item.field, target)
            if not is_compat:
                return False, msg

        return True, None

    async def get_document_configuration(
        self, batch_id: str, doc_type: str, class_id: Optional[str] = None
    ) -> Optional[DocumentFieldConfiguration]:
        """
        Retrieve existing DocumentFieldConfiguration.
        Returns None if document type is not configured (no auto-synthesizing defaults).
        """
        norm_type = normalize_document_code(doc_type) or normalize_document_type(doc_type)
        config = await self.repository.get_by_batch_and_doc_type(batch_id, norm_type, class_id=class_id)
        if config:
            if not config.display_name:
                config.display_name = DOCUMENT_DISPLAY_NAMES.get(norm_type, norm_type)
            if not getattr(config, "available_fields", None):
                config.available_fields = [f.field for f in config.fields]
            return config

        return None

    async def save_document_configuration(
        self,
        batch_id: str,
        doc_type: str,
        fields: List[WantedFieldItem],
        allowed_headers: Optional[List[str]] = None,
        class_id: Optional[str] = None,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        requirement_status: Optional[str] = None,
        allowed_types: Optional[List[str]] = None,
        max_size_mb: Optional[float] = None,
    ) -> DocumentFieldConfiguration:
        """
        Validate and save wanted field configuration for a specific document type.
        Synchronizes enabled mappings into ExcelBatchTemplate.field_mappings.
        """
        norm_type = normalize_document_code(doc_type) or normalize_document_type(doc_type)

        # 1. Validation
        is_valid, err_msg = self.validate_document_fields(norm_type, fields, allowed_headers)
        if not is_valid:
            raise ValueError(err_msg or "Invalid document field configuration.")

        # Ensure available_fields includes all configured field names
        available_fields = [f.field for f in fields]

        # 2. Save document configuration in MongoDB
        saved_config = await self.repository.save_or_update(
            batch_id=batch_id,
            document_type=norm_type,
            fields=fields,
            display_name=display_name,
            description=description,
            available_fields=available_fields,
            class_id=class_id,
            requirement_status=requirement_status,
            allowed_types=allowed_types,
            max_size_mb=max_size_mb,
        )

        # 3. Synchronize with ExcelBatchTemplate.field_mappings
        template = await ExcelBatchTemplate.find_one(
            ExcelBatchTemplate.batch_id == batch_id,
            ExcelBatchTemplate.class_id == class_id,
        ) or await ExcelBatchTemplate.find_one(ExcelBatchTemplate.batch_id == batch_id)

        if template:
            mappings = dict(template.field_mappings or {})
            # Update mappings for this document's configured fields
            for item in fields:
                if item.enabled and item.excel_header:
                    mappings[item.field] = item.excel_header
                else:
                    # If field was disabled or unmapped, remove its mapping
                    mappings.pop(item.field, None)

            template.field_mappings = mappings
            await template.save()

        return saved_config

    async def get_batch_overview(
        self, batch_id: str, class_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Return overview status across all CONFIGURED document types for a batch.
        If staff has not created any document types for this batch, returns [].
        """
        # Fetch template to know available headers
        template = await ExcelBatchTemplate.find_one(
            ExcelBatchTemplate.batch_id == batch_id,
            ExcelBatchTemplate.class_id == class_id,
        ) or await ExcelBatchTemplate.find_one(ExcelBatchTemplate.batch_id == batch_id)
        template_headers = template.headers if template else []

        # Get only the document configurations that exist in MongoDB for this batch
        configs = await self.repository.list_by_batch(batch_id, class_id=class_id)
        if not configs:
            return []

        overview: List[Dict[str, Any]] = []
        seen_overview_codes: set[str] = set()
        for config in configs:
            doc_code = config.document_type.upper().strip()
            if doc_code in seen_overview_codes:
                continue
            seen_overview_codes.add(doc_code)

            wanted_count = sum(1 for f in config.fields if f.enabled)
            mapped_count = sum(1 for f in config.fields if f.enabled and f.excel_header)
            unmapped_count = wanted_count - mapped_count

            if wanted_count == 0:
                status = "NO_WANTED_FIELDS"
            elif unmapped_count == 0:
                status = "CONFIGURED"
            else:
                status = "INCOMPLETE"

            disp_name = (
                config.display_name
                or DOCUMENT_DISPLAY_NAMES.get(config.document_type)
                or config.document_type
            )
            av_fields = getattr(config, "available_fields", None) or [f.field for f in config.fields]
            req_status = (getattr(config, "requirement_status", None) or "REQUIRED").upper()
            types = getattr(config, "allowed_types", None) or ["PDF", "JPG", "PNG"]
            max_size = getattr(config, "max_size_mb", None) or 5.0

            overview.append({
                "document_type": config.document_type,
                "display_name": disp_name,
                "description": getattr(config, "description", None),
                "wanted_count": wanted_count,
                "mapped_count": mapped_count,
                "unmapped_count": unmapped_count,
                "status": status,
                "requirement_status": req_status,
                "allowed_types": types,
                "max_size_mb": max_size,
                "version": config.version,
                "fields": [f.model_dump() for f in config.fields],
                "available_fields": av_fields,
                "template_headers": template_headers,
            })

        return overview

    async def get_student_document_requirements(
        self, batch_id: str, class_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get the dynamically configured document requirements for the Student Portal.
        Respects batch and class scoping.
        Filters out archived documents and documents with requirement_status == 'DISABLED'.
        Returns list of document requirement dicts suitable for the student checklist.
        Defensively guarantees that each document type appears at most once.
        """
        configs = await self.repository.list_by_batch(batch_id, class_id=class_id)
        if not configs and class_id:
            # Fallback to batch-level config if class-level config has no documents
            configs = await self.repository.list_by_batch(batch_id, class_id=None)

        results: List[Dict[str, Any]] = []
        seen_req_codes: set[str] = set()
        for config in configs:
            if getattr(config, "is_archived", False):
                continue
            req_status = (getattr(config, "requirement_status", None) or "REQUIRED").upper()
            if req_status == "DISABLED":
                continue

            doc_code = config.document_type.upper().strip()
            if doc_code in seen_req_codes:
                continue
            seen_req_codes.add(doc_code)

            disp_name = (
                config.display_name
                or DOCUMENT_DISPLAY_NAMES.get(config.document_type)
                or config.document_type
            )
            is_mandatory = (req_status == "REQUIRED")
            allowed_types = getattr(config, "allowed_types", None) or ["PDF", "JPG", "PNG"]
            max_size_mb = getattr(config, "max_size_mb", None) or 5.0
            wanted_fields = [f.field for f in config.fields if f.enabled]

            results.append({
                "id": str(config.id) if config.id else config.document_type,
                "name": disp_name,
                "code": config.document_type,
                "document_type": config.document_type,
                "document_name": disp_name,
                "document_code": config.document_type,
                "requirement_status": req_status,
                "required": is_mandatory,
                "type": "MANDATORY" if is_mandatory else "OPTIONAL",
                "allowed_types": allowed_types,
                "max_size_mb": max_size_mb,
                "description": getattr(config, "description", None) or "",
                "wanted_fields": wanted_fields,
                "extraction_fields": wanted_fields,
            })

        return results

