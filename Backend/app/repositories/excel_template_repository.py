from datetime import datetime, timezone
from app.models.excel_template import ExcelBatchTemplate


class ExcelTemplateRepository:
    """
    Repository for managing ExcelBatchTemplate Beanie document operations in MongoDB.
    """

    async def get_by_batch_id(self, batch_id: str) -> ExcelBatchTemplate | None:
        """Retrieve Excel batch template metadata by batch ID."""
        return await ExcelBatchTemplate.find_one(ExcelBatchTemplate.batch_id == batch_id)

    async def save_template(self, template: ExcelBatchTemplate) -> ExcelBatchTemplate:
        """Save or insert Excel batch template."""
        existing = await self.get_by_batch_id(template.batch_id)
        if existing:
            existing.template_filename = template.template_filename
            existing.file_path = template.file_path
            existing.headers = template.headers
            existing.total_rows = template.total_rows
            existing.updated_at = datetime.now(timezone.utc)
            await existing.save()
            return existing
        else:
            return await template.insert()

    async def update_mappings(
        self, batch_id: str, field_mappings: dict[str, str], lookup_column: str
    ) -> ExcelBatchTemplate | None:
        """Update field mappings and lookup key column."""
        existing = await self.get_by_batch_id(batch_id)
        if not existing:
            return None

        existing.field_mappings = field_mappings
        existing.lookup_column = lookup_column
        existing.updated_at = datetime.now(timezone.utc)
        await existing.save()
        return existing

    async def increment_updated_count(self, batch_id: str) -> ExcelBatchTemplate | None:
        """Increment updated student row counter."""
        existing = await self.get_by_batch_id(batch_id)
        if not existing:
            return None

        existing.updated_count += 1
        existing.updated_at = datetime.now(timezone.utc)
        await existing.save()
        return existing
