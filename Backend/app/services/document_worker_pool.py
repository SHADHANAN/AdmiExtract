import asyncio
import io
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pymongo import ReturnDocument
from fastapi import UploadFile

from app.core.config import settings
from app.models.document_job import (
    DocumentProcessingJob,
    JobStatus,
    SubmissionSession,
    SubmissionProcessingStatus,
)
from app.services.document_processing_pipeline import DocumentProcessingPipeline, PipelineProfiler
from app.services.excel_template_service import ExcelTemplateService
from app.services.wanted_field_service import WantedFieldService
from app.services.doc_config_version_service import DocConfigVersionService

logger = logging.getLogger("app.services.document_worker_pool")


def _job_coll():
    """Dynamically return the active Motor collection for DocumentProcessingJob."""
    return DocumentProcessingJob.get_pymongo_collection()


def _session_coll():
    """Dynamically return the active Motor collection for SubmissionSession."""
    return SubmissionSession.get_pymongo_collection()


def _safe_log(msg: str) -> None:
    """Dev-mode stdout logger with Unicode fallback."""
    if getattr(settings, "APP_ENV", "development") == "development":
        try:
            print(msg, flush=True)
        except Exception:
            try:
                ascii_msg = msg.encode('ascii', 'replace').decode('ascii')
                print(ascii_msg, flush=True)
            except Exception:
                pass


class DocumentWorkerPool:
    """
    Controlled persistent asynchronous worker pool orchestrating document extraction
    on top of the existing extraction pipeline without modifying core extraction logic.
    """

    _instance: Optional["DocumentWorkerPool"] = None

    def __init__(self):
        self.pipeline = DocumentProcessingPipeline()
        self.excel_service = ExcelTemplateService()
        self.wanted_field_service = WantedFieldService()
        self.doc_config_service = DocConfigVersionService()
        
        self.concurrency = int(getattr(settings, "EXTRACTION_WORKER_CONCURRENCY", 4))
        self.timeout_seconds = int(getattr(settings, "JOB_TIMEOUT_SECONDS", 300))
        
        self.worker_tasks: List[asyncio.Task] = []
        self.supervisor_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def gemini_semaphore(self) -> asyncio.Semaphore:
        """Ensure semaphore is bound to the currently running event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if not hasattr(self, "_sem_loop") or self._sem_loop is not loop or not hasattr(self, "_gemini_sem"):
            limit = int(getattr(settings, "GEMINI_CONCURRENCY_LIMIT", 3))
            self._gemini_sem = asyncio.Semaphore(limit)
            self._sem_loop = loop
        return self._gemini_sem

    @classmethod
    def get_instance(cls) -> "DocumentWorkerPool":
        if cls._instance is None:
            cls._instance = DocumentWorkerPool()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing and complete reloads)."""
        cls._instance = None

    @property
    def is_running(self) -> bool:
        """Check if worker pool is currently running active tasks."""
        return self._running and any(not t.done() for t in self.worker_tasks)

    async def start(self) -> bool:
        """
        Start the background worker pool and supervisor loop safely and idempotently.
        Ensures Beanie is fully initialized and MongoDB is connected before launching workers.
        Returns True if started or already running; False if database/Beanie is not initialized.
        """
        from app.db.database import is_beanie_initialized

        if not is_beanie_initialized():
            logger.warning("[WorkerPool] Refusing to start workers: Database/Beanie is not connected or initialized.")
            return False

        # Clean up any dead tasks from an earlier run
        self.worker_tasks = [t for t in self.worker_tasks if not t.done()]
        if self._running and self.worker_tasks:
            logger.info("[WorkerPool] Worker pool is already actively running. Skipping duplicate startup.")
            return True

        self._running = True
        logger.info(f"[WorkerPool] Starting {self.concurrency} extraction workers...")
        _safe_log(f"\n=======================================================\n[WorkerPool] Starting {self.concurrency} persistent document workers...\n=======================================================\n")

        # Launch worker tasks
        self.worker_tasks = [
            asyncio.create_task(self._worker_loop(worker_id=i + 1), name=f"doc_worker_{i+1}")
            for i in range(self.concurrency)
        ]
        # Launch stale job recovery supervisor
        if not self.supervisor_task or self.supervisor_task.done():
            self.supervisor_task = asyncio.create_task(self._supervisor_loop(), name="job_supervisor")

        return True

    async def stop(self) -> None:
        """Gracefully and idempotently stop all workers and supervisor."""
        if not self._running and not self.worker_tasks and not self.supervisor_task:
            return

        logger.info("[WorkerPool] Stopping document worker pool...")
        self._running = False

        if self.supervisor_task:
            self.supervisor_task.cancel()
            try:
                await self.supervisor_task
            except (asyncio.CancelledError, Exception):
                pass
            self.supervisor_task = None

        for t in self.worker_tasks:
            t.cancel()

        if self.worker_tasks:
            await asyncio.gather(*self.worker_tasks, return_exceptions=True)
            self.worker_tasks.clear()

        logger.info("[WorkerPool] Document worker pool stopped.")

    async def enqueue_submission(
        self,
        batch_id: str,
        register_number: str,
        student_name: str,
        mobile_number: Optional[str] = None,
        email: Optional[str] = None,
        files: Optional[List[UploadFile]] = None,
        file_payloads: Optional[List[Tuple[str, bytes]]] = None,
        force_refresh: bool = False,
    ) -> str:
        """
        Create a unique submission session and enqueue individual document jobs into MongoDB.
        Files are stored with strict submission/job isolation so students uploading files with
        identical names never overwrite each other.
        """
        submission_id = f"sub_{uuid.uuid4().hex[:12]}"
        files = files or []
        file_payloads = file_payloads or []

        # Scoped directory for this specific submission
        base_uploads_dir = Path(__file__).resolve().parent.parent.parent / "uploads" / "sessions" / submission_id
        base_uploads_dir.mkdir(parents=True, exist_ok=True)

        # Read file bytes upfront if UploadFile list is provided
        processed_files: List[Tuple[str, bytes]] = list(file_payloads)
        for uf in files:
            fname = uf.filename or "uploaded_document.pdf"
            fbytes = await uf.read()
            processed_files.append((fname, fbytes))

        # Retrieve Excel Headers for the batch
        try:
            excel_template = await self.excel_service.get_template_by_batch(batch_id)
            excel_headers = excel_template.headers if (excel_template and excel_template.headers) else []
        except Exception:
            excel_headers = []

        if not excel_headers:
            try:
                excel_headers = await self.doc_config_service.get_batch_extraction_fields(batch_id)
            except Exception:
                excel_headers = []

        if not excel_headers:
            excel_headers = [
                "Student Name", "Register Number", "EMIS ID", "Is EMIS ID Available",
                "Date of Birth", "Gender", "Nationality", "Community", "Caste",
                "Aadhaar Number", "State", "District", "Taluk", "Village", "Village Panchayat",
                "Permanent Address", "Father's Name", "Father's Occupation",
                "Mother's Name", "Mother's Occupation", "Application Number"
            ]

        # 1. Create parent SubmissionSession
        session = SubmissionSession(
            submission_id=submission_id,
            batch_id=batch_id.strip(),
            register_number=register_number.strip(),
            student_name=student_name.strip(),
            mobile_number=mobile_number.strip() if mobile_number else None,
            email=email.strip() if email else None,
            status=SubmissionProcessingStatus.QUEUED,
            total_documents=len(processed_files),
            completed_documents=0,
            failed_documents=0,
            created_at=datetime.now(timezone.utc),
            excel_headers=excel_headers,
        )
        await session.insert()

        # 2. Persist each document isolated to disk & create MongoDB DocumentProcessingJob
        for idx, (orig_filename, content_bytes) in enumerate(processed_files, start=1):
            job_id = f"job_{uuid.uuid4().hex[:12]}"
            clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', orig_filename)
            saved_filename = f"{job_id}_{clean_name}"
            saved_path = base_uploads_dir / saved_filename

            with open(saved_path, "wb") as f:
                f.write(content_bytes)

            mime_type = "application/pdf" if clean_name.lower().endswith(".pdf") else "image/jpeg"

            job = DocumentProcessingJob(
                job_id=job_id,
                submission_id=submission_id,
                document_id=f"doc_{idx}",
                document_name=orig_filename,
                document_type="UNKNOWN",
                file_path=str(saved_path),
                file_size_bytes=len(content_bytes),
                mime_type=mime_type,
                status=JobStatus.QUEUED,
                attempt_count=0,
                max_attempts=3,
                created_at=datetime.now(timezone.utc),
            )
            await job.insert()

        _safe_log(f"[WorkerPool] Enqueued submission '{submission_id}' with {len(processed_files)} document jobs.")
        return submission_id

    async def _claim_next_job(self) -> Optional[DocumentProcessingJob]:
        """
        Atomically claim the next QUEUED or RETRY_PENDING job from MongoDB.
        Guarantees that two workers can never claim the same job.
        """
        raw_job = await _job_coll().find_one_and_update(
            {"status": {"$in": [JobStatus.QUEUED.value, JobStatus.RETRY_PENDING.value]}},
            {
                "$set": {
                    "status": JobStatus.PROCESSING.value,
                    "started_at": datetime.now(timezone.utc),
                },
                "$inc": {"attempt_count": 1}
            },
            sort=[("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if not raw_job:
            return None

        return DocumentProcessingJob(**raw_job)

    async def _worker_loop(self, worker_id: int) -> None:
        """Continuous worker execution loop."""
        from app.db.database import is_beanie_initialized

        logger.info(f"[Worker {worker_id}] Worker online.")
        while self._running:
            try:
                if not is_beanie_initialized():
                    logger.warning(f"[Worker {worker_id}] Database/Beanie is not initialized. Exiting worker loop.")
                    break

                job = await self._claim_next_job()
                if not job:
                    await asyncio.sleep(0.5)
                    continue

                _safe_log(f"[Worker {worker_id}] Claimed job '{job.job_id}' (document: '{job.document_name}') for submission '{job.submission_id}'.")
                await self._process_single_job(job, worker_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Worker {worker_id}] Unexpected loop exception: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    async def _process_single_job(self, job: DocumentProcessingJob, worker_id: int) -> None:
        """
        Execute document extraction on the claimed job using the existing extraction pipeline,
        preserving all extraction accuracy, authority rules, and candidate isolation.
        """
        profiler = PipelineProfiler()
        doc_timer = profiler.start_document(job.document_name)

        submission = await SubmissionSession.find_one(SubmissionSession.submission_id == job.submission_id)
        if not submission:
            logger.error(f"[Worker {worker_id}] Parent submission '{job.submission_id}' not found for job '{job.job_id}'.")
            await _job_coll().update_one(
                {"job_id": job.job_id},
                {"$set": {"status": JobStatus.FAILED.value, "error_info": "Parent submission missing."}}
            )
            return

        # Update parent submission status to PROCESSING if still QUEUED
        if submission.status == SubmissionProcessingStatus.QUEUED:
            await _session_coll().update_one(
                {"submission_id": job.submission_id},
                {"$set": {"status": SubmissionProcessingStatus.PROCESSING.value, "started_at": datetime.now(timezone.utc)}}
            )

        # Retrieve Batch-Scoped Wanted Field Configurations
        batch_wanted_configs: Dict[str, List[str]] = {}
        try:
            batch_wanted_configs = await self.wanted_field_service.get_all_active_wanted_fields_by_batch(submission.batch_id)
        except Exception as wf_err:
            logger.warning(f"[WorkerPool] Could not load wanted field configs for batch {submission.batch_id}: {wf_err}")

        # Read file bytes from isolated storage
        try:
            with open(job.file_path, "rb") as f:
                fbytes = f.read()
        except Exception as read_err:
            logger.error(f"[Worker {worker_id}] Failed reading file '{job.file_path}': {read_err}")
            await _job_coll().update_one(
                {"job_id": job.job_id},
                {"$set": {"status": JobStatus.FAILED.value, "error_info": str(read_err)}}
            )
            await self._check_submission_completion(job.submission_id)
            return

        # Execute existing single document pipeline using bounded concurrency
        uploads_dir = Path(__file__).resolve().parent.parent.parent / "uploads"
        try:
            async with self.gemini_semaphore:
                # Calls the EXISTING document processing pipeline unchanged
                res = await asyncio.to_thread(
                    self.pipeline._process_single_document,
                    job.document_name,
                    fbytes,
                    submission.excel_headers,
                    uploads_dir,
                    doc_timer,
                    batch_wanted_configs=batch_wanted_configs,
                    bypass_cache=False,
                )

            extracted_fields = res.get("doc_extracted", {})
            doc_type = res.get("doc_type", "UNKNOWN")
            raw_ocr = res.get("raw_ocr", "")
            ai_status = res.get("ai_response_status", "200 OK")

            # Persist isolated extraction results to the job document
            await _job_coll().update_one(
                {"job_id": job.job_id},
                {
                    "$set": {
                        "status": JobStatus.COMPLETED.value,
                        "document_type": doc_type,
                        "doc_extracted": extracted_fields,
                        "raw_ocr": raw_ocr,
                        "ai_response_status": ai_status,
                        "completed_at": datetime.now(timezone.utc),
                        "timing_metrics": doc_timer.timings,
                    }
                }
            )
            _safe_log(f"[Worker {worker_id}] Job '{job.job_id}' COMPLETED successfully (doc_type: {doc_type}, {len(extracted_fields)} fields).")

        except Exception as proc_err:
            logger.error(f"[Worker {worker_id}] Processing failed for job '{job.job_id}': {proc_err}", exc_info=True)
            new_status = JobStatus.RETRY_PENDING.value if job.attempt_count < job.max_attempts else JobStatus.FAILED.value
            await _job_coll().update_one(
                {"job_id": job.job_id},
                {
                    "$set": {
                        "status": new_status,
                        "error_info": str(proc_err),
                        "completed_at": datetime.now(timezone.utc),
                    }
                }
            )

        # Check if all sibling jobs for this submission have finished
        await self._check_submission_completion(job.submission_id)

    async def _check_submission_completion(self, submission_id: str) -> None:
        """
        Check if all document jobs for the given submission_id are in terminal state.
        If finished, triggers order-independent cross-document merge and updates SubmissionSession.
        """
        jobs_cursor = _job_coll().find({"submission_id": submission_id})
        all_jobs = await jobs_cursor.to_list(length=100)
        if not all_jobs:
            return

        total_count = len(all_jobs)
        completed_jobs = [j for j in all_jobs if j.get("status") == JobStatus.COMPLETED.value]
        failed_jobs = [j for j in all_jobs if j.get("status") == JobStatus.FAILED.value]
        pending_jobs = [j for j in all_jobs if j.get("status") in (JobStatus.QUEUED.value, JobStatus.PROCESSING.value, JobStatus.RETRY_PENDING.value)]

        # If any job is still pending, submission is still processing
        if pending_jobs:
            return

        session = await SubmissionSession.find_one(SubmissionSession.submission_id == submission_id)
        if not session or session.status in (SubmissionProcessingStatus.READY_FOR_VERIFICATION, SubmissionProcessingStatus.PARTIAL_SUCCESS, SubmissionProcessingStatus.FAILED):
            return

        # Assemble candidate pool isolated strictly to this submission
        detected_documents: List[str] = []
        extracted_fields_per_document: Dict[str, Dict[str, Any]] = {}
        document_types_per_file: Dict[str, str] = {}

        for j in completed_jobs:
            fname = j.get("document_name", "unknown")
            dtype = j.get("document_type", "UNKNOWN")
            doc_ext = j.get("doc_extracted", {})

            if dtype and dtype != "UNKNOWN" and dtype not in detected_documents:
                detected_documents.append(dtype)

            extracted_fields_per_document[fname] = doc_ext
            document_types_per_file[fname] = dtype

        login_profile = {
            "student_name": session.student_name,
            "register_number": session.register_number,
            "mobile_number": session.mobile_number or "",
            "email": session.email or "",
        }

        # Run UNCHANGED order-independent cross-document fusion
        profiler = PipelineProfiler()
        with profiler.track_pipeline("merge"):
            verification_fields = self.pipeline._order_independent_cross_document_merge(
                detected_docs=detected_documents,
                all_extracted_pool=extracted_fields_per_document,
                excel_headers=session.excel_headers,
                student_profile=login_profile,
                document_types_per_file=document_types_per_file,
            )

        if completed_jobs and not failed_jobs:
            final_status = SubmissionProcessingStatus.READY_FOR_VERIFICATION
        elif completed_jobs and failed_jobs:
            final_status = SubmissionProcessingStatus.PARTIAL_SUCCESS
        else:
            final_status = SubmissionProcessingStatus.FAILED

        await _session_coll().update_one(
            {"submission_id": submission_id},
            {
                "$set": {
                    "status": final_status.value,
                    "completed_documents": len(completed_jobs),
                    "failed_documents": len(failed_jobs),
                    "completed_at": datetime.now(timezone.utc),
                    "verification_fields": verification_fields,
                    "detected_documents": detected_documents,
                }
            }
        )
        _safe_log(f"[WorkerPool] Submission '{submission_id}' resolved with status: {final_status.value} (Completed: {len(completed_jobs)}/{total_count}).")

    async def _supervisor_loop(self) -> None:
        """Periodic supervisor for stale job recovery and orphaned job resumption."""
        while self._running:
            try:
                await asyncio.sleep(15.0)
                stale_threshold = datetime.now(timezone.utc) - timedelta(seconds=self.timeout_seconds)

                # Reset stale jobs exceeding timeout back to RETRY_PENDING
                stale_cursor = _job_coll().find({
                    "status": JobStatus.PROCESSING.value,
                    "started_at": {"$lt": stale_threshold}
                })
                async for raw_stale in stale_cursor:
                    job_id = raw_stale["job_id"]
                    attempts = raw_stale.get("attempt_count", 1)
                    max_att = raw_stale.get("max_attempts", 3)

                    if attempts < max_att:
                        logger.warning(f"[Supervisor] Stale job '{job_id}' timed out. Resetting to RETRY_PENDING (attempt {attempts}/{max_att}).")
                        await _job_coll().update_one(
                            {"job_id": job_id},
                            {"$set": {"status": JobStatus.RETRY_PENDING.value, "started_at": None}}
                        )
                    else:
                        logger.warning(f"[Supervisor] Stale job '{job_id}' exceeded max attempts. Marking FAILED.")
                        await _job_coll().update_one(
                            {"job_id": job_id},
                            {"$set": {"status": JobStatus.FAILED.value, "error_info": "Job processing timeout exceeded."}}
                        )
                        await self._check_submission_completion(raw_stale["submission_id"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Supervisor] Error in supervisor loop: {e}", exc_info=True)
