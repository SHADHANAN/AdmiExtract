"""
Production Database & Storage Audit & Safe Cleanup Utility
==========================================================
Audits the entire MongoDB database and file storage for unnecessary,
duplicate, temporary, orphaned, and redundant data.

Safety:
- DRY_RUN=True by default.
- Never deletes active student documents or verification records.
- Never deletes without explicit flags: --execute --confirm.

Usage:
  # Dry-run audit report (default, does not delete anything):
  python scripts/audit_and_cleanup.py

  # Save JSON or Markdown audit report:
  python scripts/audit_and_cleanup.py --markdown-report audit_report.md

  # Confirmed execution of safe cleanup:
  python scripts/audit_and_cleanup.py --execute --confirm
"""

import sys
import os
import argparse
import json
from pathlib import Path
from datetime import datetime

# Add Backend root to path
backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))

from app.services.cleanup_service import StorageCleanupService

def format_bytes(b: int) -> str:
    if b >= 1024 * 1024:
        return f"{b / (1024 * 1024):.2f} MB"
    elif b >= 1024:
        return f"{b / 1024:.2f} KB"
    return f"{b} bytes"

def run_cli():
    parser = argparse.ArgumentParser(description="MongoDB & File Storage Audit & Safe Cleanup Utility")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Perform analysis only (default: True)")
    parser.add_argument("--execute", action="store_true", default=False, help="Enable actual cleanup execution")
    parser.add_argument("--confirm", action="store_true", default=False, help="Confirm cleanup execution")
    parser.add_argument("--retention-days", type=int, default=7, help="Retention period for temporary files (default: 7)")
    parser.add_argument("--max-backups", type=int, default=5, help="Max backups to keep per active batch (default: 5)")
    parser.add_argument("--json-report", type=str, default=None, help="Save structured report to JSON file")
    parser.add_argument("--markdown-report", type=str, default=None, help="Save formatted report to Markdown file")
    
    args = parser.parse_args()

    is_dry_run = not (args.execute and args.confirm)
    
    service = StorageCleanupService(
        backend_root=backend_root,
        retention_days=args.retention_days,
        max_backups_per_batch=args.max_backups,
        dry_run=is_dry_run
    )

    print("=" * 80)
    print(" ADMIEXTRACT DATABASE & FILE STORAGE AUDIT")
    print(f" Mode: {'DRY RUN (Analysis Only, 0 Deletions)' if is_dry_run else 'LIVE CLEANUP EXECUTION'}")
    print(f" Retention Days: {args.retention_days} | Max Backups per Batch: {args.max_backups}")
    print("=" * 80)

    # 1. Audit MongoDB Collections
    coll_reports = service.audit_database_collections()
    print("\n--- 1. MONGODB COLLECTION & FIELD USAGE ---")
    print(f"{'Collection Name':30} | {'Records':7} | {'Data Size':10} | {'Storage':10} | {'Action'}")
    print("-" * 80)
    for c in coll_reports:
        action = "KEEP (Production / Active)"
        if c["collection_name"] in ("student_submissions", "doc_config_versions"):
            action = "KEEP (Audit / History)"
        print(f"{c['collection_name']:30} | {c['record_count']:7} | {format_bytes(c['data_size_bytes']):10} | {format_bytes(c['storage_size_bytes']):10} | {action}")

    # 2. Storage Audit & Duplicate Detection
    storage_audit = service.audit_storage()
    print("\n--- 2. STORAGE SCAN & INTEGRITY SUMMARY ---")
    total_files = len(storage_audit["all_files"])
    total_size = sum(f["size_bytes"] for f in storage_audit["all_files"])
    ref_count = sum(1 for f in storage_audit["all_files"] if f["is_referenced"])
    unref_count = total_files - ref_count
    dup_groups_count = len(storage_audit["duplicate_groups"])
    orphaned_sessions_count = len(storage_audit["orphaned_session_dirs"])

    print(f"Total Uploaded Files:            {total_files} ({format_bytes(total_size)})")
    print(f"DB Referenced Files:             {ref_count} (Protected)")
    print(f"Unreferenced Files:              {unref_count}")
    print(f"Duplicate Groups (SHA-256):      {dup_groups_count}")
    print(f"Orphaned Disk Session Folders:   {orphaned_sessions_count} (of {storage_audit['disk_sessions_count']} total dirs)")
    print(f"Active DB Submission Sessions:   {len(storage_audit['active_db_sessions'])} {storage_audit['active_db_sessions']}")

    # 3. Cleanup Plan Analysis
    plan = service.generate_cleanup_plan()
    print("\n--- 3. CLEANUP PLAN CLASSIFICATION ---")
    print(f"Protected Files:                 {plan['protected_count']} files ({format_bytes(plan['protected_size_bytes'])})")
    print(f"Safe Cleanup Candidates:         {plan['cleanup_candidates_count']} items ({format_bytes(plan['cleanup_candidates_size_bytes'])})")

    # Breakdown of candidates by category
    from collections import defaultdict
    cat_counts = defaultdict(int)
    cat_bytes = defaultdict(int)
    for c in plan["cleanup_candidates"]:
        cat = c["category"]
        cat_counts[cat] += 1
        cat_bytes[cat] += c["size_bytes"]

    print("\nBreakdown of Proven Safe Cleanup Candidates:")
    for cat, cnt in sorted(cat_counts.items()):
        print(f"  - {cat:32}: {cnt:4} items | {format_bytes(cat_bytes[cat]):10}")

    # 4. Optional Execution
    if not is_dry_run:
        print("\n" + "=" * 80)
        print(" EXECUTING SAFE CLEANUP...")
        print("=" * 80)
        result = service.execute_cleanup(plan, confirm=True)
        print(f"Cleanup Completed:")
        print(f"  Deleted Files:       {result['deleted_files']}")
        print(f"  Deleted Directories: {result['deleted_dirs']}")
        print(f"  Freed Disk Space:    {format_bytes(result['freed_bytes'])}")
        if result["errors"]:
            print(f"  Errors encountered:  {len(result['errors'])}")
            for err in result["errors"][:5]:
                print(f"    {err['path']}: {err['error']}")
    else:
        print("\n[DRY RUN COMPLETE] No files or records were modified or deleted.")
        print("To execute safe cleanup, run with: --execute --confirm")

    # 5. Output Markdown Report if requested
    if args.markdown_report:
        report_md = f"""# Storage & Database Audit Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. MongoDB Collection Report
| Collection Name | Record Count | Data Size | Storage Size | Recommended Action |
| :--- | :--- | :--- | :--- | :--- |
"""
        for c in coll_reports:
            report_md += f"| `{c['collection_name']}` | {c['record_count']} | {format_bytes(c['data_size_bytes'])} | {format_bytes(c['storage_size_bytes'])} | KEEP (Active / Audit) |\n"

        report_md += f"""
## 2. File Storage Summary
- **Total Files:** {total_files} ({format_bytes(total_size)})
- **Active Referenced Files (Protected):** {ref_count}
- **Unreferenced / Orphaned Files:** {unref_count}
- **Duplicate Hash Groups (SHA-256):** {dup_groups_count}
- **Orphaned Session Dirs:** {orphaned_sessions_count}

## 3. Safe Cleanup Items
- **Protected Items:** {plan['protected_count']} files ({format_bytes(plan['protected_size_bytes'])})
- **Safe Cleanup Candidates:** {plan['cleanup_candidates_count']} items ({format_bytes(plan['cleanup_candidates_size_bytes'])})

| Category | Item Count | Reclaimable Space | Recommended Action |
| :--- | :--- | :--- | :--- |
"""
        for cat, cnt in sorted(cat_counts.items()):
            report_md += f"| {cat} | {cnt} | {format_bytes(cat_bytes[cat])} | DELETE (Safe) |\n"

        with open(args.markdown_report, "w", encoding="utf-8") as f:
            f.write(report_md)
        print(f"\nMarkdown report saved to: {args.markdown_report}")

    if args.json_report:
        with open(args.json_report, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "collections": coll_reports,
                "storage_summary": {
                    "total_files": total_files,
                    "total_size_bytes": total_size,
                    "referenced_files": ref_count,
                    "unreferenced_files": unref_count,
                    "duplicate_groups": dup_groups_count,
                    "orphaned_sessions": orphaned_sessions_count,
                },
                "plan_summary": {
                    "protected_count": plan["protected_count"],
                    "protected_bytes": plan["protected_size_bytes"],
                    "candidates_count": plan["cleanup_candidates_count"],
                    "candidates_bytes": plan["cleanup_candidates_size_bytes"],
                    "categories": {cat: {"count": cat_counts[cat], "bytes": cat_bytes[cat]} for cat in cat_counts}
                }
            }, f, indent=2)
        print(f"JSON report saved to: {args.json_report}")

if __name__ == "__main__":
    run_cli()
