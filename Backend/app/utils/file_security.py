import os
import re
from pathlib import Path
from typing import Optional, Set, Tuple
from fastapi import HTTPException, status

ALLOWED_DOCUMENT_EXTENSIONS: Set[str] = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_EXCEL_EXTENSIONS: Set[str] = {".xlsx"}

DANGEROUS_EXTENSIONS: Set[str] = {
    ".exe", ".bat", ".cmd", ".sh", ".bash", ".py", ".pyw", ".js", ".vbs",
    ".ps1", ".msi", ".dll", ".so", ".bin", ".com", ".scr", ".hta", ".cpl",
    ".jar", ".php", ".phtml", ".asp", ".aspx", ".cgi", ".pl"
}

# Known executable/binary magic byte signatures to block disguise attacks
EXECUTABLE_SIGNATURES = [
    b"MZ",              # Windows PE (.exe, .dll, .sys)
    b"\x7fELF",         # Linux ELF binary
    b"#!",              # Unix script shebang
    b"\xca\xfe\xba\xbe",# Java class bytecode
    b"<?php",           # PHP script
]

MAX_DOCUMENT_SIZE_BYTES: int = 25 * 1024 * 1024  # 25 MB
MAX_EXCEL_SIZE_BYTES: int = 15 * 1024 * 1024     # 15 MB

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
UPLOADS_DIR = BACKEND_DIR / "uploads"


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent path traversal and shell injection.
    Strips directory separators, null bytes, and non-printable characters.
    """
    if not filename:
        return "unnamed_document.pdf"

    name = Path(filename).name
    # Strip null bytes and non-printable chars
    name = re.sub(r'[\x00-\x1f\x7f]', '', name)
    # Remove traversal sequences
    name = name.replace("..", "").replace("/", "").replace("\\", "").strip()
    # Replace unsafe characters with underscore
    name = re.sub(r'[^a-zA-Z0-9_.\- ]', '_', name).strip()

    if not name or name.startswith("."):
        name = f"doc_{name.lstrip('.')}" if name.lstrip('.') else "unnamed_document.pdf"
    return name


def detect_file_magic_type(content: bytes) -> Optional[str]:
    """
    Verify magic bytes header to detect file type.
    """
    if len(content) < 2:
        return None

    # Check for executable disguise
    for sig in EXECUTABLE_SIGNATURES:
        if content.startswith(sig):
            return "application/x-executable-blocked"

    # PDF: %PDF- (0x25 0x50 0x44 0x46)
    if content.startswith(b"%PDF-") or content.startswith(b"%PDF"):
        return "application/pdf"

    # JPEG: 0xFF 0xD8 0xFF
    if content.startswith(b"\xFF\xD8\xFF"):
        return "image/jpeg"

    # PNG: 0x89 0x50 0x4E 0x47 0x0D 0x0A 0x1A 0x0A
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    # WebP: RIFF....WEBP
    if content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP":
        return "image/webp"

    # ZIP / XLSX (Office Open XML): PK\x03\x04
    if content.startswith(b"PK\x03\x04"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return None


def validate_uploaded_document(
    filename: str,
    content: bytes,
    max_size: int = MAX_DOCUMENT_SIZE_BYTES,
    allowed_exts: Optional[Set[str]] = None,
) -> Tuple[str, str]:
    """
    Validate uploaded document for security:
    - Path traversal & filename safety
    - File extension check against whitelist
    - File size constraints
    - Magic bytes header verification & executable disguise blocking
    Returns (safe_filename, detected_mime_type).
    """
    safe_name = sanitize_filename(filename)
    ext = Path(safe_name).suffix.lower()

    if ext in DANGEROUS_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Executable and script files ({ext}) are strictly forbidden.",
        )

    valid_exts = allowed_exts or ALLOWED_DOCUMENT_EXTENSIONS
    if ext not in valid_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed formats: {', '.join(sorted(valid_exts))}.",
        )

    file_size = len(content)
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File '{safe_name}' is empty (0 bytes).",
        )

    if file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File '{safe_name}' exceeds maximum size limit of {max_mb:.0f} MB.",
        )

    detected_mime = detect_file_magic_type(content)
    if detected_mime == "application/x-executable-blocked":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content contains executable binary header. Upload blocked.",
        )

    if not detected_mime:
        mime_map = {
            ".pdf": "application/pdf",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        detected_mime = mime_map.get(ext, "application/octet-stream")

    return safe_name, detected_mime


def validate_uploaded_excel(
    filename: str,
    content: bytes,
    max_size: int = MAX_EXCEL_SIZE_BYTES,
) -> Tuple[str, str]:
    """
    Validate uploaded Excel workbook (.xlsx).
    """
    safe_name = sanitize_filename(filename)
    ext = Path(safe_name).suffix.lower()

    if ext != ".xlsx":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xlsx Excel files are allowed. Please upload a valid Excel workbook.",
        )

    file_size = len(content)
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded Excel file is empty (0 bytes).",
        )

    if file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Excel file exceeds maximum size limit of {max_mb:.0f} MB.",
        )

    magic = detect_file_magic_type(content)
    if magic == "application/x-executable-blocked":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content contains executable binary header. Upload blocked.",
        )

    if magic and magic != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content does not match a valid Excel (.xlsx) package.",
        )

    return safe_name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def is_safe_storage_path(target_path: Path, storage_root: Optional[Path] = None) -> bool:
    """
    Verify that target_path resolves strictly within the controlled storage root
    to prevent path traversal attacks.
    """
    root = (storage_root or BACKEND_DIR).resolve()
    try:
        resolved = target_path.resolve()
        return resolved == root or root in resolved.parents
    except Exception:
        return False
