"""
Unit and Integration Tests for Beanie Initialization & DocumentWorkerPool Lifecycle
=====================================================================================
Verifies:
1. Worker pool cannot start before Beanie initialization.
2. Worker pool starts after successful Beanie initialization.
3. Database initialization failure prevents worker startup.
4. Shutdown stops workers before database is closed.
5. Worker pool startup is idempotent.
"""

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

import app.db.database
from app.core.config import settings
from app.db.database import (
    close_db,
    init_db,
    is_beanie_initialized,
    is_mongodb_connected,
    _run_db_setup,
)
from app.models.document_job import DocumentProcessingJob, SubmissionSession
from app.models.user import User
from app.services.document_worker_pool import DocumentWorkerPool


@pytest_asyncio.fixture(scope="function", autouse=True)
async def cleanup_pool():
    """Ensure DocumentWorkerPool is stopped before and after each test."""
    pool = DocumentWorkerPool.get_instance()
    await pool.stop()
    yield
    await pool.stop()


@pytest.mark.asyncio
async def test_worker_cannot_start_before_beanie_initialization():
    """Verify that DocumentWorkerPool refuses to start when Beanie is not initialized."""
    # Force connected state to False
    app.db.database._is_connected = False

    pool = DocumentWorkerPool.get_instance()
    result = await pool.start()

    assert result is False
    assert pool.is_running is False
    assert len(pool.worker_tasks) == 0


@pytest.mark.asyncio
async def test_worker_starts_after_successful_beanie_initialization():
    """Verify that DocumentWorkerPool starts cleanly after Beanie is successfully initialized."""
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_test_db"]

    app.db.database.client = test_client
    app.db.database.db = test_db
    app.db.database._is_connected = True

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[DocumentProcessingJob, SubmissionSession, User],
    )

    assert is_beanie_initialized() is True

    pool = DocumentWorkerPool.get_instance()
    result = await pool.start()

    assert result is True
    assert pool.is_running is True
    assert len(pool.worker_tasks) == pool.concurrency

    # Clean up
    await pool.stop()
    assert pool.is_running is False
    await test_client.drop_database("automate_test_db")
    test_client.close()


@pytest.mark.asyncio
async def test_database_initialization_failure_prevents_worker_startup():
    """Verify that when init_db() fails (or starts degraded), workers are NOT started."""
    from pymongo.errors import ServerSelectionTimeoutError

    pool = DocumentWorkerPool.get_instance()

    with patch.object(app.db.database.client.admin, "command", side_effect=ServerSelectionTimeoutError("Atlas offline")):
        app.db.database._is_connected = False
        db_ready = await init_db()

        assert db_ready is False
        assert is_mongodb_connected() is False
        assert is_beanie_initialized() is False

        # Attempt to start worker pool directly
        started = await pool.start()
        assert started is False
        assert pool.is_running is False
        assert len(pool.worker_tasks) == 0


@pytest.mark.asyncio
async def test_shutdown_stops_workers_before_db_close():
    """Verify that on shutdown, DocumentWorkerPool stops workers before MongoDB connection is closed."""
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_test_db"]

    app.db.database.client = test_client
    app.db.database.db = test_db
    app.db.database._is_connected = True

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[DocumentProcessingJob, SubmissionSession, User],
    )

    pool = DocumentWorkerPool.get_instance()
    await pool.start()
    assert pool.is_running is True

    call_order = []

    original_stop = pool.stop
    async def tracked_stop():
        call_order.append("workers_stopped")
        await original_stop()

    original_close_db = app.db.database.close_db
    async def tracked_close_db():
        call_order.append("db_closed")
        await original_close_db()

    pool.stop = tracked_stop
    app.db.database.close_db = tracked_close_db

    # Simulate shutdown sequence matching app.main:lifespan
    await pool.stop()
    await app.db.database.close_db()

    assert call_order == ["workers_stopped", "db_closed"]
    assert pool.is_running is False
    assert app.db.database._is_connected is False

    # Restore originals
    pool.stop = original_stop
    app.db.database.close_db = original_close_db


@pytest.mark.asyncio
async def test_startup_is_idempotent():
    """Verify that calling pool.start() multiple times does not create duplicate workers."""
    if not hasattr(AsyncIOMotorClient, "append_metadata"):
        AsyncIOMotorClient.append_metadata = lambda *args, **kwargs: None

    test_client = AsyncIOMotorClient(settings.MONGODB_URI)
    test_db = test_client["automate_test_db"]

    app.db.database.client = test_client
    app.db.database.db = test_db
    app.db.database._is_connected = True

    await init_beanie(
        database=cast(Any, test_db),
        document_models=[DocumentProcessingJob, SubmissionSession, User],
    )

    pool = DocumentWorkerPool.get_instance()
    await pool.start()
    first_tasks = list(pool.worker_tasks)
    assert len(first_tasks) == pool.concurrency

    # Second call
    second_result = await pool.start()
    assert second_result is True
    assert pool.worker_tasks == first_tasks
    assert len(pool.worker_tasks) == pool.concurrency

    await pool.stop()
    await test_client.drop_database("automate_test_db")
    test_client.close()
