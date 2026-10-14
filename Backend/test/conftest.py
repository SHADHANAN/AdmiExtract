import pytest
import pytest_asyncio
from unittest.mock import MagicMock
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.main import app
from app.services.gemini_service import GeminiService


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod

    db_mod.client = AsyncIOMotorClient(
        settings.MONGODB_URI, serverSelectionTimeoutMS=2000
    )
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest_asyncio.fixture
async def client_async():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=30.0
    ) as ac:
        yield ac


@pytest.fixture
def temp_sample_aadhaar(tmp_path):
    fpath = tmp_path / "sample_aadhaar.pdf"
    fpath.write_bytes(b"%PDF-1.4 sample aadhaar content")
    return str(fpath)


@pytest.fixture
def temp_sample_sslc(tmp_path):
    fpath = tmp_path / "sample_sslc.pdf"
    fpath.write_bytes(b"%PDF-1.4 sample sslc content")
    return str(fpath)


@pytest.fixture
def temp_sample_community(tmp_path):
    fpath = tmp_path / "sample_community.pdf"
    fpath.write_bytes(b"%PDF-1.4 sample community certificate content")
    return str(fpath)


@pytest.fixture
def mock_gemini_service():
    """Mock GeminiService to return predictable field extractions for testing."""
    mock_service = MagicMock(spec=GeminiService)

    def side_effect(file_path, prompt=None, doc_config=None, target_fields=None, **kwargs):
        requested = target_fields or ["student_name", "date_of_birth", "gender"]
        fields = {}
        summary = {}

        kb = {
            "student_name": ("Student Name", "Karthik Raja", 99.0),
            "date_of_birth": ("Date of Birth", "10/05/2006", 98.0),
            "gender": ("Gender", "MALE", 99.0),
            "community": ("Community", "BC", 97.0),
            "community_category": ("Community", "BC", 97.0),
            "father_name": ("Father Name", "Rajendran", 96.0),
            "permanent_address": ("Address", "45 Temple St, Madurai", 95.0),
            "income": ("Annual Income", "120000", 94.0),
            "annual_income": ("Annual Income", "120000", 94.0),
        }

        for req in requested:
            if req in kb:
                label, val, conf = kb[req]
                fields[label] = {"value": val, "confidence": conf}
                summary[req] = val

        return {
            "success": True,
            "document_type": "DOCUMENT",
            "confidence": 98.0,
            "fields": fields,
            "extracted_summary": summary,
        }

    mock_service.extract_from_file.side_effect = side_effect
    return mock_service
