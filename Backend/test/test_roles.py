from typing import Any, cast
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.user import User, UserRole
from app.db.database import client
from app.core.dependencies import RoleChecker
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

# Create a temporary router to test RoleChecker access controls
roles_test_router = APIRouter(prefix="/test-roles", tags=["test-roles"])

@roles_test_router.get("/super-admin-only", dependencies=[Depends(RoleChecker([UserRole.SUPER_ADMIN]))])
async def super_admin_only():
    return {"message": "Welcome Super Admin"}


@roles_test_router.get("/department-admin-only", dependencies=[Depends(RoleChecker([UserRole.DEPARTMENT_ADMIN, UserRole.SUPER_ADMIN]))])
async def department_admin_only():
    return {"message": "Welcome Department Admin"}


# Register test router
app.include_router(roles_test_router)


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

    await init_beanie(database=cast(Any, test_db), document_models=[User])
    await User.find_all().delete()
    
    yield
    
    await test_client.drop_database("automate_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def get_token_for_user(client_async: AsyncClient, username: str, name: str, email: str, role: UserRole) -> str:
    import uuid
    uniq = uuid.uuid4().hex[:6]
    u = f"{username}_{uniq}"
    e = f"{username}_{uniq}@example.com"
    # Register user with role
    reg = await client_async.post(
        "/auth/register",
        json={"username": u, "name": name, "email": e, "password": "password123", "role": role.value if hasattr(role, "value") else str(role)}
    )
    # Login user
    response = await client_async.post(
        "/auth/login",
        data={"username": u, "password": "password123"}
    )
    if "access_token" not in response.json():
        raise RuntimeError(f"Login failed: reg={reg.status_code} {reg.text} | login={response.status_code} {response.text}")
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_department_admin_role_access(client_async: AsyncClient):
    token = await get_token_for_user(client_async, "deptadmin", "Dept Admin User", "dept@example.com", UserRole.DEPARTMENT_ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    # Department Admin should access department admin endpoint
    res = await client_async.get("/test-roles/department-admin-only", headers=headers)
    assert res.status_code == 200
    assert res.json()["message"] == "Welcome Department Admin"

    # Department Admin should NOT access super admin endpoint
    res = await client_async.get("/test-roles/super-admin-only", headers=headers)
    assert res.status_code == 403
    assert res.json()["detail"] == "You do not have permission to access this resource"


@pytest.mark.asyncio
async def test_super_admin_role_access(client_async: AsyncClient):
    token = await get_token_for_user(client_async, "superadmin", "Super Admin User", "super@example.com", UserRole.SUPER_ADMIN)
    headers = {"Authorization": f"Bearer {token}"}

    # Super Admin should access department admin endpoint
    res = await client_async.get("/test-roles/department-admin-only", headers=headers)
    assert res.status_code == 200

    # Super Admin should access super admin endpoint
    res = await client_async.get("/test-roles/super-admin-only", headers=headers)
    assert res.status_code == 200
    assert res.json()["message"] == "Welcome Super Admin"

