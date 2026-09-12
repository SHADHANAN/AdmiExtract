from typing import Any, cast
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.user import User
from app.models.department import Department
from app.db.database import client
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
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

    await init_beanie(database=cast(Any, test_db), document_models=[User, Department])
    await User.find_all().delete()
    await Department.find_all().delete()
    
    yield
    
    await test_client.drop_database("automate_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def get_token_for_user(client_async: AsyncClient, name: str, email: str, role: str = "super_admin") -> str:
    username = email.split("@")[0]
    # Register
    await client_async.post(
        "/auth/register",
        json={"username": username, "name": name, "email": email, "password": "password123", "role": role}
    )
    # Login
    response = await client_async.post(
        "/auth/login",
        data={"username": username, "password": "password123"}
    )
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_create_department_success(client_async: AsyncClient):
    token = await get_token_for_user(client_async, "Staff User", "staff@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    response = await client_async.post(
        "/departments",
        json={"name": "UK September 2027", "code": "UK2027", "description": "September Intake"},
        headers=headers
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "UK September 2027"
    assert data["description"] == "September Intake"
    assert data["created_by"] == "staff"
    assert data["is_active"] is True
    assert "id" in data

    # Check DB
    dep = await Department.find_one(Department.name == "UK September 2027")
    assert dep is not None
    assert dep.created_by == "staff"


@pytest.mark.asyncio
async def test_create_department_unauthorized(client_async: AsyncClient):
    response = await client_async.post(
        "/departments",
        json={"name": "UK September 2027", "description": "September Intake"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_list_departments_success(client_async: AsyncClient):
    token = await get_token_for_user(client_async, "Staff User", "staff@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Verify empty first
    res = await client_async.get("/departments", headers=headers)
    assert res.status_code == 200
    assert res.json() == []

    # Create department
    await client_async.post(
        "/departments",
        json={"name": "UK Sept 2027", "code": "UKSEPT"},
        headers=headers
    )

    res = await client_async.get("/departments", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["name"] == "UK Sept 2027"
    assert data[0]["created_by"] == "staff"


@pytest.mark.asyncio
async def test_list_departments_unauthorized(client_async: AsyncClient):
    response = await client_async.get("/departments")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_department_by_id_success(client_async: AsyncClient):
    token = await get_token_for_user(client_async, "Staff User", "staff@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Create department
    create_res = await client_async.post(
        "/departments",
        json={"name": "UK Sept 2027", "code": "UKSEPT", "description": "September Intake"},
        headers=headers
    )
    assert create_res.status_code == 201
    dep_id = create_res.json()["id"]

    # Get by ID
    get_res = await client_async.get(f"/departments/{dep_id}", headers=headers)
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["name"] == "UK Sept 2027"
    assert data["description"] == "September Intake"


@pytest.mark.asyncio
async def test_get_department_by_id_not_found(client_async: AsyncClient):
    token = await get_token_for_user(client_async, "Staff User", "staff@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Invalid but valid format ObjectId
    fake_id = "507f1f77bcf86cd799439011"
    res = await client_async.get(f"/departments/{fake_id}", headers=headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_department_by_id_invalid_objectid(client_async: AsyncClient):
    token = await get_token_for_user(client_async, "Staff User", "staff@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    res = await client_async.get("/departments/invalid-id", headers=headers)
    assert res.status_code == 422  # FastAPI validation error


@pytest.mark.asyncio
async def test_update_department_success(client_async: AsyncClient):
    token = await get_token_for_user(client_async, "Staff User", "staff@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Create department
    create_res = await client_async.post(
        "/departments",
        json={"name": "UK Sept 2027", "code": "UKSEPT", "description": "September Intake"},
        headers=headers
    )
    dep_id = create_res.json()["id"]

    # Update description only
    update_res = await client_async.put(
        f"/departments/{dep_id}",
        json={"description": "Updated Description"},
        headers=headers
    )
    assert update_res.status_code == 200
    data = update_res.json()
    assert data["name"] == "UK Sept 2027"
    assert data["description"] == "Updated Description"


@pytest.mark.asyncio
async def test_update_department_duplicate_name(client_async: AsyncClient):
    token = await get_token_for_user(client_async, "Staff User", "staff@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Create two departments
    await client_async.post(
        "/departments",
        json={"name": "UK Sept 2027", "code": "UKSEPT"},
        headers=headers
    )
    create_res2 = await client_async.post(
        "/departments",
        json={"name": "USA Fall 2027", "code": "USAFALL"},
        headers=headers
    )
    dep_id2 = create_res2.json()["id"]

    # Try to rename the second department to the first one's name
    update_res = await client_async.put(
        f"/departments/{dep_id2}",
        json={"name": "UK Sept 2027"},
        headers=headers
    )
    assert update_res.status_code == 409
    assert "already exists" in update_res.json()["detail"]


@pytest.mark.asyncio
async def test_delete_department_success(client_async: AsyncClient):
    token = await get_token_for_user(client_async, "Staff User", "staff@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Create department
    create_res = await client_async.post(
        "/departments",
        json={"name": "UK Sept 2027", "code": "UKSEPT"},
        headers=headers
    )
    dep_id = create_res.json()["id"]

    # Delete
    del_res = await client_async.delete(f"/departments/{dep_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["message"] == "Department deleted successfully"

    # Verify deleted (should return 404)
    get_res = await client_async.get(f"/departments/{dep_id}", headers=headers)
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_create_department_duplicate_name(client_async: AsyncClient):
    token = await get_token_for_user(client_async, "Staff User", "staff@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Create one
    await client_async.post(
        "/departments",
        json={"name": "UK Sept 2027", "code": "UKSEPT"},
        headers=headers
    )

    # Try to create again
    res = await client_async.post(
        "/departments",
        json={"name": "UK Sept 2027", "code": "UKSEPT"},
        headers=headers
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_create_department_empty_name(client_async: AsyncClient):
    token = await get_token_for_user(client_async, "Staff User", "staff@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Try empty string name
    res = await client_async.post(
        "/departments",
        json={"name": "   ", "code": "UKSEPT", "description": "some desc"},
        headers=headers
    )
    assert res.status_code == 422  # Pydantic validation error due to min_length/custom validator


@pytest.mark.asyncio
async def test_department_creation_unauthorized_for_department_admin(client_async: AsyncClient):
    dept_admin_token = await get_token_for_user(client_async, "Dept Admin User", "deptadmin@example.com", role="department_admin")
    headers = {"Authorization": f"Bearer {dept_admin_token}"}

    # Should fail to create department
    response = await client_async.post(
        "/departments",
        json={"name": "UK September 2027", "code": "UK2027", "description": "September Intake"},
        headers=headers
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have permission to access this resource"

    # Should succeed to list departments
    response = await client_async.get("/departments", headers=headers)
    assert response.status_code == 200


