from app.models.batch_class import BatchClass


class BatchClassRepository:
    """
    Repository layer for managing MongoDB operations on batch_classes collection.
    """

    async def create_class(self, class_doc: BatchClass) -> BatchClass:
        """Insert a new BatchClass document into MongoDB."""
        return await class_doc.insert()

    async def get_class_by_id(self, class_id: str) -> BatchClass | None:
        """Fetch a BatchClass by ID."""
        return await BatchClass.get(class_id)

    async def get_classes_by_batch_id(self, batch_id: str) -> list[BatchClass]:
        """Fetch all BatchClass documents belonging to a given batch_id."""
        return await BatchClass.find(BatchClass.batch_id == batch_id).to_list()

    async def get_class_by_name_and_batch(self, batch_id: str, class_name: str) -> BatchClass | None:
        """Fetch a BatchClass by batch_id and exact class_name (case-insensitive check)."""
        classes = await self.get_classes_by_batch_id(batch_id)
        norm_target = class_name.strip().lower()
        for c in classes:
            if c.class_name.strip().lower() == norm_target:
                return c
        return None

    async def update_class(self, class_id: str, update_data: dict) -> BatchClass | None:
        """Update fields of a BatchClass document."""
        class_doc = await self.get_class_by_id(class_id)
        if not class_doc:
            return None
        
        for field, value in update_data.items():
            if value is not None and hasattr(class_doc, field):
                setattr(class_doc, field, value)
        
        await class_doc.save()
        return class_doc

    async def delete_class(self, class_id: str) -> bool:
        """Delete a BatchClass document by ID."""
        class_doc = await self.get_class_by_id(class_id)
        if not class_doc:
            return False
        await class_doc.delete()
        return True

    async def delete_classes_by_batch_id(self, batch_id: str) -> int:
        """Delete all BatchClass documents associated with a batch_id."""
        classes = await self.get_classes_by_batch_id(batch_id)
        count = 0
        for c in classes:
            await c.delete()
            count += 1
        return count
