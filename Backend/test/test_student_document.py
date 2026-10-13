import os
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.models.user import User, UserRole
from app.models.student_document import StudentDocument, DocumentVersion, DocumentStatus
from app.models.audit_log import AuditLog
from app.services.student_document_service import StudentDocumentService


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod
    db_mod.client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=2000)
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest_asyncio.fixture
async def client_async():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_client():
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]
    yield db
    client.close()


@pytest.fixture
def doc_service():
    return StudentDocumentService()


@pytest.mark.asyncio
async def test_create_student_document(doc_service: StudentDocumentService, db_client):
    """1. Create StudentDocument record."""
    student_id = "test_stud_001"
    batch_id = "test_batch_001"

    # Pre-clean
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        class_id="sec_a",
        department_id="AIML",
    )

    assert doc.id is not None
    assert doc.student_id == student_id
    assert doc.document_type == "AADHAAR"
    assert doc.current_version == 1
    assert len(doc.versions) == 0
    assert doc.status == "UPLOADED"

    # Cleanup
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_version_1_creation_and_preservation(doc_service: StudentDocumentService):
    """2 & 4. Create version 1 and verify it persists."""
    student_id = "test_stud_v1"
    batch_id = "test_batch_001"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        document_type="SSLC",
        document_name="10th Marksheet",
        initial_file_path="/uploads/test_sslc_v1.pdf",
        original_filename="10th_marksheet.pdf",
        file_size_bytes=1024,
    )

    assert len(doc.versions) == 1
    v1 = doc.versions[0]
    assert v1.version_number == 1
    assert v1.is_active is True
    assert doc.active_version_id == v1.version_id
    assert doc.current_version == 1

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_version_2_activation_and_v1_preservation(doc_service: StudentDocumentService):
    """3, 4, 5, 6, 7. Add version 2, verify V1 remains, V2 becomes active, only one version is active, version increments."""
    student_id = "test_stud_v2"
    batch_id = "test_batch_001"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        document_type="COMMUNITY",
        document_name="Community Certificate",
        initial_file_path="/uploads/comm_v1.pdf",
        original_filename="comm_v1.pdf",
    )
    v1_id = doc.versions[0].version_id

    # Append Version 2
    updated_doc = await doc_service.add_new_version(
        student_document_id=str(doc.id),
        file_path="/uploads/comm_v2.pdf",
        original_filename="comm_v2.pdf",
        set_active=True,
    )

    # Assertions
    assert len(updated_doc.versions) == 2
    assert updated_doc.current_version == 2

    v1 = updated_doc.versions[0]
    v2 = updated_doc.versions[1]

    assert v1.version_number == 1
    assert v1.version_id == v1_id
    assert v1.is_active is False  # V1 is no longer active

    assert v2.version_number == 2
    assert v2.is_active is True  # V2 is now active
    assert updated_doc.active_version_id == v2.version_id

    # Exactly one version is active
    active_versions = [v for v in updated_doc.versions if v.is_active]
    assert len(active_versions) == 1
    assert active_versions[0].version_id == v2.version_id

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_invalid_version_coexists_with_valid_version(doc_service: StudentDocumentService):
    """8. Invalid version (V1) coexists with Valid version (V2)."""
    student_id = "test_stud_invalid_valid"
    batch_id = "test_batch_001"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    # V1 created as INVALID
    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        document_type="TRANSFER_CERTIFICATE",
        document_name="Transfer Certificate",
        initial_file_path="/uploads/tc_v1_blurry.pdf",
        original_filename="tc_v1.pdf",
        validation_status="INVALID",
        status_value="INVALID",
    )

    assert doc.versions[0].validation_status == "INVALID"

    # V2 uploaded as VALID
    updated_doc = await doc_service.add_new_version(
        student_document_id=str(doc.id),
        file_path="/uploads/tc_v2_clear.pdf",
        original_filename="tc_v2.pdf",
        validation_status="VALID",
        set_active=True,
    )

    assert len(updated_doc.versions) == 2
    assert updated_doc.versions[0].validation_status == "INVALID"
    assert updated_doc.versions[0].file_path == "/uploads/tc_v1_blurry.pdf"

    assert updated_doc.versions[1].validation_status == "VALID"
    assert updated_doc.versions[1].file_path == "/uploads/tc_v2_clear.pdf"
    assert updated_doc.active_version.validation_status == "VALID"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_old_version_cannot_be_overwritten(doc_service: StudentDocumentService):
    """9. Old version cannot be overwritten upon new version addition."""
    student_id = "test_stud_immutable"
    batch_id = "test_batch_001"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path="/uploads/aadhaar_v1_original.pdf",
        original_filename="aadhaar_v1.pdf",
    )
    v1_created_at = doc.versions[0].created_at
    v1_path = doc.versions[0].file_path

    # Add V2
    doc2 = await doc_service.add_new_version(
        student_document_id=str(doc.id),
        file_path="/uploads/aadhaar_v2_new.pdf",
        original_filename="aadhaar_v2.pdf",
    )

    # Add V3
    doc3 = await doc_service.add_new_version(
        student_document_id=str(doc.id),
        file_path="/uploads/aadhaar_v3_latest.pdf",
        original_filename="aadhaar_v3.pdf",
    )

    assert len(doc3.versions) == 3
    assert doc3.versions[0].version_number == 1
    assert doc3.versions[0].file_path == v1_path
    v1_stored = doc3.versions[0].created_at
    if v1_stored.tzinfo is None:
        v1_stored = v1_stored.replace(tzinfo=timezone.utc)
    if v1_created_at.tzinfo is None:
        v1_created_at = v1_created_at.replace(tzinfo=timezone.utc)
    assert abs((v1_stored - v1_created_at).total_seconds()) < 2.0
    assert doc3.versions[1].version_number == 2
    assert doc3.versions[2].version_number == 3

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_student_isolation(client_async: AsyncClient, doc_service: StudentDocumentService, db_client):
    """10. Student A cannot access Student B's documents (403 Forbidden)."""
    # Create Student A user
    user_a = await db_client["users"].find_one({"username": "test_stud_a"})
    if not user_a:
        res_a = await db_client["users"].insert_one({
            "username": "test_stud_a",
            "name": "Student A",
            "email": "student_a@test.com",
            "password": get_password_hash("pass123"),
            "role": UserRole.STUDENT.value,
            "register_number": "REG_STUD_A",
        })
        user_a_id = str(res_a.inserted_id)
    else:
        user_a_id = str(user_a["_id"])

    token_a = create_access_token(data={"sub": user_a_id, "role": UserRole.STUDENT.value})

    # Create Document for Student B
    doc_b = await doc_service.create_student_document(
        student_id="REG_STUD_B",
        batch_id="batch_b",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
    )

    try:
        # Student A attempts to access Student B's document
        res = await client_async.get(
            f"/student-documents/{doc_b.student_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert res.status_code == 403
    finally:
        await StudentDocument.find(StudentDocument.student_id == "REG_STUD_B").delete()


@pytest.mark.asyncio
async def test_department_isolation(client_async: AsyncClient, doc_service: StudentDocumentService, db_client):
    """13. Department Admin (CIVIL) cannot access AIML Student Document (403 Forbidden)."""
    # Create Civil Dept Admin user
    civil_admin = await db_client["users"].find_one({"username": "test_civil_doc_admin"})
    if not civil_admin:
        res_c = await db_client["users"].insert_one({
            "username": "test_civil_doc_admin",
            "name": "Civil Doc Admin",
            "email": "civil_doc_admin@test.com",
            "password": get_password_hash("pass123"),
            "role": UserRole.DEPARTMENT_ADMIN.value,
            "department_code": "CIVIL",
        })
        civil_admin_id = str(res_c.inserted_id)
    else:
        civil_admin_id = str(civil_admin["_id"])

    civil_token = create_access_token(
        data={"sub": civil_admin_id, "role": UserRole.DEPARTMENT_ADMIN.value}
    )

    # Create document under AIML department
    doc_aiml = await doc_service.create_student_document(
        student_id="REG_AIML_01",
        batch_id="batch_aiml",
        department_id="AIML",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
    )

    try:
        # Civil admin attempts to fetch AIML student's document
        res = await client_async.get(
            f"/student-documents/{doc_aiml.student_id}",
            headers={"Authorization": f"Bearer {civil_token}"},
        )
        assert res.status_code == 403
    finally:
        await StudentDocument.find(StudentDocument.student_id == "REG_AIML_01").delete()


@pytest.mark.asyncio
async def test_unauthorized_access_rejected(client_async: AsyncClient):
    """14. Unauthenticated request must return 401."""
    res = await client_async.get("/student-documents/any_student_id")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_audit_log_created_on_document_operations(doc_service: StudentDocumentService, db_client):
    """15. Audit log record is inserted on creation and version additions."""
    student_id = "test_audit_stud"
    batch_id = "batch_audit_01"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await db_client["audit_logs"].delete_many({"student_name": f"Student_{student_id}"})

    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id=batch_id,
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path="/uploads/test_audit.pdf",
    )

    audit_create = await db_client["audit_logs"].find_one({"submission_id": str(doc.id)})
    assert audit_create is not None
    assert audit_create["action"] == "CREATE_STUDENT_DOCUMENT"

    # Add version
    await doc_service.add_new_version(
        student_document_id=str(doc.id),
        file_path="/uploads/test_audit_v2.pdf",
        original_filename="test_audit_v2.pdf",
    )

    audits = await db_client["audit_logs"].find({"submission_id": str(doc.id)}).to_list(10)
    actions = [a["action"] for a in audits]
    assert "CREATE_STUDENT_DOCUMENT" in actions
    assert "ADD_DOCUMENT_VERSION" in actions

    # Cleanup
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()
    await db_client["audit_logs"].delete_many({"submission_id": str(doc.id)})


@pytest.mark.asyncio
async def test_api_post_new_version_lifecycle(client_async: AsyncClient, doc_service: StudentDocumentService, db_client):
    """16. API endpoint POST /student-documents/{id}/versions creates immutable V2 and sets it active."""
    admin_user = await db_client["users"].find_one({"username": "admin"})
    admin_id = str(admin_user["_id"]) if admin_user else "6aa1e3b0da8b07991d686499"
    admin_token = create_access_token(
        data={"sub": admin_id, "role": UserRole.SUPER_ADMIN.value}
    )

    student_id = "test_api_stud_01"
    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    # Create V1
    doc = await doc_service.create_student_document(
        student_id=student_id,
        batch_id="batch_test_01",
        document_type="AADHAAR",
        document_name="Aadhaar Card",
        initial_file_path="/uploads/api_aadhaar_v1.pdf",
        original_filename="aadhaar_v1.pdf",
    )

    try:
        # POST new version via API
        res = await client_async.post(
            f"/student-documents/{str(doc.id)}/versions",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "file_path": "/uploads/api_aadhaar_v2.pdf",
                "original_filename": "aadhaar_v2.pdf",
                "file_size_bytes": 2048,
                "mime_type": "application/pdf",
                "validation_status": "VALID",
                "set_active": True,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["current_version"] == 2
        assert len(data["versions"]) == 2
        assert data["active_version"]["version_number"] == 2
        assert data["active_version"]["file_path"] == "/uploads/api_aadhaar_v2.pdf"

        # GET versions endpoint
        res_v = await client_async.get(
            f"/student-documents/{str(doc.id)}/versions",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_v.status_code == 200
        v_list = res_v.json()
        assert len(v_list) == 2
        assert v_list[0]["version_number"] == 1
        assert v_list[1]["version_number"] == 2

    finally:
        await StudentDocument.find(StudentDocument.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_duplicate_student_document_prevention_and_version_progression(doc_service: StudentDocumentService):
    """
    PRODUCT RULE TEST (REPLACEMENT):
    1. First Aadhaar upload -> 1 StudentDocument, 1 version record.
    2. Aadhaar re-upload -> same StudentDocument ID, 1 version record replaced in-place.
    3. Third Aadhaar upload -> same StudentDocument ID, 1 version record replaced in-place.
    4. Upload different document (TC) -> second StudentDocument created for TC.
    5. Re-upload TC -> same StudentDocument for TC, replaced in-place.
    """
    student_id = "test_stud_dedup_01"
    batch_id = "batch_test_01"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    try:
        # 1. First Aadhaar upload
        doc1 = await doc_service.create_student_document(
            student_id=student_id,
            batch_id=batch_id,
            document_type="AADHAAR",
            document_name="Aadhaar Card",
            initial_file_path="/uploads/aadhaar_v1.pdf",
            original_filename="aadhaar_v1.pdf",
        )
        assert doc1.current_version == 1
        assert len(doc1.versions) == 1
        assert doc1.versions[0].original_filename == "aadhaar_v1.pdf"

        all_docs = await StudentDocument.find(StudentDocument.student_id == student_id).to_list()
        assert len(all_docs) == 1

        # 2. Re-upload Aadhaar (calling create_student_document with same student & document_type)
        doc2 = await doc_service.create_student_document(
            student_id=student_id,
            batch_id=batch_id,
            document_type="AADHAAR",
            document_name="Aadhaar Card",
            initial_file_path="/uploads/aadhaar_v2.pdf",
            original_filename="aadhaar_v2.pdf",
        )
        assert str(doc2.id) == str(doc1.id), "Must reuse the SAME StudentDocument record"
        assert doc2.current_version == 1
        assert len(doc2.versions) == 1, "Must NOT create a second DocumentVersion"
        assert doc2.versions[0].original_filename == "aadhaar_v2.pdf"
        assert doc2.versions[0].is_active is True

        all_docs = await StudentDocument.find(StudentDocument.student_id == student_id).to_list()
        assert len(all_docs) == 1, "Must NOT create duplicate StudentDocument in database"

        # 3. Third Aadhaar upload
        doc3 = await doc_service.create_student_document(
            student_id=student_id,
            batch_id=batch_id,
            document_type="Aadhaar Card",  # Testing case / alias variations
            document_name="Aadhaar Card",
            initial_file_path="/uploads/aadhaar_v3.pdf",
            original_filename="aadhaar_v3.pdf",
        )
        assert str(doc3.id) == str(doc1.id)
        assert len(doc3.versions) == 1
        assert doc3.versions[0].original_filename == "aadhaar_v3.pdf"

        all_docs = await StudentDocument.find(StudentDocument.student_id == student_id).to_list()
        assert len(all_docs) == 1

        # 4. Upload different document (TC)
        tc1 = await doc_service.create_student_document(
            student_id=student_id,
            batch_id=batch_id,
            document_type="TRANSFER_CERTIFICATE",
            document_name="Transfer Certificate",
            initial_file_path="/uploads/tc_v1.pdf",
            original_filename="tc_v1.pdf",
        )
        assert str(tc1.id) != str(doc1.id)
        assert tc1.document_type == "TRANSFER_CERTIFICATE"
        assert tc1.current_version == 1
        assert len(tc1.versions) == 1

        all_docs = await StudentDocument.find(StudentDocument.student_id == student_id).to_list()
        assert len(all_docs) == 2, "Expected exactly 2 logical documents (Aadhaar and TC)"

        # 5. Re-upload TC
        tc2 = await doc_service.create_student_document(
            student_id=student_id,
            batch_id=batch_id,
            document_type="TRANSFER_CERTIFICATE",
            document_name="Transfer Certificate",
            initial_file_path="/uploads/tc_v2.pdf",
            original_filename="tc_v2.pdf",
        )
        assert str(tc2.id) == str(tc1.id)
        assert tc2.current_version == 1
        assert len(tc2.versions) == 1
        assert tc2.versions[0].original_filename == "tc_v2.pdf"

        all_docs = await StudentDocument.find(StudentDocument.student_id == student_id).to_list()
        assert len(all_docs) == 2

    finally:
        await StudentDocument.find(StudentDocument.student_id == student_id).delete()


@pytest.mark.asyncio
async def test_safe_consolidation_of_legacy_duplicate_documents(doc_service: StudentDocumentService):
    """
    Simulate legacy duplicate StudentDocument records in database:
    Doc A: Aadhaar Card, versions 1..11
    Doc B: Aadhaar Card, version 1
    Verify consolidation merges them into 1 Document with 12 versions, v12 active.
    """
    student_id = "test_stud_legacy_dup_01"
    batch_id = "batch_test_01"

    await StudentDocument.find(StudentDocument.student_id == student_id).delete()

    try:
        # Create legacy duplicate Doc A with 11 versions manually in DB
        versions_a = [
            DocumentVersion(
                version_id=f"v_a_{i}",
                version_number=i,
                file_path=f"/uploads/aadhaar_v{i}.pdf",
                original_filename=f"aadhaar_v{i}.pdf",
                is_active=(i == 11),
            )
            for i in range(1, 12)
        ]
        doc_a = StudentDocument(
            student_id=student_id,
            batch_id=batch_id,
            document_type="AADHAAR",
            document_name="Aadhaar Card",
            current_version=11,
            active_version_id="v_a_11",
            versions=versions_a,
        )
        await doc_a.insert()

        # Create legacy duplicate Doc B with 1 version
        versions_b = [
            DocumentVersion(
                version_id="v_b_1",
                version_number=1,
                file_path="/uploads/aadhaar_reupload_b.pdf",
                original_filename="aadhaar_reupload_b.pdf",
                is_active=True,
            )
        ]
        doc_b = StudentDocument(
            student_id=student_id,
            batch_id=batch_id,
            document_type="AADHAAR",
            document_name="Aadhaar Card",
            current_version=1,
            active_version_id="v_b_1",
            versions=versions_b,
        )
        await doc_b.insert()

        # Verify initial duplicate count
        initial_docs = await StudentDocument.find(StudentDocument.student_id == student_id).to_list()
        assert len(initial_docs) == 2

        # Run consolidation
        merged_count = await doc_service.consolidate_duplicate_documents(student_id)
        assert merged_count == 1

        # Verify only ONE document remains
        consolidated_docs = await StudentDocument.find(StudentDocument.student_id == student_id).to_list()
        assert len(consolidated_docs) == 1
        final_doc = consolidated_docs[0]
        assert final_doc.document_type == "AADHAAR"
        assert len(final_doc.versions) == 1, "Consolidation enforces single document version under replace model"
        assert final_doc.current_version == 1
        assert final_doc.active_version is not None
        assert final_doc.active_version.original_filename == "aadhaar_reupload_b.pdf"
        assert final_doc.active_version.is_active is True

    finally:
        await StudentDocument.find(StudentDocument.student_id == student_id).delete()
