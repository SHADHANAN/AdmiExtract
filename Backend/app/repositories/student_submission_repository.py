from beanie import PydanticObjectId
from app.models.student_submission import StudentSubmission


class StudentSubmissionRepository:
    """
    Repository handling database CRUD operations for StudentSubmission documents using Beanie.
    """

    async def create_submission(self, submission: StudentSubmission) -> StudentSubmission:
        """Insert a new student submission record into MongoDB."""
        return await submission.insert()

    async def get_all_submissions(self) -> list[StudentSubmission]:
        """Retrieve all student submissions sorted by newest first."""
        return await StudentSubmission.find_all().sort("-submitted_at").to_list()

    async def get_submissions_by_department(self, department_id: str) -> list[StudentSubmission]:
        """Retrieve all student submissions belonging to a specific department."""
        return await StudentSubmission.find(StudentSubmission.department_id == department_id).sort("-submitted_at").to_list()

    async def get_submission_by_id(self, submission_id: PydanticObjectId) -> StudentSubmission | None:
        """Find a student submission by ID."""
        return await StudentSubmission.get(submission_id)

    async def get_submissions_by_batch_id(self, batch_id: str) -> list[StudentSubmission]:
        """Retrieve all submissions belonging to a specific admission batch ID."""
        return await StudentSubmission.find(StudentSubmission.batch_id == batch_id).sort("-submitted_at").to_list()

    async def update_status(self, submission_id: PydanticObjectId, submission_status: str) -> StudentSubmission | None:
        """Update submission status for a student application."""
        submission = await StudentSubmission.get(submission_id)
        if not submission:
            return None

        submission.submission_status = submission_status
        if submission_status == "AI Processing":
            submission.ai_status = "Processing"
        elif submission_status in ("Verification Pending", "Verified"):
            submission.ai_status = "Complete"

        await submission.save()
        return submission

    async def update_extracted_data(self, submission_id: PydanticObjectId, extracted_data: dict) -> StudentSubmission | None:
        """Save AI extracted data into StudentSubmission document."""
        submission = await StudentSubmission.get(submission_id)
        if not submission:
            return None

        submission.extracted_data = extracted_data
        await submission.save()
        return submission
