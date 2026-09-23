import os
import re
from pathlib import Path
from typing import Optional


def resolve_document_file_path(
    raw_path: Optional[str],
    batch_id: Optional[str] = None,
    register_number: Optional[str] = None,
    document_name: Optional[str] = None,
) -> Optional[Path]:
    """
    Robustly resolves a document file path to a verified physical file on disk.
    Handles:
      - Direct absolute paths
      - Paths relative to Backend directory
      - Paths relative to uploads directory
      - Legacy directory paths (e.g. from previous project renames / moves)
      - Fabricated relative paths like 'uploads/{batch_id}/{reg_num}/{filename}'
      - Files stored in session directories: 'uploads/sessions/{submission_id}/{job_id}_{clean_name}'
      - Case-insensitive matching on Windows/Linux filesystems
    Returns the resolved Path if it exists and is a regular file, else None.
    """
    if not raw_path or not str(raw_path).strip():
        return None

    backend_dir = Path(__file__).resolve().parent.parent.parent
    uploads_dir = backend_dir / "uploads"

    # 1. Direct path check (if valid absolute path)
    try:
        p = Path(raw_path)
        if p.is_file():
            return p
    except Exception:
        pass

    # 2. Relative to Backend directory
    try:
        p = (backend_dir / raw_path).resolve()
        if p.is_file():
            return p
    except Exception:
        pass

    # 3. Relative to uploads directory
    try:
        p = (uploads_dir / raw_path).resolve()
        if p.is_file():
            return p
    except Exception:
        pass

    # 4. Re-anchor if path contains '/uploads/' or '\uploads\'
    try:
        norm = str(raw_path).replace("\\", "/")
        if "/uploads/" in norm:
            sub_rel = norm.split("/uploads/", 1)[1]
            p = (uploads_dir / sub_rel).resolve()
            if p.is_file():
                return p
    except Exception:
        pass

    # 5. Extract bare filename and check uploads_dir root
    filename = Path(raw_path).name
    if filename and uploads_dir.exists():
        p = (uploads_dir / filename).resolve()
        if p.is_file():
            return p

    # 6. Check in session uploads: uploads/sessions/*/*{filename}
    if filename and uploads_dir.exists():
        session_matches = list(uploads_dir.glob(f"sessions/*/*{filename}"))
        if session_matches and session_matches[0].is_file():
            return session_matches[0]

        # Also try sanitized filename (alphanumeric, underscores)
        clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
        if clean_name != filename:
            clean_matches = list(uploads_dir.glob(f"sessions/*/*{clean_name}"))
            if clean_matches and clean_matches[0].is_file():
                return clean_matches[0]

    # 7. Case-insensitive search in uploads_dir root
    if filename and uploads_dir.exists():
        lower_fn = filename.lower()
        for item in uploads_dir.iterdir():
            if item.is_file() and item.name.lower() == lower_fn:
                return item

    # 8. If document_name is provided, try looking for matching files with common extensions
    if document_name and uploads_dir.exists():
        clean_doc = re.sub(r'[^a-zA-Z0-9]', '', document_name).lower()
        for item in uploads_dir.iterdir():
            if item.is_file():
                item_stem_clean = re.sub(r'[^a-zA-Z0-9]', '', item.stem).lower()
                if clean_doc and item_stem_clean and clean_doc == item_stem_clean:
                    return item

    return None
