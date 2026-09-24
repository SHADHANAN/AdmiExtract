import io
import re
import logging
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageOps
from pypdf import PdfWriter, PdfReader

from app.models.student_submission import StudentSubmission, StudentDocumentMeta
from app.utils.storage_resolver import resolve_document_file_path

logger = logging.getLogger(__name__)


class NoDocumentsAvailableException(Exception):
    """Raised when no valid, uploaded documents are available for combining."""
    pass


class DocumentMergeService:
    """
    Service responsible for consolidating all uploaded documents for a student submission
    into a single combined PDF document for download.
    """

    @staticmethod
    def get_ordered_documents(submission: StudentSubmission) -> list[StudentDocumentMeta]:
        """
        Determines the document sequence:
        Uses the configured requirements order if available in snapshot,
        otherwise falls back to the submission's document order.
        """
        if not submission.documents:
            return []

        # If document_requirements_snapshot is configured, prioritize that order
        snapshot = submission.document_requirements_snapshot or []
        if snapshot:
            snapshot_order: dict[str, int] = {}
            for idx, req in enumerate(snapshot):
                req_name = req.get("name", "").strip().lower()
                if req_name and req_name not in snapshot_order:
                    snapshot_order[req_name] = idx

            # Sort documents matching snapshot order, keeping others at the end
            def sort_key(doc: StudentDocumentMeta) -> tuple[int, int]:
                name_key = doc.document_name.strip().lower()
                if name_key in snapshot_order:
                    return (0, snapshot_order[name_key])
                return (1, 9999)

            return sorted(submission.documents, key=sort_key)

        return list(submission.documents)

    @classmethod
    def convert_image_to_pdf_bytes(cls, img_path: Path) -> bytes:
        """
        Converts an image file (JPG, JPEG, PNG, WebP, etc.) into high-quality PDF bytes.
        Handles transparency, alpha channels, palette mode, and EXIF orientation.
        """
        with Image.open(img_path) as img:
            # Respect EXIF orientation if present
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            # Handle multi-frame or single frame
            frames: list[Image.Image] = []
            try:
                while True:
                    frame = img.copy()
                    if frame.mode in ("RGBA", "LA"):
                        bg = Image.new("RGB", frame.size, (255, 255, 255))
                        alpha = frame.split()[-1]
                        bg.paste(frame, mask=alpha)
                        frames.append(bg)
                    elif frame.mode == "P":
                        frame_rgba = frame.convert("RGBA")
                        bg = Image.new("RGB", frame.size, (255, 255, 255))
                        bg.paste(frame_rgba, mask=frame_rgba.split()[-1])
                        frames.append(bg)
                    elif frame.mode != "RGB":
                        frames.append(frame.convert("RGB"))
                    else:
                        frames.append(frame)
                    img.seek(img.tell() + 1)
            except EOFError:
                pass
            except Exception:
                pass

            if not frames:
                if img.mode in ("RGBA", "LA"):
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[-1])
                    frames = [bg]
                elif img.mode != "RGB":
                    frames = [img.convert("RGB")]
                else:
                    frames = [img.copy()]

            out_io = io.BytesIO()
            first_frame = frames[0]
            rest_frames = frames[1:]
            first_frame.save(
                out_io,
                format="PDF",
                save_all=bool(rest_frames),
                append_images=rest_frames,
                resolution=150.0,
            )
            return out_io.getvalue()

    @classmethod
    def generate_all_documents_pdf(
        cls, submission: StudentSubmission
    ) -> Tuple[bytes, str, int]:
        """
        Combines all available, uploaded documents for a student submission into a single PDF.

        Returns:
            Tuple[bytes, str, int]: (pdf_content_bytes, sanitized_filename, count_of_documents_included)

        Raises:
            NoDocumentsAvailableException: If no uploaded/stored documents could be found or converted.
        """
        ordered_docs = cls.get_ordered_documents(submission)
        writer = PdfWriter()
        included_count = 0

        for doc in ordered_docs:
            if doc.status != "Uploaded" or not doc.file_path:
                continue

            resolved_path = resolve_document_file_path(
                raw_path=doc.file_path,
                batch_id=submission.batch_id,
                register_number=submission.register_number,
                document_name=doc.document_name,
            )

            if not resolved_path or not resolved_path.is_file():
                logger.warning(
                    f"[generate_all_documents_pdf] Document '{doc.document_name}' file not found on server at {doc.file_path}. Skipping."
                )
                continue

            try:
                if resolved_path.stat().st_size == 0:
                    logger.warning(
                        f"[generate_all_documents_pdf] Document '{doc.document_name}' file is 0 bytes. Skipping."
                    )
                    continue

                # Check if file is PDF (by extension or magic bytes)
                is_pdf = False
                if resolved_path.suffix.lower() == ".pdf":
                    is_pdf = True
                else:
                    with open(resolved_path, "rb") as f:
                        header = f.read(5)
                        if header.startswith(b"%PDF"):
                            is_pdf = True

                if is_pdf:
                    reader = PdfReader(str(resolved_path), strict=False)
                    if reader.is_encrypted:
                        try:
                            reader.decrypt("")
                        except Exception:
                            logger.warning(f"[generate_all_documents_pdf] PDF '{doc.document_name}' is password encrypted. Skipping.")
                            continue
                    for page in reader.pages:
                        writer.add_page(page)
                    included_count += 1
                else:
                    # Treat as image
                    img_pdf_bytes = cls.convert_image_to_pdf_bytes(resolved_path)
                    reader = PdfReader(io.BytesIO(img_pdf_bytes), strict=False)
                    for page in reader.pages:
                        writer.add_page(page)
                    included_count += 1

            except Exception as doc_err:
                logger.error(
                    f"[generate_all_documents_pdf] Error processing document '{doc.document_name}': {doc_err}. Skipping."
                )
                continue

        if len(writer.pages) == 0 or included_count == 0:
            raise NoDocumentsAvailableException("No documents available for download.")

        out_io = io.BytesIO()
        writer.write(out_io)
        pdf_bytes = out_io.getvalue()

        # Build clean filename: StudentName_RegNumber_All_Documents.pdf
        clean_name = re.sub(r"[^a-zA-Z0-9_-]", "_", (submission.student_name or "Student").strip()).strip("_") or "Student"
        clean_reg = re.sub(r"[^a-zA-Z0-9_-]", "_", (submission.register_number or "Documents").strip()).strip("_") or "Documents"
        filename = f"{clean_name}_{clean_reg}_All_Documents.pdf"

        return pdf_bytes, filename, included_count
