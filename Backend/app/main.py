from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.db.database import init_db
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
    print("Connecting to MongoDB...")
    await init_db()
    print("MongoDB Connected!")
    yield
    print("Application shutting down...")


from fastapi.middleware.cors import CORSMiddleware

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
    return {
        "status": "healthy",
        "message": "Automate API is running successfully"
    }
