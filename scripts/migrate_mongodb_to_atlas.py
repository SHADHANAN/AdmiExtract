#!/usr/bin/env python3
"""
ADMIEXTRACT — Root Wrapper for MongoDB Atlas Migration Script
Delegates to Backend/scripts/migrate_mongodb_to_atlas.py
"""
import sys
from pathlib import Path
import runpy

backend_script = Path(__file__).resolve().parent.parent / "Backend" / "scripts" / "migrate_mongodb_to_atlas.py"
if not backend_script.exists():
    print(f"[ERROR] Migration script not found at {backend_script}")
    sys.exit(1)

# Execute the backend script within its directory context
runpy.run_path(str(backend_script), run_name="__main__")
