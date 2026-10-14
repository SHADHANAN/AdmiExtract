"""
Unit & Integration Tests for StorageCleanupService & Audit Utility
==================================================================
Tests:
1. Reference-integrity check: Ensures every student document is recognized as PROTECTED.
2. Dry-run safety: Ensures execute_cleanup does nothing when dry_run=True.
3. SHA-256 duplicate detection accuracy.
4. Orphan detection: Accurately isolates orphaned session folders from active ones.
"""

import os
import shutil
import pytest
from pathlib import Path
import pymongo
from app.core.config import settings
from app.services.cleanup_service import StorageCleanupService

backend_root = Path(__file__).resolve().parent.parent
uploads_dir = backend_root / "uploads"
sessions_dir = uploads_dir / "sessions"


@pytest.fixture(scope="module")
def setup_cleanup_test_environment():
    """Create isolated test fixtures for storage cleanup testing and clean up afterward."""
    uploads_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)

    client = pymongo.MongoClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]

    # 1. Create a real test protected student document
    prot_doc = uploads_dir / "test_cleanup_protected_doc.pdf"
    prot_doc.write_bytes(b"%PDF-1.4 test protected student document content")

    # 2. Create duplicate files for SHA-256 test
    dup1 = uploads_dir / "test_cleanup_dup1.pdf"
    dup2 = uploads_dir / "test_cleanup_dup2.pdf"
    dup_content = b"%PDF-1.4 identical duplicate content for sha256 grouping"
    dup1.write_bytes(dup_content)
    dup2.write_bytes(dup_content)

    # 3. Create active session on disk & DB
    active_session_id = "test_cleanup_active_session"
    active_session_dir = sessions_dir / active_session_id
    active_session_dir.mkdir(parents=True, exist_ok=True)
    (active_session_dir / "doc.pdf").write_bytes(b"%PDF-1.4 active session doc")

    # 4. Create orphan session on disk only (NOT in DB)
    orphan_session_id = "test_cleanup_orphan_session"
    orphan_session_dir = sessions_dir / orphan_session_id
    orphan_session_dir.mkdir(parents=True, exist_ok=True)
    (orphan_session_dir / "orphan.pdf").write_bytes(b"%PDF-1.4 orphan session doc")

    # Insert test student submission referencing prot_doc
    ins_sub = db["student_submissions"].insert_one({
        "batch_id": "batch_cleanup_test",
        "department_id": "AIML",
        "student_name": "Cleanup Test Student",
        "register_number": "CLEANUP_REG_01",
        "mobile_number": "9876543210",
        "submission_status": "Submitted",
        "documents": [
            {
                "document_name": "Protected Document",
                "status": "Uploaded",
                "file_path": str(prot_doc),
            }
        ],
    })

    # Insert active session in submission_sessions
    db["submission_sessions"].delete_many({"submission_id": active_session_id})
    db["submission_sessions"].insert_one({
        "submission_id": active_session_id,
        "batch_id": "batch_cleanup_test",
        "register_number": "CLEANUP_REG_01",
        "student_name": "Cleanup Test Student",
        "status": "READY_FOR_VERIFICATION",
    })

    svc = StorageCleanupService(
        mongo_uri=settings.MONGODB_URI,
        db_name=settings.DATABASE_NAME,
        backend_root=backend_root,
        dry_run=True,
    )
    plan = svc.generate_cleanup_plan()
    audit = svc.audit_storage()

    yield {
        "service": svc,
        "plan": plan,
        "audit": audit,
        "prot_doc": prot_doc,
        "dup1": dup1,
        "dup2": dup2,
        "active_session_id": active_session_id,
        "orphan_session_id": orphan_session_id,
    }

    # Teardown
    db["student_submissions"].delete_one({"_id": ins_sub.inserted_id})
    db["submission_sessions"].delete_many({"submission_id": active_session_id})
    client.close()

    for f in [prot_doc, dup1, dup2]:
        if f.exists():
            try:
                f.unlink()
            except Exception:
                pass

    for sdir in [active_session_dir, orphan_session_dir]:
        if sdir.exists():
            try:
                shutil.rmtree(sdir)
            except Exception:
                pass


def test_dry_run_safety(setup_cleanup_test_environment):
    """Verify execute_cleanup refuses to delete when dry_run=True."""
    env = setup_cleanup_test_environment
    svc = env["service"]
    plan = env["plan"]
    assert plan["protected_count"] > 0
    assert plan["cleanup_candidates_count"] >= 0

    res = svc.execute_cleanup(plan, confirm=False)
    assert res["executed"] is False
    assert res["deleted_files"] == 0
    assert res["freed_bytes"] == 0


def test_active_student_documents_are_protected(setup_cleanup_test_environment):
    """Verify that original student documents are 100% protected and never marked for deletion."""
    env = setup_cleanup_test_environment
    plan = env["plan"]
    protected_paths = {p["rel_path"].lower() for p in plan["protected_items"]}
    candidate_paths = {c["rel_path"].lower() for c in plan["cleanup_candidates"]}

    # The seeded active student doc must be protected
    prot_name = env["prot_doc"].name.lower()
    matching_prot = [p for p in protected_paths if prot_name in p]
    assert len(matching_prot) > 0, f"Critical student doc '{prot_name}' was NOT protected!"

    # Must NOT be in cleanup candidates
    matching_cand = [c for c in candidate_paths if prot_name == Path(c).name.lower()]
    assert len(matching_cand) == 0, f"Critical student doc '{prot_name}' was erroneously marked for cleanup!"


def test_active_sessions_are_not_orphaned(setup_cleanup_test_environment):
    """Verify that active submission sessions are excluded from orphaned session cleanup."""
    env = setup_cleanup_test_environment
    audit = env["audit"]
    active_sessions = set(audit["active_db_sessions"])
    orphaned_sessions = set(audit["orphaned_session_dirs"])

    # Active session must exist in active DB sessions
    assert env["active_session_id"] in active_sessions

    # Active session must NOT be in orphaned set
    assert env["active_session_id"] not in orphaned_sessions

    # Orphan session MUST be in orphaned set
    assert env["orphan_session_id"] in orphaned_sessions


def test_sha256_duplicate_detection(setup_cleanup_test_environment):
    """Verify that identical files are correctly grouped by SHA-256."""
    env = setup_cleanup_test_environment
    audit = env["audit"]
    duplicate_groups = audit["duplicate_groups"]
    assert len(duplicate_groups) > 0

    # Verify that each group actually shares the same hash
    for h, flist in list(duplicate_groups.items())[:5]:
        assert len(flist) > 1
        for f in flist:
            assert f["sha256"] == h
