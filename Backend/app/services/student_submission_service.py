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

