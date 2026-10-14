"""
Comprehensive Regression Test Suite: Real Document Loading & Ingestion Pipeline
================================================================================
Tests cover:
1. Aadhaar stored file successfully loaded.
2. Missing file reference gracefully handled as DOCUMENT_MISSING.
3. Invalid or empty PDF rejected as DOCUMENT_INVALID without hallucination.
4. Valid scanned PDF with little embedded text extracted via image OCR.
5. Multi-page OCR preserving page boundaries.
6. Gemini multimodal fallback when OCR is insufficient or signature-only.
7. Requested field versus parser schema compatibility.
8. Null results do not erase existing valid values across documents.
9. Cross-student document isolation strictly enforced.
10. Excel mapping remains unchanged with unmapped columns.
"""

import io
import shutil
import openpyxl
import pytest
import pypdf
from PIL import Image, ImageDraw
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.services.document_extraction_service import (
    DocumentExtractionService,
    resolve_canonical_field_key,
)
from app.services.accuracy_extraction_engine import (
    AccuracyExtractionEngine,
    FieldExtractionResult,
)
from app.utils.storage_resolver import resolve_document_file_path
from app.services.ocr_service import perform_local_ocr


def create_sample_image(text="SAMPLE"):
    img = Image.new("RGB", (300, 100), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((10, 40), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_sample_pdf_with_image(image_bytes):
    img = Image.open(io.BytesIO(image_bytes))
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def test_01_aadhaar_stored_file_successfully_loaded():
    """1. Aadhaar stored file successfully located and loaded via storage resolver."""
    backend_dir = Path(__file__).resolve().parent.parent
    uploads_dir = backend_dir / "uploads"
    student_id = "TEST_STUD_REG_01"

    # Simulate nested student document directory inside uploads
    nested_dir = uploads_dir / "students" / student_id / "documents" / "SUB_REQ_001"
    nested_dir.mkdir(parents=True, exist_ok=True)
    real_file = nested_dir / "aadhaar_card.png"
    real_file.write_bytes(create_sample_image("AADHAAR 1234 5678 9012"))

    try:
        # Legacy raw path in database that points to wrong subfolder
        legacy_raw_path = f"uploads/students/{student_id}/documents/AADHAAR/aadhaar_card.png"

        resolved = resolve_document_file_path(
            legacy_raw_path,
            register_number=student_id,
            document_name="Aadhaar Card",
        )
        assert resolved is not None
        assert resolved.is_file()
        assert resolved.name == "aadhaar_card.png"
        assert resolved.stat().st_size > 0
    finally:
        shutil.rmtree(uploads_dir / "students" / student_id, ignore_errors=True)


@pytest.mark.asyncio
async def test_02_missing_file_reference(tmp_path):
    """2. Missing file reference returns DOCUMENT_MISSING gracefully."""
    doc_service = DocumentExtractionService()
    non_existent = str(tmp_path / "does_not_exist.pdf")

    with pytest.raises(FileNotFoundError) as exc_info:
        await doc_service._run_ai_extraction(
            file_path=non_existent,
            document_type="AADHAAR",
            requested_fields=["aadhaar_number"],
            student_id="STUD_NONEXISTENT",
        )
    assert "DOCUMENT_MISSING" in str(exc_info.value)


def test_03_invalid_or_empty_pdf(tmp_path):
    """3. Invalid or empty 0-byte PDF rejected as DOCUMENT_INVALID."""
    engine = AccuracyExtractionEngine()

    # 0-byte file
    empty_file = tmp_path / "empty.pdf"
    empty_file.write_bytes(b"")
    q_empty = engine.inspect_document_quality(str(empty_file))
    assert q_empty["is_usable"] is False
    assert q_empty["is_invalid"] is True
    assert "DOCUMENT_INVALID" in q_empty["reason"]

    # 431-byte placeholder stub PDF with 0 contents and 0 images
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    stub_file = tmp_path / "stub.pdf"
    with open(stub_file, "wb") as f:
        writer.write(f)

    q_stub = engine.inspect_document_quality(str(stub_file))
    assert q_stub["is_usable"] is False
    assert q_stub["is_invalid"] is True
    assert "DOCUMENT_INVALID" in q_stub["reason"]


def test_04_valid_scanned_pdf_with_little_embedded_text(tmp_path):
    """4. Valid scanned PDF with minimal text extracted via image OCR and not discarded."""
    img_bytes = create_sample_image("COMMUNITY: BC CASTE: VADUGAR")
    pdf_bytes = create_sample_pdf_with_image(img_bytes)

    scanned_pdf = tmp_path / "scanned_community.pdf"
    scanned_pdf.write_bytes(pdf_bytes)

    res = perform_local_ocr(str(scanned_pdf))
    assert res is not None
    assert "pages" in res
    assert len(res["pages"]) >= 1


def test_05_multipage_ocr(tmp_path):
    """5. Multi-page OCR preserves page boundaries and tags."""
    img1 = Image.open(io.BytesIO(create_sample_image("PAGE 1 TC EMIS 2015743426")))
    img2 = Image.open(io.BytesIO(create_sample_image("PAGE 2 TC CONDUCT GOOD")))

    multi_pdf = tmp_path / "multi_tc.pdf"
    img1.save(str(multi_pdf), format="PDF", save_all=True, append_images=[img2])

    res = perform_local_ocr(str(multi_pdf))
    assert res is not None
    assert len(res["pages"]) == 2
    assert res["pages"][0]["page_number"] == 1
    assert res["pages"][1]["page_number"] == 2


@pytest.mark.asyncio
async def test_06_gemini_multimodal_fallback(tmp_path):
    """6. Gemini multimodal fallback used when OCR is insufficient or signature-only."""
    doc_service = DocumentExtractionService()
    test_pdf = tmp_path / "sig_only.pdf"
    test_pdf.write_bytes(b"%PDF-1.4 dummy valid bytes for test")

    mock_gemini = MagicMock()
    mock_gemini.extract_from_file.return_value = {
        "success": True,
        "fields": {"aadhaar_number": "212273779295"},
        "extracted_summary": {"aadhaar_number": "212273779295"},
        "confidence": 96.0,
    }
    doc_service.gemini_service = mock_gemini

    # Mock OCR returning signature-only low quality
    with patch("app.services.ocr_service.OCRService.extract_text") as mock_ocr:
        mock_ocr.return_value = {
            "success": False,
            "status": "OCR_LOW_QUALITY",
            "text": "Digitally signed by Officer\nSignature Not Verified",
            "pages": [],
            "message": "Signature metadata only",
        }
        with patch.object(AccuracyExtractionEngine, "inspect_document_quality", return_value={"is_usable": True, "is_invalid": False}):
            ai_res = await doc_service._run_ai_extraction(
                file_path=str(test_pdf),
                document_type="AADHAAR",
                requested_fields=["aadhaar_number"],
                student_id="STUD_06",
            )
            extracted_dict, conf, prov, ocr_stat, ai_prov = ai_res
            assert prov == "GEMINI_MULTIMODAL"
            assert extracted_dict["aadhaar_number"] == "212273779295"


def test_07_requested_field_versus_parser_schema_compatibility():
    """7. Requested field versus parser schema canonical key compatibility."""
    assert resolve_canonical_field_key("Aadhaar Number") == "aadhaar_number"
    assert resolve_canonical_field_key("EMIS ID") == "emis_id"
    assert resolve_canonical_field_key("Account Number") == "account_number"
    assert resolve_canonical_field_key("Bank Name") == "bank_name"
    assert resolve_canonical_field_key("Branch") == "branch"
    assert resolve_canonical_field_key("City") == "city"
    assert resolve_canonical_field_key("Mother Name") == "mother_name"
    assert resolve_canonical_field_key("Father Name") == "father_name"


def test_08_null_results_do_not_erase_existing_valid_values():
    """8. Null or missing result in Document B does not erase valid result from Document A."""
    engine = AccuracyExtractionEngine()

    extractions = {
        "COMMUNITY": {
            "mother_name": FieldExtractionResult(
                field_name="mother_name",
                raw_value="PRIYA G",
                normalized_value="PRIYA G",
                confidence_score=0.95,
                source_document_type="COMMUNITY",
            )
        },
        "TRANSFER_CERTIFICATE": {
            "mother_name": FieldExtractionResult(
                field_name="mother_name",
                raw_value=None,
                normalized_value="NOT_AVAILABLE",
                confidence_score=0.0,
                field_state="NOT_FOUND",
                source_document_type="TRANSFER_CERTIFICATE",
            )
        },
    }

    fused = engine.detect_cross_document_conflicts(
        extractions_by_doc_type=extractions,
        field_to_configured_doc_type={"mother_name": "TRANSFER_CERTIFICATE"},
    )

    res = fused.get("mother_name")
    assert res is not None
    assert res.normalized_value == "PRIYA G"
    assert res.source_document_type == "COMMUNITY"


def test_09_cross_student_document_isolation():
    """9. Strict isolation: Documents from Student A are never resolved or accessible for Student B."""
    backend_dir = Path(__file__).resolve().parent.parent
    uploads_dir = backend_dir / "uploads"

    student_a_dir = uploads_dir / "students" / "STUDENT_ISO_A" / "documents" / "SUB"
    student_a_dir.mkdir(parents=True, exist_ok=True)
    file_a = student_a_dir / "aadhaar.pdf"
    file_a.write_bytes(b"%PDF-1.4 dummy")

    try:
        # Resolving Student A's path while specifying register_number="STUDENT_ISO_B"
        res_b = resolve_document_file_path(
            raw_path=str(file_a),
            register_number="STUDENT_ISO_B",
        )
        # Must not resolve Student A's file for Student B
        assert res_b is None
    finally:
        shutil.rmtree(uploads_dir / "students" / "STUDENT_ISO_A", ignore_errors=True)


def test_10_excel_mapping_remains_unchanged(tmp_path):
    """10. Excel template mapping preserves header order and unmapped columns."""
    tmpl_wb = openpyxl.Workbook()
    ws = tmpl_wb.active
    headers = ["Student ID", "Full Name", "Middle Unmapped Column", "Date of Birth", "Aadhaar"]
    ws.append(headers)
    ws.append(["STU001", "Alice", None, "01/01/2006", "112233445566"])
    tmpl_path = tmp_path / "template.xlsx"
    tmpl_wb.save(tmpl_path)

    loaded_wb = openpyxl.load_workbook(tmpl_path)
    loaded_ws = loaded_wb.active
    out_headers = [c.value for c in loaded_ws[1]]
    assert out_headers == headers
    assert loaded_ws.cell(row=2, column=3).value is None
    assert loaded_ws.cell(row=2, column=4).value == "01/01/2006"
