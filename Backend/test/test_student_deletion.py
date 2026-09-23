import os
import pytest
import pytest_asyncio
from pathlib import Path
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from app.core.security import create_access_token, get_password_hash
from app.models.user import UserRole


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(base_url="http://127.0.0.1:8000") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_client():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["admiextract"]
    yield db
    client.close()


@pytest.mark.asyncio
async def test_student_deletion_unauthenticated(client_async: AsyncClient):
    """Unauthenticated request must return 401."""
    res = await client_async.delete("/student-submissions/6aa519c1b75402822fce8f97")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_student_deletion_student_role_forbidden(client_async: AsyncClient, db_client):
    """Students cannot delete records (must return 403)."""
    # Ensure a real student user exists in database
    student_user = await db_client["users"].find_one({"username": "test_student_deleter"})
    if not student_user:
        res_ins = await db_client["users"].insert_one({
            "username": "test_student_deleter",
            "name": "Test Student",
            "email": "student_deleter@test.com",
            "password": get_password_hash("student123"),
            "role": UserRole.STUDENT.value,
        })
        student_id = str(res_ins.inserted_id)
    else:
        student_id = str(student_user["_id"])

    student_token = create_access_token(
        data={"sub": student_id, "role": UserRole.STUDENT.value}
    )
    res = await client_async.delete(
        "/student-submissions/6aa519c1b75402822fce8f97",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_student_deletion_cross_department_forbidden(client_async: AsyncClient, db_client):
    """Department Admin from CIVIL cannot delete AIML department student (403)."""
    # 1. Create or get department admin for CIVIL
    dept_user = await db_client["users"].find_one({"username": "test_civil_admin"})
    if not dept_user:
        res_ins = await db_client["users"].insert_one({
            "username": "test_civil_admin",
            "name": "Civil Admin",
            "email": "civil_admin@test.com",
            "password": get_password_hash("admin123"),
            "role": UserRole.DEPARTMENT_ADMIN.value,
            "department_code": "CIVIL",
        })
        dept_user_id = str(res_ins.inserted_id)
    else:
        dept_user_id = str(dept_user["_id"])

    other_dept_token = create_access_token(
        data={"sub": dept_user_id, "role": UserRole.DEPARTMENT_ADMIN.value}
    )

    # 2. Create student in AIML department
    ins_sub = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_b988676d",
        "department_id": "AIML",
        "student_name": "AIML Student",
        "register_number": "AIML_REG_123",
        "mobile_number": "9876543210",
        "submission_status": "Submitted",
        "documents": [],
    })
    sub_id = str(ins_sub.inserted_id)

    try:
        res = await client_async.delete(
            f"/student-submissions/{sub_id}",
            headers={"Authorization": f"Bearer {other_dept_token}"},
        )
        assert res.status_code == 403
        assert "Forbidden" in res.json().get("detail", "")
    finally:
        await db_client["student_submissions"].delete_one({"_id": ObjectId(sub_id)})


@pytest.mark.asyncio
async def test_student_deletion_not_found(client_async: AsyncClient):
    """Non-existent student submission must return 404."""
    admin_token = create_access_token(
        data={"sub": "6aa1e3b0da8b07991d686499", "role": UserRole.SUPER_ADMIN.value}
    )
    res = await client_async.delete(
        "/student-submissions/000000000000000000000000",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_student_deletion_active_processing_blocked(client_async: AsyncClient, db_client):
    """Deletion must be blocked if student is actively processing."""
    admin_token = create_access_token(
        data={"sub": "6aa1e3b0da8b07991d686499", "role": UserRole.SUPER_ADMIN.value}
    )

    # 1. Create a test submission with "AI Processing" status directly in DB
    ins_res = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_b988676d",
        "department_id": "AIML",
        "student_name": "Active Processing Student",
        "register_number": "ACTIVE_REG_999",
        "mobile_number": "9999999999",
        "submission_status": "AI Processing",
        "documents": [],
    })
    sub_id = str(ins_res.inserted_id)

    try:
        # Attempt deletion while active
        res = await client_async.delete(
            f"/student-submissions/{sub_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 400
        assert "currently active" in res.json().get("detail", "").lower()
    finally:
        await db_client["student_submissions"].delete_one({"_id": ObjectId(sub_id)})


@pytest.mark.asyncio
async def test_student_deletion_full_lifecycle_and_file_safety(client_async: AsyncClient, db_client):
    """
    Test full lifecycle:
      - Create dummy test physical files: one unique, one shared with another submission.
      - Create test submission A referencing both.
      - Create test submission B referencing the shared file.
      - Delete submission A.
      - Verify:
          1. Submission A is deleted from MongoDB.
          2. Submission B is intact.
          3. Shared file is PRESERVED on disk.
          4. Unique file is DELETED from disk.
          5. AuditLog record is inserted with accurate counts.
    """
    admin_token = create_access_token(
        data={"sub": "6aa1e3b0da8b07991d686499", "role": UserRole.SUPER_ADMIN.value}
    )

    backend_root = Path(__file__).resolve().parent.parent
    uploads_dir = backend_root / "uploads"
    test_unique_file = uploads_dir / "test_unique_del_doc.pdf"
    test_shared_file = uploads_dir / "test_shared_del_doc.pdf"

    test_unique_file.write_bytes(b"%PDF-1.4 unique test file content")
    test_shared_file.write_bytes(b"%PDF-1.4 shared test file content")

    # Create submission A in DB
    ins_a = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_b988676d",
        "department_id": "AIML",
        "student_name": "Student To Delete",
        "register_number": "DEL_TEST_A",
        "mobile_number": "9876543210",
        "submission_status": "Submitted",
        "documents": [
            {
                "document_name": "Unique Document",
                "status": "Uploaded",
                "file_path": str(test_unique_file),
            },
            {
                "document_name": "Shared Document",
                "status": "Uploaded",
                "file_path": str(test_shared_file),
            },
        ],
    })
    sub_a_id = ins_a.inserted_id

    # Create submission B referencing the shared file
    ins_b = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_b988676d",
        "department_id": "AIML",
        "student_name": "Student Keeper",
        "register_number": "DEL_TEST_B",
        "mobile_number": "9876543211",
        "submission_status": "Submitted",
        "documents": [
            {
                "document_name": "Shared Document",
                "status": "Uploaded",
                "file_path": str(test_shared_file),
            },
        ],
    })
    sub_b_id = ins_b.inserted_id

    # Create a dummy processing job and session for student A
    await db_client["submission_sessions"].insert_one({
        "submission_id": "sub_test_del_session",
        "batch_id": "batch_b988676d",
        "register_number": "DEL_TEST_A",
        "student_name": "Student To Delete",
        "status": "READY_FOR_VERIFICATION",
    })

    await db_client["document_processing_jobs"].insert_one({
        "job_id": "job_test_del_1",
        "submission_id": "sub_test_del_session",
        "document_id": "doc_1",
        "document_name": "Unique Document",
        "file_path": str(test_unique_file),
        "status": "COMPLETED",
    })

    try:
        # Perform deletion of Student A
        res = await client_async.delete(
            f"/student-submissions/{str(sub_a_id)}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") is True
        assert data.get("student_name") == "Student To Delete"

        # 1. Verify Student A is deleted from MongoDB
        deleted_check = await db_client["student_submissions"].find_one({"_id": sub_a_id})
        assert deleted_check is None

        # 2. Verify Student B still exists
        keeper_check = await db_client["student_submissions"].find_one({"_id": sub_b_id})
        assert keeper_check is not None

        # 3. Verify unique file was safely deleted
        assert not test_unique_file.exists()

        # 4. Verify shared file was PRESERVED
        assert test_shared_file.exists()

        # 5. Verify linked session and job were deleted
        assert await db_client["submission_sessions"].find_one({"submission_id": "sub_test_del_session"}) is None
        assert await db_client["document_processing_jobs"].find_one({"job_id": "job_test_del_1"}) is None

        # 6. Verify AuditLog was recorded
        audit = await db_client["audit_logs"].find_one({"submission_id": str(sub_a_id)})
        assert audit is not None
        assert audit["action"] == "DELETE_STUDENT"
        assert audit["actor_username"] == "admin"
        assert audit["student_name"] == "Student To Delete"
        assert audit["result"] == "SUCCESS"
        assert audit["files_deleted_count"] >= 1
        assert audit["files_preserved_count"] >= 1

    finally:
        # Cleanup any remaining files or docs
        await db_client["student_submissions"].delete_one({"_id": sub_b_id})
        if test_unique_file.exists():
            try:
                os.remove(test_unique_file)
            except Exception:
                pass
        if test_shared_file.exists():
            try:
                os.remove(test_shared_file)
            except Exception:
                pass
        await db_client["audit_logs"].delete_many({"submission_id": str(sub_a_id)})


@pytest.mark.asyncio
async def test_student_deletion_section_isolation(client_async: AsyncClient, db_client):
    """
    Test section isolation:
      - Student A in Section A (class_id="sec_a")
      - Student B in Section B (class_id="sec_b")
      - Deleting Student A must NEVER delete or mutate Student B.
    """
    admin_token = create_access_token(
        data={"sub": "6aa1e3b0da8b07991d686499", "role": UserRole.SUPER_ADMIN.value}
    )

    ins_a = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_b988676d",
        "department_id": "AIML",
        "class_id": "sec_a",
        "class_name": "A",
        "student_name": "Student In Section A",
        "register_number": "SEC_A_REG_101",
        "mobile_number": "9876543201",
        "submission_status": "Submitted",
        "documents": [],
    })
    sub_a_id = ins_a.inserted_id

    ins_b = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_b988676d",
        "department_id": "AIML",
        "class_id": "sec_b",
        "class_name": "B",
        "student_name": "Student In Section B",
        "register_number": "SEC_B_REG_202",
        "mobile_number": "9876543202",
        "submission_status": "Submitted",
        "documents": [],
    })
    sub_b_id = ins_b.inserted_id

    try:
        # Delete Student A
        res = await client_async.delete(
            f"/student-submissions/{str(sub_a_id)}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200

        # Student A is deleted
        check_a = await db_client["student_submissions"].find_one({"_id": sub_a_id})
        assert check_a is None

        # Student B is untouched
        check_b = await db_client["student_submissions"].find_one({"_id": sub_b_id})
        assert check_b is not None
        assert check_b["class_id"] == "sec_b"
        assert check_b["register_number"] == "SEC_B_REG_202"

        # Audit log contains class_id "sec_a"
        audit = await db_client["audit_logs"].find_one({"submission_id": str(sub_a_id)})
        assert audit is not None
        assert audit["class_id"] == "sec_a"
    finally:
        await db_client["student_submissions"].delete_one({"_id": sub_a_id})
        await db_client["student_submissions"].delete_one({"_id": sub_b_id})
        await db_client["audit_logs"].delete_many({"submission_id": str(sub_a_id)})


def test_gemini_targeted_cache_invalidation():
    """
    Test that invalidating cache for student A's document hashes
    removes ONLY student A's cache entries and preserves student B's cache entries.
    """
    from app.services.gemini_service import GeminiService
    service = GeminiService()

    hash_a = "abc12345hasha"
    hash_b = "xyz98765hashb"

    with service._cache_lock:
        service._response_cache[f"{hash_a}_EXTRACT_AADHAAR"] = {"data": "student_a_aadhaar"}
        service._response_cache[f"{hash_a}_EXTRACT_MARKS"] = {"data": "student_a_marks"}
        service._response_cache[f"{hash_b}_EXTRACT_AADHAAR"] = {"data": "student_b_aadhaar"}

    # Invalidate only hash_a
    evicted = service.invalidate_cache_for_hashes([hash_a])
    assert evicted == 2

    with service._cache_lock:
        # hash_a entries are evicted
        assert f"{hash_a}_EXTRACT_AADHAAR" not in service._response_cache
        assert f"{hash_a}_EXTRACT_MARKS" not in service._response_cache
        # hash_b entry is strictly PRESERVED
        assert f"{hash_b}_EXTRACT_AADHAAR" in service._response_cache


@pytest.mark.asyncio
async def test_student_deletion_cross_batch_rejected(client_async: AsyncClient, db_client):
    """Attempting to delete a student with mismatched batch_id must return 400 Bad Request."""
    admin_token = create_access_token(
        data={"sub": "6aa1e3b0da8b07991d686499", "role": UserRole.SUPER_ADMIN.value}
    )

    ins = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_real_123",
        "department_id": "AIML",
        "student_name": "Batch Test Student",
        "register_number": "BATCH_MISMATCH_01",
        "mobile_number": "9876543210",
        "submission_status": "Submitted",
        "documents": [],
    })
    sub_id = str(ins.inserted_id)

    try:
        # Pass mismatched batch_id
        res = await client_async.delete(
            f"/student-submissions/{sub_id}?batch_id=batch_other_999",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 400
        assert "Cross-batch deletion rejected" in res.json().get("detail", "")

        # Pass correct batch_id
        res_ok = await client_async.delete(
            f"/student-submissions/{sub_id}?batch_id=batch_real_123",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_ok.status_code == 200
    finally:
        await db_client["student_submissions"].delete_one({"_id": ObjectId(sub_id)})


@pytest.mark.asyncio
async def test_student_deletion_cross_section_rejected(client_async: AsyncClient, db_client):
    """Attempting to delete a student with mismatched class_id must return 400 Bad Request."""
    admin_token = create_access_token(
        data={"sub": "6aa1e3b0da8b07991d686499", "role": UserRole.SUPER_ADMIN.value}
    )

    ins = await db_client["student_submissions"].insert_one({
        "batch_id": "batch_real_123",
        "department_id": "AIML",
        "class_id": "section_a_id",
        "class_name": "Section A",
        "student_name": "Section Test Student",
        "register_number": "SEC_MISMATCH_01",
        "mobile_number": "9876543210",
        "submission_status": "Submitted",
        "documents": [],
    })
    sub_id = str(ins.inserted_id)

    try:
        # Pass mismatched section
        res = await client_async.delete(
            f"/student-submissions/{sub_id}?class_id=section_b_id",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 400
        assert "Cross-section deletion rejected" in res.json().get("detail", "")

        # Pass correct section
        res_ok = await client_async.delete(
            f"/student-submissions/{sub_id}?class_id=section_a_id",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_ok.status_code == 200
    finally:
        await db_client["student_submissions"].delete_one({"_id": ObjectId(sub_id)})
