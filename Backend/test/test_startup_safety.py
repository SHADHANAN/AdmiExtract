"""
Tests for Backend Startup Safety & Port Conflict Prevention
===========================================================
Verifies:
1. App import does not start Uvicorn or initialize resources with side effects.
2. DocumentWorkerPool initialization is idempotent (single set of workers).
3. DocumentWorkerPool shutdown is safe and idempotent.
4. Repeated startup/shutdown cycles are idempotent and cleanly reclaim resources.
5. Port conflict detection and runner safety:
   - Port free: launches backend
   - Existing AdmiExtract backend: detects existing PID, prints friendly banner, exits 0 without duplicate launch
   - Restart flag: safely terminates existing AdmiExtract backend and restarts
   - Unrelated process: refuses to terminate/start, prints clear diagnostic, returns 1
6. Backend root and /auth/login endpoints function properly.
"""

import asyncio
import os
import socket
import sys
from typing import Any, cast
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

import run_backend
from run_backend import (
    verify_port_available,
    find_pid_on_port,
    is_admiextract_backend,
    wait_port_freed,
    run,
)
from app.main import app
from app.services.document_worker_pool import DocumentWorkerPool
from app.models.user import User
from app.core.config import settings


# ---------------------------------------------------------------------------
# 1. FastAPI App Import & WorkerPool Idempotency Tests
# ---------------------------------------------------------------------------

def test_app_import_safety():
    """Verify that importing app.main only exposes the FastAPI instance and doesn't run Uvicorn."""
    from app.main import app as main_app
    from fastapi import FastAPI

    assert isinstance(main_app, FastAPI)
    assert main_app.title == "Automate API"
    pool = DocumentWorkerPool.get_instance()
    assert isinstance(pool, DocumentWorkerPool)


@pytest.mark.asyncio
async def test_worker_pool_one_initialization():
    """Verify that calling worker_pool.start() multiple times does not create duplicate workers."""
    pool = DocumentWorkerPool.get_instance()
    await pool.stop()  # Clean slate

    try:
        await pool.start()
        first_count = len(pool.worker_tasks)
        assert first_count == pool.concurrency
        assert pool.is_running is True

        # Second call to start must be idempotent
        await pool.start()
        assert len(pool.worker_tasks) == first_count
        assert pool.is_running is True
    finally:
        await pool.stop()
        assert pool.is_running is False


@pytest.mark.asyncio
async def test_worker_pool_safe_shutdown():
    """Verify that worker_pool.stop() cancels tasks and repeated stop calls are safe."""
    pool = DocumentWorkerPool.get_instance()
    await pool.start()
    assert pool.is_running is True

    # First stop
    await pool.stop()
    assert pool.is_running is False
    assert len(pool.worker_tasks) == 0
    assert pool.supervisor_task is None

    # Second stop (idempotent)
    await pool.stop()
    assert pool.is_running is False


@pytest.mark.asyncio
async def test_worker_pool_repeated_cycles_idempotent():
    """Verify multiple start/stop cycles succeed without task leakage or errors."""
    pool = DocumentWorkerPool.get_instance()
    for _ in range(3):
        await pool.start()
        assert pool.is_running is True
        assert len(pool.worker_tasks) == pool.concurrency

        await pool.stop()
        assert pool.is_running is False
        assert len(pool.worker_tasks) == 0


# ---------------------------------------------------------------------------
# 2. Port Management & Runner Unit Tests
# ---------------------------------------------------------------------------

def test_port_conflict_detection_free_port():
    """Verify that verify_port_available returns None when a port is free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]

    result = verify_port_available("127.0.0.1", free_port)
    assert result is None


def test_port_conflict_detection_occupied_port(monkeypatch):
    """Verify that verify_port_available identifies an occupied port from an external process."""
    monkeypatch.setattr(run_backend, "find_pid_on_port", lambda port: 99999)
    monkeypatch.setattr(run_backend, "get_process_command_line", lambda pid: "some_other_service.exe")

    result = verify_port_available("127.0.0.1", 8000)
    assert result is not None
    assert "Port 8000" in result
    assert "99999" in result


def test_is_admiextract_backend_detection(monkeypatch):
    """Verify process classification for AdmiExtract vs external apps."""
    monkeypatch.setattr(
        run_backend,
        "get_process_command_line",
        lambda pid: r"C:\Python312\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000",
    )
    assert is_admiextract_backend(12345) is True

    monkeypatch.setattr(
        run_backend,
        "get_process_command_line",
        lambda pid: r"D:\Projects\AdmiExtract-main\AdmiExtract\Backend\venv\Scripts\python.exe run_backend.py",
    )
    assert is_admiextract_backend(12346) is True

    monkeypatch.setattr(
        run_backend,
        "get_process_command_line",
        lambda pid: r"C:\Program Files\Apache\httpd.exe -k runservice",
    )
    assert is_admiextract_backend(12347) is False


# ---------------------------------------------------------------------------
# 3. Runner Behavior Tests (Port Free, Existing Backend, Restart, Unrelated)
# ---------------------------------------------------------------------------

def test_runner_port_free_launches_uvicorn(monkeypatch):
    """Test A: When port is free, runner launches Uvicorn."""
    monkeypatch.setattr(run_backend, "find_pid_on_port", lambda port: None)
    launched = []

    class MockCompletedProcess:
        returncode = 0

    def mock_subprocess_run(cmd, cwd=None, **kwargs):
        launched.append((cmd, cwd))
        return MockCompletedProcess()

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)

    exit_code = run(port=8999, reload=True, restart=False)
    assert exit_code == 0
    assert len(launched) == 1
    cmd, cwd = launched[0]
    assert "uvicorn" in " ".join(cmd)
    assert "app.main:app" in cmd
    assert "--port" in cmd
    assert "8999" in cmd


def test_runner_existing_backend_prints_banner_and_exits_zero(monkeypatch, capsys):
    """Test B: When AdmiExtract backend is already running, prints banner and exits 0 without second launch."""
    monkeypatch.setattr(run_backend, "find_pid_on_port", lambda port: 21780)
    monkeypatch.setattr(
        run_backend,
        "get_process_command_line",
        lambda pid: r"python -m uvicorn app.main:app --host 0.0.0.0 --port 8000",
    )

    launched = []
    monkeypatch.setattr("subprocess.run", lambda cmd, **kwargs: launched.append(cmd))

    exit_code = run(port=8000, reload=True, restart=False)
    assert exit_code == 0
    assert len(launched) == 0  # No second Uvicorn launched

    captured = capsys.readouterr()
    assert "AdmiExtract Backend Already Running" in captured.out
    assert "PID: 21780" in captured.out
    assert "Reusing the existing backend" in captured.out
    assert "No second Uvicorn instance will be started" in captured.out


def test_runner_restart_terminates_existing_and_restarts(monkeypatch, capsys):
    """Test C: When --restart is passed, safely terminates AdmiExtract backend and restarts."""
    killed_pids = []
    calls = {"find_count": 0}

    def fake_find(port):
        calls["find_count"] += 1
        # First 2 calls report PID 21780, after kill report None (freed)
        return 21780 if calls["find_count"] <= 2 else None

    monkeypatch.setattr(run_backend, "find_pid_on_port", fake_find)
    monkeypatch.setattr(
        run_backend,
        "get_process_command_line",
        lambda pid: r"python -m uvicorn app.main:app --host 0.0.0.0 --port 8000",
    )
    monkeypatch.setattr(run_backend, "kill_process_safely", lambda pid: killed_pids.append(pid) or True)

    launched = []

    class MockCompletedProcess:
        returncode = 0

    monkeypatch.setattr("subprocess.run", lambda cmd, **kwargs: launched.append(cmd) or MockCompletedProcess())

    exit_code = run(port=8000, reload=True, restart=True)
    assert exit_code == 0
    assert 21780 in killed_pids
    assert len(launched) == 1
    assert "app.main:app" in launched[0]

    captured = capsys.readouterr()
    assert "Terminating existing AdmiExtract backend" in captured.out
    assert "Port 8000 freed successfully" in captured.out


def test_runner_unrelated_process_refuses_to_start_or_kill(monkeypatch, capsys):
    """Test D: When an unrelated process owns the port, runner refuses to kill/start and exits 1."""
    monkeypatch.setattr(run_backend, "find_pid_on_port", lambda port: 99999)
    monkeypatch.setattr(
        run_backend,
        "get_process_command_line",
        lambda pid: r"C:\Windows\System32\svchost.exe -k netsvcs",
    )

    killed_pids = []
    monkeypatch.setattr(run_backend, "kill_process_safely", lambda pid: killed_pids.append(pid))
    launched = []
    monkeypatch.setattr("subprocess.run", lambda cmd, **kwargs: launched.append(cmd))

    # Normal start attempt
    exit_code_normal = run(port=8000, reload=True, restart=False)
    assert exit_code_normal == 1
    assert len(launched) == 0
    assert len(killed_pids) == 0

    # Restart attempt
    exit_code_restart = run(port=8000, reload=True, restart=True)
    assert exit_code_restart == 1
    assert len(launched) == 0
    assert len(killed_pids) == 0

    captured = capsys.readouterr()
    assert "occupied by an external application" in captured.out


def test_runner_status_check(monkeypatch, capsys):
    """Verify --status displays active backend details."""
    monkeypatch.setattr(run_backend, "find_pid_on_port", lambda port: 12345)
    monkeypatch.setattr(run_backend, "get_process_command_line", lambda pid: "python run_backend.py")

    exit_code = run(port=8000, status=True)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Backend is ACTIVE on port 8000 (PID: 12345)" in captured.out


# ---------------------------------------------------------------------------
# 4. API Health & Auth Login Verification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_backend_api_responds_normally():
    """Verify that root API endpoint responds with healthy/degraded status."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "app_name" in data
        assert data["app_name"] == "Automate API"


@pytest_asyncio.fixture
async def setup_test_auth_db():
    """Initialize test db and admin user for login verification."""
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

    from app.core.security import get_password_hash
    from app.models.user import UserRole
    test_user = User(
        name="Admin Test",
        email="admin@test.com",
        username="admintest",
        password=get_password_hash("SecretPassword123!"),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    await test_user.insert()

    yield

    await test_client.drop_database("automate_test_db")
    test_client.close()


@pytest.mark.asyncio
async def test_auth_login_endpoint(setup_test_auth_db):
    """Test G: Verify POST /auth/login returns status 200 with valid credentials."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/auth/login",
            data={"username": "admintest", "password": "SecretPassword123!"},
        )
        assert response.status_code == 200
        token_data = response.json()
        assert "access_token" in token_data
        assert token_data["token_type"] == "bearer"
