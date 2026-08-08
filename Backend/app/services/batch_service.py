import uuid
from app.models.batch import AdmissionBatch
from app.schemas.batch import BatchCreate
from app.repositories.batch_repository import BatchRepository


class BatchNotFoundException(Exception):
    def __init__(self, message: str = "Admission batch not found"):
        self.message = message
        super().__init__(self.message)


class BatchService:
    def __init__(self, repository: BatchRepository | None = None):
        self.repository = repository or BatchRepository()

    async def create_batch(self, data: BatchCreate, created_by: str) -> AdmissionBatch:
        batch_id = data.id.strip() if data.id else f"batch_{uuid.uuid4().hex[:8]}"
        
        # Check if ID already exists
        existing = await self.repository.get_batch_by_id(batch_id)
        if existing:
            raise ValueError(f"Batch with ID '{batch_id}' already exists.")

        new_batch = AdmissionBatch(
            id=batch_id,
            name=data.name.strip(),
            department_id=data.department_id.strip(),
            academic_year=data.academic_year.strip(),
            description=data.description.strip() if data.description else None,
            start_date=data.start_date.strip() if data.start_date else None,
            end_date=data.end_date.strip() if data.end_date else None,
            status=data.status,
            created_by=created_by,
        )
        return await self.repository.create_batch(new_batch)

    async def get_batch_by_id(self, batch_id: str) -> AdmissionBatch:
        batch = await self.repository.get_batch_by_id(batch_id)
        if not batch:
            raise BatchNotFoundException(f"Batch with ID '{batch_id}' not found.")
        return batch

    async def get_all_batches(self) -> list[AdmissionBatch]:
        return await self.repository.get_all_batches()

    async def get_batches_by_department(self, department_id: str) -> list[AdmissionBatch]:
        return await self.repository.get_batches_by_department(department_id)

    async def update_batch(self, batch_id: str, update_data: dict) -> AdmissionBatch:
        updated = await self.repository.update_batch(batch_id, update_data)
        if not updated:
            raise BatchNotFoundException(f"Batch with ID '{batch_id}' not found.")
        return updated

    async def delete_batch(self, batch_id: str) -> bool:
        deleted = await self.repository.delete_batch(batch_id)
        if not deleted:
            raise BatchNotFoundException(f"Batch with ID '{batch_id}' not found.")
        return True
