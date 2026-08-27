from datetime import datetime, timezone
from app.models.excel_template import ExcelBatchTemplate


class ExcelTemplateRepository:
    """
    Repository for managing ExcelBatchTemplate Beanie document operations in MongoDB.
    Supports per-class and per-batch Excel template resolution.
    """

    async def get_by_batch_id(self, batch_id: str, class_id: str | None = None) -> ExcelBatchTemplate | None:
        """
        Retrieve Excel batch template metadata.
        If class_id is provided, look for a class-specific template first.
        Fallback to batch-level template if class_id template is not found.
        """
        if class_id:
            class_template = await ExcelBatchTemplate.find_one(
                ExcelBatchTemplate.class_id == class_id
            )
            if class_template:
                return class_template
        
        # Fallback to batch level
        return await ExcelBatchTemplate.find_one(
            ExcelBatchTemplate.batch_id == batch_id,
            ExcelBatchTemplate.class_id == None  # noqa: E711
        ) or await ExcelBatchTemplate.find_one(ExcelBatchTemplate.batch_id == batch_id)

    async def save_template(self, template: ExcelBatchTemplate) -> ExcelBatchTemplate:
        """Save or insert Excel batch/class template."""
        if template.class_id:
            existing = await ExcelBatchTemplate.find_one(ExcelBatchTemplate.class_id == template.class_id)
        else:
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
        self, batch_id: str, field_mappings: dict[str, str], lookup_column: str, class_id: str | None = None
    ) -> ExcelBatchTemplate | None:
        """Update field mappings and lookup key column."""
        existing = await self.get_by_batch_id(batch_id, class_id=class_id)
        if not existing:
            return None

        existing.field_mappings = field_mappings
        existing.lookup_column = lookup_column
        existing.updated_at = datetime.now(timezone.utc)
        await existing.save()
        return existing

    async def increment_updated_count(self, batch_id: str, class_id: str | None = None) -> ExcelBatchTemplate | None:
        """Increment updated student row counter."""
        existing = await self.get_by_batch_id(batch_id, class_id=class_id)
        if not existing:
            return None

        existing.updated_count += 1
        existing.updated_at = datetime.now(timezone.utc)
        await existing.save()
        return existing
