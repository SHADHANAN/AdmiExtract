import asyncio
import io
import os
import sys
from fastapi import UploadFile

# Ensure Backend root is in sys.path
sys.path.insert(0, os.path.dirname(__file__))

from app.core.config import settings
from app.db.database import init_db
from app.models.batch import AdmissionBatch
from app.services.document_processing_pipeline import DocumentProcessingPipeline

async def run_benchmark():
    print("=" * 70)
    print("STARTING PRODUCTION EXTRACTION PIPELINE BENCHMARK")
    print("=" * 70)

    # Initialize DB
    await init_db()

    batch_id = "test-perf-benchmark-batch"

    # Ensure Batch exists
    batch = await AdmissionBatch.find_one({"_id": batch_id})
    if not batch:
        batch = AdmissionBatch(
            id=batch_id,
            name="Perf Benchmark Batch",
            department_id="DEPT-PERF",
            academic_year="2027-2028",
            status="active",
            created_by="admin"
        )
        await batch.insert()

    # Load 4 real files from uploads
    uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
    file_specs = [
        ("TC.pdf", "application/pdf"),
        ("digital_commity.pdf", "application/pdf"),
        ("Screenshot 2026-08-05 162541.png", "image/png"),
        ("10th Mark sheet.pdf", "application/pdf"),
    ]

    def make_upload_files():
        ufs = []
        for fname, mime in file_specs:
            fpath = os.path.join(uploads_dir, fname)
            with open(fpath, "rb") as f:
                content = f.read()
            uf = UploadFile(
                filename=fname,
                file=io.BytesIO(content),
                headers={"content-type": mime}
            )
            ufs.append(uf)
        return ufs

    pipeline = DocumentProcessingPipeline()

    print("\n>>> EXECUTING RUN 1 (BASELINE COLD RUN) <<<")
    result1 = await pipeline.process_student_documents(
        batch_id=batch_id,
        register_number="24AM0965",
        student_name="Shadhanan",
        mobile_number="9488203077",
        files=make_upload_files()
    )

    print("\n>>> EXECUTING RUN 2 (WARM RE-EXTRACTION RUN) <<<")
    result2 = await pipeline.process_student_documents(
        batch_id=batch_id,
        register_number="24AM0965",
        student_name="Shadhanan",
        mobile_number="9488203077",
        files=make_upload_files()
    )

if __name__ == "__main__":
    asyncio.run(run_benchmark())
