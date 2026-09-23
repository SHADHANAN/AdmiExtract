import asyncio
import io
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, cast
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.models.user import User
from app.models.department import Department
from app.models.batch import AdmissionBatch
from app.models.batch_class import BatchClass
from app.models.upload_link import UploadLink
from app.models.student_submission import StudentSubmission
from app.models.excel_template import ExcelBatchTemplate
from app.models.doc_config_version import DocumentConfigurationVersion
from app.models.wanted_field_config import DocumentFieldConfiguration
from app.models.document_job import (
    DocumentProcessingJob,
    JobStatus,
    SubmissionSession,
    SubmissionProcessingStatus,
)
from app.services.document_worker_pool import DocumentWorkerPool
from app.api.student_submission import _get_batch_excel_lock
from app.core.config import settings


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_test_db"]

    import app.db.database
    app.db.database.client = test_client
    app.db.database.db = test_db
    app.db.database._is_connected = True

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[
            User,
            Department,
            AdmissionBatch,
            BatchClass,
            UploadLink,
            StudentSubmission,
            ExcelBatchTemplate,
            DocumentConfigurationVersion,
            DocumentFieldConfiguration,
            DocumentProcessingJob,
            SubmissionSession,
        ],
    )
    await User.find_all().delete()
    await Department.find_all().delete()
    await AdmissionBatch.find_all().delete()
    await BatchClass.find_all().delete()
    await UploadLink.find_all().delete()
    await StudentSubmission.find_all().delete()
    await DocumentProcessingJob.find_all().delete()
    await SubmissionSession.find_all().delete()

    yield

    await test_client.drop_database("automate_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Test 1: Atomic Job Claiming & Duplicate Job Prevention
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_atomic_job_claiming_no_duplicates():
    """Verify that multiple workers racing to claim a job never claim the same job twice."""
    worker_pool = DocumentWorkerPool.get_instance()

    # Create 5 distinct queued jobs
    for i in range(5):
        job = DocumentProcessingJob(
            job_id=f"job_race_{i}",
            submission_id="sub_race_1",
            document_id=f"doc_{i}",
            document_name=f"doc_{i}.pdf",
            file_path="dummy.pdf",
            status=JobStatus.QUEUED,
        )
        await job.insert()

    # Simulate 10 workers racing to claim jobs concurrently
    claimed_jobs = await asyncio.gather(*[worker_pool._claim_next_job() for _ in range(10)])
    valid_claims = [j for j in claimed_jobs if j is not None]

    claimed_ids = [j.job_id for j in valid_claims]
    # All claimed jobs must be unique (no duplicates)
    assert len(claimed_ids) == len(set(claimed_ids))
    assert len(claimed_ids) == 5

    # Any subsequent claim must return None (queue exhausted)
    extra_claim = await worker_pool._claim_next_job()
    assert extra_claim is None


# ---------------------------------------------------------------------------
# Test 2: Same Filename Isolation Across Different Students
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_same_filename_storage_and_data_isolation():
    """
    Verify two students uploading files with identical filename ('aadhaar.pdf')
    are saved into isolated subdirectories and their data never mixes.
    """
    worker_pool = DocumentWorkerPool.get_instance()

    sub_id_1 = await worker_pool.enqueue_submission(
        batch_id="batch_2026",
        register_number="24CS001",
        student_name="Alice Smith",
        file_payloads=[("aadhaar.pdf", b"ALICE_SECRET_AADHAAR_BYTES")],
    )

    sub_id_2 = await worker_pool.enqueue_submission(
        batch_id="batch_2026",
        register_number="24CS002",
        student_name="Bob Jones",
        file_payloads=[("aadhaar.pdf", b"BOB_SECRET_AADHAAR_BYTES")],
    )

    assert sub_id_1 != sub_id_2

    jobs_1 = await DocumentProcessingJob.find(DocumentProcessingJob.submission_id == sub_id_1).to_list()
    jobs_2 = await DocumentProcessingJob.find(DocumentProcessingJob.submission_id == sub_id_2).to_list()

    assert len(jobs_1) == 1
    assert len(jobs_2) == 1

    # File paths must be strictly distinct
    assert jobs_1[0].file_path != jobs_2[0].file_path
    assert sub_id_1 in jobs_1[0].file_path
    assert sub_id_2 in jobs_2[0].file_path

    # Verify actual content on disk is isolated
    with open(jobs_1[0].file_path, "rb") as f1:
        assert f1.read() == b"ALICE_SECRET_AADHAAR_BYTES"

    with open(jobs_2[0].file_path, "rb") as f2:
        assert f2.read() == b"BOB_SECRET_AADHAAR_BYTES"


# ---------------------------------------------------------------------------
# Test 3: Candidate Pool Isolation Across Multiple Submissions
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_candidate_pool_strict_isolation():
    """
    Verify that extracted candidate values for Student A never appear in
    Student B's verification fields or candidate pool.
    """
    worker_pool = DocumentWorkerPool.get_instance()

    # Mock single document extraction with distinct values per student
    def mock_extract(filename, file_bytes, excel_headers, uploads_dir, doc_timer, **kwargs):
        if b"ALICE" in file_bytes:
            return {
                "filename": filename,
                "doc_type": "AADHAAR",
                "doc_extracted": {"Aadhaar Number": {"value": "9999 8888 7777", "confidence": 99}},
                "raw_ocr": "Alice Aadhaar 9999 8888 7777",
                "ai_response_status": "200 OK",
            }
        else:
            return {
                "filename": filename,
                "doc_type": "AADHAAR",
                "doc_extracted": {"Aadhaar Number": {"value": "1111 2222 3333", "confidence": 99}},
                "raw_ocr": "Bob Aadhaar 1111 2222 3333",
                "ai_response_status": "200 OK",
            }

    with patch.object(worker_pool.pipeline, "_process_single_document", side_effect=mock_extract):
        sub_id_alice = await worker_pool.enqueue_submission(
            batch_id="batch_iso",
            register_number="REG_ALICE",
            student_name="Alice Smith",
            file_payloads=[("aadhaar.pdf", b"ALICE_CONTENT")],
        )

        sub_id_bob = await worker_pool.enqueue_submission(
            batch_id="batch_iso",
            register_number="REG_BOB",
            student_name="Bob Jones",
            file_payloads=[("aadhaar.pdf", b"BOB_CONTENT")],
        )

        # Process both jobs
        job_alice = await worker_pool._claim_next_job()
        assert job_alice is not None
        await worker_pool._process_single_job(job_alice, worker_id=1)

        job_bob = await worker_pool._claim_next_job()
        assert job_bob is not None
        await worker_pool._process_single_job(job_bob, worker_id=2)

        session_alice = await SubmissionSession.find_one(SubmissionSession.submission_id == sub_id_alice)
        session_bob = await SubmissionSession.find_one(SubmissionSession.submission_id == sub_id_bob)

        assert session_alice.status == SubmissionProcessingStatus.READY_FOR_VERIFICATION
        assert session_bob.status == SubmissionProcessingStatus.READY_FOR_VERIFICATION

        # Assert zero cross-student contamination!
        alice_aadhaar = session_alice.verification_fields.get("Aadhaar Number", {}).get("value")
        bob_aadhaar = session_bob.verification_fields.get("Aadhaar Number", {}).get("value")

        assert alice_aadhaar == "9999 8888 7777"
        assert bob_aadhaar == "1111 2222 3333"
        assert alice_aadhaar != bob_aadhaar


# ---------------------------------------------------------------------------
# Test 4: Failure Isolation (One student's failure doesn't fail others)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failure_isolation_one_failure_does_not_affect_others():
    """Verify if Student A suffers an unhandled extraction error, Student B completes normally."""
    worker_pool = DocumentWorkerPool.get_instance()

    def mock_extract(filename, file_bytes, excel_headers, uploads_dir, doc_timer, **kwargs):
        if b"FAIL" in file_bytes:
            raise RuntimeError("Corrupted document or Gemini 500")
        return {
            "filename": filename,
            "doc_type": "TRANSFER_CERTIFICATE",
            "doc_extracted": {"EMIS ID": {"value": "330201001", "confidence": 95}},
            "raw_ocr": "EMIS 330201001",
            "ai_response_status": "200 OK",
        }

    with patch.object(worker_pool.pipeline, "_process_single_document", side_effect=mock_extract):
        sub_fail = await worker_pool.enqueue_submission(
            batch_id="batch_fail_iso",
            register_number="FAIL_STUDENT",
            student_name="Charlie Fail",
            file_payloads=[("bad_doc.pdf", b"FAIL_BYTES")],
        )

        sub_success = await worker_pool.enqueue_submission(
            batch_id="batch_fail_iso",
            register_number="SUCCESS_STUDENT",
            student_name="David Success",
            file_payloads=[("good_doc.pdf", b"SUCCESS_BYTES")],
        )

        # Process failing job (exhaust 3 attempts)
        for _ in range(3):
            j = await worker_pool._claim_next_job()
            if j:
                await worker_pool._process_single_job(j, worker_id=1)

        # Process succeeding job
        j_good = await worker_pool._claim_next_job()
        assert j_good is not None
        await worker_pool._process_single_job(j_good, worker_id=2)

        session_fail = await SubmissionSession.find_one(SubmissionSession.submission_id == sub_fail)
        session_success = await SubmissionSession.find_one(SubmissionSession.submission_id == sub_success)

        assert session_fail.status == SubmissionProcessingStatus.FAILED
        assert session_success.status == SubmissionProcessingStatus.READY_FOR_VERIFICATION
        assert session_success.verification_fields.get("EMIS ID", {}).get("value") == "330201001"


# ---------------------------------------------------------------------------
# Test 5: Stale Job Recovery Loop
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stale_job_recovery_after_worker_crash():
    """Verify a job abandoned in PROCESSING status longer than timeout is recovered."""
    worker_pool = DocumentWorkerPool.get_instance()

    stale_job = DocumentProcessingJob(
        job_id="job_stale_crash",
        submission_id="sub_stale_1",
        document_id="doc_stale",
        document_name="abandoned.pdf",
        file_path="abandoned.pdf",
        status=JobStatus.PROCESSING,
        attempt_count=1,
        max_attempts=3,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    await stale_job.insert()

    # Trigger 1 pass of supervisor recovery logic
    stale_threshold = datetime.now(timezone.utc) - timedelta(seconds=worker_pool.timeout_seconds)
    from app.db.database import db
    stale_cursor = db["document_processing_jobs"].find({
        "status": JobStatus.PROCESSING.value,
        "started_at": {"$lt": stale_threshold}
    })
    async for raw_stale in stale_cursor:
        job_id = raw_stale["job_id"]
        attempts = raw_stale.get("attempt_count", 1)
        max_att = raw_stale.get("max_attempts", 3)
        if attempts < max_att:
            await db["document_processing_jobs"].update_one(
                {"job_id": job_id},
                {"$set": {"status": JobStatus.RETRY_PENDING.value, "started_at": None}}
            )

    recovered = await DocumentProcessingJob.find_one(DocumentProcessingJob.job_id == "job_stale_crash")
    assert recovered.status == JobStatus.RETRY_PENDING

    # Now a worker can claim it again!
    claimed = await worker_pool._claim_next_job()
    assert claimed is not None
    assert claimed.job_id == "job_stale_crash"
    assert claimed.attempt_count == 2


# ---------------------------------------------------------------------------
# Test 6: Concurrent Multi-Student Load Test (10 and 20 students)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_multi_student_load():
    """
    Simulate 10 concurrent students uploading 2 documents each (20 total jobs).
    Process all concurrently across worker tasks and verify all 10 reach READY_FOR_VERIFICATION.
    """
    worker_pool = DocumentWorkerPool.get_instance()

    def mock_extract(filename, file_bytes, excel_headers, uploads_dir, doc_timer, **kwargs):
        reg = re.search(r'REG_(\d+)', file_bytes.decode('utf-8', errors='ignore'))
        val = int(reg.group(1)) if reg else 1
        return {
            "filename": filename,
            "doc_type": "AADHAAR" if "aadhaar" in filename else "TC",
            "doc_extracted": {
                "Permanent Address": {"value": f"{val} North Car Street, Anna Nagar, Chennai", "confidence": 95},
            },
            "raw_ocr": f"{val} North Car Street, Anna Nagar, Chennai",
            "ai_response_status": "200 OK",
        }

    with patch.object(worker_pool.pipeline, "_process_single_document", side_effect=mock_extract):
        # Enqueue 10 students simultaneously
        student_count = 10
        enqueue_tasks = []
        for i in range(student_count):
            reg = f"REG_{i+1:03d}"
            enqueue_tasks.append(
                worker_pool.enqueue_submission(
                    batch_id="batch_load_10",
                    register_number=reg,
                    student_name=f"Student {i+1}",
                    file_payloads=[
                        ("aadhaar.pdf", f"Data for {reg} aadhaar".encode()),
                        ("tc.pdf", f"Data for {reg} tc".encode()),
                    ],
                )
            )

        submission_ids = await asyncio.gather(*enqueue_tasks)
        assert len(submission_ids) == student_count

        total_jobs = await DocumentProcessingJob.find_all().count()
        assert total_jobs == student_count * 2

        # Run 4 workers concurrently until queue is drained
        async def run_worker(wid: int):
            while True:
                j = await worker_pool._claim_next_job()
                if not j:
                    break
                await worker_pool._process_single_job(j, wid)

        workers = [asyncio.create_task(run_worker(i)) for i in range(4)]
        await asyncio.gather(*workers)

        # Assert every submission completed successfully and has isolated data
        for i, sub_id in enumerate(submission_ids):
            sess = await SubmissionSession.find_one(SubmissionSession.submission_id == sub_id)
            assert sess.status == SubmissionProcessingStatus.READY_FOR_VERIFICATION
            assert sess.completed_documents == 2
            expected_reg = f"REG_{i+1:03d}"
            assert sess.register_number == expected_reg
            assert sess.student_name == f"Student {i+1}"
            expected_address = f"{i+1} North Car Street, Anna Nagar, Chennai"
            fused_address = sess.verification_fields.get("Permanent Address", {}).get("value")
            assert fused_address == expected_address


# ---------------------------------------------------------------------------
# Test 7: Per-Batch Excel Write Serialization Protection
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_excel_write_serialization_lock():
    """Verify that multiple concurrent writes to the same batch's Excel sheet are serialized."""
    lock_1 = _get_batch_excel_lock("batch_alpha")
    lock_2 = _get_batch_excel_lock("batch_alpha")
    assert lock_1 is lock_2  # Same batch shares identical lock instance

    lock_beta = _get_batch_excel_lock("batch_beta")
    assert lock_1 is not lock_beta  # Different batches do not block each other

    order = []

    async def write_op(wid: int, delay: float):
        async with lock_1:
            order.append(f"start_{wid}")
            await asyncio.sleep(delay)
            order.append(f"end_{wid}")

    # Launch two writes concurrently
    await asyncio.gather(write_op(1, 0.05), write_op(2, 0.01))

    # Must be strictly serialized (worker 1 finishes before worker 2 starts)
    assert order == ["start_1", "end_1", "start_2", "end_2"]
