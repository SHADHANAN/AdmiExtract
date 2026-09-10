"""
Database Connection & Initialization Module
============================================

Manages Async Motor client, Beanie ODM initialization, legacy migrations,
and initial data seeding.

Features:
- Fast connection validation with 2s timeout.
- Graceful degraded startup when MongoDB is temporarily offline.
- Clear, actionable diagnostic startup error banners.
- Automatic background reconnection when MongoDB comes online.
"""

import asyncio
import logging
from typing import Any, cast
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError, PyMongoError
from beanie import init_beanie

from app.core.config import settings

logger = logging.getLogger("app.db.database")

# Monkeypatch AsyncIOMotorClient to bypass Beanie/Motor compatibility issue
if not hasattr(AsyncIOMotorClient, "append_metadata"):
    AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

# Default client and database instances
client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=2000)
db = client[settings.DATABASE_NAME]

_is_connected: bool = False
_reconnect_task: asyncio.Task | None = None


def is_mongodb_connected() -> bool:
    """Return True if the database is currently connected and initialized."""
    return _is_connected


async def _run_db_setup():
    """Execute collection migrations, Beanie document registration, and seed data."""
    global _is_connected
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

    _is_connected = True


async def _background_reconnect():
    """Background task that periodically attempts to reconnect to MongoDB if startup was degraded."""
    global _is_connected
    while not _is_connected:
        await asyncio.sleep(5)
        try:
            await client.admin.command("ping")
            await _run_db_setup()
            print("\n" + "=" * 70)
            print("[INFO] MongoDB Connected! Database initialized and seed data verified.")
            print("=" * 70 + "\n")
            break
        except Exception:
            pass


async def init_db():
    """
    Initialize database connection and verify MongoDB availability.
    If MongoDB is offline, prints diagnostic guidance and starts background retry.
    """
    global _is_connected, _reconnect_task

    print(f"Connecting to MongoDB at '{settings.MONGODB_URI}' (Database: '{settings.DATABASE_NAME}')...")

    try:
        # Fast health check with 2s timeout
        await client.admin.command("ping")
        await _run_db_setup()
        print("MongoDB Connected successfully!")
    except (ServerSelectionTimeoutError, PyMongoError, OSError) as exc:
        _is_connected = False
        print("\n" + "=" * 78)
        print(" [WARNING] MongoDB is UNAVAILABLE at startup!")
        print(f" URI:      {settings.MONGODB_URI}")
        print(f" Database: {settings.DATABASE_NAME}")
        print(f" Details:  {exc}")
        print("-" * 78)
        print(" The application is starting in DEGRADED mode.")
        print(" Endpoints that require database storage will return 503 until MongoDB is up.")
        print("")
        print(" Troubleshooting:")
        print("   1. Start local MongoDB service:")
        print("      - Windows Command:  net start MongoDB")
        print("      - Standalone:       mongod --dbpath <data_directory>")
        print("      - Docker:           docker run -d -p 27017:27017 --name mongodb mongo:latest")
        print("   2. Or set a cloud MongoDB Atlas URI in your '.env' file:")
        print("      MONGODB_URI=mongodb+srv://<username>:<password>@cluster.mongodb.net/")
        print("=" * 78 + "\n")

        # Launch background reconnect polling
        _reconnect_task = asyncio.create_task(_background_reconnect())


async def close_db():
    """Gracefully close database client and cancel background retry tasks."""
    global _reconnect_task, client
    if _reconnect_task and not _reconnect_task.done():
        _reconnect_task.cancel()
        try:
            await _reconnect_task
        except asyncio.CancelledError:
            pass
    client.close()
