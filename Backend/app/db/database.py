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
    from app.models.batch_class import BatchClass
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

    # Drop legacy unique batch_id_1 index on excel_templates to allow non-unique per-class template index creation
    try:
        index_info = await db["excel_templates"].index_information()
        if "batch_id_1" in index_info and index_info["batch_id_1"].get("unique"):
            await db["excel_templates"].drop_index("batch_id_1")
    except Exception:
        pass

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
            BatchClass,
        ],
        allow_index_dropping=True,
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


