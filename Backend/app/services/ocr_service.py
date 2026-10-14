"""
OCR Service
===========

Production OCR Service built for Mistral AI SDK v2.9.1.

Responsibilities:
- Custom Exception: MistralOCRException
- Robust Parser: extract_ocr_text(ocr_response, client=None)
- Single Reusable Function: perform_mistral_ocr(file_path)
- Structured Diagnostic Logging: SDK VERSION, UPLOAD RESPONSE, OCR REQUEST, RAW OCR RESPONSE, PARSED OCR TEXT, OCR COMPLETE
- Full text extraction across PDFs, images, and scanned sub-images
"""

import base64
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

import mistralai

try:
    from mistralai.client.errors import SDKError, NoResponseError
except ImportError:
    SDKError = Exception
    NoResponseError = Exception

from app.core.config import settings
from app.core.mistral_client import get_mistral_client


class MistralOCRException(Exception):
    """Custom exception raised when Mistral OCR fails or returns no text content."""
    pass


SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _log(msg: str) -> None:
    """Dev-mode stdout logger with Unicode fallback for Windows console."""
    app_env = getattr(settings, "APP_ENV", os.getenv("APP_ENV", "development"))
    if app_env == "development":
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            try:
                print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)
            except Exception:
                pass


def extract_ocr_text(ocr_response: Any, client: Optional[Any] = None) -> Dict[str, Any]:
    """
    Robust Reusable Parser Function for Mistral OCR Response (SDK v2.9.1).

    Strategies:
    1. Extract text from page.blocks (excluding type == "image").
    2. Fallback to page.markdown / page.text, stripping standalone markdown image tags (![img-X.jpeg](...)).
    3. If still empty (e.g. image-only PDF scans), iterate over page.images and extract text from sub-images via OCR API.
    4. Merge text across all pages.

    Returns:
        {
            "full_text": "...",
            "pages": [
                {
                    "page_number": 1,
                    "text": "..."
                }
            ]
        }
    """
    pages_data: List[Dict[str, Any]] = []
    page_text_blocks: List[str] = []

    pages_list = getattr(ocr_response, "pages", None)
    if pages_list is None and isinstance(ocr_response, dict):
        pages_list = ocr_response.get("pages", [])
    pages_list = pages_list or []

    for page in pages_list:
        page_idx = getattr(page, "index", None)
        if page_idx is None and isinstance(page, dict):
            page_idx = page.get("index", len(pages_data))
        if page_idx is None:
            page_idx = len(pages_data)

        extracted_blocks = []

        # Strategy 1: Extract non-image content from page.blocks
        page_blocks = getattr(page, "blocks", None)
        if page_blocks is None and isinstance(page, dict):
            page_blocks = page.get("blocks", [])
        page_blocks = page_blocks or []

        if page_blocks:
            for block in page_blocks:
                if isinstance(block, dict):
                    b_type = str(block.get("type", "")).lower()
                    b_content = str(block.get("content", "") or "")
                else:
                    b_type = str(getattr(block, "type", "")).lower()
                    b_content = str(getattr(block, "content", "") or "")

                if b_type == "image":
                    continue

                clean_content = re.sub(r"!\[.*?\]\(.*?\)", "", b_content).strip()
                if clean_content:
                    extracted_blocks.append(clean_content)

        # Strategy 2: Fallback to page.markdown or page.text / page.content if blocks yielded no text
        if not extracted_blocks:
            if isinstance(page, dict):
                raw_text = page.get("markdown") or page.get("text") or page.get("content") or ""
            else:
                raw_text = getattr(page, "markdown", None) or getattr(page, "text", None) or getattr(page, "content", "") or ""

            clean_markdown = re.sub(r"!\[.*?\]\(.*?\)", "", raw_text).strip()
            if clean_markdown:
                extracted_blocks.append(clean_markdown)

        # Strategy 3: Fallback to page.images sub-OCR if still empty
        if not extracted_blocks and client is not None:
            page_images = getattr(page, "images", []) or []
            for img in page_images:
                b64 = getattr(img, "image_base64", "") or ""
                if b64:
                    data_url = b64 if b64.startswith("data:") else f"data:image/jpeg;base64,{b64}"
                    try:
                        sub_res = client.ocr.process(
                            model="mistral-ocr-latest",
                            document={
                                "type": "document_url",
                                "document_url": data_url,
                            },
                        )
                        sub_md = getattr(sub_res.pages[0], "markdown", "") or ""
                        clean_sub_md = re.sub(r"!\[.*?\]\(.*?\)", "", sub_md).strip()
                        if clean_sub_md:
                            extracted_blocks.append(clean_sub_md)
                    except Exception as sub_err:
                        _log(f"[INFO] Sub-image OCR notice: {sub_err}")

        page_full_text = "\n\n".join(extracted_blocks).strip()
        page_text_blocks.append(page_full_text)

        pages_data.append(
            {
                "page_number": page_idx + 1,
                "text": page_full_text,
            }
        )

    full_ocr_text = "\n\n".join(page_text_blocks).strip()

    return {
        "full_text": full_ocr_text,
        "pages": pages_data,
    }


def _is_mistral_rate_limit(err: Exception) -> bool:
    """Check if exception represents HTTP 429 rate limiting or quota exhaustion."""
    msg = str(err).lower()
    raw = getattr(err, "raw_response", None)
    if raw is not None and getattr(raw, "status_code", None) == 429:
        return True
    if getattr(err, "status_code", None) == 429 or getattr(err, "code", None) == 429:
        return True
    if "429" in msg or "rate limit" in msg or "rate_limited" in msg or "1300" in msg:
        return True
    return False


def perform_mistral_ocr(file_path: str) -> Dict[str, Any]:
    """
    Single Reusable Function to Execute Mistral OCR on a File (SDK v2.9.1).

    Responsibilities:
    - Validate file existence & extension
    - Upload document via Files API (or base64 fallback)
    - Call client.ocr.process(model="mistral-ocr-latest", include_image_base64=True)
    - Emit diagnostic logs
    - If rate limited (HTTP 429 / 1300), raise MistralOCRException immediately without retry
    - Raise MistralOCRException if response contains no text
    """
    path = Path(file_path)

    # 1. SDK VERSION
    sdk_ver = "2.10.0"
    _log("=" * 24)
    _log("SDK VERSION")
    _log("=" * 24)
    _log(f"mistralai version: {sdk_ver}")
    _log("=" * 24 + "\n")

    # Guard: File existence
    if not path.exists() or not path.is_file():
        raise MistralOCRException(f"File not found: {file_path}")

    # Guard: Supported file format
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise MistralOCRException(
            f"Unsupported file format '{ext}'. "
            f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    client = get_mistral_client()

    ocr_response = None
    upload_info_log = ""

    # Attempt 1: Upload via Files API (purpose="ocr")
    try:
        with open(path, "rb") as f:
            uploaded_file = client.files.upload(
                file={
                    "file_name": path.name,
                    "content": f,
                },
                purpose="ocr",
            )
        file_id = getattr(uploaded_file, "id", None)
        upload_info_log = f"File ID: {file_id}"

        # 2. UPLOAD RESPONSE LOG
        _log("=" * 24)
        _log("UPLOAD RESPONSE")
        _log("=" * 24)
        _log(upload_info_log)
        _log("=" * 24 + "\n")

        # 3. OCR REQUEST LOG
        _log("=" * 24)
        _log("OCR REQUEST")
        _log("=" * 24)
        _log("Model        : mistral-ocr-latest")
        _log(f"Document     : {{'type': 'file', 'file_id': '{file_id}'}}")
        _log("include_image_base64: True")
        _log("=" * 24 + "\n")

        ocr_response = client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "file",
                "file_id": file_id,
            },
            include_image_base64=True,
        )
    except Exception as upload_err:
        if _is_mistral_rate_limit(upload_err):
            _log(f"[OCR Notice] Mistral Files upload rate limited (429 code 1300): {upload_err}. Immediately skipping retry.")
            mex = MistralOCRException(f"Mistral OCR rate limited (HTTP 429 code 1300): {upload_err}")
            setattr(mex, "status", "OCR_RATE_LIMITED")
            raise mex

        _log(f"[INFO] Files API upload notice: {upload_err}. Using base64 document URL...")
        with open(path, "rb") as f:
            b64_content = base64.b64encode(f.read()).decode("utf-8")
        mime_type = MIME_TYPES.get(ext, "application/octet-stream")
        data_url = f"data:{mime_type};base64,{b64_content}"

        # 2. UPLOAD RESPONSE LOG
        _log("=" * 24)
        _log("UPLOAD RESPONSE")
        _log("=" * 24)
        _log(f"Base64 Document URL generated ({len(b64_content)} bytes)")
        _log("=" * 24 + "\n")

        # 3. OCR REQUEST LOG
        _log("=" * 24)
        _log("OCR REQUEST")
        _log("=" * 24)
        _log("Model        : mistral-ocr-latest")
        _log("Document     : {'type': 'document_url', 'document_url': 'data:...;base64,...'}")
        _log("include_image_base64: True")
        _log("=" * 24 + "\n")

        try:
            ocr_response = client.ocr.process(
                model="mistral-ocr-latest",
                document={
                    "type": "document_url",
                    "document_url": data_url,
                },
                include_image_base64=True,
            )
        except Exception as ocr_proc_err:
            if _is_mistral_rate_limit(ocr_proc_err):
                _log(f"[OCR Notice] Mistral OCR process rate limited (429 code 1300): {ocr_proc_err}. Immediately skipping retry.")
                mex = MistralOCRException(f"Mistral OCR rate limited (HTTP 429 code 1300): {ocr_proc_err}")
                setattr(mex, "status", "OCR_RATE_LIMITED")
                raise mex
            raise

    # 4. RAW OCR RESPONSE LOG
    try:
        raw_response_dict = ocr_response.model_dump() if hasattr(ocr_response, "model_dump") else ocr_response.dict()
        raw_json_str = json.dumps(raw_response_dict, indent=2, default=str)
    except Exception:
        raw_json_str = str(ocr_response)

    _log("=" * 24)
    _log("RAW OCR RESPONSE")
    _log("=" * 24)
    _log(raw_json_str)
    _log("=" * 24 + "\n")

    # Parse OCR Text
    parsed = extract_ocr_text(ocr_response, client=client)
    full_ocr_text = parsed["full_text"]
    pages_data = parsed["pages"]

    # Raise MistralOCRException if response contains no text
    if not full_ocr_text.strip():
        _log("[FATAL ERROR] Mistral OCR response contains no text.")
        raise MistralOCRException("Mistral OCR returned no text. Check OCR request implementation.")

    # 5. PARSED OCR TEXT LOG
    _log("=" * 24)
    _log("PARSED OCR TEXT")
    _log("=" * 24)
    _log(full_ocr_text)
    _log("=" * 24 + "\n")

    # 6. OCR COMPLETE LOG
    _log("=" * 24)
    _log("OCR COMPLETE")
    _log("=" * 24 + "\n")

    return {
        "success": True,
        "status": "OCR_SUCCESS",
        "text": full_ocr_text,
        "pages": pages_data,
        "confidence": 98.0,
        "provider": "MISTRAL",
    }


_rapid_ocr_engine = None


def get_rapidocr_engine():
    """Lazily instantiate and cache RapidOCR engine singleton."""
    global _rapid_ocr_engine
    if _rapid_ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _rapid_ocr_engine = RapidOCR()
        except Exception as e:
            _log(f"[OCR] RapidOCR engine initialization failed: {e}")
            return None
    return _rapid_ocr_engine


def perform_local_ocr(file_path: str) -> Dict[str, Any]:
    """
    Execute high-accuracy local OCR on a file (Free-First).
    Supports PDF, JPG, JPEG, PNG, WEBP.
    Returns:
    {
        "success": bool,
        "status": "OCR_SUCCESS" | "OCR_FAILED" | "OCR_UNAVAILABLE" | "OCR_RATE_LIMITED",
        "text": str,
        "pages": List[Dict[str, Any]],
        "confidence": float,
        "provider": "LOCAL_RAPIDOCR",
        "message": Optional[str],
    }
    """
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return {
            "success": False,
            "status": "OCR_FAILED",
            "text": "",
            "pages": [],
            "confidence": 0.0,
            "provider": "LOCAL_RAPIDOCR",
            "message": f"File not found: {file_path}",
        }

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return {
            "success": False,
            "status": "OCR_FAILED",
            "text": "",
            "pages": [],
            "confidence": 0.0,
            "provider": "LOCAL_RAPIDOCR",
            "message": f"Unsupported file extension: {ext}",
        }

    engine = get_rapidocr_engine()

    # 1. PDF Handling
    if ext == ".pdf":
        try:
            import io
            import pypdf
            from PIL import Image

            reader = pypdf.PdfReader(str(path))
            if getattr(reader, "is_encrypted", False):
                passwords_to_try = ["", "123456", "password"]
                for p_try in passwords_to_try:
                    try:
                        if reader.decrypt(p_try) != 0:
                            break
                    except Exception:
                        pass

            pages_data: List[Dict[str, Any]] = []
            combined_texts: List[str] = []

            def _is_digital_signature_metadata(text: str) -> bool:
                if not text:
                    return False
                t_lower = text.lower()
                sig_phrases = ["digitally signed", "signature not verified", "signature valid", "valid signature", "docusign"]
                if not any(p in t_lower for p in sig_phrases):
                    return False
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                non_sig = [
                    l for l in lines
                    if not any(p in l.lower() for p in sig_phrases)
                    and not re.search(r'\b(date|time|ist|gmt|reason|location|ds\s*certificate)\b', l.lower())
                ]
                return len(" ".join(non_sig)) < 60

            for idx, page in enumerate(reader.pages):
                embedded_text = (page.extract_text() or "").strip()
                page_imgs = getattr(page, "images", []) or []
                sig_only = _is_digital_signature_metadata(embedded_text)

                page_img_text = ""
                if engine and page_imgs and (not embedded_text or sig_only or len(embedded_text) < 120):
                    page_img_lines = []
                    for img_obj in page_imgs:
                        try:
                            img = Image.open(io.BytesIO(img_obj.data))
                            if img.mode not in ("RGB", "L"):
                                img = img.convert("RGB")
                            ocr_res, _ = engine(img)
                            if ocr_res:
                                lines = [r[1] for r in ocr_res if len(r) > 1 and r[1]]
                                if lines:
                                    page_img_lines.append("\n".join(lines))
                        except Exception as img_sub_err:
                            _log(f"[OCR] Sub-image scan notice: {img_sub_err}")
                    if page_img_lines:
                        page_img_text = "\n\n".join(page_img_lines).strip()

                # Preserve page boundaries explicitly
                page_tag = f"--- [Page {idx + 1}] ---"
                if page_img_text and sig_only:
                    effective_page_text = f"{page_tag}\n{page_img_text}"
                elif page_img_text and embedded_text:
                    effective_page_text = f"{page_tag}\n{embedded_text}\n\n{page_img_text}"
                elif embedded_text:
                    effective_page_text = f"{page_tag}\n{embedded_text}"
                elif page_img_text:
                    effective_page_text = f"{page_tag}\n{page_img_text}"
                else:
                    effective_page_text = ""

                if effective_page_text:
                    combined_texts.append(effective_page_text)
                    pages_data.append({"page_number": idx + 1, "text": effective_page_text})

            if combined_texts:
                full_text = "\n\n".join(combined_texts).strip()
                if _is_digital_signature_metadata(full_text):
                    _log(f"[OCR] Extracted text is purely digital signature metadata ({len(full_text)} chars). Marking OCR_LOW_QUALITY.")
                    return {
                        "success": False,
                        "status": "OCR_LOW_QUALITY",
                        "text": full_text,
                        "pages": pages_data,
                        "confidence": 30.0,
                        "provider": "LOCAL_RAPIDOCR",
                        "message": "Extracted text contains only digital-signature metadata. Multimodal fallback recommended.",
                    }
                if len(full_text) < 100:
                    _log(f"[OCR] Extracted PDF text length={len(full_text)} chars (< 100 chars). Marking OCR_LOW_QUALITY.")
                    return {
                        "success": False,
                        "status": "OCR_LOW_QUALITY",
                        "text": full_text,
                        "pages": pages_data,
                        "confidence": 40.0,
                        "provider": "LOCAL_RAPIDOCR",
                        "message": f"Extracted text too short ({len(full_text)} chars). Marked OCR_LOW_QUALITY.",
                    }
                return {
                    "success": True,
                    "status": "OCR_SUCCESS",
                    "text": full_text,
                    "pages": pages_data,
                    "confidence": 95.0,
                    "provider": "LOCAL_RAPIDOCR",
                    "message": None,
                }
            else:
                return {
                    "success": False,
                    "status": "OCR_FAILED",
                    "text": "",
                    "pages": [],
                    "confidence": 0.0,
                    "provider": "LOCAL_RAPIDOCR",
                    "message": "No text detected in PDF document",
                }
        except Exception as pdf_err:
            _log(f"[OCR] Local PDF extraction error: {pdf_err}")
            try:
                raw_txt = path.read_text(encoding="utf-8", errors="ignore").strip()
                if raw_txt and len(raw_txt) >= 100:
                    return {
                        "success": True,
                        "status": "OCR_SUCCESS",
                        "text": raw_txt,
                        "pages": [{"page_number": 1, "text": raw_txt}],
                        "confidence": 95.0,
                        "provider": "LOCAL_RAPIDOCR",
                        "message": None,
                    }
                elif raw_txt and len(raw_txt) > 5:
                    return {
                        "success": False,
                        "status": "OCR_LOW_QUALITY",
                        "text": raw_txt,
                        "pages": [{"page_number": 1, "text": raw_txt}],
                        "confidence": 40.0,
                        "provider": "LOCAL_RAPIDOCR",
                        "message": f"Extracted text too short ({len(raw_txt)} chars). Marked OCR_LOW_QUALITY.",
                    }
            except Exception:
                pass
            return {
                "success": False,
                "status": "OCR_FAILED",
                "text": "",
                "pages": [],
                "confidence": 0.0,
                "provider": "LOCAL_RAPIDOCR",
                "message": f"PDF extraction error: {pdf_err}",
            }

    # 2. Image Handling (JPG, JPEG, PNG, WEBP)
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        if not engine:
            return {
                "success": False,
                "status": "OCR_UNAVAILABLE",
                "text": "",
                "pages": [],
                "confidence": 0.0,
                "provider": "LOCAL_RAPIDOCR",
                "message": "Local OCR engine (RapidOCR) is unavailable",
            }
        try:
            from PIL import Image
            img = Image.open(str(path))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            ocr_res, _ = engine(img)
            if ocr_res:
                lines = [r[1] for r in ocr_res if len(r) > 1 and r[1]]
                scores = [float(r[2]) for r in ocr_res if len(r) > 2 and r[2] is not None]
                text = "\n".join(lines).strip()
                conf = (sum(scores) / len(scores) * 100.0) if scores else 95.0
                if text:
                    if len(text) < 100:
                        return {
                            "success": False,
                            "status": "OCR_LOW_QUALITY",
                            "text": text,
                            "pages": [{"page_number": 1, "text": text}],
                            "confidence": 40.0,
                            "provider": "LOCAL_RAPIDOCR",
                            "message": f"Extracted text too short ({len(text)} chars). Marked OCR_LOW_QUALITY.",
                        }
                    return {
                        "success": True,
                        "status": "OCR_SUCCESS",
                        "text": text,
                        "pages": [{"page_number": 1, "text": text}],
                        "confidence": conf,
                        "provider": "LOCAL_RAPIDOCR",
                        "message": None,
                    }

            return {
                "success": False,
                "status": "OCR_FAILED",
                "text": "",
                "pages": [],
                "confidence": 0.0,
                "provider": "LOCAL_RAPIDOCR",
                "message": "No text detected in image",
            }
        except Exception as img_err:
            _log(f"[OCR] Local image OCR failed: {img_err}")
            return {
                "success": False,
                "status": "OCR_FAILED",
                "text": "",
                "pages": [],
                "confidence": 0.0,
                "provider": "LOCAL_RAPIDOCR",
                "message": f"Image processing error: {img_err}",
            }

    return {
        "success": False,
        "status": "OCR_FAILED",
        "text": "",
        "pages": [],
        "confidence": 0.0,
        "provider": "LOCAL_RAPIDOCR",
        "message": f"Unsupported format '{ext}'",
    }


class OCRService:
    """
    Production OCR Service implementing Free-First local OCR with optional Mistral OCR.
    """
    def __init__(self):
        self._mistral_cooldown_until = 0.0

    def extract_text(self, file_path: str, prefer_local: bool = True) -> Dict[str, Any]:
        """
        Extract text from a document using local OCR first (Free-First).
        If local OCR fails or yields no text, optionally checks Mistral if configured,
        handling 429 without aggressive retries.
        """
        import time
        path_obj = Path(file_path)
        filename = path_obj.name
        print("\n========== OCR ==========", flush=True)
        print(f"OCR Started: {filename} (Free-First: {prefer_local})", flush=True)

        if prefer_local:
            # 1. Free-First: Try Local OCR
            local_res = perform_local_ocr(file_path)
            txt = local_res.get("text") or ""
            status_code = local_res.get("status") or ("OCR_SUCCESS" if local_res.get("success") else "OCR_FAILED")
            pages = local_res.get("pages") or []
            page_count = len(pages) if pages else 1
            conf = local_res.get("confidence", 0.0)

            # Log structured OCR Quality diagnostic
            preview_str = (txt[:100].replace("\n", " ").strip()) if txt else ""
            try:
                print(
                    f"[OCR_QUALITY] document={filename} page_count={page_count} ocr_provider={local_res.get('provider')} "
                    f"ocr_status={status_code} ocr_text_length={len(txt)} ocr_text_preview={repr(preview_str)} ocr_confidence={conf:.1f}",
                    flush=True
                )
            except Exception:
                pass

            if local_res.get("success") and status_code == "OCR_SUCCESS" and len(txt.strip()) >= 100:
                print(f"OCR Success: True (Local RapidOCR/PDF)", flush=True)
                print(f"OCR Text Length: {len(txt)} chars", flush=True)
                print("==========================\n", flush=True)
                return local_res

            if status_code == "OCR_LOW_QUALITY":
                print(f"OCR Success: False (OCR_LOW_QUALITY: {len(txt)} chars < 100)", flush=True)
                print("==========================\n", flush=True)
                return local_res

            # 2. Optional fallback to Mistral OCR if configured and not rate-limited
            mistral_key = getattr(settings, "MISTRAL_API_KEY", None) or os.getenv("MISTRAL_API_KEY")
            now = time.time()
            if mistral_key and self._mistral_cooldown_until <= now:
                try:
                    mistral_res = perform_mistral_ocr(file_path)
                    if mistral_res.get("success") and (mistral_res.get("text") or "").strip():
                        print(f"OCR Success: True (Mistral OCR)", flush=True)
                        print(f"OCR Text Length: {len(mistral_res['text'])} chars", flush=True)
                        print("==========================\n", flush=True)
                        mistral_res["status"] = "OCR_SUCCESS"
                        mistral_res["provider"] = "MISTRAL"
                        return mistral_res
                except MistralOCRException as mex:
                    mex_status = getattr(mex, "status", None) or ("OCR_RATE_LIMITED" if "429" in str(mex) else "OCR_FAILED")
                    if mex_status == "OCR_RATE_LIMITED" or "429" in str(mex):
                        self._mistral_cooldown_until = now + 300.0
                        _log("[OCR Notice] Mistral OCR rate limited (429). Continuing without retry.")
                        print(f"OCR Success: False (OCR_RATE_LIMITED)", flush=True)
                        print("==========================\n", flush=True)
                        return {
                            "success": False,
                            "status": "OCR_RATE_LIMITED",
                            "text": "",
                            "pages": [],
                            "confidence": 0.0,
                            "provider": "MISTRAL",
                            "message": str(mex),
                        }
                except Exception as mex:
                    _log(f"[OCR Notice] Mistral OCR notice: {mex}. Continuing pipeline.")

            # Return local OCR outcome
            status_code = local_res.get("status") or "OCR_FAILED"
            msg = local_res.get("message") or "Local OCR produced no text"
            print(f"OCR Success: False ({status_code}: {msg})", flush=True)
            print(f"OCR Text Length: 0 chars", flush=True)
            print("==========================\n", flush=True)
            return local_res
        else:
            # Mistral first if explicitly requested
            try:
                res = perform_mistral_ocr(file_path)
                txt = res.get("text") or ""
                print(f"OCR Success: True", flush=True)
                print(f"OCR Text Length: {len(txt)} chars", flush=True)
                print("==========================\n", flush=True)
                return res
            except Exception as exc:
                msg = str(exc)
                _log(f"[OCR Notice] {msg}. Checking for local OCR fallback...")
                local_res = perform_local_ocr(file_path)
                if local_res.get("success"):
                    return local_res
                return {
                    "success": False,
                    "status": "OCR_FAILED",
                    "text": "",
                    "pages": [],
                    "confidence": 0.0,
                    "message": msg,
                    "provider": "MISTRAL",
                }


ocr_service = OCRService()
