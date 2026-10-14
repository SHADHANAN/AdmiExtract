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
import os
import re
from typing import Any, cast
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError, PyMongoError
from beanie import init_beanie

from app.core.config import settings

logger = logging.getLogger("app.db.database")


def mask_mongodb_uri(uri: str) -> str:
    """Mask credentials in MongoDB URI to prevent secret exposure in logs."""
    if not uri:
        return "<EMPTY>"
    pattern = r"(mongodb(?:\+srv)?:\/\/)([^:@]+):([^@]+)@(.+)"
    return re.sub(pattern, r"\1*****:*****@\4", uri)


# Monkeypatch AsyncIOMotorClient to bypass Beanie/Motor compatibility issue
if not hasattr(AsyncIOMotorClient, "append_metadata"):
    AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

# Default client and database instances (allow 5s for remote Atlas clusters, 2s for local)
_timeout_ms = 5000 if ("mongodb+srv://" in settings.MONGODB_URI or os.getenv("RENDER") or os.getenv("IS_RENDER")) else 2000
client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=_timeout_ms)
db = client[settings.DATABASE_NAME]

_is_connected: bool = False
_reconnect_task: asyncio.Task | None = None


def is_mongodb_connected() -> bool:
    """Return True if the database is currently connected and initialized."""
    return _is_connected


def is_beanie_initialized() -> bool:
    """Return True only if Beanie document models have been successfully initialized."""
    global _is_connected
    if not _is_connected:
        return False
    try:
        from beanie.exceptions import CollectionWasNotInitialized
        from app.models.document_job import DocumentProcessingJob
        return DocumentProcessingJob.get_pymongo_collection() is not None
    except Exception:
        return False


async def _run_db_setup():
    """Execute collection migrations, Beanie document registration, and seed data."""
    global _is_connected
    from app.models.user import User, UserRole
    from app.models.department import Department
    from app.models.upload_link import UploadLink
    from app.models.student_submission import StudentSubmission
    from app.models.doc_config_version import DocumentConfigurationVersion
    from app.models.batch import AdmissionBatch
    from app.models.batch_class import BatchClass
    from app.models.wanted_field_config import DocumentFieldConfiguration
    from app.models.document_job import DocumentProcessingJob, SubmissionSession
    from app.models.student_document import StudentDocument
    from app.models.document_extraction_request import DocumentExtractionRequest
    from app.models.document_extraction_result import DocumentExtractionResult
    from app.models.audit_log import AuditLog
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

    # Safe migration for global register number uniqueness before creating unique index
    from app.utils.normalization import normalize_register_number
    sub_cursor = db["student_submissions"].find({})
    seen_normalized: set[str] = set()
    async for sub_doc in sub_cursor:
        sub_id = sub_doc["_id"]
        raw_reg = sub_doc.get("register_number", "")
        norm = normalize_register_number(raw_reg)
        if not norm:
            norm = f"UNKNOWN_{str(sub_id)[-6:]}"

        existing_norm = sub_doc.get("normalized_register_number")
        is_conflict = sub_doc.get("has_duplicate_conflict", False)

        if is_conflict and existing_norm:
            # Already disambiguated conflict document from a prior migration run
            seen_normalized.add(existing_norm)
            continue

        target_norm = existing_norm if existing_norm else norm

        if target_norm in seen_normalized:
            # Duplicate conflict found: disambiguate key and mark conflict flag without deleting document
            disambiguated = f"{norm}-CONFLICT-{str(sub_id)[-6:]}"
            await db["student_submissions"].update_one(
                {"_id": sub_id},
                {
                    "$set": {
                        "normalized_register_number": disambiguated,
                        "has_duplicate_conflict": True,
                        "conflict_original_normalized_register_number": norm,
                    }
                }
            )
            seen_normalized.add(disambiguated)
            print(f"[DB SETUP] Disambiguated duplicate register number '{raw_reg}' in submission {sub_id} to '{disambiguated}'.")
        else:
            seen_normalized.add(target_norm)
            if not existing_norm or existing_norm != target_norm:
                await db["student_submissions"].update_one(
                    {"_id": sub_id},
                    {
                        "$set": {
                            "normalized_register_number": target_norm,
                            "has_duplicate_conflict": False,
                        }
                    }
                )

    from app.models.document_verification import DocumentFieldVerification
    from app.models.batch_extraction import BatchExtractionRequest
    from app.models.verification_token import VerificationToken
    from app.models.verification_notification import VerificationNotification
    from app.models.excel_template import ExcelBatchTemplate

    await init_beanie(
        database=cast(Any, db),
        document_models=[
            User,
            Department,
            UploadLink,
            StudentSubmission,
            DocumentConfigurationVersion,
            AdmissionBatch,
            BatchClass,
            DocumentFieldConfiguration,
            DocumentProcessingJob,
            SubmissionSession,
            AuditLog,
            StudentDocument,
            DocumentExtractionRequest,
            DocumentExtractionResult,
            DocumentFieldVerification,
            BatchExtractionRequest,
            VerificationToken,
            VerificationNotification,
            ExcelBatchTemplate,
        ],
        allow_index_dropping=True,
    )

    # Consolidate legacy duplicate StudentDocument records if any exist
    try:
        from app.repositories.student_document_repository import StudentDocumentRepository
        doc_repo = StudentDocumentRepository()
        merged_count = await doc_repo.consolidate_duplicate_documents()
        if merged_count > 0:
            print(f"[DB SETUP] Successfully consolidated {merged_count} duplicate StudentDocument record(s).")
    except Exception as cons_err:
        print(f"[DB SETUP] Note during document consolidation: {cons_err}")

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

    # Seed default user accounts ONLY in non-production environments to avoid default credentials in production
    is_prod_env = settings.APP_ENV in ("production", "staging") or bool(os.getenv("RENDER"))
    if not is_prod_env:
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

            # Start worker pool now that Beanie is fully initialized
            try:
                from app.services.document_worker_pool import DocumentWorkerPool
                pool = DocumentWorkerPool.get_instance()
                if not pool.is_running:
                    await pool.start()
            except Exception as w_err:
                logger.error("[WorkerPool] Error starting workers post-reconnect: %s", w_err)
            break
        except Exception:
            pass


async def init_db() -> bool:
    """
    Initialize database connection and verify MongoDB availability.
    If MongoDB is offline, prints diagnostic guidance and starts background retry.
    Returns True if database and Beanie are fully initialized, False otherwise.
    """
    global _is_connected, _reconnect_task

    if _is_connected and is_beanie_initialized():
        return True

    uri_scheme = "mongodb+srv" if settings.MONGODB_URI.startswith("mongodb+srv://") else "mongodb"
    is_render_or_prod = bool(
        os.getenv("RENDER") or os.getenv("IS_RENDER") or settings.APP_ENV in ("production", "staging")
    )
    env_display = "production/render" if is_render_or_prod else f"development ({settings.APP_ENV})"
    print(f"[STARTUP DIAGNOSTIC] environment: {env_display} | scheme: {uri_scheme} | database: {settings.DATABASE_NAME}")

    try:
        await client.admin.command("ping")
        await _run_db_setup()
        print("MongoDB Connected successfully and Beanie initialized!")
        return True
    except (ServerSelectionTimeoutError, PyMongoError, OSError, Exception) as exc:
        _is_connected = False
        print("\n" + "=" * 78)
        print(" [WARNING] MongoDB is UNAVAILABLE at startup!")
        print(f" Environment: {env_display}")
        print(f" Scheme:      {uri_scheme}")
        print(f" Database:    {settings.DATABASE_NAME}")
        print(f" Details:  {exc}")
        print("-" * 78)
        print(" The application is starting in DEGRADED mode.")
        print(" Endpoints that require database storage will return 503 until MongoDB is up.")
        print(" DocumentWorkerPool will NOT start until database/Beanie is online.")
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
        if not _reconnect_task or _reconnect_task.done():
            _reconnect_task = asyncio.create_task(_background_reconnect())
        return False


async def close_db():
    """Gracefully close database client and cancel background retry tasks."""
    global _reconnect_task, client, _is_connected
    _is_connected = False
    if _reconnect_task and not _reconnect_task.done():
        _reconnect_task.cancel()
        try:
            await _reconnect_task
        except asyncio.CancelledError:
            pass
        _reconnect_task = None
    client.close()
