from app.models.doc_config_version import (
    DocumentConfigurationVersion,
    DocumentRequirementItem,
    get_default_extraction_fields,
)
from app.repositories.doc_config_version_repository import DocConfigVersionRepository
from app.schemas.doc_config_version import DocRequirementSchema
from app.utils.field_canonicalizer import is_profile_field


DEFAULT_V1_DOCUMENTS = [
    DocumentRequirementItem(
        id="req_1",
        name="Aadhaar Card",
        required=True,
        type="MANDATORY",
        description="Aadhaar card front and back",
        extraction_fields=["Aadhaar Number"],
    ),
    DocumentRequirementItem(
        id="req_2",
        name="SSLC Marksheet",
        required=True,
        type="MANDATORY",
        description="10th official marks statement",
        extraction_fields=["SSLC Mark Percentage"],
    ),
    DocumentRequirementItem(
        id="req_3",
        name="HSC Marksheet",
        required=True,
        type="MANDATORY",
        description="12th official marks statement",
        extraction_fields=["HSC Mark Percentage"],
    ),
    DocumentRequirementItem(
        id="req_4",
        name="Community Certificate",
        required=True,
        type="MANDATORY",
        description="Community reservation certificate",
        extraction_fields=["Community Category"],
    ),
]


class DocConfigVersionService:
    """
    Service handling document configuration version creation, history tracking,
    and fallback initialization.
    """

    def __init__(self, repository: DocConfigVersionRepository | None = None):
        self.repository = repository or DocConfigVersionRepository()

    async def get_or_create_current_version(self, batch_id: str) -> DocumentConfigurationVersion:
        """
        Get active version for batch_id. If none exists, create default Version 1.
        """
        current = await self.repository.get_current_by_batch_id(batch_id)
        if not current:
            from app.models.batch import AdmissionBatch
            batch_doc = await AdmissionBatch.get(batch_id)
            department_id = batch_doc.department_id if batch_doc else None

            current = DocumentConfigurationVersion(
                batch_id=batch_id,
                department_id=department_id,
                version=1,
                documents=DEFAULT_V1_DOCUMENTS,
                is_current=True,
                change_summary="Initial document configuration (Version 1)",
                created_by="System",
            )
            await self.repository.save_version(current)
        return current

    async def create_new_version(
        self,
        batch_id: str,
        documents: list[DocRequirementSchema],
        change_summary: str | None = None,
        created_by: str = "Staff",
    ) -> DocumentConfigurationVersion:
        """
        Create a new configuration version (e.g. Version 2) without mutating existing student records.
        """
        current = await self.get_or_create_current_version(batch_id)
        new_version_num = current.version + 1

        # Archive current active version
        await self.repository.archive_previous_current(batch_id)

        # Convert schemas to model items
        doc_items = []
        for d in documents:
            ef = d.extraction_fields if d.extraction_fields else get_default_extraction_fields(d.name)
            doc_items.append(
                DocumentRequirementItem(
                    id=d.id,
                    name=d.name,
                    required=d.required,
                    allowed_types=d.allowed_types,
                    max_size_mb=d.max_size_mb,
                    description=d.description,
                    type=d.type,
                    extraction_fields=ef,
                )
            )

        from app.models.batch import AdmissionBatch
        batch_doc = await AdmissionBatch.get(batch_id)
        department_id = batch_doc.department_id if batch_doc else None

        new_version = DocumentConfigurationVersion(
            batch_id=batch_id,
            department_id=department_id,
            version=new_version_num,
            documents=doc_items,
            is_current=True,
            change_summary=change_summary or f"Updated to Version {new_version_num}",
            created_by=created_by,
        )
        return await self.repository.save_version(new_version)

    async def get_version_history(self, batch_id: str) -> list[DocumentConfigurationVersion]:
        """
        Get all versions for an admission batch. Ensures Version 1 exists.
        """
        history = await self.repository.get_history_by_batch_id(batch_id)
        if not history:
            v1 = await self.get_or_create_current_version(batch_id)
            return [v1]
        return history

    async def get_batch_extraction_fields(self, batch_id: str) -> list[str]:
        """
        Collect unique extraction fields across all active document requirements for a batch.
        """
        version = await self.get_or_create_current_version(batch_id)
        unique_fields: list[str] = []
        for doc in version.documents:
            fields = doc.extraction_fields if doc.extraction_fields else get_default_extraction_fields(doc.name)
            for f in fields:
                f_clean = f.strip()
                if f_clean and not is_profile_field(f_clean) and f_clean not in unique_fields:
                    unique_fields.append(f_clean)
        return unique_fields

