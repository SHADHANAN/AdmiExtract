"""
Production Safe Cleanup: Deduplicate Document Field Configurations
==================================================================
Safely detects and consolidates duplicate DocumentFieldConfiguration records
within the exact scope: (batch_id, class_id, document_type).

Safety Guarantees:
- DRY_RUN=True by default.
- Keeps the canonical/latest valid configuration per scope.
- Merges wanted-field mappings into the canonical record.
- Deletes only redundant duplicate configuration records.
- NEVER modifies or deletes student submissions.
- NEVER deletes or touches actual uploaded student files.
"""

import sys
import argparse
import asyncio
from typing import Any, Dict, List, Tuple
from pathlib import Path

# Add Backend root to sys.path
backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from app.models.user import User
from app.models.wanted_field_config import DocumentFieldConfiguration, WantedFieldItem
from app.models.excel_template import ExcelBatchTemplate
from app.models.student_submission import StudentSubmission
from app.models.doc_config_version import DocumentConfigurationVersion


async def init_db():
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client.get_default_database()
    await init_beanie(
        database=db,
        document_models=[
            User,
            DocumentFieldConfiguration,
            ExcelBatchTemplate,
            StudentSubmission,
            DocumentConfigurationVersion,
        ],
    )
    return client


async def run_cleanup(dry_run: bool = True) -> Dict[str, Any]:
    print("=" * 80)
    print(" ADMIEXTRACT DOCUMENT CONFIGURATION SAFE DEDUPLICATION")
    print(f" Mode: {'DRY RUN (Analysis only, 0 changes)' if dry_run else 'LIVE DEDUPLICATION EXECUTION'}")
    print("=" * 80)

    # Fetch all document field configurations
    all_configs = await DocumentFieldConfiguration.find_all().to_list()
    print(f"Total Document Field Configuration records scanned: {len(all_configs)}")

    # Group by (batch_id, class_id, document_type)
    groups: Dict[Tuple[str, str | None, str], List[DocumentFieldConfiguration]] = {}
    for cfg in all_configs:
        norm_type = (cfg.document_type or "").upper().strip()
        key = (cfg.batch_id, cfg.class_id, norm_type)
        groups.setdefault(key, []).append(cfg)

    duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"Duplicate groups found: {len(duplicate_groups)}")

    total_duplicates_to_remove = sum(len(v) - 1 for v in duplicate_groups.values())
    print(f"Total duplicate records to remove: {total_duplicates_to_remove}")

    consolidated_count = 0
    removed_ids: List[str] = []

    for (batch_id, class_id, doc_type), doc_list in duplicate_groups.items():
        print(f"\nProcessing duplicate group for Batch: '{batch_id}', Class: '{class_id}', Doc: '{doc_type}' ({len(doc_list)} records)")

        # Sort to find canonical: prefer non-archived, highest version, latest updated_at
        sorted_docs = sorted(
            doc_list,
            key=lambda d: (
                0 if getattr(d, "is_archived", False) else 1,
                getattr(d, "version", 1),
                getattr(d, "updated_at", getattr(d, "created_at", None)),
            ),
            reverse=True,
        )

        canonical = sorted_docs[0]
        duplicates = sorted_docs[1:]

        print(f"  -> Keeping Canonical ID: {canonical.id} (v{canonical.version}, status={canonical.requirement_status})")

        # Merge wanted fields from duplicates into canonical
        existing_field_names = {f.field: f for f in canonical.fields}
        merged_available = list(canonical.available_fields or [f.field for f in canonical.fields])

        for dup in duplicates:
            print(f"  -> Duplicate ID to remove: {dup.id} (v{dup.version}, status={dup.requirement_status})")
            for f in dup.fields:
                if f.field not in existing_field_names:
                    canonical.fields.append(f)
                    existing_field_names[f.field] = f
                else:
                    # If duplicate has enabled field with mapping and canonical doesn't, adopt it
                    canon_item = existing_field_names[f.field]
                    if not canon_item.enabled and f.enabled:
                        canon_item.enabled = True
                    if not canon_item.excel_header and f.excel_header:
                        canon_item.excel_header = f.excel_header

            for av in (dup.available_fields or []):
                if av not in merged_available:
                    merged_available.append(av)

        canonical.available_fields = merged_available

        if not dry_run:
            canonical.version += 1
            await canonical.save()
            for dup in duplicates:
                await dup.delete()
                removed_ids.append(str(dup.id))
            consolidated_count += 1
        else:
            removed_ids.extend(str(dup.id) for dup in duplicates)

    print("\n" + "=" * 80)
    print(f" Summary: {len(duplicate_groups)} duplicate scopes resolved.")
    print(f" Removed: {len(removed_ids)} redundant records.")
    print(f" Student submissions & uploaded files: 0 touched (PROTECTED).")
    print("=" * 80)

    return {
        "duplicate_groups_count": len(duplicate_groups),
        "removed_ids_count": len(removed_ids),
        "removed_ids": removed_ids,
        "dry_run": dry_run,
    }


def main():
    parser = argparse.ArgumentParser(description="Clean duplicate document field configurations")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview duplicates (default: True)")
    parser.add_argument("--execute", action="store_true", default=False, help="Execute cleanup")
    parser.add_argument("--confirm", action="store_true", default=False, help="Confirm execution")

    args = parser.parse_args()
    is_dry = not (args.execute and args.confirm)

    async def _runner():
        client = await init_db()
        try:
            await run_cleanup(dry_run=is_dry)
        finally:
            client.close()

    asyncio.run(_runner())


if __name__ == "__main__":
    main()
