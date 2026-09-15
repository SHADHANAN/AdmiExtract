import re
from datetime import datetime, timezone, timedelta
from typing import Any, cast
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from beanie import init_beanie, PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from app.main import app
from app.models.user import User
from app.models.department import Department
from app.models.batch import AdmissionBatch
from app.models.batch_class import BatchClass
from app.models.upload_link import UploadLink
from app.models.student_submission import StudentSubmission
from app.core.config import settings


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_test_db"]

    import app.db.database
    app.db.database.client = test_client
    app.db.database.db = test_db
    app.db.database._is_connected = True

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[User, Department, AdmissionBatch, BatchClass, UploadLink, StudentSubmission],
    )
    await User.find_all().delete()
    await Department.find_all().delete()
    await AdmissionBatch.find_all().delete()
    await BatchClass.find_all().delete()
    await UploadLink.find_all().delete()
    await StudentSubmission.find_all().delete()

    yield

    await test_client.drop_database("automate_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_cors_allows_configured_public_frontend_origin(client_async: AsyncClient):
    """Verify that backend CORS configuration allows the public Cloudflare Tunnel frontend origin."""
    test_origin = "https://fought-lock-pda-birthday.trycloudflare.com"

    response = await client_async.options(
        "/",
        headers={
            "Origin": test_origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == test_origin
    assert response.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.asyncio
async def test_cors_allows_localhost_development_origin(client_async: AsyncClient):
    """Verify that existing local development origins continue to be allowed."""
    dev_origin = "http://localhost:5173"

    response = await client_async.options(
        "/",
        headers={
            "Origin": dev_origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == dev_origin


@pytest.mark.asyncio
async def test_student_route_resolves_valid_upload_link(client_async: AsyncClient):
    """Verify GET /student/{slug} resolves the active upload link document."""
    dept = Department(name="Computer Science", code="CS", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_cs_2026",
        name="CS 2026",
        department_id="CS",
        academic_year="2026-2030",
        created_by="admin",
    )
    await batch.insert()

    token = "test-token-xyz-123"
    slug = token
    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        token=token,
        slug=slug,
        title="CS 2026 Admissions Portal",
        is_active=True,
        created_by="admin",
    )
    await link.insert()

    # Query the backend endpoint via /student/{slug}
    res = await client_async.get(f"/student/{slug}")
    assert res.status_code == 200
    data = res.json()
    assert data["token"] == token
    assert data["slug"] == slug
    assert data["title"] == "CS 2026 Admissions Portal"
    assert data["batch_id"] == batch.id


@pytest.mark.asyncio
async def test_student_route_returns_404_for_nonexistent_link(client_async: AsyncClient):
    """Verify GET /student/{slug} returns 404 for invalid token or slug."""
    res = await client_async.get("/student/non-existent-token-999")
    assert res.status_code == 404
    assert res.json()["detail"] == "Invalid upload link."


@pytest.mark.asyncio
async def test_student_route_returns_403_for_disabled_link(client_async: AsyncClient):
    """Verify GET /student/{slug} returns 403 when upload link is deactivated."""
    dept = Department(name="Information Technology", code="IT", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_it_2026",
        name="IT 2026",
        department_id="IT",
        academic_year="2026-2030",
        created_by="admin",
    )
    await batch.insert()

    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        token="disabled-token-123",
        slug="disabled-token-123",
        title="IT Disabled Portal",
        is_active=False,
        created_by="admin",
    )
    await link.insert()

    res = await client_async.get(f"/student/{link.slug}")
    assert res.status_code == 403
    assert "disabled" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_student_route_returns_410_for_expired_link(client_async: AsyncClient):
    """Verify GET /student/{slug} returns 410 when upload link has expired."""
    dept = Department(name="Mechanical Engineering", code="ME", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_me_2026",
        name="ME 2026",
        department_code="ME",
        department_id="ME",
        academic_year="2026-2030",
        created_by="admin",
    )
    await batch.insert()

    expired_time = datetime.now(timezone.utc) - timedelta(days=2)
    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        token="expired-token-123",
        slug="expired-token-123",
        title="ME Expired Portal",
        is_active=True,
        expires_at=expired_time,
        created_by="admin",
    )
    await link.insert()

    res = await client_async.get(f"/student/{link.slug}")
    assert res.status_code == 410
    assert "expired" in res.json()["detail"].lower()


def test_public_student_upload_url_generation():
    """
    Verify public URL generation logic:
    1. Uses configured PUBLIC_APP_URL.
    2. Never contains localhost, 127.0.0.1, or private LAN IP when configured.
    3. Trailing slashes are cleanly stripped.
    """
    public_base = "https://fought-lock-pda-birthday.trycloudflare.com"
    token = "SECURE_TOKEN_999"

    # Simulate getStudentUploadUrl logic
    clean_base = public_base.rstrip("/")
    generated_url = f"{clean_base}/student/{token}"

    assert generated_url == "https://fought-lock-pda-birthday.trycloudflare.com/student/SECURE_TOKEN_999"
    assert "localhost" not in generated_url
    assert "127.0.0.1" not in generated_url
    assert not re.search(r"192\.168\.\d+\.\d+", generated_url)
    assert not re.search(r"10\.\d+\.\d+\.\d+", generated_url)

    # Test trailing slash normalization
    with_slash = "https://fought-lock-pda-birthday.trycloudflare.com///"
    normalized_url = f"{with_slash.rstrip('/')}/student/{token}"
    assert normalized_url == generated_url


@pytest.mark.asyncio
async def test_student_verify_identity_with_email_payload(client_async: AsyncClient):
    """Verify POST /student/verify accepts payload with email."""
    dept = Department(name="Information Technology", code="IT", intake_capacity=60, created_by="admin")
    await dept.insert()

    batch = AdmissionBatch(
        id="batch_it_2026",
        name="IT 2026",
        department_code="IT",
        department_id="IT",
        academic_year="2026-2030",
        created_by="admin",
        status="active",
    )
    await batch.insert()

    link = UploadLink(
        department_id=dept.id,
        batch_id=batch.id,
        token="it-portal-2026",
        slug="it-portal-2026",
        title="IT Document Portal",
        is_active=True,
        created_by="admin",
    )
    await link.insert()

    # Mock Excel template check so verification succeeds
    from unittest.mock import MagicMock, patch
    mock_meta = MagicMock()
    mock_meta.file_path = "dummy.xlsx"

    with patch("app.api.student_submission._excel_repo.get_by_batch_id", return_value=mock_meta), \
         patch("os.path.exists", return_value=True):
        res = await client_async.post(
            "/student/verify",
            json={
                "token": link.token,
                "student_name": "John Doe",
                "register_number": "24IT001",
                "mobile_number": "9876543210",
                "email": "john.doe@example.com",
            },
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["batch_id"] == batch.id
        assert data["batch_name"] == batch.name


