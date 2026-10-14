import os
import time
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.database import init_db, close_db, is_mongodb_connected, mask_mongodb_uri
from app.api.user import router as user_router
from app.api.auth import router as auth_router
from app.api.department import router as department_router
from app.api.student_submission import (
    router as student_submission_router,
    student_router,
    students_me_router,
    submissions_alias_router,
)
from app.api.doc_config_version import router as doc_config_version_router
from app.api.batch import router as batch_router, public_router as public_batch_router
from app.api.batch_class import router as batch_class_router
from app.api.upload_link import router as upload_link_router
from app.api.wanted_field import router as wanted_field_router
from app.api.student_document import router as student_document_router
from app.api.document_extraction import router as document_extraction_router
from app.api.document_verification import router as document_verification_router
from app.api.batch_extraction import router as batch_extraction_router
from app.api.notification import router as notification_router
from app.api.staff import router as staff_router

from app.services.document_worker_pool import DocumentWorkerPool

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Database connection & Beanie initialization
    db_ready = await init_db()

    # 2. Worker pool startup - workers start ONLY after Beanie is successfully initialized
    worker_pool = DocumentWorkerPool.get_instance()
    if db_ready:
        await worker_pool.start()
    else:
        print("[LIFESPAN] Database/Beanie not initialized; DocumentWorkerPool startup postponed until connection is established.")

    yield

    # 3. Graceful shutdown: workers must stop BEFORE database is closed
    print("Application shutting down...")
    await worker_pool.stop()
    await close_db()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

allowed_origins = [
    "https://admiextract.pages.dev",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Dynamically add configured public app URL and CORS_ORIGINS
if getattr(settings, "PUBLIC_APP_URL", None) and settings.PUBLIC_APP_URL.strip():
    clean_pub = settings.PUBLIC_APP_URL.strip().rstrip("/")
    if clean_pub not in allowed_origins:
        allowed_origins.append(clean_pub)

if getattr(settings, "CORS_ORIGINS", None) and settings.CORS_ORIGINS.strip():
    for raw_origin in settings.CORS_ORIGINS.split(","):
        clean_origin = raw_origin.strip().rstrip("/")
        if clean_origin and clean_origin not in allowed_origins:
            allowed_origins.append(clean_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^https?:\/\/(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Process-Time"],
)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Observability middleware tracking request execution time."""
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}s"
    return response


@app.middleware("http")
async def check_database_availability(request: Request, call_next):
    """
    Middleware interceptor to gracefully return HTTP 503 if an API endpoint
    is invoked while MongoDB is offline, avoiding unhandled 500 server crashes.
    """
    # Allow root, health, documentation, and OpenAPI paths regardless of database status
    whitelisted_prefixes = ("/", "/health", "/docs", "/redoc", "/openapi.json")
    if request.url.path in whitelisted_prefixes:
        return await call_next(request)

    if not is_mongodb_connected():
        masked_uri = mask_mongodb_uri(settings.MONGODB_URI)
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "detail": (
                    f"Database is currently offline. Please ensure MongoDB is running and "
                    f"accessible at '{masked_uri}'."
                )
            }
        )

    return await call_next(request)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Production error handler: prevents leakage of internal stack traces,
    filesystem paths, or database credentials in 500 responses.
    """
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    logger.error(f"[Unhandled Error] {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred. Please try again later or contact an administrator."
        }
    )


app.include_router(auth_router)
app.include_router(user_router)
app.include_router(department_router)
app.include_router(batch_router)
app.include_router(batch_class_router)
app.include_router(public_batch_router)
app.include_router(upload_link_router)
app.include_router(student_submission_router)
app.include_router(submissions_alias_router)
app.include_router(student_router)
app.include_router(students_me_router)
app.include_router(doc_config_version_router)
app.include_router(wanted_field_router)
app.include_router(student_document_router)
app.include_router(document_extraction_router)
app.include_router(document_verification_router)
app.include_router(batch_extraction_router)
app.include_router(notification_router)
app.include_router(staff_router)


@app.get("/")
@app.get("/health")
async def root():
    connected = is_mongodb_connected()
    worker_pool = DocumentWorkerPool.get_instance()

    queue_depth = 0
    processing_count = 0
    if connected:
        try:
            from app.models.document_job import DocumentProcessingJob, JobStatus
            queue_depth = await DocumentProcessingJob.find(
                DocumentProcessingJob.status == JobStatus.QUEUED
            ).count()
            processing_count = await DocumentProcessingJob.find(
                DocumentProcessingJob.status == JobStatus.PROCESSING
            ).count()
        except Exception:
            pass

    return {
        "status": "healthy" if connected else "degraded",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "message": (
            "Automate API is running successfully"
            if connected
            else "Automate API is running in degraded mode (MongoDB unavailable)"
        ),
        "database": {
            "status": "connected" if connected else "disconnected",
            "name": settings.DATABASE_NAME,
        },
        "worker_pool": {
            "is_running": worker_pool.is_running,
            "concurrency": worker_pool.concurrency,
            "queued_jobs": queue_depth,
            "processing_jobs": processing_count,
        },
        "docs_url": "/docs",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
