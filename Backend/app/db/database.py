from typing import Any, cast
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.core.config import settings

# Monkeypatch AsyncIOMotorClient to bypass Beanie/Motor compatibility issue
if not hasattr(AsyncIOMotorClient, "append_metadata"):
    AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

client = AsyncIOMotorClient(settings.MONGODB_URI)

db = client[settings.DATABASE_NAME]


async def init_db():
    from app.models.user import User, UserRole
    from app.models.department import Department
    from app.models.upload_link import UploadLink
    from app.models.student_submission import StudentSubmission
    from app.models.excel_template import ExcelBatchTemplate
    from app.models.doc_config_version import DocumentConfigurationVersion
    from app.models.batch import AdmissionBatch
    from app.core.security import get_password_hash

    # Clean up legacy user documents with missing or null username to allow unique index creation
    await db["users"].delete_many({"$or": [{"username": {"$exists": False}}, {"username": None}]})

    # Clean up legacy department documents with missing or null code
    await db["departments"].delete_many({"$or": [{"code": {"$exists": False}}, {"code": None}]})

    # Migrate legacy upload links with missing or null slug to set slug = token before index creation
    links_cursor = db["upload_links"].find({"$or": [{"slug": {"$exists": False}}, {"slug": None}]})
    async for doc in links_cursor:
        token = doc.get("token")
        if token:
            await db["upload_links"].update_one(
                {"_id": doc["_id"]},
                {"$set": {"slug": token}}
            )

    await init_beanie(
        database=cast(Any, db),
        document_models=[
            User,
            Department,
            UploadLink,
            StudentSubmission,
            ExcelBatchTemplate,
            DocumentConfigurationVersion,
            AdmissionBatch,
        ],
    )


    # Seed default AIML Department
    aiml_dept = await Department.find_one(Department.code == "AIML")
    if not aiml_dept:
        await Department(
            name="Artificial Intelligence & Machine Learning",
            code="AIML",
            description="Artificial Intelligence & Machine Learning Department",
            created_by="system",
            is_active=True,
        ).insert()

    # Seed default CSE Department
    cse_dept = await Department.find_one(Department.code == "CSE")
    if not cse_dept:
        await Department(
            name="Computer Science & Engineering",
            code="CSE",
            description="Computer Science & Engineering Department",
            created_by="system",
            is_active=True,
        ).insert()

    # Seed default ECE Department
    ece_dept = await Department.find_one(Department.code == "ECE")
    if not ece_dept:
        await Department(
            name="Electronics & Communication Engineering",
            code="ECE",
            description="Electronics & Communication Engineering Department",
            created_by="system",
            is_active=True,
        ).insert()

    # Seed default Admission Batches
    batch1 = await AdmissionBatch.get("batch_1")
    if not batch1:
        await AdmissionBatch(
            id="batch_1",
            name="AIML 2025-2029",
            department_id="AIML",
            academic_year="2025-2029",
            description="Admissions batch for AI and Machine Learning specialization courses.",
            start_date="2025-06-01",
            end_date="2025-08-30",
            status="active",
            created_by="system",
        ).insert()

    batch2 = await AdmissionBatch.get("batch_2")
    if not batch2:
        await AdmissionBatch(
            id="batch_2",
            name="CSE 2025-2029",
            department_id="CSE",
            academic_year="2025-2029",
            description="Admissions batch for standard Computer Science engineering curriculum.",
            start_date="2025-06-01",
            end_date="2025-08-30",
            status="active",
            created_by="system",
        ).insert()

    batch3 = await AdmissionBatch.get("batch_3")
    if not batch3:
        await AdmissionBatch(
            id="batch_3",
            name="ECE 2025-2029",
            department_id="ECE",
            academic_year="2025-2029",
            description="Admissions batch for Electronics and Communication courses.",
            start_date="2025-05-15",
            end_date="2025-07-31",
            status="closed",
            created_by="system",
        ).insert()

    # Seed default Upload Links
    aiml_link = await UploadLink.find_one(UploadLink.token == "aiml-2025-portal")
    if not aiml_link:
        dept = await Department.find_one(Department.code == "AIML")
        if dept:
            await UploadLink(
                department_id=dept.id,
                batch_id="batch_1",
                token="aiml-2025-portal",
                slug="aiml-2025-portal",
                title="AIML Public Upload",
                description="Admissions upload portal for AI & ML specialization.",
                is_active=True,
                expires_at=datetime(2026, 8, 30, 23, 59, 59, tzinfo=timezone.utc),
                max_submissions=100,
                submission_count=15,
                created_by="system",
            ).insert()
    else:
        changed = False
        if not aiml_link.batch_id:
            aiml_link.batch_id = "batch_1"
            changed = True
        if not getattr(aiml_link, "slug", None):
            aiml_link.slug = "aiml-2025-portal"
            changed = True
        if changed:
            await aiml_link.save()

    cse_link = await UploadLink.find_one(UploadLink.token == "cse-2025-portal")
    if not cse_link:
        dept = await Department.find_one(Department.code == "CSE")
        if dept:
            await UploadLink(
                department_id=dept.id,
                batch_id="batch_2",
                token="cse-2025-portal",
                slug="cse-2025-portal",
                title="CSE Public Upload",
                description="Admissions upload portal for Computer Science & Engineering.",
                is_active=True,
                expires_at=datetime(2026, 8, 30, 23, 59, 59, tzinfo=timezone.utc),
                max_submissions=100,
                submission_count=32,
                created_by="system",
            ).insert()
    else:
        changed = False
        if not cse_link.batch_id:
            cse_link.batch_id = "batch_2"
            changed = True
        if not getattr(cse_link, "slug", None):
            cse_link.slug = "cse-2025-portal"
            changed = True
        if changed:
            await cse_link.save()

    # Seed default Super Admin user (username: admin, password: admin123, department: null)
    admin_user = await User.find_one(User.username == "admin")
    if not admin_user:
        await User(
            username="admin",
            name="Super Admin",
            email="admin@test.com",
            password=get_password_hash("admin123"),
            role=UserRole.SUPER_ADMIN,
            department_code=None,
            is_active=True,
        ).insert()

    # Seed default Department Admin user (username: aiml, password: aiml123, department: AIML)
    aiml_user = await User.find_one(User.username == "aiml")
    if not aiml_user:
        await User(
            username="aiml",
            name="AIML Department Admin",
            email="aiml@test.com",
            password=get_password_hash("aiml123"),
            role=UserRole.DEPARTMENT_ADMIN,
            department_code="AIML",
            is_active=True,
        ).insert()


