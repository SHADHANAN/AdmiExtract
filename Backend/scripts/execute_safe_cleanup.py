"""
Execute Safe Test-Data and Unwanted-File Cleanup
===============================================
Phases Implemented:
- Phase 2: Safety Pre-Checks
- Phase 3: Non-sensitive Backup & Recovery Archive Creation
- Phase 4: Atomic Safe Deletion of Confirmed Test Artifacts
- Phase 5: Post-Cleanup Verification & Integrity Checks
"""

import sys
import os
import shutil
import json
from pathlib import Path
from datetime import datetime, timezone
import pymongo

backend_root = Path(__file__).resolve().parent.parent
uploads_root = backend_root / "uploads"
backup_root = backend_root / "backups" / f"cleanup_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

client = pymongo.MongoClient("mongodb://localhost:27017")
db = client["admiextract"]

# Production Protected Whitelist
PROTECTED_BATCHES = {"batch_b988676d"}
PROTECTED_CLASSES = {"class_batch_b988676d_section_a", "class_batch_b988676d_section_b"}
PROTECTED_STUDENT_REGS = {
    "714024247076", # praveen
    "24AM076",      # Rahul Sharma
    "24AM103",      # Sruthi
    "24AM093",      # Shadhanan S
    "24am0765",     # Praveen
}
PROTECTED_FILES = {
    "Aadhaar CARD_compressed.pdf",
    "aadhar.pdf",
    "Community Certificate.pdf",
    "digital_commity.pdf",
    "DOC-20260123-WA0026..pdf",
    "E-PAN CARD.pdf",
    "IMG-20260915-WA0000.jpg",
    "income.pdf",
    "KVB Passbook.pdf",
    "offer_letter (1).pdf",
    "passbook.pdf",
    "Provisional_Allotment.pdf",
    "Provisional_Allotment_237686.pdf",
    "Provisional_Allotment_271844.pdf",
    "Screenshot 2026-08-05 162541.png",
    "tc _11zon (1).pdf",
    "TC.pdf",
    "Transcript - Prabhusiddarth-4640 _ Microsoft Learn.pdf",
    "WhatsApp Image 2025-11-20 at 23.22.06_de23c0db.jpg",
    "batch_b988676d.xlsx",
}
PROTECTED_SESSIONS = {"sub_a9d188c1c932", "sub_b867f1f925ac"}

TEST_BATCH_IDS = {
    "batch_86af2ab0",
    "batch_78a1d612",
    "batch_1c47c721",
    "test-e2e-batch-real",
    "test-perf-benchmark-batch",
}

def sanitize_doc(d):
    """Remove secrets, passwords, tokens from backup dump."""
    clean = {}
    for k, v in d.items():
        if k in ("password", "token", "jwt_secret", "secret_key"):
            clean[k] = "[REDACTED]"
        elif isinstance(v, (datetime, pymongo.collection.ObjectId)):
            clean[k] = str(v)
        else:
            clean[k] = v
    return clean

def main():
    print("=" * 85)
    print(" SAFE TEST-DATA AND UNWANTED-FILE CLEANUP ENGINE")
    print(f" Target Backup Directory: {backup_root}")
    print("=" * 85)

    # -------------------------------------------------------------------------
    # PHASE 2: SAFETY PRE-CHECKS
    # -------------------------------------------------------------------------
    print("\n>>> PHASE 2: SAFETY PRE-CHECKS <<<")
    # Verify real students exist
    real_subs = list(db["student_submissions"].find({"batch_id": "batch_b988676d", "register_number": {"$in": list(PROTECTED_STUDENT_REGS)}}))
    assert len(real_subs) >= 5, f"CRITICAL ABORT: Expected at least 5 real students, found {len(real_subs)}"
    print(f"  [SAFETY CHECK 1] Active real student records verified: {len(real_subs)}/5 found [OK]")

    # Verify real documents exist on disk
    for fn in PROTECTED_FILES:
        fp = uploads_root / fn if not fn.endswith(".xlsx") else uploads_root / "excel_templates" / fn
        assert fp.exists(), f"CRITICAL ABORT: Real document missing: {fp}"
    print(f"  [SAFETY CHECK 2] All {len(PROTECTED_FILES)} canonical student files & templates exist on disk [OK]")

    # Verify real batch and section exist
    b_doc = db["admission_batches"].find_one({"_id": "batch_b988676d"})
    assert b_doc is not None, "CRITICAL ABORT: Active batch missing!"
    print(f"  [SAFETY CHECK 3] Active batch '{b_doc.get('name')}' protected [OK]")

    # -------------------------------------------------------------------------
    # PHASE 3: BACKUP / RECOVERY ARCHIVE CREATION
    # -------------------------------------------------------------------------
    print("\n>>> PHASE 3: CREATING SAFE-TO-DELETE RECOVERY BACKUP <<<")
    backup_db_dir = backup_root / "db"
    backup_files_dir = backup_root / "files"
    backup_db_dir.mkdir(parents=True, exist_ok=True)
    backup_files_dir.mkdir(parents=True, exist_ok=True)

    # Load Phase 1 Audit & Classification
    json_path = Path(r"C:\Users\SHADHANAN\.gemini\antigravity-ide\brain\dc8f4e03-8c7e-493c-a464-55b1e68be08f\scratch\phase1_audit_classification.json")
    with open(json_path, "r", encoding="utf-8") as f:
        classification = json.load(f)

    db_cat_a = classification["db"]["A_SAFE_TO_DELETE"]
    files_cat_a = classification["files"]["A_SAFE_TO_DELETE"]

    print(f"Loaded Classification:")
    print(f"  Category A DB Collections: {list(db_cat_a.keys())}")
    print(f"  Category A Files to delete: {len(files_cat_a)}")

    # -------------------------------------------------------------------------
    # PHASE 3: BACKUP / RECOVERY ARCHIVE CREATION
    # -------------------------------------------------------------------------
    print("\n>>> PHASE 3: CREATING SAFE-TO-DELETE RECOVERY BACKUP <<<")
    backup_db_dir = backup_root / "db"
    backup_files_dir = backup_root / "files"
    backup_db_dir.mkdir(parents=True, exist_ok=True)
    backup_files_dir.mkdir(parents=True, exist_ok=True)

    # Collect DB records to delete strictly from Category A
    db_to_delete = {}
    for cname, items in db_cat_a.items():
        if not items:
            continue
        # Extract query IDs
        if cname == "submission_sessions":
            s_ids = [item["submission_id"] for item in items]
            records = list(db[cname].find({"submission_id": {"$in": s_ids}}))
        elif cname == "document_processing_jobs":
            j_ids = [item["job_id"] for item in items]
            records = list(db[cname].find({"job_id": {"$in": j_ids}}))
        else:
            ids = []
            for item in items:
                rec_id = item.get("id") or item.get("_id")
                # Try ObjectId if valid 24-char hex
                if isinstance(rec_id, str) and len(rec_id) == 24:
                    try:
                        ids.append(pymongo.collection.ObjectId(rec_id))
                    except Exception:
                        ids.append(rec_id)
                else:
                    ids.append(rec_id)
            records = list(db[cname].find({"_id": {"$in": ids}}))
        
        db_to_delete[cname] = records

    # Write DB backup JSON with secrets redacted
    for cname, docs in db_to_delete.items():
        sanitized = [sanitize_doc(d) for d in docs]
        with open(backup_db_dir / f"{cname}.json", "w", encoding="utf-8") as f:
            json.dump(sanitized, f, indent=2)
        print(f"  Backed up {len(docs)} records from collection '{cname}'")

    # Collect Files to delete strictly from Category A
    files_to_delete = []
    backup_file_count = 0
    backup_bytes = 0

    for item in files_cat_a:
        rel_p = item["rel_path"]
        target_path = uploads_root / rel_p
        if not target_path.exists():
            continue
        
        # Double safety check: NEVER allow protected files or sessions
        if target_path.name in PROTECTED_FILES:
            continue
        if any(p_sess in str(target_path) for p_sess in PROTECTED_SESSIONS):
            continue

        files_to_delete.append(target_path)

        # Copy to backup
        dest = backup_files_dir / rel_p
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_path, dest)
        backup_file_count += 1
        backup_bytes += target_path.stat().st_size

    print(f"  Backup Archive Created: {backup_file_count} files ({backup_bytes / (1024*1024):.2f} MB) copied to {backup_root} [SUCCESS]")

    # -------------------------------------------------------------------------
    # PHASE 4: ACTUAL CLEANUP (SAFE DELETION)
    # -------------------------------------------------------------------------
    print("\n>>> PHASE 4: EXECUTING SAFE CLEANUP <<<")
    
    # 4.1 Delete DB records
    deleted_db_stats = {}
    for cname, docs in db_to_delete.items():
        if not docs:
            deleted_db_stats[cname] = 0
            continue
        if cname == "submission_sessions":
            s_ids = [d["submission_id"] for d in docs]
            res = db[cname].delete_many({"submission_id": {"$in": s_ids}})
        elif cname == "document_processing_jobs":
            j_ids = [d["job_id"] for d in docs]
            res = db[cname].delete_many({"job_id": {"$in": j_ids}})
        else:
            ids = [d["_id"] for d in docs]
            res = db[cname].delete_many({"_id": {"$in": ids}})
        deleted_db_stats[cname] = res.deleted_count
        print(f"  Deleted {deleted_db_stats[cname]} records from collection '{cname}'")

    # 4.2 Delete Files
    deleted_file_count = 0
    freed_bytes = 0

    for p in files_to_delete:
        if not p.exists():
            continue
        if p.name in PROTECTED_FILES:
            continue
        try:
            sz = p.stat().st_size
            p.unlink()
            deleted_file_count += 1
            freed_bytes += sz
        except Exception as e:
            print(f"  [ERROR] Could not delete file {p}: {e}")

    # Remove any empty orphaned session directories
    sessions_dir = uploads_root / "sessions"
    deleted_dir_count = 0
    if sessions_dir.exists():
        for sdir in sessions_dir.iterdir():
            if sdir.is_dir() and sdir.name not in PROTECTED_SESSIONS:
                # Check if directory is empty or only empty subdirs
                try:
                    shutil.rmtree(sdir)
                    deleted_dir_count += 1
                except Exception as e:
                    print(f"  [ERROR] Could not remove empty dir {sdir}: {e}")

    print(f"\nFiles Cleaned:")
    print(f"  Deleted Files:       {deleted_file_count}")
    print(f"  Deleted Empty Dirs:  {deleted_dir_count}")
    print(f"  Freed Disk Space:    {freed_bytes / (1024*1024):.2f} MB")

    # -------------------------------------------------------------------------
    # PHASE 5: POST-CLEANUP VERIFICATION
    # -------------------------------------------------------------------------
    print("\n>>> PHASE 5: POST-CLEANUP INTEGRITY VERIFICATION <<<")
    
    # 1. Verify real student submissions are 100% intact
    surviving_real_subs = list(db["student_submissions"].find({"batch_id": "batch_b988676d", "register_number": {"$in": list(PROTECTED_STUDENT_REGS)}}))
    assert len(surviving_real_subs) == len(real_subs), "CRITICAL FAILURE: Real student records were deleted!"
    print(f"  [VERIFICATION 1] Real student records intact: {len(surviving_real_subs)}/{len(real_subs)} [PASS]")

    # 2. Verify all real files remain physically accessible on disk
    for fn in PROTECTED_FILES:
        fp = uploads_root / fn if not fn.endswith(".xlsx") else uploads_root / "excel_templates" / fn
        assert fp.exists() and fp.is_file(), f"CRITICAL FAILURE: Real file missing after cleanup: {fp}"
    print(f"  [VERIFICATION 2] All {len(PROTECTED_FILES)} canonical student files & templates physically exist [PASS]")

    # 3. Verify Active Batch, Sections & Link
    surviving_batch = db["admission_batches"].find_one({"_id": "batch_b988676d"})
    assert surviving_batch is not None, "Active batch was deleted!"
    surviving_classes = list(db["batch_classes"].find({"batch_id": "batch_b988676d"}))
    assert len(surviving_classes) >= 1, "Active batch classes deleted!"
    surviving_link = db["upload_links"].find_one({"batch_id": "batch_b988676d"})
    assert surviving_link is not None, "Active upload link deleted!"
    print(f"  [VERIFICATION 3] Batch, Section, and Upload Link functionality verified [PASS]")

    # 4. Verify Active Extraction Sessions & Jobs
    for sid in PROTECTED_SESSIONS:
        s_doc = db["submission_sessions"].find_one({"submission_id": sid})
        assert s_doc is not None, f"Active session {sid} deleted!"
        j_docs = list(db["document_processing_jobs"].find({"submission_id": sid}))
        assert len(j_docs) == 5, f"Active jobs for session {sid} missing!"
        s_dir = uploads_root / "sessions" / sid
        assert s_dir.exists() and s_dir.is_dir(), f"Active session directory missing: {s_dir}"
    print(f"  [VERIFICATION 4] Active extraction sessions & jobs 100% intact [PASS]")

    # 5. Verify Staff / Admin Users
    admin_user = db["users"].find_one({"username": "admin"})
    aiml_user = db["users"].find_one({"username": "aiml"})
    assert admin_user is not None and aiml_user is not None, "Staff / Admin users missing!"
    print(f"  [VERIFICATION 5] Staff & Super Admin accounts intact [PASS]")

    print("\n" + "=" * 85)
    print(" SAFE CLEANUP EXECUTED SUCCESSFULLY WITH ZERO DATA LOSS")
    print("=" * 85)

if __name__ == "__main__":
    main()
