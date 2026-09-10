from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.database import init_db, close_db, is_mongodb_connected
from app.api.user import router as user_router
from app.api.auth import router as auth_router
from app.api.department import router as department_router
from app.api.student_submission import router as student_submission_router, student_router, students_me_router
from app.api.excel_template import router as excel_template_router
from app.api.doc_config_version import router as doc_config_version_router
from app.api.batch import router as batch_router, public_router as public_batch_router
from app.api.batch_class import router as batch_class_router
from app.api.upload_link import router as upload_link_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    print("Application shutting down...")
    await close_db()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def check_database_availability(request: Request, call_next):
    """
    Middleware interceptor to gracefully return HTTP 503 if an API endpoint
    is invoked while MongoDB is offline, avoiding unhandled 500 server crashes.
    """
    # Allow root, documentation, and OpenAPI paths regardless of database status
    whitelisted_prefixes = ("/", "/docs", "/redoc", "/openapi.json")
    if request.url.path in whitelisted_prefixes:
        return await call_next(request)

    if not is_mongodb_connected():
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "detail": (
                    f"Database is currently offline. Please ensure MongoDB is running and "
                    f"accessible at '{settings.MONGODB_URI}'."
                )
            }
        )

    return await call_next(request)


app.include_router(auth_router)
app.include_router(user_router)
app.include_router(department_router)
app.include_router(batch_router)
app.include_router(batch_class_router)
app.include_router(public_batch_router)
app.include_router(upload_link_router)
app.include_router(student_submission_router)
app.include_router(student_router)
app.include_router(students_me_router)
app.include_router(excel_template_router)
app.include_router(doc_config_version_router)


@app.get("/")
async def root():
    connected = is_mongodb_connected()
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
        "docs_url": "/docs",
    }
