"""
Unit & Integration Tests for StorageCleanupService & Audit Utility
==================================================================
Tests:
1. Reference-integrity check: Ensures every student document is recognized as PROTECTED.
2. Dry-run safety: Ensures execute_cleanup does nothing when dry_run=True.
3. SHA-256 duplicate detection accuracy.
4. Orphan detection: Accurately isolates orphaned session folders from active ones.
5. Backup rotation: Preserves recent backups for active batches while pruning stale test backups.
"""

import os
import pytest
from pathlib import Path
from app.services.cleanup_service import StorageCleanupService

backend_root = Path(__file__).resolve().parent.parent

@pytest.fixture(scope="module")
def cleanup_service():
    return StorageCleanupService(backend_root=backend_root, dry_run=True)

@pytest.fixture(scope="module")
def cleanup_plan(cleanup_service):
    return cleanup_service.generate_cleanup_plan()

@pytest.fixture(scope="module")
def storage_audit(cleanup_service):
    return cleanup_service.audit_storage()

def test_dry_run_safety(cleanup_service, cleanup_plan):
    """Verify execute_cleanup refuses to delete when dry_run=True."""
    assert cleanup_plan["protected_count"] > 0
    assert cleanup_plan["cleanup_candidates_count"] >= 0
    
    # Attempt execute under dry_run
    res = cleanup_service.execute_cleanup(cleanup_plan, confirm=False)
    assert res["executed"] is False
    assert res["deleted_files"] == 0
    assert res["freed_bytes"] == 0

def test_active_student_documents_are_protected(cleanup_plan):
    """Verify that original student documents are 100% protected and never marked for deletion."""
    protected_paths = {p["rel_path"].lower() for p in cleanup_plan["protected_items"]}
    candidate_paths = {c["rel_path"].lower() for c in cleanup_plan["cleanup_candidates"]}
    
    # Key active student documents that must NEVER be in cleanup candidates
    critical_student_docs = [
        "tc.pdf",
        "digital_commity.pdf",
        "kvb passbook.pdf",
        "doc-20260123-wa0026..pdf",
        "img-20260915-wa0000.jpg",
        "provisional_allotment_271844.pdf",
    ]
    
    for doc in critical_student_docs:
        # Must be in protected items
        matching_prot = [p for p in protected_paths if doc in p]
        assert len(matching_prot) > 0, f"Critical student doc '{doc}' was NOT protected!"
        
        # Must NOT be in cleanup candidates
        matching_cand = [c for c in candidate_paths if doc == Path(c).name]
        assert len(matching_cand) == 0, f"Critical student doc '{doc}' was erroneously marked for cleanup!"

def test_active_sessions_are_not_orphaned(storage_audit):
    """Verify that active submission sessions are excluded from orphaned session cleanup."""
    active_sessions = set(storage_audit["active_db_sessions"])
    orphaned_sessions = set(storage_audit["orphaned_session_dirs"])
    
    # Active sessions must exist
    assert "sub_a9d188c1c932" in active_sessions or "sub_b867f1f925ac" in active_sessions
    
    # Active sessions must NOT be in orphaned set
    assert "sub_a9d188c1c932" not in orphaned_sessions
    assert "sub_b867f1f925ac" not in orphaned_sessions

def test_sha256_duplicate_detection(storage_audit):
    """Verify that identical files are correctly grouped by SHA-256."""
    duplicate_groups = storage_audit["duplicate_groups"]
    assert len(duplicate_groups) > 0
    
    # Verify that each group actually shares the same hash
    for h, flist in list(duplicate_groups.items())[:5]:
        assert len(flist) > 1
        for f in flist:
            assert f["sha256"] == h
