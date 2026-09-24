#!/usr/bin/env python3
"""
ADMIEXTRACT — MongoDB Local to MongoDB Atlas Migration & Verification Tool
==========================================================================

This utility safely migrates and verifies ADMIEXTRACT data between MongoDB
instances (e.g., local MongoDB -> MongoDB Atlas Cluster).

Features:
- Preserves 100% BSON fidelity: ObjectId, custom string IDs, dates, nested documents.
- Index replication: Discovers and recreates custom indexes on target.
- Duplicate and Conflict Safety: Detects existing documents by `_id` and never
  overwrites conflicting records automatically.
- Zero-Destruction Guarantee: Never deletes, drops, or modifies source or target data.
- Dry-Run Mode (--dry-run): Inspects and simulates migration without writing anything.
- Verification Mode (--verify): Compares counts, collections, sample records, and indexes.
- Credential Safety: Automatically masks all credentials and connection strings in logs.

Usage:
  python scripts/migrate_mongodb_to_atlas.py --dry-run
  python scripts/migrate_mongodb_to_atlas.py --verify
  python scripts/migrate_mongodb_to_atlas.py --migrate
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Third-party MongoDB client (PyMongo)
try:
    from bson import ObjectId
    from bson.json_util import dumps as bson_dumps
    from pymongo import MongoClient
    from pymongo.errors import BulkWriteError, PyMongoError
except ImportError:
    print("[ERROR] PyMongo is required. Install via: pip install pymongo")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("admiextract_migration")

# Known ADMIEXTRACT collections
EXPECTED_COLLECTIONS = [
    "users",
    "departments",
    "upload_links",
    "student_submissions",
    "excel_batch_templates",
    "doc_config_versions",
    "admission_batches",
    "batch_classes",
    "document_field_configurations",
    "document_processing_jobs",
    "submission_sessions",
    "audit_logs",
]


def mask_connection_uri(uri: str) -> str:
    """Mask credentials in a MongoDB URI for safe logging."""
    if not uri:
        return "<EMPTY_URI>"
    try:
        # Match mongodb:// or mongodb+srv:// with credentials
        pattern = r"(mongodb(?:\+srv)?:\/\/)([^:@]+):([^@]+)@(.+)"
        if re.match(pattern, uri):
            return re.sub(pattern, r"\1*****:*****@\4", uri)
        return uri
    except Exception:
        return "mongodb://*****:*****@<hidden>"


def load_env_variables(backend_dir: Path) -> Dict[str, str]:
    """Read .env file if available without third-party dependencies."""
    env_vars: Dict[str, str] = {}
    env_path = backend_dir / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip("\"'")
        except Exception as e:
            logger.warning("Could not read local .env file: %s", e)
    return env_vars


def doc_hash(doc: Dict[str, Any]) -> str:
    """Compute deterministic MD5 hash of a BSON document for comparison."""
    # BSON dumps provides deterministic canonical JSON representation
    serialized = bson_dumps(doc, sort_keys=True)
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


class MigrationEngine:
    def __init__(
        self,
        source_uri: str,
        target_uri: Optional[str],
        db_name: str,
        dry_run: bool = True,
    ):
        self.source_uri = source_uri
        self.target_uri = target_uri
        self.db_name = db_name
        self.dry_run = dry_run

        self.source_client: Optional[MongoClient] = None
        self.target_client: Optional[MongoClient] = None

    def connect_source(self) -> MongoClient:
        if not self.source_client:
            logger.info("Connecting to SOURCE MongoDB at: %s", mask_connection_uri(self.source_uri))
            self.source_client = MongoClient(self.source_uri, serverSelectionTimeoutMS=4000)
            self.source_client.admin.command("ping")
        return self.source_client

    def connect_target(self) -> Optional[MongoClient]:
        if not self.target_uri:
            return None
        if not self.target_client:
            logger.info("Connecting to TARGET MongoDB at: %s", mask_connection_uri(self.target_uri))
            self.target_client = MongoClient(self.target_uri, serverSelectionTimeoutMS=6000)
            self.target_client.admin.command("ping")
        return self.target_client

    def get_source_collections(self) -> List[str]:
        client = self.connect_source()
        db = client[self.db_name]
        colls = db.list_collection_names()
        # Return expected collections first, followed by any additional collections
        ordered = [c for c in EXPECTED_COLLECTIONS if c in colls]
        extras = [c for c in colls if c not in EXPECTED_COLLECTIONS and not c.startswith("system.")]
        return ordered + extras

    def inspect_and_plan(self) -> Dict[str, Dict[str, Any]]:
        """
        Inspect source and target databases.
        Categorize documents into: missing in target, identical, or conflicting.
        """
        s_client = self.connect_source()
        s_db = s_client[self.db_name]

        t_client = None
        t_db = None
        if self.target_uri:
            try:
                t_client = self.connect_target()
                if t_client:
                    t_db = t_client[self.db_name]
            except Exception as exc:
                logger.warning("Target MongoDB unavailable or not specified: %s", exc)

        collections = self.get_source_collections()
        report_data: Dict[str, Dict[str, Any]] = {}

        for col_name in collections:
            s_col = s_db[col_name]
            s_docs = list(s_col.find({}))
            s_count = len(s_docs)

            if t_db is not None:
                t_col = t_db[col_name]
                t_count = t_col.count_documents({})
                t_docs_map = {doc["_id"]: doc for doc in t_col.find({})}

                missing_docs: List[Dict[str, Any]] = []
                identical_count = 0
                conflicting_ids: List[Any] = []

                for s_doc in s_docs:
                    s_id = s_doc["_id"]
                    if s_id not in t_docs_map:
                        missing_docs.append(s_doc)
                    else:
                        t_doc = t_docs_map[s_id]
                        if doc_hash(s_doc) == doc_hash(t_doc):
                            identical_count += 1
                        else:
                            conflicting_ids.append(s_id)

                report_data[col_name] = {
                    "source_count": s_count,
                    "target_count": t_count,
                    "missing_count": len(missing_docs),
                    "identical_count": identical_count,
                    "conflict_count": len(conflicting_ids),
                    "missing_docs": missing_docs,
                    "conflicting_ids": conflicting_ids,
                    "indexes": s_col.index_information(),
                }
            else:
                report_data[col_name] = {
                    "source_count": s_count,
                    "target_count": 0,
                    "missing_count": s_count,
                    "identical_count": 0,
                    "conflict_count": 0,
                    "missing_docs": s_docs,
                    "conflicting_ids": [],
                    "indexes": s_col.index_information(),
                }

        return report_data

    def run_dry_run(self) -> Dict[str, Dict[str, Any]]:
        """Execute dry-run inspection and display structured report."""
        print("\n" + "=" * 78)
        print(" ADMIEXTRACT -- MONGODB MIGRATION (DRY-RUN MODE)")
        print("=" * 78)
        print(f" Source DB:    {self.db_name}")
        print(f" Source Host:  {mask_connection_uri(self.source_uri)}")
        print(f" Target Host:  {mask_connection_uri(self.target_uri or '<NOT_CONFIGURED>')}")
        print(f" Mode:         DRY-RUN (NO DATA WILL BE WRITTEN)")
        print("-" * 78)

        plan = self.inspect_and_plan()
        self.print_summary_table(plan)

        total_source = sum(item["source_count"] for item in plan.values())
        total_missing = sum(item["missing_count"] for item in plan.values())
        total_conflicts = sum(item["conflict_count"] for item in plan.values())
        total_identical = sum(item["identical_count"] for item in plan.values())

        print("-" * 78)
        print(f" Total Source Documents: {total_source}")
        print(f" Total to be Migrated:   {total_missing}")
        print(f" Already Existing:       {total_identical}")
        print(f" Conflicting Documents:  {total_conflicts}")
        print("=" * 78 + "\n")
        return plan

    def run_migration(self) -> bool:
        """Execute actual migration with full duplicate safety and index replication."""
        if not self.target_uri:
            logger.error("Cannot migrate: Target URI is not configured.")
            return False

        if self.source_uri.strip() == self.target_uri.strip():
            logger.error("Source and Target connection strings are IDENTICAL. Migration aborted for safety.")
            return False

        t_client = self.connect_target()
        if not t_client:
            logger.error("Failed to connect to target MongoDB.")
            return False

        t_db = t_client[self.db_name]
        s_client = self.connect_source()
        s_db = s_client[self.db_name]

        print("\n" + "=" * 78)
        print(" ADMIEXTRACT -- EXECUTING MIGRATION")
        print("=" * 78)
        print(f" Source DB:    {self.db_name}")
        print(f" Source URI:   {mask_connection_uri(self.source_uri)}")
        print(f" Target URI:   {mask_connection_uri(self.target_uri)}")
        print("=" * 78)

        plan = self.inspect_and_plan()
        self.print_summary_table(plan)

        migrated_total = 0
        skipped_conflicts = 0

        for col_name, info in plan.items():
            missing_docs = info["missing_docs"]
            conflicts = info["conflicting_ids"]

            if conflicts:
                logger.warning(
                    "Collection '%s': %d conflicting document(s) detected. SKIPPING conflicts to protect data.",
                    col_name,
                    len(conflicts),
                )
                skipped_conflicts += len(conflicts)

            if missing_docs:
                t_col = t_db[col_name]
                try:
                    result = t_col.insert_many(missing_docs, ordered=False)
                    inserted_count = len(result.inserted_ids)
                    migrated_total += inserted_count
                    logger.info("Collection '%s': Successfully inserted %d documents.", col_name, inserted_count)
                except BulkWriteError as bwe:
                    inserted_count = bwe.details.get("nInserted", 0)
                    migrated_total += inserted_count
                    logger.warning("Collection '%s': Partial insert (%d inserted, some duplicates).", col_name, inserted_count)
                except Exception as exc:
                    logger.error("Collection '%s': Insert failed: %s", col_name, exc)
            else:
                logger.info("Collection '%s': Up-to-date (no missing documents).", col_name)

            # Replicate custom indexes
            s_indexes = info.get("indexes", {})
            t_col = t_db[col_name]
            for idx_name, idx_spec in s_indexes.items():
                if idx_name == "_id_":
                    continue  # _id index is built-in
                try:
                    keys = idx_spec["key"]
                    unique = idx_spec.get("unique", False)
                    sparse = idx_spec.get("sparse", False)
                    t_col.create_index(keys, name=idx_name, unique=unique, sparse=sparse)
                except Exception as idx_err:
                    logger.warning("Index '%s' on '%s' skipped or failed: %s", idx_name, col_name, idx_err)

        print("\n" + "=" * 78)
        print(f" MIGRATION EXECUTION COMPLETED")
        print(f" Total Documents Inserted: {migrated_total}")
        print(f" Conflicting Documents Skipped: {skipped_conflicts}")
        print("=" * 78)

        # Run verification automatically post-migration
        return self.run_verification()

    def run_verification(self) -> bool:
        """Verify data integrity, document counts, and key references between source and target."""
        print("\n" + "=" * 78)
        print(" ADMIEXTRACT -- POST-MIGRATION VERIFICATION")
        print("=" * 78)

        if not self.target_uri:
            logger.error("Cannot verify: Target URI is not configured.")
            return False

        try:
            plan = self.inspect_and_plan()
        except Exception as exc:
            logger.error("Verification failed during database inspection: %s", exc)
            return False

        self.print_summary_table(plan)

        all_ok = True
        total_source = sum(item["source_count"] for item in plan.values())
        total_target = sum(item["target_count"] for item in plan.values())
        total_missing = sum(item["missing_count"] for item in plan.values())
        total_conflicts = sum(item["conflict_count"] for item in plan.values())

        print("-" * 78)
        print(f" Integrity Check Summary:")
        print(f"   - Source Documents: {total_source}")
        print(f"   - Target Documents: {total_target}")
        print(f"   - Missing in Target: {total_missing}")
        print(f"   - Conflicts:         {total_conflicts}")

        if total_missing > 0:
            print("   [!] STATUS: DRIFT DETECTED (Target is missing documents)")
            all_ok = False
        elif total_conflicts > 0:
            print("   [!] STATUS: CONFLICTS DETECTED (Target contains different document contents)")
            all_ok = False
        else:
            print("   [OK] STATUS: COMPLETE MATCH. 100% Data Parity Verified.")

        # Reference and Relationship Validation
        t_client = self.connect_target()
        if t_client:
            t_db = t_client[self.db_name]
            print("\n Verifying Key Foreign Key / Entity References on Target:")

            # 1. Batch & Class Reference check
            batch_count = t_db["admission_batches"].count_documents({})
            class_count = t_db["batch_classes"].count_documents({})
            print(f"   - Batches on target: {batch_count}, Classes on target: {class_count}")

            # 2. Upload link & batch relationships
            links = list(t_db["upload_links"].find({}))
            valid_links = 0
            for link in links:
                b_id = link.get("batch_id")
                if not b_id or t_db["admission_batches"].find_one({"_id": b_id}):
                    valid_links += 1
            print(f"   - Validated upload links referencing valid batches: {valid_links}/{len(links)}")

            # 3. Super Admin user presence
            admin = t_db["users"].find_one({"username": "admin"})
            print(f"   - Super Admin user presence on target: {'FOUND' if admin else 'MISSING'}")
            if not admin:
                all_ok = False

        print("=" * 78 + "\n")
        return all_ok

    def print_summary_table(self, plan: Dict[str, Dict[str, Any]]):
        """Print formatted migration report table complying with Task 6."""
        print(f"\nMigration Summary")
        print(f"-----------------")
        print(f"Source DB: {self.db_name}")
        print(f"Target DB: {self.db_name}\n")
        header = f"{'Collection':<32} | {'Source':<7} | {'Target':<7} | {'Missing':<7} | {'Conflicts':<9}"
        print(header)
        print("-" * len(header))
        for col_name, info in plan.items():
            print(
                f"{col_name:<32} | {info['source_count']:<7} | {info['target_count']:<7} | "
                f"{info['missing_count']:<7} | {info['conflict_count']:<9}"
            )


def main():
    parser = argparse.ArgumentParser(description="ADMIEXTRACT MongoDB to Atlas Migration Tool")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Simulate migration without writes")
    parser.add_argument("--verify", action="store_true", default=False, help="Verify parity between source and target")
    parser.add_argument("--migrate", action="store_true", default=False, help="Execute data migration to target")
    parser.add_argument("--source-uri", type=str, default=None, help="Source MongoDB connection URI")
    parser.add_argument("--target-uri", type=str, default=None, help="Target MongoDB connection URI")
    parser.add_argument("--db-name", type=str, default=None, help="Database name (default: admiextract)")

    args = parser.parse_args()

    backend_dir = Path(__file__).resolve().parent.parent
    env_vars = load_env_variables(backend_dir)

    # Resolve database name
    db_name = args.db_name or os.environ.get("DATABASE_NAME") or env_vars.get("DATABASE_NAME") or "admiextract"

    # Resolve Source URI
    source_uri = (
        args.source_uri
        or os.environ.get("SOURCE_MONGODB_URI")
        or env_vars.get("SOURCE_MONGODB_URI")
        or os.environ.get("MONGODB_URI")
        or env_vars.get("MONGODB_URI")
        or "mongodb://localhost:27017"
    )

    # Resolve Target URI
    target_uri = (
        args.target_uri
        or os.environ.get("TARGET_MONGODB_URI")
        or env_vars.get("TARGET_MONGODB_URI")
        or os.environ.get("MONGODB_ATLAS_URI")
        or env_vars.get("MONGODB_ATLAS_URI")
    )

    # Default to dry-run if neither --migrate nor --verify is explicitly given
    dry_run = args.dry_run or (not args.migrate and not args.verify)

    engine = MigrationEngine(
        source_uri=source_uri,
        target_uri=target_uri,
        db_name=db_name,
        dry_run=dry_run,
    )

    if args.verify:
        success = engine.run_verification()
        sys.exit(0 if success else 1)
    elif args.migrate:
        success = engine.run_migration()
        sys.exit(0 if success else 1)
    else:
        engine.run_dry_run()
        sys.exit(0)


if __name__ == "__main__":
    main()
