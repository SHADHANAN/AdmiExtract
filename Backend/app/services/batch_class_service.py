import uuid
from app.models.batch import AdmissionBatch
from app.models.batch_class import BatchClass
from app.schemas.batch_class import ClassCreate, ClassUpdate
from app.repositories.batch_class_repository import BatchClassRepository


class ClassNotFoundException(Exception):
    def __init__(self, message: str = "Class not found"):
        self.message = message
        super().__init__(self.message)


class BatchClassService:
    """
    Service layer handling business logic for Batch Classes.
    Enforces unique class name constraints per batch.
    """

    def __init__(self, repository: BatchClassRepository | None = None):
        self.repository = repository or BatchClassRepository()

    async def create_class(self, batch_id: str, data: ClassCreate) -> BatchClass:
        """
        Create a new Class inside an Admission Batch.
        Enforces unique class_name within the batch.
        """
        batch_id_clean = batch_id.strip()
        
        # Verify batch exists
        batch_doc = await AdmissionBatch.get(batch_id_clean)
        if not batch_doc:
            raise ValueError(f"Admission Batch with ID '{batch_id}' not found.")

        clean_name = data.class_name.strip()
        
        # Check uniqueness constraint: Class names must be unique within a batch
        existing = await self.repository.get_class_by_name_and_batch(batch_id_clean, clean_name)
        if existing:
            raise ValueError(f"Class name '{clean_name}' already exists in batch '{batch_id_clean}'.")

        # Generate a deterministic/clean string ID
        slug = clean_name.lower().replace(" ", "_").replace("-", "_").replace(".", "")
        custom_id = f"class_{batch_id_clean}_{slug}"
        
        # Fallback to UUID suffix if custom_id exists
        if await self.repository.get_class_by_id(custom_id):
            custom_id = f"class_{batch_id_clean}_{slug}_{uuid.uuid4().hex[:6]}"

        class_doc = BatchClass(
            id=custom_id,
            batch_id=batch_id_clean,
            class_name=clean_name,
            department=data.department.strip(),
            section=data.section.strip(),
            academic_year=data.academic_year.strip(),
        )

        return await self.repository.create_class(class_doc)

    async def get_classes_by_batch(self, batch_id: str) -> list[BatchClass]:
        """List all classes for a batch."""
        return await self.repository.get_classes_by_batch_id(batch_id.strip())

    async def get_class_by_id(self, class_id: str) -> BatchClass:
        """Fetch class details by class_id."""
        class_doc = await self.repository.get_class_by_id(class_id.strip())
        if not class_doc:
            raise ClassNotFoundException(f"Class with ID '{class_id}' not found.")
        return class_doc

    async def update_class(self, class_id: str, data: ClassUpdate) -> BatchClass:
        """Update class details."""
        class_doc = await self.get_class_by_id(class_id)
        
        update_dict = data.model_dump(exclude_unset=True)
        if not update_dict:
            return class_doc

        # Check unique class name constraint if name is being changed
        if "class_name" in update_dict and update_dict["class_name"]:
            new_name = update_dict["class_name"].strip()
            if new_name.lower() != class_doc.class_name.lower():
                existing = await self.repository.get_class_by_name_and_batch(class_doc.batch_id, new_name)
                if existing and existing.id != class_doc.id:
                    raise ValueError(f"Class name '{new_name}' already exists in batch '{class_doc.batch_id}'.")
            update_dict["class_name"] = new_name

        updated = await self.repository.update_class(class_id, update_dict)
        if not updated:
            raise ClassNotFoundException(f"Class with ID '{class_id}' not found.")
        return updated

    async def delete_class(self, class_id: str) -> bool:
        """Delete a class."""
        class_doc = await self.get_class_by_id(class_id)
        
        # Check if students are mapped to this class before deletion
        from app.models.student_submission import StudentSubmission
        student_count = await StudentSubmission.find(StudentSubmission.class_id == class_doc.id).count()
        if student_count > 0:
            raise ValueError(f"Cannot delete class '{class_doc.class_name}': {student_count} student submission(s) are mapped to it.")

        return await self.repository.delete_class(class_id)
