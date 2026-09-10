from typing import Any
import os
import re
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


def _find_best_worksheet_and_headers(wb: openpyxl.Workbook) -> tuple[Any, int, list[str], dict[str, int]]:
    """
    Intelligently identify the student admission data worksheet and true header row.
    Inspects all sheets and rows 1 to 5 to avoid title banners or instructions tabs.
    Returns: (sheet, header_row_idx, headers_list, header_col_map)
    """
    best_sheet = wb.active or wb.worksheets[0]
    best_row_idx = 1
    best_headers: list[str] = []
    best_map: dict[str, int] = {}
    best_score = -1

    admission_keywords = [
        "reg", "register", "roll", "student", "name", "candidate", "applicant",
        "sno", "s.no", "aadhaar", "aadhar", "community", "caste", "dob", "birth",
        "gender", "sex", "father", "mother", "address", "mark", "mobile", "phone",
        "email", "quota", "emis", "branch", "course", "degree",
    ]

    for sheet in wb.worksheets:
        max_r = min(sheet.max_row, 5)
        for r_idx in range(1, max_r + 1):
            row_headers: list[str] = []
            row_map: dict[str, int] = {}
            score = 0

            for col_idx, cell in enumerate(sheet[r_idx], start=1):
                if cell.value is not None:
                    val_str = str(cell.value).strip()
                    if val_str:
                        row_headers.append(val_str)
                        row_map[val_str] = col_idx
                        v_lower = val_str.lower()
                        if any(kw in v_lower for kw in admission_keywords):
                            score += 2
                        else:
                            score += 1

            if score > best_score and len(row_map) >= 2:
                best_score = score
                best_sheet = sheet
                best_row_idx = r_idx
                best_headers = row_headers
                best_map = row_map

    # Fallback to active sheet row 1 if scoring failed
    if not best_map and best_sheet:
        for col_idx, cell in enumerate(best_sheet[1], start=1):
            if cell.value is not None and str(cell.value).strip():
                val = str(cell.value).strip()
                best_headers.append(val)
                best_map[val] = col_idx

    return best_sheet, best_row_idx, best_headers, best_map


def _find_lookup_col_index(header_col_map: dict[str, int], template_lookup_column: str | None = None) -> tuple[str, int]:
    """
    Locate register number lookup column with prioritized keyword matching:
    1. Exact template_lookup_column match
    2. Normalized REGISTER NUMBER / REG NO / REGISTRATION NUMBER
    3. ROLL NUMBER / ROLL NO
    4. ADMISSION NUMBER / ADM NO (excluding quota/year/fees)
    5. APPLICATION NUMBER / APP NO
    """
    if template_lookup_column and template_lookup_column in header_col_map:
        return template_lookup_column, header_col_map[template_lookup_column]

    if template_lookup_column:
        target_norm = normalize_register_number(template_lookup_column)
        for name, idx in header_col_map.items():
            if normalize_register_number(name) == target_norm:
                return name, idx

    # Priority 1: Register Number keywords
    for name, idx in header_col_map.items():
        n_norm = normalize_register_number(name)
        if any(k in n_norm for k in ["REGISTERNUMBER", "REGISTERNO", "REGNO", "REGISTRATIONNO", "REGISTRATIONNUMBER"]):
            return name, idx

    # Priority 2: Roll Number keywords
    for name, idx in header_col_map.items():
        n_norm = normalize_register_number(name)
        if any(k in n_norm for k in ["ROLLNUMBER", "ROLLNO"]):
            return name, idx

    # Priority 3: Admission Number keywords (strictly excluding quota, category, date, year)
    for name, idx in header_col_map.items():
        n_norm = normalize_register_number(name)
        if ("ADMISSION" in n_norm or "ADM" in n_norm) and any(no in n_norm for no in ["NO", "NUM", "ID"]):
            if not any(neg in n_norm for neg in ["QUOTA", "YEAR", "DATE", "FEE", "CATEGORY", "STATUS"]):
                return name, idx

    # Priority 4: Partial register/roll matches
    for name, idx in header_col_map.items():
        n_norm = normalize_register_number(name)
        if any(k in n_norm for k in ["REG", "ROLL"]):
            if not any(neg in n_norm for neg in ["QUOTA", "YEAR", "DATE", "FEE", "CATEGORY", "STATUS"]):
                return name, idx

    # Fallback to first column or column 1
    if header_col_map:
        first_k = next(iter(header_col_map))
        return first_k, header_col_map[first_k]
    return "Register Number", 1


class ExcelTemplateService:
    """
    Production service layer handling Excel template upload, header parsing, cell mapping,
    and non-destructive openpyxl workbook row updating with structured logging.
    """

    def __init__(self, repository: ExcelTemplateRepository | None = None):
        self.repository = repository or ExcelTemplateRepository()

    async def upload_template(self, batch_id: str, file: UploadFile, class_id: str | None = None) -> ExcelBatchTemplate:
        """
        Validate .xlsx file, store on disk, parse column headers via openpyxl,
        and save template metadata in MongoDB. Supports optional class_id.
        """
        if not file.filename or not file.filename.lower().endswith(".xlsx"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only .xlsx Excel files are allowed. Please upload a valid Excel workbook.",
            )

        file_key = f"{batch_id}_{class_id}" if class_id else batch_id
        file_path = os.path.join(UPLOAD_DIR, f"{file_key}.xlsx")

        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        try:
            wb = openpyxl.load_workbook(file_path, data_only=True)
            sheet, header_row_idx, headers, header_col_map = _find_best_worksheet_and_headers(wb)

            # Count total non-empty student data rows (starting after header row)
            total_rows = 0
            for row in sheet.iter_rows(min_row=header_row_idx + 1, values_only=True):
                if any(cell is not None and str(cell).strip() != "" for cell in row):
                    total_rows += 1

            wb.close()

            lookup_col, _ = _find_lookup_col_index(header_col_map)

            from app.models.batch import AdmissionBatch
            batch_doc = await AdmissionBatch.get(batch_id)
            department_id = batch_doc.department_id if batch_doc else None

            template = ExcelBatchTemplate(
                batch_id=batch_id,
                class_id=class_id,
                department_id=department_id,
                template_filename=file.filename,
                file_path=file_path,
                headers=headers,
                lookup_column=lookup_col,
                total_rows=total_rows,
                updated_count=0,
            )

            print("\n========== EXCEL ==========", flush=True)
            print(f"Workbook Loaded: {file.filename}", flush=True)
            print(f"Worksheet Selected: '{sheet.title}' (Header Row: {header_row_idx})", flush=True)
            print(f"Headers Found: {headers}", flush=True)
            print(f"Default Lookup Column: '{lookup_col}'", flush=True)
            print(f"Total Student Rows: {total_rows}", flush=True)
            print("===========================\n", flush=True)

            return await self.repository.save_template(template)

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to process Excel workbook: {str(e)}",
            )

    async def get_template_by_batch(self, batch_id: str, class_id: str | None = None) -> ExcelBatchTemplate | None:
        """Retrieve Excel template metadata for a batch or class."""
        return await self.repository.get_by_batch_id(batch_id, class_id=class_id)

    async def update_mappings(
        self, batch_id: str, field_mappings: dict[str, str], lookup_column: str, class_id: str | None = None
    ) -> ExcelBatchTemplate:
        """Update field mappings and lookup column."""
        updated = await self.repository.update_mappings(batch_id, field_mappings, lookup_column, class_id=class_id)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No Excel template found for Admission Batch '{batch_id}' (Class: '{class_id}'). Please upload a template first.",
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
            sheet, header_row_idx, _, header_col_map = _find_best_worksheet_and_headers(wb)

            _, lookup_col_idx = _find_lookup_col_index(header_col_map, template.lookup_column)
            target_norm = normalize_register_number(register_number)

            for row in sheet.iter_rows(min_row=header_row_idx + 1, values_only=True):
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
        Returns: (row_index, row_record_dict, status_code)
        """
        template = await self.repository.get_by_batch_id(batch_id)
        if not template or not os.path.exists(template.file_path):
            return None, None, "not_found"

        try:
            wb = openpyxl.load_workbook(template.file_path, data_only=True, read_only=True)
            sheet, header_row_idx, headers, header_col_map = _find_best_worksheet_and_headers(wb)

            lookup_col_name, lookup_col_idx = _find_lookup_col_index(header_col_map, template.lookup_column)
            target_norm = normalize_register_number(register_number)

            matches: list[tuple[int, dict]] = []
            loaded_registers: list[str] = []
            total_data_rows = 0

            for row_idx, row in enumerate(sheet.iter_rows(min_row=header_row_idx + 1, values_only=True), start=header_row_idx + 1):
                if not any(cell is not None and str(cell).strip() != "" for cell in row):
                    continue
                total_data_rows += 1

                cell_val = row[lookup_col_idx - 1] if lookup_col_idx <= len(row) else None
                norm_cell = normalize_register_number(cell_val)
                if norm_cell:
                    loaded_registers.append(norm_cell)

                if compare_register_numbers(cell_val, target_norm):
                    row_dict = {}
                    for idx, h in enumerate(headers):
                        if idx < len(row) and h:
                            row_dict[h] = row[idx]
                    matches.append((row_idx, row_dict))

            wb.close()

            print("\n========== EXCEL ==========", flush=True)
            print(f"Workbook Loaded: {template.template_filename}", flush=True)
            print(f"Worksheet: '{sheet.title}' | Header Row: {header_row_idx}", flush=True)
            print(f"Lookup Column: '{lookup_col_name}' (Col {lookup_col_idx})", flush=True)
            print(f"Searching Register: '{register_number}' (Normalized: '{target_norm}')", flush=True)
            print(f"Total Rows Scanned: {total_data_rows} | Matches Found: {len(matches)}", flush=True)

            if len(matches) == 0:
                print("Result: NO MATCH FOUND [NOT FOUND]", flush=True)
                print("===========================\n", flush=True)
                return None, None, "not_found"
            elif len(matches) > 1:
                print(f"Result: DUPLICATE MATCHES FOUND ({len(matches)}) [DUPLICATE]", flush=True)
                print("===========================\n", flush=True)
                return None, None, "duplicate_records"
            else:
                matched_row_idx, matched_row_dict = matches[0]
                print(f"Result: MATCH SUCCESSFUL (Row {matched_row_idx}) [OK]", flush=True)
                print("===========================\n", flush=True)
                return matched_row_idx, matched_row_dict, "success"

        except Exception as e:
            print(f"[Excel Row Lookup Error] {str(e)}", flush=True)
            return None, None, "not_found"

    async def get_student_row_by_register_number(self, batch_id: str, register_number: str) -> dict | None:
        row_idx, row_dict, status_code = await self.find_student_excel_row(batch_id, register_number)
        return row_dict

    def _resolve_header_value(self, header: str, data_dict: dict[str, Any]) -> Any:
        """
        Adaptive semantic field resolver matching any reasonable Excel column header against student data.
        Never returns literal 'NO', 'NULL', 'NONE', 'N/A'. Returns None for blank cells.
        """
        if not header or not data_dict:
            return None

        def _clean_val(v: Any) -> Any:
            if v is None:
                return None
            if isinstance(v, dict):
                v = v.get("value")
            if v is None:
                return None
            v_str = str(v).strip()
            if not v_str or v_str.upper() in ["NULL", "NONE", "N/A", "NOT DETECTED", "NOT FOUND"]:
                return None
            if v_str.upper() == "NO":
                if (
                    any(q in header.lower() for q in ["yes/no", "(yes/no)", "yes / no", "same as", "did ", "whether", "income", "orphan", "quota", "abled"])
                    or header.lower().startswith("is ")
                ):
                    return "No"
                return None
            return v


        h_clean = header.strip()
        h_lower = h_clean.lower()
        h_norm = re.sub(r'[\s_\-\./\(\)]+', '', h_lower)

        # ---------------------------------------------------------
        # Priority 1: Profile Identity Fields (Guaranteed Match)
        # ---------------------------------------------------------
        # Student Name
        name_indicators = [
            "student name", "name of the student", "name of candidate",
            "candidate name", "applicant name", "name of the applicant",
            "student's name", "candidate's name", "name", "full name",
            "student full name", "student_name", "candidate_name",
        ]
        if any(h_norm == re.sub(r'[\s_\-\./\(\)]+', '', ind) for ind in name_indicators) or (
            ("name" in h_lower and any(s in h_lower for s in ["student", "candidate", "applicant"]))
            and not any(neg in h_lower for neg in ["father", "mother", "parent", "guardian", "school", "college", "bank", "caste", "community", "branch"])
        ):
            for k in ["Student Name", "Name", "Student Full Name", "Candidate Name", "student_name", "name", "candidate_name"]:
                if k in data_dict:
                    val = _clean_val(data_dict[k])
                    if val is not None:
                        return val

        # Register Number
        reg_indicators = [
            "register number", "register no", "reg no", "reg. no", "reg_no",
            "registration number", "registration no", "roll number", "roll no",
            "roll_no", "roll. no", "regno", "rollno", "admission number", "admission no",
            "adm no", "adm. no",
        ]
        if any(h_norm == re.sub(r'[\s_\-\./\(\)]+', '', ind) for ind in reg_indicators) or (
            any(r in h_lower for r in ["register", "roll", "reg no", "reg. no"])
            and not any(neg in h_lower for neg in ["quota", "year", "date", "fee", "status"])
        ):
            for k in ["Register Number", "register_number", "Reg No", "Registration Number", "Roll No", "Roll Number", "Admission Number", "reg_no"]:
                if k in data_dict:
                    val = _clean_val(data_dict[k])
                    if val is not None:
                        return val

        # Mobile Number
        mobile_indicators = [
            "mobile number", "mobile no", "mobile", "phone number", "phone no",
            "phone", "contact number", "contact no", "cell", "cell no", "student mobile",
            "mobile_number", "phone_number",
        ]
        if any(h_norm == re.sub(r'[\s_\-\./\(\)]+', '', ind) for ind in mobile_indicators) or (
            any(m in h_lower for m in ["mobile", "phone", "cell", "contact no"])
            and not any(neg in h_lower for neg in ["father", "mother", "parent", "guardian", "emergency"])
        ):
            for k in ["Mobile Number", "mobile_number", "Mobile", "Phone Number", "phone_number", "Phone"]:
                if k in data_dict:
                    val = _clean_val(data_dict[k])
                    if val is not None:
                        return val

        # Email
        email_indicators = ["email", "email id", "email address", "e-mail", "e-mail id", "student email", "email_address"]
        if any(h_norm == re.sub(r'[\s_\-\./\(\)]+', '', ind) for ind in email_indicators) or "email" in h_lower or "e-mail" in h_lower:
            for k in ["Email", "email", "Email Address", "email_address", "Email ID"]:
                if k in data_dict:
                    val = _clean_val(data_dict[k])
                    if val is not None:
                        return val

        # ---------------------------------------------------------
        # Priority 2: Direct Match & Normalized Exact Match
        # ---------------------------------------------------------
        for k, raw_v in data_dict.items():
            if not k:
                continue
            k_norm = re.sub(r'[\s_\-\./\(\)]+', '', k.strip().lower())
            if k_norm == h_norm:
                val = _clean_val(raw_v)
                if val is not None:
                    return val

        # ---------------------------------------------------------
        # Priority 3: Canonical Aliases Dictionary Mapping
        # ---------------------------------------------------------
        from app.utils.field_canonicalizer import (
            get_aliases_for_header,
            is_name_conflict,
            is_number_conflict,
            is_category_conflict,
            is_phone_conflict,
            is_address_conflict,
        )

        def _has_conflict(h: str, candidate: str) -> bool:
            return (
                is_name_conflict(h, candidate)
                or is_number_conflict(h, candidate)
                or is_category_conflict(h, candidate)
                or is_phone_conflict(h, candidate)
                or is_address_conflict(h, candidate)
            )

        aliases = get_aliases_for_header(h_clean)
        for alias in aliases:
            a_norm = re.sub(r'[\s_\-\./\(\)]+', '', alias.strip().lower())
            for k, raw_v in data_dict.items():
                if not k or _has_conflict(h_clean, k):
                    continue
                k_norm = re.sub(r'[\s_\-\./\(\)]+', '', k.strip().lower())
                if k_norm == a_norm:
                    val = _clean_val(raw_v)
                    if val is not None:
                        return val

        # ---------------------------------------------------------
        # Priority 4: FieldMappingService Multi-tier Semantic Resolver
        # ---------------------------------------------------------
        try:
            from app.services.field_mapping_service import FieldMappingService
            mapper = FieldMappingService()
            resolved_val, conf, _ = mapper.resolve_field_value(
                excel_header=h_clean,
                extracted_data_pool=data_dict,
                student_profile=data_dict,
            )
            if resolved_val is not None and conf >= 50:
                clean = _clean_val(resolved_val)
                if clean is not None:
                    return clean
        except Exception:
            pass

        # ---------------------------------------------------------
        # Priority 5: RapidFuzz Fuzzy Match against all data_dict keys
        # ---------------------------------------------------------
        try:
            from rapidfuzz import fuzz
            best_score = 0.0
            best_val = None
            for k, raw_v in data_dict.items():
                if not k or _has_conflict(h_clean, k):
                    continue
                score = fuzz.token_sort_ratio(h_lower, k.strip().lower())
                if score > best_score and score >= 85:
                    v = _clean_val(raw_v)
                    if v is not None:
                        best_score = score
                        best_val = v
            if best_val is not None:
                return best_val
        except Exception:
            pass

        # ---------------------------------------------------------
        # Priority 6: Substring Fallback (Context-Guarded)
        # ---------------------------------------------------------
        from app.utils.field_canonicalizer import is_yes_no_question_field
        is_h_q = is_yes_no_question_field(h_clean)
        for k, raw_v in data_dict.items():
            if not k or _has_conflict(h_clean, k):
                continue
            if not is_h_q and is_yes_no_question_field(k):
                continue
            if is_h_q and not is_yes_no_question_field(k):
                continue
            k_lower = k.strip().lower()
            # Guard against generic keywords
            if h_lower in ["name", "number", "code", "mark", "id", "date"] or k_lower in ["name", "number", "code", "mark", "id", "date"]:
                continue
            if len(h_lower) >= 5 and len(k_lower) >= 5:
                if h_lower in k_lower or k_lower in h_lower:
                    val = _clean_val(raw_v)
                    if val is not None:
                        return val

        return None

    async def append_or_update_student_row_in_excel(
        self,
        batch_id: str,
        register_number: str,
        student_data: dict[str, Any],
        class_id: str | None = None,
    ) -> bool:
        """
        Template-driven Excel output generator:
        1. Load master Excel template (locating student data sheet and header row).
        2. Look for existing row matching Register Number.
        3. If existing row is found -> update that row safely without erasing existing data.
        4. If not found -> append a NEW row at the end of the sheet.
        5. For every column header, write non-empty matching values from student_data.
        """
        template = await self.repository.get_by_batch_id(batch_id, class_id=class_id)
        if not template or not os.path.exists(template.file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Master Excel template file not found for admission batch '{batch_id}' (class: '{class_id}').",
            )

        lock = _get_batch_lock(f"{batch_id}_{class_id}" if class_id else batch_id)

        async with lock:
            self._create_backup(template.file_path, batch_id)

            try:
                wb = openpyxl.load_workbook(template.file_path, data_only=False)
                sheet, header_row_idx, headers, header_col_map = _find_best_worksheet_and_headers(wb)

                if not header_col_map:
                    raise ValueError(f"Excel template '{template.template_filename}' contains no header columns.")

                lookup_col_name, lookup_col_idx = _find_lookup_col_index(header_col_map, template.lookup_column)
                target_norm = normalize_register_number(register_number)

                target_row = None
                is_existing_row = False

                for r_idx in range(header_row_idx + 1, sheet.max_row + 1):
                    cell_val = sheet.cell(row=r_idx, column=lookup_col_idx).value
                    if compare_register_numbers(cell_val, target_norm):
                        target_row = r_idx
                        is_existing_row = True
                        break

                # If not found -> Append new row at end of sheet
                if not target_row:
                    first_empty_row = header_row_idx + 1
                    while True:
                        row_cells = [sheet.cell(row=first_empty_row, column=c).value for c in range(1, len(header_col_map) + 1)]
                        if not any(v is not None and str(v).strip() != "" for v in row_cells):
                            break
                        first_empty_row += 1
                    target_row = first_empty_row
                    is_existing_row = False

                written_cells: dict[str, Any] = {}

                # Write values into target_row for every defined header column non-destructively
                from app.utils.normalization import (
                    clean_text_noise,
                    validate_and_normalize_aadhaar,
                    validate_and_normalize_mobile,
                    validate_and_normalize_dob,
                    validate_and_normalize_gender,
                    validate_and_normalize_email,
                    validate_and_normalize_ifsc,
                    validate_and_normalize_community,
                    validate_and_normalize_pincode,
                )

                for header_name, col_idx in header_col_map.items():
                    val = self._resolve_header_value(header_name, student_data)
                    if val is not None:
                        val_str = str(val).strip()
                        if val_str.upper() not in ["NO", "NULL", "NONE", "N/A", "NOT DETECTED", "NOT FOUND"]:
                            hn_lower = header_name.lower()
                            # Field-level validation and normalization
                            if "aadhaar" in hn_lower or "aadhar" in hn_lower:
                                without_space = "without space" in hn_lower or "nospace" in hn_lower
                                v_norm = validate_and_normalize_aadhaar(val, without_space=without_space)
                                if not v_norm:
                                    continue
                                val = v_norm
                            elif any(m in hn_lower for m in ["mobile", "phone", "cell"]):
                                v_norm = validate_and_normalize_mobile(val)
                                if not v_norm:
                                    continue
                                val = v_norm
                            elif any(d in hn_lower for d in ["dob", "date of birth", "birth"]):
                                v_norm = validate_and_normalize_dob(val, target_format="DD.MM.YYYY" if "dd.mm.yyyy" in hn_lower else "DD/MM/YYYY")
                                if not v_norm:
                                    continue
                                val = v_norm
                            elif "gender" in hn_lower or "sex" in hn_lower:
                                v_norm = validate_and_normalize_gender(val)
                                if not v_norm:
                                    continue
                                val = v_norm
                            elif "email" in hn_lower:
                                v_norm = validate_and_normalize_email(val)
                                if not v_norm:
                                    continue
                                val = v_norm
                            elif "ifsc" in hn_lower:
                                v_norm = validate_and_normalize_ifsc(val)
                                if not v_norm:
                                    continue
                                val = v_norm
                            elif "pincode" in hn_lower or "pin code" in hn_lower:
                                v_norm = validate_and_normalize_pincode(val)
                                if not v_norm:
                                    continue
                                val = v_norm
                            elif "community" in hn_lower:
                                v_norm = validate_and_normalize_community(val)
                                if v_norm:
                                    val = v_norm
                            elif "address" in hn_lower:
                                val = clean_text_noise(val)

                            sheet.cell(row=target_row, column=col_idx, value=val)
                            written_cells[header_name] = val
                        elif (
                            any(q in header_name.lower() for q in ["yes/no", "(yes/no)", "yes / no", "same as", "did ", "whether"])
                            or header_name.lower().startswith("is ")
                        ):
                            sheet.cell(row=target_row, column=col_idx, value="No")
                            written_cells[header_name] = "No"

                wb.save(template.file_path)
                wb.close()

                await self.repository.increment_updated_count(batch_id, class_id=class_id)

                print("\n========== EXCEL ==========", flush=True)
                print(f"Workbook Loaded: {template.template_filename}", flush=True)
                print(f"Worksheet: '{sheet.title}' | Header Row: {header_row_idx}", flush=True)
                print(f"Headers Found ({len(headers)}): {headers}", flush=True)
                print(f"Lookup Column: '{lookup_col_name}' (Col {lookup_col_idx})", flush=True)
                print(f"Target Student Register: '{register_number}' (Normalized: '{target_norm}')", flush=True)
                print(f"Writing Row: Row {target_row} ({'Updated Existing' if is_existing_row else 'Appended New'})", flush=True)
                print(f"Cells Populated ({len(written_cells)}):", flush=True)
                for hk, hv in written_cells.items():
                    print(f"  - {hk} = {hv}", flush=True)
                print(f"Workbook Saved: {template.file_path} [OK]", flush=True)
                print("===========================\n", flush=True)

                return True

            except Exception as e:
                print(f"\n[Excel Write Error] {str(e)}", flush=True)
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
        class_id: str | None = None,
    ) -> bool:
        """
        Locate candidate row in Excel workbook matching register_number using openpyxl,
        write mapped extracted fields into corresponding row cells, and save updated workbook safely.
        """
        return await self.append_or_update_student_row_in_excel(
            batch_id=batch_id,
            register_number=register_number,
            student_data=extracted_data,
            class_id=class_id,
        )
