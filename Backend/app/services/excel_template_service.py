import io
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from fastapi import HTTPException, status

from app.models.excel_template import ExcelBatchTemplate
from app.services.document_extraction_service import resolve_canonical_field_key

logger = logging.getLogger("app.services.excel_template_service")

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
UPLOADS_DIR = BACKEND_DIR / "uploads"
TEMPLATES_DIR = UPLOADS_DIR / "excel_templates"


class ExcelTemplateService:
    """
    Authoritative service for uploading, parsing, storing, retrieving, and managing
    Excel templates used during Data Extraction and Export.
    """

    def __init__(self):
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    def parse_workbook_structure(
        self, file_content: bytes, filename: str
    ) -> Dict[str, Any]:
        """
        Parse an uploaded Excel workbook to extract exact sheets, header row index,
        exact column headers, 1-based column indices, and sample rows.
        """
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Excel file format: {str(e)}",
            )

        sheet_names = wb.sheetnames
        if not sheet_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Excel file contains no worksheets.",
            )

        sheet = wb.active or wb.worksheets[0]
        sheet_name = sheet.title

        if sheet.max_row < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Excel file worksheet appears to be empty.",
            )

        header_row_idx = 1
        headers: List[str] = []
        column_indices: Dict[str, int] = {}

        # Detect the header row by scanning first 10 rows
        for r_idx in range(1, min(sheet.max_row + 1, 10)):
            row_cells = sheet[r_idx]
            detected_headers: List[str] = []
            col_map: Dict[str, int] = {}
            for col_idx, cell in enumerate(row_cells, start=1):
                val = cell.value
                if val is not None:
                    hdr_str = str(val).strip()
                    if hdr_str:
                        detected_headers.append(hdr_str)
                        col_map[hdr_str] = col_idx
            if len(detected_headers) >= 1:
                headers = detected_headers
                column_indices = col_map
                header_row_idx = r_idx
                break

        if not headers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not detect column headers in the uploaded Excel template.",
            )

        column_mapping: Dict[str, str] = {}
        canonical_fields: List[str] = []
        seen_canonical = set()

        for col_name in headers:
            canon = resolve_canonical_field_key(col_name)
            if not canon:
                canon = re.sub(r'[^a-zA-Z0-9_]+', '_', col_name.strip().lower()).strip('_')
            column_mapping[col_name] = canon
            if canon not in seen_canonical:
                canonical_fields.append(canon)
                seen_canonical.add(canon)

        student_rows_count = max(0, sheet.max_row - header_row_idx)
        sample_rows: List[Dict[str, Any]] = []
        if student_rows_count > 0:
            for r_idx in range(header_row_idx + 1, min(header_row_idx + 6, sheet.max_row + 1)):
                row_dict: Dict[str, Any] = {}
                for col_name, c_idx in column_indices.items():
                    val = sheet.cell(row=r_idx, column=c_idx).value
                    row_dict[col_name] = str(val).strip() if val is not None else ""
                if any(row_dict.values()):
                    sample_rows.append(row_dict)

        return {
            "sheet_name": sheet_name,
            "sheet_names": sheet_names,
            "header_row_index": header_row_idx,
            "headers": headers,
            "column_indices": column_indices,
            "column_mapping": column_mapping,
            "canonical_fields": canonical_fields,
            "total_columns": len(headers),
            "detected_students_count": student_rows_count,
            "sample_rows": sample_rows,
        }

    async def save_template_file(
        self,
        file_content: bytes,
        filename: str,
        batch_id: str,
        class_id: Optional[str] = None,
        department_id: Optional[str] = None,
        uploaded_by: str = "system",
    ) -> ExcelBatchTemplate:
        """
        Parse, persist template to disk, and save/update ExcelBatchTemplate document in database.
        """
        parsed = self.parse_workbook_structure(file_content, filename)
        clean_class = class_id.strip() if class_id and class_id.strip().lower() not in ("none", "null", "undefined", "") else None

        # Create unique filename on disk
        clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
        disk_filename = f"batch_{batch_id}_{uuid.uuid4().hex[:8]}_{clean_name}"
        saved_file_path = TEMPLATES_DIR / disk_filename

        with open(saved_file_path, "wb") as f:
            f.write(file_content)

        # Check existing template record
        existing = await ExcelBatchTemplate.find_one({
            "batch_id": batch_id,
            "class_id": clean_class,
        })

        if existing:
            existing.template_filename = filename
            existing.file_path = str(saved_file_path)
            existing.sheet_name = parsed["sheet_name"]
            existing.sheet_names = parsed["sheet_names"]
            existing.header_row_index = parsed["header_row_index"]
            existing.headers = parsed["headers"]
            existing.column_indices = parsed["column_indices"]
            existing.total_columns = parsed["total_columns"]
            existing.total_rows = parsed["detected_students_count"]
            existing.department_id = department_id or existing.department_id
            existing.uploaded_by = uploaded_by
            existing.updated_at = datetime.now(timezone.utc)
            await existing.save()
            return existing

        template = ExcelBatchTemplate(
            batch_id=batch_id,
            class_id=clean_class,
            department_id=department_id,
            template_filename=filename,
            file_path=str(saved_file_path),
            sheet_name=parsed["sheet_name"],
            sheet_names=parsed["sheet_names"],
            header_row_index=parsed["header_row_index"],
            headers=parsed["headers"],
            column_indices=parsed["column_indices"],
            total_columns=parsed["total_columns"],
            total_rows=parsed["detected_students_count"],
            uploaded_by=uploaded_by,
        )
        await template.insert()
        return template

    async def get_template_by_batch(
        self, batch_id: str, class_id: Optional[str] = None
    ) -> Optional[ExcelBatchTemplate]:
        """
        Get active template for a batch (and optional section).
        Falls back to batch-level template if class-specific template is not found.
        """
        clean_class = class_id.strip() if class_id and class_id.strip().lower() not in ("none", "null", "undefined", "") else None
        if clean_class:
            t = await ExcelBatchTemplate.find_one({
                "batch_id": batch_id,
                "class_id": clean_class,
            })
            if t:
                return t

        return await ExcelBatchTemplate.find_one({
            "batch_id": batch_id,
            "class_id": None,
        })

    async def delete_template(self, batch_id: str, class_id: Optional[str] = None) -> bool:
        """
        Delete template record and disk file.
        """
        clean_class = class_id.strip() if class_id and class_id.strip().lower() not in ("none", "null", "undefined", "") else None
        tmpl = await ExcelBatchTemplate.find_one({
            "batch_id": batch_id,
            "class_id": clean_class,
        })
        if not tmpl:
            return False

        try:
            if tmpl.file_path and os.path.exists(tmpl.file_path):
                os.remove(tmpl.file_path)
        except Exception as e:
            logger.warning(f"Error removing template file: {e}")

        await tmpl.delete()
        return True
