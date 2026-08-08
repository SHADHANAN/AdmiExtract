from typing import Any, cast
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.user import User, UserRole
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

    await init_beanie(database=cast(Any, test_db), document_models=[User])
    await User.find_all().delete()
    
    yield
    
    await test_client.drop_database("automate_test_db")
    test_client.close()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_headers(client_async: AsyncClient) -> dict:
    """Fixture to register a super_admin user and return authorization headers."""
    await client_async.post(
        "/auth/register",
        json={"username": "adminuser", "name": "Admin User", "email": "admin@example.com", "password": "adminpassword123", "role": "super_admin"}
    )
    response = await client_async.post(
        "/auth/login",
        data={"username": "adminuser", "password": "adminpassword123"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_user_success(client_async: AsyncClient, admin_headers: dict):
    response = await client_async.post(
        "/users",
        json={"username": "alice", "name": "Alice", "email": "alice@example.com", "password": "alicepassword123", "role": "department_admin", "department_code": "AIML"},
        headers=admin_headers
    )
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "alice"
    assert data["name"] == "Alice"
    assert data["email"] == "alice@example.com"
    assert data["role"] == "department_admin"
    assert data["department_code"] == "AIML"
    assert "id" in data
    assert "password" not in data
    
    # Check DB
    user = await User.find_one(User.username == "alice")
    assert user is not None
    assert user.password != "alicepassword123"


@pytest.mark.asyncio
async def test_create_user_duplicate_email(client_async: AsyncClient, admin_headers: dict):
    await client_async.post(
        "/users",
        json={"username": "alice1", "name": "Alice", "email": "alice@example.com", "password": "alicepassword123"},
        headers=admin_headers
    )
    response = await client_async.post(
        "/users",
        json={"username": "alice2", "name": "Alice Two", "email": "alice@example.com", "password": "anotherpassword"},
        headers=admin_headers
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "A user with this email address already exists."


@pytest.mark.asyncio
async def test_list_users(client_async: AsyncClient, admin_headers: dict):
    # Empty list first (only contains the logged-in admin user)
    response = await client_async.get("/users", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["username"] == "adminuser"

    # Insert two users
    await client_async.post(
        "/users",
        json={"username": "alice", "name": "Alice", "email": "alice@example.com", "password": "alicepassword123"},
        headers=admin_headers
    )
    await client_async.post(
        "/users",
        json={"username": "bob", "name": "Bob", "email": "bob@example.com", "password": "bobpassword123"},
        headers=admin_headers
    )

    response = await client_async.get("/users", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    usernames = [u["username"] for u in data]
    assert "adminuser" in usernames
    assert "alice" in usernames
    assert "bob" in usernames


@pytest.mark.asyncio
async def test_get_user_by_id(client_async: AsyncClient, admin_headers: dict):
    create_res = await client_async.post(
        "/users",
        json={"username": "alice", "name": "Alice", "email": "alice@example.com", "password": "alicepassword123"},
        headers=admin_headers
    )
    user_id = create_res.json()["id"]

    response = await client_async.get(f"/users/{user_id}", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Alice"
    assert data["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_get_user_not_found(client_async: AsyncClient, admin_headers: dict):
    response = await client_async.get("/users/60b9f15c721c0e35f4a7c1b5", headers=admin_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


@pytest.mark.asyncio
async def test_update_user_fields(client_async: AsyncClient, admin_headers: dict):
    create_res = await client_async.post(
        "/users",
        json={"username": "alice", "name": "Alice", "email": "alice@example.com", "password": "alicepassword123"},
        headers=admin_headers
    )
    user_id = create_res.json()["id"]

    # Update name, email, and password using UserUpdate
    response = await client_async.put(
        f"/users/{user_id}",
        json={"name": "Alice Updated", "email": "alice@example.com", "password": "newpassword456"},
        headers=admin_headers
    )
    assert response.status_code == 200
    
    # Verify password updated in DB
    user = await User.find_one(User.username == "alice")
    assert user is not None
    from app.core.security import verify_password
    assert verify_password("newpassword456", user.password)
    assert not verify_password("alicepassword123", user.password)


@pytest.mark.asyncio
async def test_update_user_email_conflict(client_async: AsyncClient, admin_headers: dict):
    await client_async.post(
        "/users",
        json={"username": "alice", "name": "Alice", "email": "alice@example.com", "password": "alicepassword123"},
        headers=admin_headers
    )
    create_bob = await client_async.post(
        "/users",
        json={"username": "bob", "name": "Bob", "email": "bob@example.com", "password": "bobpassword123"},
        headers=admin_headers
    )
    bob_id = create_bob.json()["id"]

    # Try updating Bob's email to Alice's email
    response = await client_async.put(
        f"/users/{bob_id}",
        json={"name": "Bob", "email": "alice@example.com", "password": "bobpassword123"},
        headers=admin_headers
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "A user with this email address already exists."


@pytest.mark.asyncio
async def test_delete_user(client_async: AsyncClient, admin_headers: dict):
    create_res = await client_async.post(
        "/users",
        json={"username": "alice", "name": "Alice", "email": "alice@example.com", "password": "alicepassword123"},
        headers=admin_headers
    )
    user_id = create_res.json()["id"]

    # Delete
    response = await client_async.delete(f"/users/{user_id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["message"] == "User deleted successfully"

    # Verify gone from DB
    get_res = await client_async.get(f"/users/{user_id}", headers=admin_headers)
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_user_endpoints_unauthorized(client_async: AsyncClient):
    """Test that requests without authentication or with non-super_admin roles are rejected."""
    await client_async.post(
        "/auth/register",
        json={"username": "deptadmin", "name": "Dept Admin User", "email": "deptadmin@example.com", "password": "deptpassword123", "role": "department_admin"}
    )
    login_res = await client_async.post(
        "/auth/login",
        data={"username": "deptadmin", "password": "deptpassword123"}
    )
    dept_token = login_res.json()["access_token"]
    dept_headers = {"Authorization": f"Bearer {dept_token}"}

    # 1. Unauthenticated (no token) -> 401
    res = await client_async.get("/users")
    assert res.status_code == 401

    # 2. Authenticated but unauthorized role (department_admin) -> 403
    res = await client_async.get("/users", headers=dept_headers)
    assert res.status_code == 403
    assert res.json()["detail"] == "You do not have permission to access this resource"

    # 3. Create attempt by department_admin -> 403
    res = await client_async.post("/users", json={"username": "attacker", "name": "Attacker", "email": "attacker@example.com", "password": "pass"}, headers=dept_headers)
    assert res.status_code == 403

