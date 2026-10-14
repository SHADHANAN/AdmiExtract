import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.main import app
from app.models.batch import AdmissionBatch
from app.models.student_submission import StudentSubmission
from app.models.user import User, UserRole
from app.schemas.user import UserCreate
from app.services.user_service import UserService, UserAlreadyExistsException


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod

    db_mod.client = AsyncIOMotorClient(
        settings.MONGODB_URI, serverSelectionTimeoutMS=2000
    )
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()

    # Clean up test-specific data before and after
    test_prefixes = ["UNIQ_BATCH_", "CONCURRENT_BATCH_"]
    for p in test_prefixes:
        await AdmissionBatch.find({"_id": {"$regex": f"^{p}"}}).delete()
    await StudentSubmission.find({"register_number": {"$regex": "^(REG_UNIQ_|CONCURRENT_REG_|STU_USER_)"}}).delete()
    await User.find({"register_number": {"$regex": "^(STU_USER_)"}}).delete()


@pytest.mark.asyncio
async def test_cross_batch_duplicate_rejected():
    """
    Test 1: Creating two students with the same Register Number in different batches is rejected.
    - Student A is created in Batch 1.
    - Student B attempts to register with the same Register Number in Batch 2.
    - Rejected with HTTP 409 Conflict and privacy-safe message (no private info disclosed).
    """
    batch1_id = "UNIQ_BATCH_01"
    batch2_id = "UNIQ_BATCH_02"
    reg_number = "REG_UNIQ_001"

    # Seed batches
    await AdmissionBatch(id=batch1_id, name="Batch 1", department_id="AIML", academic_year="2025-2026", created_by="system").insert()
    await AdmissionBatch(id=batch2_id, name="Batch 2", department_id="CSE", academic_year="2025-2026", created_by="system").insert()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Create first student in Batch 1
        res1 = await client.post(
            "/student-submissions",
            json={
                "batch_id": batch1_id,
                "student_name": "Student Alpha",
                "register_number": reg_number,
                "mobile_number": "9876543210",
                "email": "alpha@example.com",
            },
        )
        assert res1.status_code == 201, f"Expected 201, got {res1.status_code}: {res1.text}"

        # 2. Attempt to create another student in Batch 2 with same register number
        res2 = await client.post(
            "/student-submissions",
            json={
                "batch_id": batch2_id,
                "student_name": "Student Beta",
                "register_number": reg_number,
                "mobile_number": "9876543211",
                "email": "beta@example.com",
            },
        )
        assert res2.status_code == 409, f"Expected 409 Conflict, got {res2.status_code}: {res2.text}"
        error_detail = res2.json()["detail"]
        assert "already assigned" in error_detail.lower()
        # Ensure error message does not disclose Student Alpha's name or Batch 1
        assert "Student Alpha" not in error_detail
        assert batch1_id not in error_detail


@pytest.mark.asyncio
async def test_same_batch_duplicate_different_name_rejected():
    """
    Test 2: Creating two students with the same Register Number in the same batch with different names is rejected.
    """
    batch_id = "UNIQ_BATCH_03"
    reg_number = "REG_UNIQ_002"

    await AdmissionBatch(id=batch_id, name="Batch 3", department_id="ECE", academic_year="2025-2026", created_by="system").insert()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create student with Name Alice
        res1 = await client.post(
            "/student-submissions",
            json={
                "batch_id": batch_id,
                "student_name": "Alice Smith",
                "register_number": reg_number,
                "mobile_number": "9876543210",
            },
        )
        assert res1.status_code == 201

        # Attempt to create different student with Name Bob with same register number
        res2 = await client.post(
            "/student-submissions",
            json={
                "batch_id": batch_id,
                "student_name": "Bob Jones",
                "register_number": reg_number,
                "mobile_number": "9876543212",
            },
        )
        assert res2.status_code == 409
        assert "already assigned" in res2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_case_and_whitespace_variations_detected():
    """
    Test 3: Case variations and whitespace variations of the same Register Number are detected as duplicates.
    e.g. 'REG_UNIQ_003', '  reg_uniq_003  ', 'REG _ UNIQ _ 003'
    """
    batch1_id = "UNIQ_BATCH_04"
    batch2_id = "UNIQ_BATCH_05"

    await AdmissionBatch(id=batch1_id, name="Batch 4", department_id="AIML", academic_year="2025-2026", created_by="system").insert()
    await AdmissionBatch(id=batch2_id, name="Batch 5", department_id="CSE", academic_year="2025-2026", created_by="system").insert()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Register initial student
        res1 = await client.post(
            "/student-submissions",
            json={
                "batch_id": batch1_id,
                "student_name": "John Doe",
                "register_number": "REG_UNIQ_003",
                "mobile_number": "9876543210",
            },
        )
        assert res1.status_code == 201

        # Variation 1: Lowercase with leading & trailing whitespace in Batch 2
        res2 = await client.post(
            "/student-submissions",
            json={
                "batch_id": batch2_id,
                "student_name": "Jane Doe",
                "register_number": "   reg_uniq_003   ",
                "mobile_number": "9876543215",
            },
        )
        assert res2.status_code == 409
        assert "already assigned" in res2.json()["detail"].lower()

        # Variation 2: Whitespace inside in Batch 2
        res3 = await client.post(
            "/student-submissions",
            json={
                "batch_id": batch2_id,
                "student_name": "Another Student",
                "register_number": "REG _ UNIQ _ 003",
                "mobile_number": "9876543216",
            },
        )
        assert res3.status_code == 409
        assert "already assigned" in res3.json()["detail"].lower()


@pytest.mark.asyncio
async def test_user_register_number_duplicate_rejected():
    """
    Test 4: Updating or creating a user with a Register Number already in use is rejected.
    """
    user_service = UserService()

    # Create User 1
    u1 = await user_service.create_user(
        UserCreate(
            username="stu_user_1",
            name="Student One",
            email="stu1@example.com",
            password="Password123!",
            role=UserRole.STUDENT,
            register_number="STU_USER_01",
        )
    )
    assert u1.register_number == "STU_USER_01"

    # Attempt to create User 2 with same register number (different casing/whitespace)
    with pytest.raises(UserAlreadyExistsException) as excinfo:
        await user_service.create_user(
            UserCreate(
                username="stu_user_2",
                name="Student Two",
                email="stu2@example.com",
                password="Password123!",
                role=UserRole.STUDENT,
                register_number="  stu_user_01  ",
            )
        )
    assert "already assigned" in str(excinfo.value).lower()

    # Create User 3 with unique register number
    u3 = await user_service.create_user(
        UserCreate(
            username="stu_user_3",
            name="Student Three",
            email="stu3@example.com",
            password="Password123!",
            role=UserRole.STUDENT,
            register_number="STU_USER_03",
        )
    )

    # Attempt to update User 3's register number to User 1's register number
    with pytest.raises(UserAlreadyExistsException) as update_exc:
        await user_service.update_user(u3.id, {"register_number": "stu_user_01"})
    assert "already assigned" in str(update_exc.value).lower()


@pytest.mark.asyncio
async def test_concurrent_registrations_handled_safely():
    """
    Test 5: Concurrent registration attempts result in exactly one successful record and 409 for the rest.
    Tests database-level unique index enforcement and application conflict handling.
    """
    batch1_id = "CONCURRENT_BATCH_01"
    batch2_id = "CONCURRENT_BATCH_02"
    shared_reg = "CONCURRENT_REG_999"

    await AdmissionBatch(id=batch1_id, name="Concurrent Batch 1", department_id="AIML", academic_year="2025-2026", created_by="system").insert()
    await AdmissionBatch(id=batch2_id, name="Concurrent Batch 2", department_id="CSE", academic_year="2025-2026", created_by="system").insert()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Fire 6 simultaneous creation requests across both batches
        requests = [
            client.post(
                "/student-submissions",
                json={
                    "batch_id": batch1_id if i % 2 == 0 else batch2_id,
                    "student_name": f"Concurrent Candidate {i}",
                    "register_number": shared_reg,
                    "mobile_number": f"98765432{i:02d}",
                },
            )
            for i in range(6)
        ]

        responses = await asyncio.gather(*requests)
        status_codes = [r.status_code for r in responses]

        # Exactly 1 request should succeed (201 Created)
        assert status_codes.count(201) == 1, f"Expected exactly one 201, got: {status_codes}"
        # All remaining 5 requests should be safely rejected with 409 Conflict
        assert status_codes.count(409) == 5, f"Expected five 409 Conflicts, got: {status_codes}"
        # Ensure zero 500 server errors
        assert 500 not in status_codes


@pytest.mark.asyncio
async def test_same_student_update_and_flow_continues_to_work():
    """
    Test 6: Legitimate updates by the same student for their own register number succeed seamlessly.
    """
    batch_id = "UNIQ_BATCH_06"
    reg_number = "REG_UNIQ_004"

    await AdmissionBatch(id=batch_id, name="Batch 6", department_id="AIML", academic_year="2025-2026", created_by="system").insert()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Initial submission
        res1 = await client.post(
            "/student-submissions",
            json={
                "batch_id": batch_id,
                "student_name": "David Miller",
                "register_number": reg_number,
                "mobile_number": "9876543210",
                "email": "david@example.com",
            },
        )
        assert res1.status_code == 201
        sub_id = res1.json()["id"]

        # Legitimate update (updating mobile number / email for same student in same batch)
        res2 = await client.post(
            "/student-submissions",
            json={
                "batch_id": batch_id,
                "student_name": "David Miller",
                "register_number": reg_number,
                "mobile_number": "9999988888",
                "email": "david.new@example.com",
            },
        )
        assert res2.status_code == 201
        assert res2.json()["id"] == sub_id
        assert res2.json()["mobile_number"] == "9999988888"
        assert res2.json()["email"] == "david.new@example.com"
