from beanie import PydanticObjectId
from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.schemas.student_submission import StudentSubmissionCreate
from app.repositories.student_submission_repository import StudentSubmissionRepository
from app.services.doc_config_version_service import DocConfigVersionService
from app.utils.normalization import compare_register_numbers


class StudentSubmissionNotFoundException(Exception):
    def __init__(self, message: str = "Student submission not found"):
        self.message = message
        super().__init__(self.message)


class StudentSubmissionService:
    """
    Service layer for managing StudentSubmission operations.
    Handles business validations and coordinates with StudentSubmissionRepository.
    """

    def __init__(self, repository: StudentSubmissionRepository | None = None):
        self.repository = repository or StudentSubmissionRepository()
        self.doc_config_service = DocConfigVersionService()

    async def create_submission(self, data: StudentSubmissionCreate) -> StudentSubmission:
        """Create a new student application submission, freezing the active document configuration version snapshot."""
        batch_id = data.batch_id.strip()

        # Fetch current active document configuration version for the batch
        active_version = await self.doc_config_service.get_or_create_current_version(batch_id)

        # Fetch batch to retrieve department_id
        from app.models.batch import AdmissionBatch
        batch_doc = await AdmissionBatch.get(batch_id)
        department_id = batch_doc.department_id if batch_doc else None

        # Freeze snapshot of document requirements
        snapshot = [
            {
                "id": d.id,
                "name": d.name,
                "required": d.required,
                "allowed_types": d.allowed_types,
                "max_size_mb": d.max_size_mb,
                "description": d.description,
                "type": d.type,
            }
            for d in active_version.documents
        ]

        doc_metas = [
            StudentDocumentMeta(
                document_name=d.document_name,
                status=d.status,
                file_path=d.file_path,
                file_size_mb=d.file_size_mb,
                file_type=d.file_type,
                uploaded_at=d.uploaded_at,
            )
            for d in data.documents
        ]

        class_id = data.class_id.strip() if data.class_id else None
        class_name = data.class_name.strip() if data.class_name else None

        if class_id and not class_name:
            from app.models.batch_class import BatchClass
            class_doc = await BatchClass.get(class_id)
            if class_doc:
                class_name = class_doc.class_name

        submission = StudentSubmission(
            batch_id=batch_id,
            batch_name=data.batch_name.strip() if data.batch_name else None,
            class_id=class_id,
            class_name=class_name,
            department_id=department_id,
            upload_link_id=data.upload_link_id.strip() if data.upload_link_id else None,
            student_name=data.student_name.strip(),
            register_number=data.register_number.strip(),
            mobile_number=data.mobile_number.strip(),
            email=data.email.strip() if data.email else None,
            submission_status=data.submission_status,
            document_version=active_version.version,
            document_version_id=str(active_version.id),
            document_requirements_snapshot=snapshot,
            documents=doc_metas,
            extracted_data=data.extracted_data,
        )

        return await self.repository.create_submission(submission)


    async def get_all_submissions(self, department_id: str | None = None) -> list[StudentSubmission]:
        """Retrieve all student submissions, optionally filtered by department."""
        if department_id:
            return await self.repository.get_submissions_by_department(department_id)
        return await self.repository.get_all_submissions()

    async def get_submission_by_id(self, submission_id: str) -> StudentSubmission:
        """Retrieve a submission by ID."""
        try:
            pyd_id = PydanticObjectId(submission_id)
        except Exception:
            raise StudentSubmissionNotFoundException(f"Invalid submission ID format: {submission_id}")

        submission = await self.repository.get_submission_by_id(pyd_id)
        if not submission:
            raise StudentSubmissionNotFoundException(f"Submission with ID {submission_id} not found.")
        return submission

    async def get_submissions_by_batch_id(self, batch_id: str) -> list[StudentSubmission]:
        """Retrieve all submissions for a given admission batch ID."""
        return await self.repository.get_submissions_by_batch_id(batch_id.strip())

    async def update_status(self, submission_id: str, status: str) -> StudentSubmission:
        """Update submission status."""
        try:
            pyd_id = PydanticObjectId(submission_id)
        except Exception:
            raise StudentSubmissionNotFoundException(f"Invalid submission ID format: {submission_id}")

        updated = await self.repository.update_status(pyd_id, status)
        if not updated:
            raise StudentSubmissionNotFoundException(f"Submission with ID {submission_id} not found.")
        return updated

    async def check_duplicate_submission(self, batch_id: str, register_number: str) -> bool:
        """
        Return True if a submission already exists for the given batch and register number.
        Used by the public identity verification endpoint to block re-submissions.
        """
        submissions = await self.repository.get_submissions_by_batch_id(batch_id.strip())
        for s in submissions:
            if compare_register_numbers(s.register_number, register_number):
                return True
        return False

    async def save_extracted_data(self, submission_id: str, extracted_data: dict) -> StudentSubmission:
        """Save AI extracted data into StudentSubmission.extracted_data."""
        try:
            pyd_id = PydanticObjectId(submission_id)
        except Exception:
            raise StudentSubmissionNotFoundException(f"Invalid submission ID format: {submission_id}")

        updated = await self.repository.update_extracted_data(pyd_id, extracted_data)
        if not updated:
            raise StudentSubmissionNotFoundException(f"Submission with ID {submission_id} not found.")
        return updated

    async def _is_file_referenced_by_others(
        self,
        target_path: "Path",
        current_sub_id: PydanticObjectId,
        student_session_ids: list[str],
    ) -> bool:
        """
        Reference count check: checks if any active student submission, job, or template
        outside of the current student's scope references the target physical file.
        """
        from pathlib import Path
        from app.utils.storage_resolver import resolve_document_file_path
        from app.models.document_job import DocumentProcessingJob
        from app.models.excel_template import ExcelBatchTemplate

        target_resolved = target_path.resolve()

        # 1. Check other student submissions
        other_subs = await StudentSubmission.find(StudentSubmission.id != current_sub_id).to_list()
        for s in other_subs:
            for doc in s.documents:
                if doc.file_path:
                    p = resolve_document_file_path(doc.file_path, s.batch_id, s.register_number, doc.document_name)
                    if p and p.resolve() == target_resolved:
                        return True

        # 2. Check jobs from other sessions
        other_jobs = await DocumentProcessingJob.find({"submission_id": {"$nin": student_session_ids}}).to_list()
        for j in other_jobs:
            if j.file_path:
                p = resolve_document_file_path(j.file_path)
                if p and p.resolve() == target_resolved:
                    return True

        # 3. Check Excel batch templates
        templates = await ExcelBatchTemplate.find_all().to_list()
        for t in templates:
            if t.file_path:
                p = resolve_document_file_path(t.file_path)
                if p and p.resolve() == target_resolved:
                    return True

        return False

    async def delete_student_submission(
        self,
        submission_id: str,
        current_user: "User",
        batch_id: str | None = None,
        class_id: str | None = None,
    ) -> dict:
        """
        Safely and permanently deletes a student submission, ensuring:
          1. Authenticated staff RBAC authorization & department/section/batch isolation.
          2. Active processing protection (blocks deletion if extraction/jobs are active).
          3. Reference-counted file storage cleanup (shared files are preserved, unreferenced files deleted).
          4. Cascade cleanup of linked DocumentProcessingJob and SubmissionSession records.
          5. Deletion of the StudentSubmission record itself.
          6. Immutable audit logging without exposing sensitive document content.
        """
        import os
        from pathlib import Path
        from fastapi import HTTPException, status
        from app.models.user import UserRole
        from app.models.document_job import (
            SubmissionSession,
            DocumentProcessingJob,
            SubmissionProcessingStatus,
            JobStatus,
        )
        from app.models.audit_log import AuditLog
        from app.utils.storage_resolver import resolve_document_file_path

        # 1. Fetch submission
        try:
            pyd_id = PydanticObjectId(submission_id)
        except Exception:
            raise StudentSubmissionNotFoundException(f"Invalid submission ID format: {submission_id}")

        submission = await self.repository.get_submission_by_id(pyd_id)
        if not submission:
            raise StudentSubmissionNotFoundException(f"Submission with ID {submission_id} not found.")

        # 2. Cross-Batch and Cross-Section Isolation Checks
        if batch_id and str(submission.batch_id) != str(batch_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cross-batch deletion rejected: Student does not belong to batch '{batch_id}'.",
            )

        if class_id:
            sub_class_id = str(getattr(submission, "class_id", "") or "")
            if sub_class_id != str(class_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cross-section deletion rejected: Student does not belong to section '{class_id}'.",
                )

        # 3. RBAC Department Isolation
        if current_user.role == UserRole.DEPARTMENT_ADMIN:
            dept_id = submission.department_id
            if not dept_id and submission.batch_id:
                try:
                    from app.models.batch import AdmissionBatch
                    b = await AdmissionBatch.get(submission.batch_id)
                    if b:
                        dept_id = b.department_id
                except Exception:
                    pass
            if dept_id and dept_id != current_user.department_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to delete another department's student.",
                )

        # 3. Active Processing Protection
        if submission.submission_status in ["AI Processing", "Processing"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Student processing is currently active. Please wait until processing finishes before deleting.",
            )

        # Check SubmissionSessions for active processing
        active_sessions = await SubmissionSession.find(
            SubmissionSession.batch_id == submission.batch_id,
            SubmissionSession.register_number == submission.register_number,
            {"status": {"$in": [
                SubmissionProcessingStatus.QUEUED.value,
                SubmissionProcessingStatus.PROCESSING.value,
                SubmissionProcessingStatus.UPLOADING.value,
            ]}}
        ).to_list()
        if active_sessions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Student processing is currently active. Please wait until processing finishes before deleting.",
            )

        # Find all student sessions to check active jobs
        all_student_sessions = await SubmissionSession.find(
            SubmissionSession.batch_id == submission.batch_id,
            SubmissionSession.register_number == submission.register_number,
        ).to_list()
        session_ids = [s.submission_id for s in all_student_sessions]

        if session_ids:
            active_jobs = await DocumentProcessingJob.find(
                {"submission_id": {"$in": session_ids}, "status": {"$in": [
                    JobStatus.QUEUED.value,
                    JobStatus.PROCESSING.value,
                    JobStatus.RETRY_PENDING.value,
                ]}}
            ).to_list()
            if active_jobs:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Student processing is currently active. Please wait until processing finishes before deleting.",
                )

        # 4. Reference-Counted File Storage Cleanup
        candidate_paths: set[Path] = set()
        for doc in submission.documents:
            if doc.file_path:
                p = resolve_document_file_path(doc.file_path, submission.batch_id, submission.register_number, doc.document_name)
                if p and p.is_file():
                    candidate_paths.add(p.resolve())

        # Also collect session job files
        if session_ids:
            student_jobs = await DocumentProcessingJob.find({"submission_id": {"$in": session_ids}}).to_list()
            for j in student_jobs:
                if j.file_path:
                    p = resolve_document_file_path(j.file_path)
                    if p and p.is_file():
                        candidate_paths.add(p.resolve())

        # Collect hashes for targeted cache invalidation
        import hashlib
        file_hashes: list[str] = []
        for fpath in candidate_paths:
            try:
                with open(fpath, "rb") as fh:
                    file_hashes.append(hashlib.sha256(fh.read()).hexdigest())
            except Exception:
                pass

        files_deleted_count = 0
        files_preserved_count = 0
        failure_messages: list[str] = []

        for fpath in candidate_paths:
            is_shared = await self._is_file_referenced_by_others(fpath, pyd_id, session_ids)
            if is_shared:
                files_preserved_count += 1
            else:
                try:
                    os.remove(fpath)
                    files_deleted_count += 1
                    # If file was in a session folder, clean up session directory if now empty
                    parent_dir = fpath.parent
                    if "sessions" in parent_dir.parts and parent_dir.is_dir():
                        if not any(parent_dir.iterdir()):
                            try:
                                parent_dir.rmdir()
                            except Exception:
                                pass
                except Exception as del_err:
                    failure_messages.append(f"Failed to delete {fpath.name}: {del_err}")

        # Targeted cache cleanup without flushing global caches
        if file_hashes:
            try:
                from app.services.gemini_service import GeminiService
                gemini_svc = GeminiService()
                gemini_svc.invalidate_cache_for_hashes(file_hashes)
            except Exception:
                pass

        # 5. Cascade Database Cleanup
        if session_ids:
            await DocumentProcessingJob.find({"submission_id": {"$in": session_ids}}).delete()
        
        # Always clean up any SubmissionSessions matching this student's exact batch and register_number
        await SubmissionSession.find(
            SubmissionSession.batch_id == submission.batch_id,
            SubmissionSession.register_number == submission.register_number,
        ).delete()

        # Delete the student submission record
        await self.repository.delete_submission(pyd_id)

        # 6. Immutable Audit Logging
        failure_info_str = "; ".join(failure_messages) if failure_messages else None
        audit = AuditLog(
            action="DELETE_STUDENT",
            actor_user_id=str(current_user.id),
            actor_username=current_user.username,
            actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            submission_id=str(submission.id),
            student_name=submission.student_name,
            register_number=submission.register_number,
            batch_id=submission.batch_id,
            class_id=submission.class_id,
            documents_count=len(submission.documents),
            files_deleted_count=files_deleted_count,
            files_preserved_count=files_preserved_count,
            result="PARTIAL_FAILURE" if failure_info_str else "SUCCESS",
            failure_info=failure_info_str,
        )
        await audit.insert()

        if failure_info_str:
            return {
                "success": False,
                "message": "Student deletion requires cleanup retry. Please contact an administrator.",
                "submission_id": str(submission.id),
                "student_name": submission.student_name,
                "register_number": submission.register_number,
                "files_deleted": files_deleted_count,
                "files_preserved": files_preserved_count,
                "failure_info": failure_info_str,
            }

        return {
            "success": True,
            "message": "Student deleted successfully.",
            "submission_id": str(submission.id),
            "student_name": submission.student_name,
            "register_number": submission.register_number,
            "files_deleted": files_deleted_count,
            "files_preserved": files_preserved_count,
            "failure_info": None,
        }

