from app.models.doc_config_version import DocumentConfigurationVersion


class DocConfigVersionRepository:
    """
    Repository handling database operations for document configuration versions.
    """

    async def get_current_by_batch_id(self, batch_id: str) -> DocumentConfigurationVersion | None:
        """Retrieve the currently active document configuration version for a batch."""
        return await DocumentConfigurationVersion.find_one(
            DocumentConfigurationVersion.batch_id == batch_id,
            DocumentConfigurationVersion.is_current == True,
        )

    async def get_history_by_batch_id(self, batch_id: str) -> list[DocumentConfigurationVersion]:
        """Retrieve all document configuration versions for a batch, ordered by version descending."""
        return await DocumentConfigurationVersion.find(
            DocumentConfigurationVersion.batch_id == batch_id
        ).sort("-version").to_list()

    async def get_by_version(self, batch_id: str, version: int) -> DocumentConfigurationVersion | None:
        """Retrieve a specific document configuration version by version number."""
        return await DocumentConfigurationVersion.find_one(
            DocumentConfigurationVersion.batch_id == batch_id,
            DocumentConfigurationVersion.version == version,
        )

    async def save_version(self, version_doc: DocumentConfigurationVersion) -> DocumentConfigurationVersion:
        """Save a new document configuration version."""
        await version_doc.insert()
        return version_doc

    async def archive_previous_current(self, batch_id: str) -> None:
        """Mark previous versions as not current."""
        current = await self.get_current_by_batch_id(batch_id)
        if current:
            current.is_current = False
            await current.save()
