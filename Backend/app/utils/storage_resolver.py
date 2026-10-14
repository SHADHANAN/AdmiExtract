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

    def _is_safe(cand: Path) -> bool:
        try:
            res = cand.resolve()
            return res.is_file()
        except Exception:
            return False

    # Extract bare filename and clean register number
    filename = Path(raw_path).name
    norm_path = str(raw_path).replace("\\", "/")

    clean_reg = None
    if register_number and str(register_number).strip():
        clean_reg = str(register_number).strip()
    else:
        # Extract student identifier from raw path pattern: .../students/<student_id>/...
        m_reg = re.search(r'students[\\/]([^\\/]+)', norm_path, re.IGNORECASE)
        if m_reg:
            clean_reg = m_reg.group(1).strip()

    # Strict Student Tenancy Isolation:
    # If path references a student, ensure it matches clean_reg if clean_reg was explicitly provided.
    m_path_reg = re.search(r'students[\\/]([^\\/]+)', norm_path, re.IGNORECASE)
    if m_path_reg and clean_reg:
        path_student = m_path_reg.group(1).strip().upper()
        if path_student != clean_reg.upper():
            # Cross-student path access strictly blocked
            return None

    # 1. Direct path check (if valid absolute or existing path)
    try:
        p = Path(raw_path)
        if _is_safe(p):
            # If path points to students directory, verify it belongs to clean_reg
            p_norm = str(p.resolve()).replace("\\", "/")
            p_reg = re.search(r'students[\\/]([^\\/]+)', p_norm, re.IGNORECASE)
            if p_reg and clean_reg and p_reg.group(1).strip().upper() != clean_reg.upper():
                return None
            return p.resolve()
    except Exception:
        pass

    # 2. Check student's own stored documents directory: uploads/students/{clean_reg}/documents/**
    if clean_reg and uploads_dir.exists():
        student_dir = uploads_dir / "students" / clean_reg
        if student_dir.is_dir():
            # Exact filename match within student's folder
            if filename:
                for candidate in student_dir.rglob(filename):
                    if candidate.is_file() and candidate.stat().st_size > 0:
                        return candidate.resolve()

                # Case-insensitive filename match within student's folder
                lower_fn = filename.lower()
                for candidate in student_dir.rglob("*"):
                    if candidate.is_file() and candidate.name.lower() == lower_fn and candidate.stat().st_size > 0:
                        return candidate.resolve()

            # If document_name provided, match by document name stem in student's folder
            if document_name:
                clean_doc = re.sub(r'[^a-zA-Z0-9]', '', str(document_name)).lower()
                if clean_doc:
                    for candidate in student_dir.rglob("*"):
                        if candidate.is_file() and candidate.stat().st_size > 0:
                            cand_stem = re.sub(r'[^a-zA-Z0-9]', '', candidate.stem).lower()
                            if clean_doc in cand_stem or cand_stem in clean_doc:
                                return candidate.resolve()

        # Strict Student Tenancy Isolation:
        # If a specific register_number was specified, never leak files from other students or session folders.
        return None

    # 3. Relative to Backend directory
    try:
        p = (backend_dir / raw_path).resolve()
        if p.is_file():
            return p
    except Exception:
        pass

    # 4. Relative to uploads directory
    try:
        p = (uploads_dir / raw_path).resolve()
        if p.is_file():
            return p
    except Exception:
        pass

    # 5. Re-anchor if path contains '/uploads/' or '\uploads\'
    try:
        if "/uploads/" in norm_path:
            sub_rel = norm_path.split("/uploads/", 1)[1]
            p = (uploads_dir / sub_rel).resolve()
            if p.is_file():
                return p
    except Exception:
        pass

    # 6. Extract bare filename and check uploads_dir root
    if filename and uploads_dir.exists():
        p = (uploads_dir / filename).resolve()
        if p.is_file():
            return p

    # 7. Check in session uploads: uploads/sessions/*/*{filename}
    if filename and uploads_dir.exists():
        session_matches = list(uploads_dir.glob(f"sessions/*/*{filename}"))
        if session_matches and session_matches[0].is_file():
            return session_matches[0]

        clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
        if clean_name != filename:
            clean_matches = list(uploads_dir.glob(f"sessions/*/*{clean_name}"))
            if clean_matches and clean_matches[0].is_file():
                return clean_matches[0]

    # 8. Case-insensitive search in uploads_dir root
    if filename and uploads_dir.exists():
        lower_fn = filename.lower()
        for item in uploads_dir.iterdir():
            if item.is_file() and item.name.lower() == lower_fn:
                return item

    return None
