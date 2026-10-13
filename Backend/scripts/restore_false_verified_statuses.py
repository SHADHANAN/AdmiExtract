"""
Restore False Verified Statuses Script
======================================
Inspects all DocumentFieldVerification records marked STUDENT_VERIFIED or STUDENT_CONFIRMED.
- Where reliable audit history proves that a student never submitted verification
  (no student audit action, student_updated_at is None, no completed token, no student submission record),
  restores status to AI_EXTRACTED and clears unverified student_value.
- Preserves all records with valid successful student submission evidence.
- Reports all actions taken and flags any unclassified/ambiguous records.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import asyncio
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings


async def restore_false_statuses(dry_run: bool = False):
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]

    print(f"Connecting to database '{settings.DATABASE_NAME}'...")

    # Load completed tokens and verified student submissions for reference
    completed_tokens = await db.verification_tokens.find({"status": "COMPLETED"}).to_list(10000)
    completed_student_ids = {t.get("student_id") for t in completed_tokens if t.get("student_id")}

    verified_subs = await db.student_submissions.find({"submission_status": "Student Verified"}).to_list(10000)
    verified_sub_ids = {str(s.get("_id")) for s in verified_subs}
    verified_sub_regs = {s.get("register_number") or s.get("student_id") for s in verified_subs}

    cursor = db.document_field_verifications.find({
        "status": {"$in": ["STUDENT_VERIFIED", "STUDENT_CONFIRMED"]}
    })
    recs = await cursor.to_list(50000)
    print(f"Total candidate records to inspect: {len(recs)}")

    preserved_records = []
    restored_records = []
    ambiguous_records = []

    now = datetime.now(timezone.utc)

    for r in recs:
        s_id = r.get("student_id")
        sub_id = r.get("student_submission_id")
        history = r.get("history", [])

        has_student_history = any(
            h.get("action") in ("STUDENT_CONFIRM", "STUDENT_EDIT", "STUDENT_CORRECTION")
            or h.get("actor_role") in ("student", "STUDENT_PUBLIC")
            for h in history
        )
        has_student_updated_at = bool(r.get("student_updated_at"))
        has_completed_token = (s_id in completed_student_ids)
        has_verified_sub = (s_id in verified_sub_regs or sub_id in verified_sub_ids)

        if has_student_history or has_student_updated_at:
            # Genuine student action recorded
            preserved_records.append(r)
        elif not has_student_history and not has_student_updated_at and not has_completed_token and not has_verified_sub:
            # Clear evidence of no student submission: False status
            restored_records.append(r)
        else:
            ambiguous_records.append(r)

    print(f"\n--- Inspection Breakdown ---")
    print(f"Preserved records (genuine student submission): {len(preserved_records)}")
    print(f"False records to restore (no student submission): {len(restored_records)}")
    print(f"Ambiguous / unclassified records: {len(ambiguous_records)}")

    if ambiguous_records:
        print("\nWARNING: Unclassified records found:")
        for ar in ambiguous_records:
            print(f"  ID: {ar.get('_id')} | Student: {ar.get('student_id')} | Status: {ar.get('status')}")

    # Restore false records
    if restored_records and not dry_run:
        restored_ids = [r["_id"] for r in restored_records]
        res = await db.document_field_verifications.update_many(
            {"_id": {"$in": restored_ids}},
            {
                "$set": {
                    "status": "AI_EXTRACTED",
                    "student_value": None,
                    "student_updated_at": None,
                    "student_comment": None,
                    "updated_at": now,
                }
            }
        )
        print(f"\nSuccessfully restored {res.modified_count} false records to AI_EXTRACTED.")

        # Group restored records by student
        by_student = {}
        for r in restored_records:
            sid = r.get("student_id")
            by_student.setdefault(sid, 0)
            by_student[sid] += 1

        print("Restored records per student:")
        for sid, count in by_student.items():
            print(f"  - Student {sid}: {count} records restored to AI_EXTRACTED (pending)")

    return {
        "total_inspected": len(recs),
        "preserved_count": len(preserved_records),
        "restored_count": len(restored_records),
        "ambiguous_count": len(ambiguous_records),
    }


if __name__ == "__main__":
    asyncio.run(restore_false_statuses())
