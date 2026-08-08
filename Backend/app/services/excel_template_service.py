from typing import Any
import os
import shutil
import asyncio
from datetime import datetime, timezone
import openpyxl
from fastapi import UploadFile, HTTPException, status
from app.models.excel_template import ExcelBatchTemplate
from app.repositories.excel_template_repository import ExcelTemplateRepository
from app.utils.normalization import normalize_register_number, compare_register_numbers

UPLOAD_DIR = os.path.join(os.getcwd(), "uploads", "excel_templates")
BACKUP_DIR = os.path.join(os.getcwd(), "uploads", "excel_backups")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# Per-batch lock registry for concurrent openpyxl write isolation
_BATCH_LOCKS: dict[str, asyncio.Lock] = {}


def _get_batch_lock(batch_id: str) -> asyncio.Lock:
    if batch_id not in _BATCH_LOCKS:
        _BATCH_LOCKS[batch_id] = asyncio.Lock()
    return _BATCH_LOCKS[batch_id]


class ExcelTemplateService:
    """
    Service layer handling Excel template upload, header parsing, cell mapping,
    and non-destructive openpyxl workbook row updating.
    """

    def __init__(self, repository: ExcelTemplateRepository | None = None):
        self.repository = repository or ExcelTemplateRepository()

    async def upload_template(self, batch_id: str, file: UploadFile) -> ExcelBatchTemplate:
        """
        Validate .xlsx file, store on disk, parse column headers via openpyxl,
        and save template metadata in MongoDB.
        """
        if not file.filename or not file.filename.lower().endswith(".xlsx"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only .xlsx Excel files are allowed. Please upload a valid Excel workbook.",
            )

        file_path = os.path.join(UPLOAD_DIR, f"{batch_id}.xlsx")
        
        # Save file to disk
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        # Parse Excel headers & rows using openpyxl
        try:
            wb = openpyxl.load_workbook(file_path, data_only=True)
            sheet = wb.active
            if sheet is None:
                raise ValueError("Active worksheet not found")

            # Extract header columns from row 1
            headers: list[str] = []
            for cell in sheet[1]:
                val = str(cell.value).strip() if cell.value is not None else ""
                headers.append(val)

            # Count total non-empty student data rows (starting from row 2)
            total_rows = 0
            for row in sheet.iter_rows(min_row=2, values_only=True):
                if any(cell is not None for cell in row):
                    total_rows += 1

            wb.close()

            # Default lookup column guessing
            lookup_col = "Register Number"
            for h in headers:
                h_norm = normalize_register_number(h)
                if any(k in h_norm for k in ["REG", "REGISTER", "ROLL", "ADM"]):
                    lookup_col = h
                    break

            # Fetch the batch to retrieve its department_id
            from app.models.batch import AdmissionBatch
            batch_doc = await AdmissionBatch.get(batch_id)
            department_id = batch_doc.department_id if batch_doc else None

            template = ExcelBatchTemplate(
                batch_id=batch_id,
                department_id=department_id,
                template_filename=file.filename,
                file_path=file_path,
                headers=headers,
                lookup_column=lookup_col,
                total_rows=total_rows,
                updated_count=0,
            )

            return await self.repository.save_template(template)

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to process Excel workbook: {str(e)}",
            )

    async def get_template_by_batch(self, batch_id: str) -> ExcelBatchTemplate | None:
        """Retrieve Excel template metadata for a batch."""
        return await self.repository.get_by_batch_id(batch_id)

    async def update_mappings(
        self, batch_id: str, field_mappings: dict[str, str], lookup_column: str
    ) -> ExcelBatchTemplate:
        """Update field mappings and lookup column."""
        updated = await self.repository.update_mappings(batch_id, field_mappings, lookup_column)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No Excel template found for Admission Batch '{batch_id}'. Please upload a template first.",
            )
        return updated

    def _create_backup(self, file_path: str, batch_id: str) -> str:
        """Create a timestamped backup before modifying the workbook."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        backup_path = os.path.join(BACKUP_DIR, f"{batch_id}_backup_{timestamp}.xlsx")
        shutil.copy2(file_path, backup_path)
        return backup_path

    async def register_number_exists(self, batch_id: str, register_number: str) -> bool:
        """
        Return True if the given register_number can be found in the Excel template for
        the specified batch, False otherwise.
        """
        template = await self.repository.get_by_batch_id(batch_id)
        if not template or not os.path.exists(template.file_path):
            return False

        try:
            wb = openpyxl.load_workbook(template.file_path, data_only=True, read_only=True)
            sheet = wb.active
            if sheet is None:
                wb.close()
                return False

            headers: list[str] = [str(cell.value).strip() if cell.value is not None else "" for cell in sheet[1]]
            
            lookup_col_idx: int | None = None
            if template.lookup_column:
                target_norm = normalize_register_number(template.lookup_column)
                for col_idx, h in enumerate(headers, start=1):
                    if normalize_register_number(h) == target_norm:
                        lookup_col_idx = col_idx
                        break

            if lookup_col_idx is None:
                for col_idx, h in enumerate(headers, start=1):
                    h_norm = normalize_register_number(h)
                    if any(k in h_norm for k in ["REG", "REGISTER", "ROLL", "ADM"]):
                        lookup_col_idx = col_idx
                        break

            if lookup_col_idx is None:
                lookup_col_idx = 1

            target_norm = normalize_register_number(register_number)
            for row in sheet.iter_rows(min_row=2, values_only=True):
                if lookup_col_idx <= len(row):
                    cell_val = row[lookup_col_idx - 1]
                    if compare_register_numbers(cell_val, target_norm):
                        wb.close()
                        return True

            wb.close()
            return False
        except Exception:
            return False

    async def find_student_excel_row(
        self, batch_id: str, register_number: str
    ) -> tuple[int | None, dict | None, str]:
        """
        Locate the single candidate row in the uploaded Excel workbook.
        Returns:
            (row_index, row_record_dict, status_code)
            Status codes:
            - "not_found": 0 matching rows found
            - "duplicate_records": >1 matching rows found
            - "success": Exactly 1 matching row found
        """
        template = await self.repository.get_by_batch_id(batch_id)
        if not template or not os.path.exists(template.file_path):
            return None, None, "not_found"

        try:
            wb = openpyxl.load_workbook(template.file_path, data_only=True, read_only=True)
            sheet = wb.active
            if sheet is None:
                wb.close()
                return None, None, "not_found"

            sheet_name = sheet.title
            headers: list[str] = [str(cell.value).strip() if cell.value is not None else "" for cell in sheet[1]]

            lookup_col_idx: int | None = None
            if template.lookup_column:
                target_norm = normalize_register_number(template.lookup_column)
                for col_idx, h in enumerate(headers, start=1):
                    if normalize_register_number(h) == target_norm:
                        lookup_col_idx = col_idx
                        break

            if lookup_col_idx is None:
                for col_idx, h in enumerate(headers, start=1):
                    h_norm = normalize_register_number(h)
                    if any(k in h_norm for k in ["REG", "REGISTER", "ROLL", "ADM"]):
                        lookup_col_idx = col_idx
                        break

            if lookup_col_idx is None:
                lookup_col_idx = 1

            target_norm = normalize_register_number(register_number)
            loaded_registers: list[str] = []
            matches: list[tuple[int, dict]] = []

            total_data_rows = 0
            for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                if not any(cell is not None for cell in row):
                    continue
                total_data_rows += 1
                
                cell_val = row[lookup_col_idx - 1] if lookup_col_idx <= len(row) else None
                norm_cell = normalize_register_number(cell_val)
                if norm_cell:
                    loaded_registers.append(norm_cell)

                if compare_register_numbers(cell_val, target_norm):
                    row_dict = {}
                    for idx, header in enumerate(headers):
                        if idx < len(row) and header:
                            row_dict[header] = row[idx]
                    matches.append((row_idx, row_dict))

            wb.close()

            # Diagnostic logging output
            print("\n========================", flush=True)
            print("EXCEL FILE", flush=True)
            print(f"Filename   : {template.template_filename}", flush=True)
            print(f"Sheet Name : {sheet_name}", flush=True)
            print(f"Total Rows : {total_data_rows}", flush=True)
            print("========================\n", flush=True)

            print("========================", flush=True)
            print("LOADED REGISTER NUMBERS", flush=True)
            for reg in loaded_registers:
                print(reg, flush=True)
            print("========================\n", flush=True)

            if len(matches) == 0:
                print("========================", flush=True)
                print("NO MATCH FOUND", flush=True)
                print(f"Student Register: '{register_number}' (Normalized: '{target_norm}')", flush=True)
                print(f"Difference      : Student register '{register_number}' was not found in admission list.", flush=True)
                print("========================\n", flush=True)
                return None, None, "not_found"

            elif len(matches) > 1:
                print("========================", flush=True)
                print("DUPLICATE MATCHES FOUND", flush=True)
                print(f"Student Register: '{register_number}' (Normalized: '{target_norm}')", flush=True)
                print(f"Matched Row Indices: {[m[0] for m in matches]}", flush=True)
                print("========================\n", flush=True)
                return None, None, "duplicate_records"

            else:
                matched_row_idx, matched_row_dict = matches[0]
                print("========================", flush=True)
                print("VERIFICATION MATCH FOUND", flush=True)
                print(f"Student Register : '{register_number}' (Normalized: '{target_norm}')", flush=True)
                print(f"Matched Row Index: Row {matched_row_idx}", flush=True)
                print(f"Status           : MATCH SUCCESSFUL ✅", flush=True)
                print("========================\n", flush=True)
                return matched_row_idx, matched_row_dict, "success"

        except Exception as e:
            print(f"[Excel Row Lookup Error] {str(e)}", flush=True)
            return None, None, "not_found"

    async def get_student_row_by_register_number(self, batch_id: str, register_number: str) -> dict | None:
        row_idx, row_dict, status_code = await self.find_student_excel_row(batch_id, register_number)
        return row_dict

    def _resolve_header_value(self, header: str, data_dict: dict[str, Any]) -> Any:
        """
        Flexible lookup matcher that resolves a value for an Excel column header from student data
        using priority ordered field aliases.
        """
        if not header or not data_dict:
            return None

        from app.utils.field_canonicalizer import get_aliases_for_header
        aliases = get_aliases_for_header(header)

        # Check aliases in priority order
        for alias in aliases:
            alias_lower = alias.lower()
            for k, v in data_dict.items():
                if k and k.strip().lower() == alias_lower and v is not None and str(v).strip() != "":
                    return v

        # Fallback to key or substring matches in data_dict
        header_lower = header.strip().lower()
        for k, v in data_dict.items():
            if not k:
                continue
            k_lower = k.strip().lower()
            if (header_lower in k_lower or k_lower in header_lower) and v is not None and str(v).strip() != "":
                return v

        return None

    async def append_or_update_student_row_in_excel(
        self,
        batch_id: str,
        register_number: str,
        student_data: dict[str, Any],
    ) -> bool:
        """
        Template-driven Excel output generator:
        1. Load master Excel template (contains column headers in Row 1).
        2. Look for existing row with matching Register Number.
        3. If existing row is found -> update that row.
        4. If not found -> append a NEW row at the end of the sheet.
        5. For every column header, write matching value from student_data or leave blank.
        """
        template = await self.repository.get_by_batch_id(batch_id)
        if not template or not os.path.exists(template.file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Master Excel template file not found for admission batch '{batch_id}'.",
            )

        lock = _get_batch_lock(batch_id)

        async with lock:
            self._create_backup(template.file_path, batch_id)

            try:
                wb = openpyxl.load_workbook(template.file_path, data_only=False)
                sheet = wb.active
                if sheet is None:
                    raise ValueError("Active worksheet not found in workbook.")

                # Read column headers from Row 1
                header_col_map: dict[str, int] = {}
                for col_idx, cell in enumerate(sheet[1], start=1):
                    val = str(cell.value).strip() if cell.value is not None else ""
                    if val:
                        header_col_map[val] = col_idx

                if not header_col_map:
                    raise ValueError("Excel template contains no header columns in Row 1.")

                # Find lookup column index for Register Number
                lookup_col_idx = None
                if template.lookup_column:
                    lookup_col_idx = header_col_map.get(template.lookup_column)

                if not lookup_col_idx:
                    for name, idx in header_col_map.items():
                        n_norm = normalize_register_number(name)
                        if any(k in n_norm for k in ["REG", "REGISTER", "ROLL", "ADM"]):
                            lookup_col_idx = idx
                            break

                if not lookup_col_idx:
                    lookup_col_idx = 1

                # Search existing rows (from Row 2 onwards) for matching register number
                target_row = None
                target_norm = normalize_register_number(register_number)

                for r_idx in range(2, sheet.max_row + 1):
                    cell_val = sheet.cell(row=r_idx, column=lookup_col_idx).value
                    if compare_register_numbers(cell_val, target_norm):
                        target_row = r_idx
                        break

                # If not found -> Append new row at end of sheet
                if not target_row:
                    first_empty_row = 2
                    while True:
                        row_cells = [sheet.cell(row=first_empty_row, column=c).value for c in range(1, len(header_col_map) + 1)]
                        if not any(v is not None and str(v).strip() != "" for v in row_cells):
                            break
                        first_empty_row += 1
                    target_row = first_empty_row

                print(f"[Excel Append/Update] Target Row for '{register_number}': Row {target_row}", flush=True)

                # Write values into target_row for every defined header column
                for header_name, col_idx in header_col_map.items():
                    val = self._resolve_header_value(header_name, student_data)
                    cell = sheet.cell(row=target_row, column=col_idx)
                    cell.value = val if val is not None else ""

                wb.save(template.file_path)
                wb.close()

                await self.repository.increment_updated_count(batch_id)
                print(f"[Excel Append/Update] Successfully saved Row {target_row} to {template.file_path}", flush=True)
                return True

            except Exception as e:
                print(f"[Excel Write Error] {str(e)}", flush=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to update Excel workbook: {str(e)}",
                )

    async def update_student_row_in_excel(
        self,
        batch_id: str,
        register_number: str,
        extracted_data: dict[str, str | int | float | None],
        row_index: int | None = None,
    ) -> bool:
        """
        Locate candidate row in Excel workbook matching register_number using openpyxl,
        write mapped extracted fields into corresponding row cells while keeping formatting intact,
        and save updated workbook safely with concurrency locks and pre-write backups.
        """
        template = await self.repository.get_by_batch_id(batch_id)
        if not template or not os.path.exists(template.file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Master Excel file not found for admission batch '{batch_id}'.",
            )

        lock = _get_batch_lock(batch_id)

        async with lock:
            backup_path = self._create_backup(template.file_path, batch_id)

            try:
                wb = openpyxl.load_workbook(template.file_path, data_only=False)
                sheet = wb.active
                if sheet is None:
                    raise ValueError("Active worksheet not found in workbook.")

                header_col_map: dict[str, int] = {}
                for col_idx, cell in enumerate(sheet[1], start=1):
                    val = str(cell.value).strip() if cell.value is not None else ""
                    if val:
                        header_col_map[val] = col_idx

                matched_row_idx = row_index

                if not matched_row_idx:
                    lookup_col_name = template.lookup_column
                    lookup_col_idx = header_col_map.get(lookup_col_name)

                    if not lookup_col_idx:
                        for name, idx in header_col_map.items():
                            n_norm = normalize_register_number(name)
                            if any(k in n_norm for k in ["REG", "REGISTER", "ROLL", "ADM"]):
                                lookup_col_idx = idx
                                break

                    if not lookup_col_idx:
                        lookup_col_idx = 1

                    target_norm = normalize_register_number(register_number)

                    for r_idx in range(2, sheet.max_row + 1):
                        cell_val = sheet.cell(row=r_idx, column=lookup_col_idx).value
                        if compare_register_numbers(cell_val, target_norm):
                            matched_row_idx = r_idx
                            break

                if not matched_row_idx:
                    wb.close()
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Register Number '{register_number}' not found in Excel template data rows. Record flagged for review.",
                    )

                # Write mapped values into matched row cells
                mappings = template.field_mappings
                for ai_field, excel_header in mappings.items():
                    if excel_header in header_col_map and ai_field in extracted_data:
                        val_to_write = extracted_data[ai_field]
                        if val_to_write is not None:
                            col_idx = header_col_map[excel_header]
                            sheet.cell(row=matched_row_idx, column=col_idx, value=val_to_write)

                # Direct header matching for student profile fields (Student Name, Register Number, Mobile Number, Email)
                for header_name, col_idx in header_col_map.items():
                    if header_name in extracted_data and extracted_data[header_name] is not None:
                        sheet.cell(row=matched_row_idx, column=col_idx, value=extracted_data[header_name])

                wb.save(template.file_path)
                wb.close()

                # Increment updated count in database
                await self.repository.increment_updated_count(batch_id)
                return True

            except HTTPException:
                raise
            except Exception as e:
                # Restore from backup on failure
                if os.path.exists(backup_path):
                    shutil.copy2(backup_path, template.file_path)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to update Excel row (restored from backup): {str(e)}",
                )

