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


def format_document_download_filename(
    register_number: Optional[str],
    student_name: Optional[str],
    document_name: Optional[str],
    original_filename_or_ext: Optional[str] = None,
    original_filename: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> str:
    """
    Generate an authoritative, standardized document download filename using the exact format:
    RegisterNumber_StudentName_DocumentName.extension

    Examples:
    - 23CS001_Arun_Kumar_Aadhaar_Card.jpg
    - 23CS001_Arun_Kumar_Community_Certificate.pdf
    - 23CS001_Arun_Kumar_12th_HSC_Marksheet.jpg

    Rules:
    1. Retrieve the student's actual register number and name from the authorized student record,
       and the document name from the document's configured display name.
    2. Sanitize filename characters safely, preserve non-English names where supported,
       and preserve the original file extension.
    3. Never use a hardcoded register number or student name. If a field is missing, use a safe fallback.
    """
    def _clean_segment(text: Optional[str], fallback: str) -> str:
        if not text or not str(text).strip():
            return fallback
        val = str(text).strip()
        # Remove version suffix like "(v1)" if present
        val = re.sub(r'\s*\(v\d+\)\s*$', '', val, flags=re.IGNORECASE)
        # Strip forbidden characters: path separators, control chars, quotes, punctuation that breaks headers
        # Preserve Unicode letters (non-English), digits, and safe characters
        val = re.sub(r'[\s\\/:*?"<>|\x00-\x1f\x7f;,=]+', '_', val)
        # Collapse multiple underscores
        val = re.sub(r'_+', '_', val).strip('._')
        return val or fallback

    clean_reg = _clean_segment(register_number, "STUDENT")
    clean_name = _clean_segment(student_name, "UNKNOWN")
    clean_doc = _clean_segment(document_name, "Document")

    # Resolve extension source
    source_ref = original_filename_or_ext or original_filename

    ext = ""
    if source_ref:
        raw_ref = str(source_ref).strip()
        if raw_ref.startswith("."):
            ext = raw_ref.lower()
        else:
            p_ext = Path(raw_ref).suffix.lower()
            if p_ext:
                ext = p_ext
            elif "." in raw_ref:
                ext = "." + raw_ref.split(".")[-1].lower()

    if not ext and mime_type:
        mime_clean = str(mime_type).strip().lower()
        if "pdf" in mime_clean:
            ext = ".pdf"
        elif "jpeg" in mime_clean or "jpg" in mime_clean:
            ext = ".jpg"
        elif "png" in mime_clean:
            ext = ".png"
        elif "webp" in mime_clean:
            ext = ".webp"

    if not ext:
        ext = ".pdf"

    # Sanitize extension (alphanumeric only after dot)
    ext = "." + re.sub(r'[^a-zA-Z0-9]', '', ext.lstrip('.'))
    if ext == ".":
        ext = ".pdf"

    return f"{clean_reg}_{clean_name}_{clean_doc}{ext}"


def build_content_disposition_header(filename: str, disposition_type: str = "inline") -> str:
    """
    Construct an RFC 6266 / RFC 5987 compliant Content-Disposition header.
    Supports UTF-8 encoded filenames for non-English student names while providing
    safe ASCII fallback for older clients.
    """
    import urllib.parse

    ascii_fallback = re.sub(r'[^\x20-\x7E]', '_', filename).replace('"', '\\"')
    encoded = urllib.parse.quote(filename, encoding="utf-8")

    if ascii_fallback == filename:
        return f'{disposition_type}; filename="{filename}"'
    else:
        return f'{disposition_type}; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'

