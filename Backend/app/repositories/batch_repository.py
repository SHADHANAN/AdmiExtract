from app.models.batch import AdmissionBatch


class BatchRepository:
    async def create_batch(self, batch: AdmissionBatch) -> AdmissionBatch:
        return await batch.insert()

    async def get_batch_by_id(self, batch_id: str) -> AdmissionBatch | None:
        return await AdmissionBatch.get(batch_id)

    async def get_all_batches(self) -> list[AdmissionBatch]:
        return await AdmissionBatch.find_all().sort("-created_at").to_list()

    async def get_batches_by_department(self, department_id: str) -> list[AdmissionBatch]:
        return await AdmissionBatch.find(AdmissionBatch.department_id == department_id).sort("-created_at").to_list()

    async def update_batch(self, batch_id: str, update_data: dict) -> AdmissionBatch | None:
        batch = await AdmissionBatch.get(batch_id)
        if not batch:
            return None

        for key, value in update_data.items():
            if hasattr(batch, key):
                setattr(batch, key, value)

        await batch.save()
        return batch

    async def delete_batch(self, batch_id: str) -> bool:
        batch = await AdmissionBatch.get(batch_id)
        if not batch:
            return False
        await batch.delete()
        return True
