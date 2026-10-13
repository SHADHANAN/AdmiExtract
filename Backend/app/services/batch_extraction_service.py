import io
import os
import re
import mimetypes
import uuid
import shutil
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import openpyxl
from fastapi import HTTPException, status
from beanie import PydanticObjectId

from app.utils.file_security import detect_file_magic_type

from app.models.user import User, UserRole
from app.models.batch import AdmissionBatch
from app.models.batch_extraction import (
    BatchExtractionRequest,
    BatchExtractionStatus,
    BatchVerificationStatus,
    BatchExportStatus,
    BatchDownloadStatus,
)
from app.models.student_document import StudentDocument, DocumentVersion
from app.models.student_submission import StudentSubmission
from app.models.document_extraction_request import (
    DocumentExtractionRequest,
    ExtractionRequestStatus,
)
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
    VerificationHistoryEntry,
)
from app.models.audit_log import AuditLog
from app.models.wanted_field_config import DocumentFieldConfiguration
from app.models.excel_template import ExcelBatchTemplate
from app.services.excel_template_service import ExcelTemplateService, TEMPLATES_DIR
from app.repositories.wanted_field_repository import WantedFieldRepository
from app.repositories.batch_extraction_repository import BatchExtractionRepository
from app.utils.storage_resolver import resolve_document_file_path
from app.repositories.student_document_repository import StudentDocumentRepository
from app.repositories.batch_repository import BatchRepository
from app.repositories.document_verification_repository import DocumentVerificationRepository
from app.services.document_extraction_service import (
    DocumentExtractionService,
    FIELD_ALIAS_TO_CANONICAL_KEY,
    resolve_canonical_field_key,
    ALLOWED_CANONICAL_FIELDS_BY_DOC_TYPE,
)
from app.services.field_source_rules import (
    FIELD_SOURCE_RULES,
    normalize_document_type,
    resolve_canonical_document_type,
)
from app.services.accuracy_extraction_engine import (
    AccuracyExtractionEngine,
    FieldExtractionResult,
)
from app.services.gemini_service import GeminiService
from app.services.verification_token_service import VerificationTokenService
from app.models.verification_token import VerificationToken, VerificationTokenStatus
from app.utils.normalization import compare_register_numbers
from app.utils.evidence_yes_no import (
    is_yes_no_field,
    normalize_yes_no_not_found,
)
from app.utils.logger_masking import mask_sensitive_value
from app.schemas.batch_extraction import (
    TemplatePreviewResponse,
    BatchExtractionSummaryResponse,
    BatchExtractionStatsResponse,
    BatchExtractionDetailResponse,
    StudentExtractionRowResponse,
    StudentExtractionFieldItem,
    CorrectionQueueItem,
)

logger = logging.getLogger("app.services.batch_extraction_service")


def _mask_student_id(student_id: str) -> str:
    value = str(student_id or "")
    if len(value) <= 4:
        return "[MASKED]"
    return f"{value[:2]}...{value[-2:]}"


def infer_document_mime_type(
    file_path: Optional[str],
    meta_file_type: Optional[str] = None,
) -> str:
    """
    Safely and accurately infer MIME type for a document.
    Priority:
    1. Valid MIME type from stored metadata (e.g. 'application/pdf', 'image/png')
    2. Extension from stored metadata mapped to MIME type (e.g. 'png' -> 'image/png')
    3. Magic header inspection of actual file bytes (PDF, JPEG, PNG, WEBP, XLSX, etc.)
    4. mimetypes.guess_type from file path / extension
    5. Fallback based on extension or safe optional representation 'application/octet-stream'
    """
    # 1. Stored metadata MIME type or extension
    if meta_file_type and isinstance(meta_file_type, str):
        clean_m = meta_file_type.strip().lower()
        if "/" in clean_m:
            return clean_m
        ext_lookup = f".{clean_m}" if not clean_m.startswith(".") else clean_m
        guessed = mimetypes.types_map.get(ext_lookup)
        if guessed:
            return guessed

    # 2. Inspect physical file if available
    if file_path and os.path.isfile(file_path):
        try:
            with open(file_path, "rb") as f:
                header = f.read(64)
            magic = detect_file_magic_type(header)
            if magic and magic != "application/x-executable-blocked":
                return magic
        except Exception:
            pass

        # 3. Guess from file_path extension
        guessed, _ = mimetypes.guess_type(file_path)
        if guessed:
            return guessed

        ext = Path(file_path).suffix.lower()
        ext_map = {
            ".pdf": "application/pdf",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
            ".bmp": "image/bmp",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
            ".csv": "text/csv",
            ".txt": "text/plain",
        }
        if ext in ext_map:
            return ext_map[ext]

    # 4. If file is not locally readable but has a path or filename
    if file_path:
        guessed, _ = mimetypes.guess_type(str(file_path))
        if guessed:
            return guessed
        ext = Path(str(file_path)).suffix.lower()
        if ext in (".pdf",):
            return "application/pdf"
        if ext in (".jpg", ".jpeg"):
            return "image/jpeg"
        if ext in (".png",):
            return "image/png"

    # 5. Safe optional/unknown representation matching project convention
    return "application/octet-stream"


class CanonicalStudentUnit:
    """
    Represents a single canonical physical student entity for data extraction and export.
    Ensures 1 student = 1 extraction result = 1 verification record set = 1 Excel row.
    """
    def __init__(
        self,
        canonical_id: str,
        student_submission_id: Optional[str] = None,
        register_number: Optional[str] = None,
        student_name: Optional[str] = None,
        class_id: Optional[str] = None,
        email: Optional[str] = None,
        mobile_number: Optional[str] = None,
        profile_data: Optional[Dict[str, str]] = None,
        submission_status: Optional[str] = None,
    ):
        self.canonical_id = canonical_id.strip().upper()
        self.student_submission_id = str(student_submission_id).strip() if student_submission_id else None
        self.register_number = (register_number or canonical_id).strip().upper()
        self.student_name = student_name
        self.class_id = class_id
        self.email = email
        self.mobile_number = mobile_number
        self.submission_status = submission_status
        self.aliases: Set[str] = set()
        self.documents: List[StudentDocument] = []
        self.profile_data: Dict[str, str] = dict(profile_data) if profile_data else {}

        if canonical_id:
            self.aliases.add(canonical_id)
            self.aliases.add(canonical_id.strip())
            self.aliases.add(canonical_id.strip().upper())
            self.aliases.add(canonical_id.strip().lower())
        if student_submission_id:
            self.aliases.add(str(student_submission_id).strip())
        if register_number:
            self.aliases.add(register_number)
            self.aliases.add(register_number.strip())
            self.aliases.add(register_number.strip().upper())
            self.aliases.add(register_number.strip().lower())

    def get_profile_value(self, field_key: str) -> Optional[str]:
        """Retrieve a verified profile value for field_key if available."""
        if not field_key or not self.profile_data:
            return None
        fk_clean = field_key.strip().lower()
        if fk_clean in self.profile_data:
            return self.profile_data[fk_clean]
        from app.services.document_extraction_service import resolve_canonical_field_key
        canon = resolve_canonical_field_key(field_key)
        if canon and canon in self.profile_data:
            return self.profile_data[canon]
        return None


class BatchExtractionService:
    """
    Core service orchestrating the Data Extraction module:
    - Multi-extraction batch workflows with partial batch completion
    - Real-time progress calculation and breakdown metrics
    - Missing document detection without hallucinating values
    - Resilient retry without deleting stored documents
    - Focused correction queue and staff review
    - Verified Excel export preserving requested columns
    """

    infer_document_mime_type = staticmethod(infer_document_mime_type)
    _infer_document_mime_type = staticmethod(infer_document_mime_type)

    def __init__(
        self,
        repository: Optional[BatchExtractionRepository] = None,
        doc_repository: Optional[StudentDocumentRepository] = None,
        batch_repository: Optional[BatchRepository] = None,
        verif_repository: Optional[DocumentVerificationRepository] = None,
        extraction_service: Optional[DocumentExtractionService] = None,
        accuracy_engine: Optional[AccuracyExtractionEngine] = None,
        wanted_field_repository: Optional[WantedFieldRepository] = None,
        excel_template_service: Optional[ExcelTemplateService] = None,
    ):
        self.repository = repository or BatchExtractionRepository()
        self.doc_repository = doc_repository or StudentDocumentRepository()
        self.batch_repository = batch_repository or BatchRepository()
        self.verif_repository = verif_repository or DocumentVerificationRepository()
        self.extraction_service = extraction_service or DocumentExtractionService()
        self.accuracy_engine = accuracy_engine or AccuracyExtractionEngine()
        self.wanted_field_repository = wanted_field_repository or WantedFieldRepository()
        self.excel_template_service = excel_template_service or ExcelTemplateService()

    async def _build_canonical_student_units(
        self, batch_ids: List[Any], clean_class_id: Optional[str] = None
    ) -> List[CanonicalStudentUnit]:
        """
        Build deduplicated canonical student units for a batch (+ optional class).
        Maps all StudentSubmissions and StudentDocuments to exact single physical student entities.
        Ensures 1 student = 1 CanonicalStudentUnit regardless of document count or alias formats.
        """
        single_section_cls = None
        if len(batch_ids) == 1:
            from app.models.batch_class import BatchClass
            classes = await BatchClass.find(BatchClass.batch_id == batch_ids[0]).to_list()
            if len(classes) == 1:
                single_section_cls = classes[0]
                # Auto-heal any student in this single-section batch missing class_id
                unassigned_subs = await StudentSubmission.find(
                    StudentSubmission.batch_id == batch_ids[0],
                    {"$or": [
                        {"class_id": None},
                        {"class_id": ""},
                        {"class_id": {"$exists": False}},
                        {"class_name": None},
                        {"class_name": ""},
                        {"class_name": {"$exists": False}},
                    ]}
                ).to_list()
                for u in unassigned_subs:
                    u.class_id = single_section_cls.id
                    u.class_name = single_section_cls.class_name
                    await u.save()

                unassigned_docs = await StudentDocument.find(
                    StudentDocument.batch_id == batch_ids[0],
                    {"$or": [
                        {"class_id": None},
                        {"class_id": ""},
                        {"class_id": {"$exists": False}},
                        {"section_id": None},
                        {"section_id": ""},
                        {"section_id": {"$exists": False}},
                    ]}
                ).to_list()
                for ud in unassigned_docs:
                    ud.class_id = single_section_cls.id
                    ud.section_id = single_section_cls.id
                    await ud.save()

        sub_query: Dict[str, Any] = {"batch_id": {"$in": batch_ids}}
        doc_query: Dict[str, Any] = {"batch_id": {"$in": batch_ids}}

        if clean_class_id:
            if single_section_cls and (single_section_cls.id == clean_class_id or single_section_cls.class_name == clean_class_id):
                # In single section batch, section scope matches all batch students
                sub_query = {"batch_id": {"$in": batch_ids}}
                doc_query = {"batch_id": {"$in": batch_ids}}
            else:
                sub_query["$or"] = [{"class_id": clean_class_id}, {"class_name": clean_class_id}]
                doc_query["$or"] = [{"class_id": clean_class_id}, {"section_id": clean_class_id}]

        submissions = await StudentSubmission.find(sub_query).to_list()
        stored_docs = await StudentDocument.find(doc_query).to_list()

        # Older submissions may retain stored upload paths without a corresponding
        # StudentDocument record. Reconcile those existing files into the canonical
        # document/version store before source routing; this never uploads or copies data.
        existing_doc_keys = {
            (
                str(doc.batch_id),
                str(doc.student_id).strip().upper(),
                resolve_canonical_document_type(doc.document_type, doc.document_name),
            )
            for doc in stored_docs
        }
        from app.models.student_document import DocumentStatus
        from app.utils.storage_resolver import resolve_document_file_path

        for submission in submissions:
            for meta in submission.documents:
                if meta.status not in ("Uploaded", "Submitted", "Verified", None) or not meta.file_path:
                    continue
                resolved_p = resolve_document_file_path(
                    meta.file_path,
                    batch_id=str(submission.batch_id),
                    register_number=submission.register_number,
                    document_name=meta.document_name,
                )
                if not resolved_p or not resolved_p.is_file():
                    logger.warning(
                        "[FIELD_EXTRACTION] student=%s source_document=%s original_file_loaded=false",
                        _mask_student_id(submission.register_number),
                        resolve_canonical_document_type(meta.document_type, meta.document_name),
                    )
                    continue
                file_path = str(resolved_p.resolve())
                filename = os.path.basename(file_path)
                mime_type = infer_document_mime_type(file_path, getattr(meta, "file_type", None))
                doc_type = resolve_canonical_document_type(meta.document_type, meta.document_name)
                doc_key = (str(submission.batch_id), submission.register_number.strip().upper(), doc_type)
                if doc_key in existing_doc_keys:
                    for sd in stored_docs:
                        if (str(sd.batch_id), sd.student_id.strip().upper(), resolve_canonical_document_type(sd.document_type, sd.document_name)) == doc_key:
                            av = sd.active_version
                            if av and (not av.file_path or not os.path.exists(av.file_path) or av.file_size_bytes == 0 or os.path.getsize(av.file_path) < 1024):
                                if os.path.exists(file_path) and os.path.getsize(file_path) > 1024:
                                    av.file_path = file_path
                                    av.file_size_bytes = os.path.getsize(file_path)
                                    av.mime_type = mime_type
                                    av.original_filename = filename
                                    try:
                                        await sd.save()
                                    except Exception:
                                        pass
                    continue
                version = DocumentVersion(
                    version_number=max(1, int(meta.version or 1)),
                    file_path=file_path,
                    original_filename=filename,
                    file_size_bytes=os.path.getsize(file_path),
                    mime_type=mime_type,
                    uploaded_at=meta.uploaded_at or submission.submitted_at,
                    uploaded_by=submission.register_number,
                    validation_status="PENDING",
                    expected_document_type=doc_type,
                    detected_document_type=doc_type,
                    is_active=True,
                )
                synced_doc = StudentDocument(
                    student_id=submission.register_number.strip(),
                    submission_id=str(submission.id),
                    batch_id=str(submission.batch_id),
                    class_id=submission.class_id,
                    section_id=submission.class_id,
                    department_id=submission.department_id,
                    document_type=doc_type,
                    document_name=meta.document_name,
                    current_version=version.version_number,
                    active_version_id=version.version_id,
                    status=DocumentStatus.UPLOADED.value,
                    versions=[version],
                )
                await synced_doc.insert()
                stored_docs.append(synced_doc)
                existing_doc_keys.add(doc_key)
                logger.info(
                    "[FIELD_EXTRACTION] student=%s source_document=%s document_version=%s original_file_loaded=true mime_type=%s file_size=%d",
                    _mask_student_id(submission.register_number),
                    doc_type,
                    version.version_number,
                    mime_type,
                    version.file_size_bytes,
                )

        # Link documents referenced by submissions within this batch
        sub_reg_nos = [
            s.register_number.strip()
            for s in submissions
            if s.register_number and s.register_number.strip()
        ]
        sub_ids = [str(s.id) for s in submissions]
        if sub_reg_nos or sub_ids:
            extra_doc_queries = []
            if sub_reg_nos:
                extra_doc_queries.append({"student_id": {"$in": sub_reg_nos}})
                extra_doc_queries.append({"student_id": {"$in": [r.upper() for r in sub_reg_nos]}})
            if sub_ids:
                extra_doc_queries.append({"submission_id": {"$in": sub_ids}})
            if extra_doc_queries:
                extra_docs = await StudentDocument.find({"$or": extra_doc_queries}).to_list()
                existing_doc_ids = {str(d.id) for d in stored_docs}
                for ed in extra_docs:
                    if str(ed.id) not in existing_doc_ids and (not batch_ids or ed.batch_id in batch_ids):
                        stored_docs.append(ed)
                        existing_doc_ids.add(str(ed.id))

        units_by_key: Dict[str, CanonicalStudentUnit] = {}
        alias_to_unit: Dict[str, CanonicalStudentUnit] = {}

        # 1. Register canonical units from Submissions first
        for sub in submissions:
            sub_id_str = str(sub.id)
            reg_no = sub.register_number.strip() if sub.register_number and sub.register_number.strip() else None
            canonical_key = reg_no.upper() if reg_no else sub_id_str

            s_name = sub.student_name
            s_email = getattr(sub, "email", None)
            s_mobile = getattr(sub, "mobile_number", None)

            s_status = getattr(sub, "submission_status", None)

            if canonical_key in units_by_key:
                unit = units_by_key[canonical_key]
                if not unit.student_submission_id and sub_id_str:
                    unit.student_submission_id = sub_id_str
                if not unit.student_name and s_name:
                    unit.student_name = s_name
                if not unit.email and s_email:
                    unit.email = s_email
                if not unit.mobile_number and s_mobile:
                    unit.mobile_number = s_mobile
                if not unit.submission_status and s_status:
                    unit.submission_status = s_status
            else:
                unit = CanonicalStudentUnit(
                    canonical_id=canonical_key,
                    student_submission_id=sub_id_str,
                    register_number=reg_no or canonical_key,
                    student_name=s_name,
                    class_id=sub.class_id or clean_class_id,
                    email=s_email,
                    mobile_number=s_mobile,
                    submission_status=s_status,
                )
                units_by_key[canonical_key] = unit

            # Populate profile_data with trusted application and admission records
            prof_dict: Dict[str, str] = {}
            if s_name:
                prof_dict["student_name"] = s_name
                prof_dict["name"] = s_name
            if reg_no:
                prof_dict["register_number"] = reg_no
                prof_dict["student_id"] = reg_no
                prof_dict["roll_no"] = reg_no
            if s_email:
                prof_dict["email"] = s_email
            if s_mobile:
                prof_dict["mobile_number"] = s_mobile
                prof_dict["phone"] = s_mobile
            if sub.extracted_data:
                for k, v in sub.extracted_data.items():
                    if v and str(v).strip() not in ("", "NOT_AVAILABLE", "NOT_FOUND"):
                        prof_dict[k.strip().lower()] = str(v).strip()
                        canon_k = resolve_canonical_field_key(k)
                        if canon_k:
                            prof_dict[canon_k.lower()] = str(v).strip()
            if batch_ids:
                try:
                    from app.models.batch import Batch
                    b_obj = await Batch.get(batch_ids[0])
                    if b_obj and getattr(b_obj, "academic_year", None):
                        ay = str(b_obj.academic_year).strip()
                        if ay:
                            prof_dict["academic_year"] = ay
                            prof_dict["academic_year_of_joining"] = ay
                            prof_dict["year_of_joining"] = ay
                except Exception:
                    pass
            unit.profile_data.update(prof_dict)

            for alias in [sub_id_str, reg_no, canonical_key]:
                if alias:
                    alias_to_unit[alias] = unit
                    alias_to_unit[alias.upper()] = unit
                    alias_to_unit[alias.lower()] = unit
                    alias_to_unit[alias.strip()] = unit

        # 2. Attach stored documents to canonical units
        for doc in stored_docs:
            sub_id = doc.submission_id.strip() if doc.submission_id and str(doc.submission_id).strip() else None
            stud_id = doc.student_id.strip() if doc.student_id and str(doc.student_id).strip() else None

            unit: Optional[CanonicalStudentUnit] = None
            if sub_id and sub_id in alias_to_unit:
                unit = alias_to_unit[sub_id]
            elif stud_id and stud_id in alias_to_unit:
                unit = alias_to_unit[stud_id]
            elif stud_id and stud_id.upper() in alias_to_unit:
                unit = alias_to_unit[stud_id.upper()]
            elif sub_id and sub_id.upper() in alias_to_unit:
                unit = alias_to_unit[sub_id.upper()]

            if not unit:
                # Orphan document without existing submission unit
                canon_key = (stud_id or sub_id or str(doc.id)).strip().upper()
                if canon_key in units_by_key:
                    unit = units_by_key[canon_key]
                else:
                    unit = CanonicalStudentUnit(
                        canonical_id=canon_key,
                        student_submission_id=sub_id,
                        register_number=stud_id or canon_key,
                        student_name=None,
                        class_id=doc.class_id or clean_class_id,
                    )
                    units_by_key[canon_key] = unit

                for alias in [sub_id, stud_id, canon_key]:
                    if alias:
                        alias_to_unit[alias] = unit
                        alias_to_unit[alias.upper()] = unit
                        alias_to_unit[alias.lower()] = unit

            # Deduplicate documents in unit by document id
            if not any(str(d.id) == str(doc.id) for d in unit.documents):
                unit.documents.append(doc)
            if stud_id:
                unit.aliases.add(stud_id)
                unit.aliases.add(stud_id.upper())
            if sub_id:
                unit.aliases.add(sub_id)

        # Check User collection for missing student profile info
        missing_user_regs = [
            u.register_number for u in units_by_key.values()
            if not u.email or not u.mobile_number or not u.student_name
        ]
        if missing_user_regs:
            try:
                users = await User.find({
                    "$or": [
                        {"register_number": {"$in": missing_user_regs}},
                        {"username": {"$in": missing_user_regs}},
                    ]
                }).to_list()
                user_map = {}
                for usr in users:
                    if usr.register_number:
                        user_map[usr.register_number.strip().upper()] = usr
                    if usr.username:
                        user_map[usr.username.strip().upper()] = usr
                for u in units_by_key.values():
                    usr = user_map.get(u.register_number.upper()) or user_map.get(u.canonical_id.upper())
                    if usr:
                        if not u.student_name and usr.name:
                            u.student_name = usr.name
                        if not u.email and usr.email:
                            u.email = str(usr.email)
                        if not u.mobile_number and usr.mobile_number:
                            u.mobile_number = usr.mobile_number
            except Exception as e:
                logger.warning(f"[CanonicalUnit] Error looking up User profiles: {e}")

        # Build verified profile_data dictionary on each unit
        for u in units_by_key.values():
            p_data: Dict[str, str] = {}
            if u.student_name and str(u.student_name).strip():
                val = str(u.student_name).strip()
                p_data["student_name"] = val
                p_data["student name"] = val
                p_data["name"] = val
                p_data["candidate_name"] = val
                p_data["candidate name"] = val
                p_data["applicant_name"] = val
                p_data["applicant name"] = val
            if u.register_number and str(u.register_number).strip():
                val = str(u.register_number).strip()
                p_data["register_number"] = val
                p_data["register number"] = val
                p_data["roll_number"] = val
                p_data["roll number"] = val
                p_data["roll_no"] = val
                p_data["reg_no"] = val
                p_data["register_no"] = val
            if u.email and str(u.email).strip():
                val = str(u.email).strip()
                p_data["email"] = val
                p_data["email_id"] = val
                p_data["email id"] = val
                p_data["email address"] = val
                p_data["email_address"] = val
                p_data["student_email"] = val
                p_data["student email"] = val
            if u.mobile_number and str(u.mobile_number).strip():
                val = str(u.mobile_number).strip()
                p_data["mobile_number"] = val
                p_data["mobile number"] = val
                p_data["mobile"] = val
                p_data["phone"] = val
                p_data["phone_number"] = val
                p_data["contact_number"] = val
            u.profile_data = p_data

        # Sort units deterministically by register number
        sorted_units = sorted(list(units_by_key.values()), key=lambda u: u.register_number)
        return sorted_units

    def verify_batch_access(self, batch: AdmissionBatch, actor: User) -> None:
        """Enforce strict RBAC and department tenancy on admission batch."""
        if actor.role == UserRole.SUPER_ADMIN:
            return
        if actor.role == UserRole.DEPARTMENT_ADMIN:
            user_dept = getattr(actor, "department_code", None) or getattr(actor, "department_id", None)
            if not user_dept or batch.department_id != user_dept:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: You do not have permission to access another department's admission batch.",
                )
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Unauthorized batch access.",
        )

    async def list_authorized_batches(self, actor: User) -> List[BatchExtractionStatsResponse]:
        """
        List all admission batches authorized for the staff user with high-level
        data extraction stats (students, stored documents, previous extractions, verification).
        """
        if actor.role == UserRole.SUPER_ADMIN:
            batches = await self.batch_repository.get_all_batches()
        elif actor.role == UserRole.DEPARTMENT_ADMIN:
            user_dept = getattr(actor, "department_code", None) or getattr(actor, "department_id", None)
            if not user_dept:
                logger.info(
                    "[DATA_EXTRACTION_BATCHES] user_id=%s role=%s department_id=%s "
                    "batch_count=0 batch_ids=[] response_status=200",
                    self._mask_log_identifier(str(actor.id)),
                    actor.role.value,
                    "[MASKED]",
                )
                return []
            batches = await self.batch_repository.get_batches_by_department(user_dept)
        else:
            logger.info(
                "[DATA_EXTRACTION_BATCHES] user_id=%s role=%s department_id=%s "
                "batch_count=0 batch_ids=[] response_status=200",
                self._mask_log_identifier(str(actor.id)),
                actor.role.value,
                "[MASKED]",
            )
            return []

        batch_ids = [str(batch.id) for batch in batches]
        department_id = getattr(actor, "department_code", None) or getattr(actor, "department_id", None)
        logger.info(
            "[DATA_EXTRACTION_BATCHES] user_id=%s role=%s department_id=%s "
            "batch_count=%d batch_ids=%s response_status=200",
            self._mask_log_identifier(str(actor.id)),
            actor.role.value,
            self._mask_log_identifier(str(department_id)) if department_id else "[MASKED]",
            len(batches),
            batch_ids,
        )

        stats_list: List[BatchExtractionStatsResponse] = []
        for b in batches:
            b_str = str(b.id)
            b_ids = [b_str]
            if hasattr(b, "name") and b.name and b.name != b_str:
                b_ids.append(b.name)
            if isinstance(b.id, PydanticObjectId):
                b_ids.append(b.id)

            canonical_students = await self._build_canonical_student_units(b_ids)
            students_count = len(canonical_students)
            stored_docs_count = sum(len(u.documents) for u in canonical_students)

            extractions = await self.repository.list_by_batch(b.id)
            extractions_count = len(extractions)

            latest_ext_resp = None
            verif_status = "PENDING"
            download_history_count = 0
            if extractions:
                latest = extractions[0]
                latest_ext_resp = self._to_summary_response(latest)
                verif_status = latest.verification_status
                download_history_count = sum(e.download_count for e in extractions)

            stats_list.append(
                BatchExtractionStatsResponse(
                    batch_id=b_str,
                    batch_name=b.name,
                    academic_year=b.academic_year,
                    department_id=b.department_id,
                    students_count=students_count,
                    stored_documents_count=stored_docs_count,
                    extractions_count=extractions_count,
                    latest_extraction=latest_ext_resp,
                    verification_status=verif_status,
                    download_history_count=download_history_count,
                )
            )

        return stats_list

    @staticmethod
    def _mask_log_identifier(value: str) -> str:
        if len(value) <= 8:
            return "[MASKED]"
        return f"{value[:4]}...{value[-4:]}"

    async def get_batch_extraction_overview(
        self, batch_id: str, actor: User
    ) -> BatchExtractionStatsResponse:
        """Retrieve extraction stats and overview for a specific batch."""
        batch = await self.batch_repository.get_batch_by_id(batch_id)
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Admission batch '{batch_id}' not found.",
            )
        self.verify_batch_access(batch, actor)

        b_str = str(batch.id)
        b_ids = [b_str]
        if hasattr(batch, "name") and batch.name and batch.name != b_str:
            b_ids.append(batch.name)
        if isinstance(batch.id, PydanticObjectId):
            b_ids.append(batch.id)

        canonical_students = await self._build_canonical_student_units(b_ids)
        students_count = len(canonical_students)
        stored_docs_count = sum(len(u.documents) for u in canonical_students)

        extractions = await self.repository.list_by_batch(batch.id)

        latest_ext_resp = self._to_summary_response(extractions[0]) if extractions else None
        verif_status = extractions[0].verification_status if extractions else "PENDING"
        download_history_count = sum(e.download_count for e in extractions)

        return BatchExtractionStatsResponse(
            batch_id=b_str,
            batch_name=batch.name,
            academic_year=batch.academic_year,
            department_id=batch.department_id,
            students_count=students_count,
            stored_documents_count=stored_docs_count,
            extractions_count=len(extractions),
            latest_extraction=latest_ext_resp,
            verification_status=verif_status,
            download_history_count=download_history_count,
        )

    async def list_batch_extractions_history(
        self, batch_id: str, actor: User
    ) -> List[BatchExtractionSummaryResponse]:
        """List active extraction run for a batch (historical logs are not permanently accumulated)."""
        batch = await self.batch_repository.get_batch_by_id(batch_id)
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Admission batch '{batch_id}' not found.",
            )
        self.verify_batch_access(batch, actor)

        extractions = await self.repository.list_by_batch(batch.id)
        return [self._to_summary_response(e) for e in extractions]

    async def parse_and_store_excel_template(
        self,
        file_content: bytes,
        filename: str,
        batch_id: Optional[str] = None,
        class_id: Optional[str] = None,
        department_id: Optional[str] = None,
        uploaded_by: str = "system",
    ) -> TemplatePreviewResponse:
        """
        Parse an uploaded Excel field template, identify required output columns,
        and normalize each field. If batch_id is provided, permanently saves the template
        and registers it with ExcelBatchTemplate for future extraction and export.
        """
        parsed = self.excel_template_service.parse_workbook_structure(file_content, filename)
        template_id = None

        if batch_id:
            tmpl = await self.excel_template_service.save_template_file(
                file_content=file_content,
                filename=filename,
                batch_id=batch_id,
                class_id=class_id,
                department_id=department_id,
                uploaded_by=uploaded_by,
            )
            template_id = str(tmpl.id)

        return TemplatePreviewResponse(
            template_id=template_id,
            template_filename=filename,
            sheet_name=parsed["sheet_name"],
            sheet_names=parsed["sheet_names"],
            header_row_index=parsed["header_row_index"],
            requested_columns=parsed["headers"],
            canonical_fields=parsed["canonical_fields"],
            column_mapping=parsed["column_mapping"],
            column_indices=parsed["column_indices"],
            detected_students_count=parsed["detected_students_count"],
            sample_rows=parsed["sample_rows"],
        )

    def parse_excel_template_preview(
        self, file_content: bytes, filename: str
    ) -> TemplatePreviewResponse:
        """
        Synchronous wrapper for previewing template structure without modifying DB.
        """
        parsed = self.excel_template_service.parse_workbook_structure(file_content, filename)
        return TemplatePreviewResponse(
            template_filename=filename,
            sheet_name=parsed["sheet_name"],
            sheet_names=parsed["sheet_names"],
            header_row_index=parsed["header_row_index"],
            requested_columns=parsed["headers"],
            canonical_fields=parsed["canonical_fields"],
            column_mapping=parsed["column_mapping"],
            column_indices=parsed["column_indices"],
            detected_students_count=parsed["detected_students_count"],
            sample_rows=parsed["sample_rows"],
        )

    async def create_and_run_batch_extraction(
        self,
        batch_id: str,
        requested_columns: Optional[List[str]],
        requested_fields: Optional[List[str]],
        actor: User,
        column_mapping: Optional[Dict[str, str]] = None,
        template_filename: Optional[str] = None,
        class_id: Optional[str] = None,
    ) -> BatchExtractionSummaryResponse:
        """
        Execute on-demand data extraction for all students in a batch:
        - Reuses stored documents from StudentDocument collection.
        - Resolves authoritative document type for each requested field.
        - Automatically includes ALL students belonging to the batch/section.
        - Rejects batches with zero students with a 400 Bad Request error.
        - Missing documents return 'NOT_AVAILABLE' safely without failing the whole batch.
        - Calculates live progress and verified counts.
        - Creates an immutable snapshot of the uploaded template and field mappings.
        """
        batch = await self.batch_repository.get_batch_by_id(batch_id)
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Admission batch '{batch_id}' not found.",
            )
        self.verify_batch_access(batch, actor)

        batch_id_str = str(batch.id)
        batch_ids = [batch_id_str]
        if hasattr(batch, "name") and batch.name and batch.name != batch_id_str:
            batch_ids.append(batch.name)
        if isinstance(batch.id, PydanticObjectId):
            batch_ids.append(batch.id)

        clean_class_id = (
            str(class_id).strip()
            if class_id and str(class_id).strip().lower() not in ("none", "null", "undefined", "")
            else None
        )

        # Look up active Excel template for this batch (and optional Section)
        tmpl = None
        if clean_class_id:
            tmpl = await self.excel_template_service.get_template_by_batch(batch_id_str, clean_class_id)
        if not tmpl:
            tmpl = await self.excel_template_service.get_template_by_batch(batch_id_str, None)

        template_id = str(tmpl.id) if tmpl else None
        template_fn = (tmpl.template_filename if tmpl else None) or template_filename
        template_fp = tmpl.file_path if (tmpl and tmpl.file_path and os.path.exists(tmpl.file_path)) else None
        template_sheet = tmpl.sheet_name if tmpl else None
        template_hdr_row = tmpl.header_row_index if tmpl else 1
        template_hdrs = list(tmpl.headers) if tmpl else []
        header_to_col = dict(tmpl.column_indices) if tmpl else {}

        # If template exists on disk, create an immutable snapshot copy for this extraction request
        request_template_file_path = template_fp
        if template_fp and os.path.exists(template_fp):
            try:
                import shutil
                ext_snapshot_dir = TEMPLATES_DIR / "extractions"
                ext_snapshot_dir.mkdir(parents=True, exist_ok=True)
                clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', template_fn or 'template.xlsx')
                snapshot_name = f"ext_{uuid.uuid4().hex[:12]}_{clean_name}"
                snapshot_dest = ext_snapshot_dir / snapshot_name
                shutil.copy2(template_fp, snapshot_dest)
                request_template_file_path = str(snapshot_dest)
            except Exception as snap_err:
                logger.warning(f"Could not create extraction template snapshot copy: {snap_err}")
                request_template_file_path = template_fp

        final_canonical_fields: List[str] = []
        final_requested_columns: List[str] = requested_columns or (list(template_hdrs) if template_hdrs else [])
        final_column_mapping: Dict[str, str] = column_mapping or {}

        if requested_fields:
            for f in requested_fields:
                canon = resolve_canonical_field_key(f) or f.strip().lower().replace(" ", "_")
                if canon not in final_canonical_fields:
                    final_canonical_fields.append(canon)

        if final_requested_columns:
            for col in final_requested_columns:
                if col not in final_column_mapping:
                    canon = resolve_canonical_field_key(col) or col.strip().lower().replace(" ", "_")
                    final_column_mapping[col] = canon
                canon = final_column_mapping[col]
                if canon not in final_canonical_fields:
                    final_canonical_fields.append(canon)

        if not final_canonical_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one valid field must be requested for extraction.",
            )

        # Build deduplicated canonical student units for this Batch (+ optional Section)
        canonical_units = await self._build_canonical_student_units(batch_ids, clean_class_id)
        if len(canonical_units) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No students found for this Batch/Section.",
            )

        # Query configured wanted fields for this batch (+ Section override if applicable)
        doc_configs = await self.wanted_field_repository.list_by_batch(batch_id_str, class_id=clean_class_id)
        field_to_configured_doc_types: Dict[str, List[str]] = {}
        field_to_configured_doc_type: Dict[str, str] = {}
        field_to_source_doc_name: Dict[str, str] = {}
        field_to_source_field: Dict[str, str] = {}
        field_to_target_header: Dict[str, str] = {}
        field_mappings_snapshot: List[Dict[str, Any]] = []

        for dc in doc_configs:
            canon_doc_type = resolve_canonical_document_type(dc.document_type, dc.display_name)
            for f in dc.fields:
                if f.enabled:
                    f_canon = resolve_canonical_field_key(f.field) or f.field.strip().lower().replace(" ", "_")
                    effective_doc_type = canon_doc_type
                    # Guard: If field is academic year or joining, do not route to AADHAAR
                    if effective_doc_type == "AADHAAR" and any(k in f_canon for k in ["academic_year", "academic year", "year of joining", "joining"]):
                        logger.warning(f"[BatchExtraction] Guard: Disallowing AADHAAR routing for academic field '{f.field}'")
                        effective_doc_type = "STUDENT_PROFILE"

                    if f_canon not in field_to_configured_doc_types:
                        field_to_configured_doc_types[f_canon] = []
                    if effective_doc_type not in field_to_configured_doc_types[f_canon]:
                        field_to_configured_doc_types[f_canon].append(effective_doc_type)
                    if f_canon not in field_to_configured_doc_type:
                        field_to_configured_doc_type[f_canon] = effective_doc_type
                    field_to_source_doc_name[f_canon] = "Admission Record" if effective_doc_type == "STUDENT_PROFILE" else (dc.display_name or dc.document_type)
                    field_to_source_field[f_canon] = f.field

                    target_hdr = f.excel_header.strip() if f.excel_header else None
                    if target_hdr:
                        field_to_target_header[f_canon] = target_hdr

                    col_idx = None
                    if target_hdr:
                        col_idx = header_to_col.get(target_hdr)
                        if not col_idx and target_hdr in template_hdrs:
                            col_idx = template_hdrs.index(target_hdr) + 1

                    field_mappings_snapshot.append({
                        "source_document": dc.document_type,
                        "canonical_document_type": canon_doc_type,
                        "source_field": f.field,
                        "field_key": f_canon,
                        "target_excel_header": target_hdr,
                        "target_column_index": col_idx,
                    })

        # Augment with any explicit column mappings
        for hdr, canon in final_column_mapping.items():
            if not any(fm.get("target_excel_header") == hdr for fm in field_mappings_snapshot):
                col_idx = header_to_col.get(hdr)
                if not col_idx and hdr in template_hdrs:
                    col_idx = template_hdrs.index(hdr) + 1
                field_mappings_snapshot.append({
                    "source_document": "MAPPED_HEADER",
                    "canonical_document_type": "OTHER",
                    "source_field": hdr,
                    "field_key": canon,
                    "target_excel_header": hdr,
                    "target_column_index": col_idx,
                })

        now = datetime.now(timezone.utc)
        batch_req = BatchExtractionRequest(
            batch_id=batch_id_str,
            batch_name=batch.name,
            academic_year=batch.academic_year,
            department_id=batch.department_id,
            class_id=clean_class_id,
            template_id=template_id,
            template_filename=template_fn,
            template_file_path=request_template_file_path,
            template_sheet_name=template_sheet,
            header_row_index=template_hdr_row,
            template_headers=template_hdrs,
            header_to_column_index=header_to_col,
            field_mappings=field_mappings_snapshot,
            requested_fields=final_canonical_fields,
            requested_columns=final_requested_columns or [f.replace("_", " ").title() for f in final_canonical_fields],
            column_mapping=final_column_mapping,
            total_students=len(canonical_units),
            processed_count=0,
            result_count=0,
            successful_count=0,
            partial_count=0,
            missing_docs_count=0,
            failed_count=0,
            verified_count=0,
            correction_requested_count=0,
            pending_verification_count=0,
            status=BatchExtractionStatus.PROCESSING.value,
            verification_status=BatchVerificationStatus.PENDING.value,
            export_status=BatchExportStatus.NOT_READY.value,
            created_by=actor.username,
            created_at=now,
            started_at=now,
        )
        await self.repository.create(batch_req)

        try:
            processed_count = 0
            successful_count = 0
            partial_count = 0
            missing_docs_count = 0
            failed_count = 0
            pending_verification_students = 0
            source_versions_summary: List[Dict[str, Any]] = []
            all_student_data: Dict[str, Dict[str, Any]] = {}

            for unit in canonical_units:
                student_id = unit.canonical_id
                stud_docs = unit.documents

                # Group student's stored documents strictly by canonical document type
                # Prioritize active versions
                def _doc_score(doc: StudentDocument) -> int:
                    if doc.active_version and doc.active_version.file_path and os.path.exists(doc.active_version.file_path):
                        return 2
                    if doc.active_version:
                        return 1
                    return 0

                docs_by_type: Dict[str, StudentDocument] = {}
                for d in stud_docs:
                    norm_type = resolve_canonical_document_type(d.document_type, d.document_name)
                    if norm_type not in docs_by_type or _doc_score(d) > _doc_score(docs_by_type[norm_type]):
                        docs_by_type[norm_type] = d

                    # Also register common aliases for deterministic lookup
                    if norm_type == "TRANSFER_CERTIFICATE":
                        docs_by_type["TC"] = d
                    elif norm_type == "BANK_PASSBOOK":
                        docs_by_type["PASSBOOK"] = d
                    elif norm_type == "SSLC":
                        docs_by_type["10TH"] = d
                    elif norm_type == "HSC":
                        docs_by_type["12TH"] = d

                    # Self-heal document_type in DB if previously stored as raw ObjectId
                    if d.document_type != norm_type and norm_type not in ("UNKNOWN", "OTHER"):
                        try:
                            d.document_type = norm_type
                            await d.save()
                        except Exception:
                            pass

                # Multi-document extraction and soft authority fusion for requested fields
                extractions_by_doc: Dict[str, Dict[str, FieldExtractionResult]] = {}
                student_extracted_fields: Dict[str, Any] = {}
                student_field_results: Dict[str, FieldExtractionResult] = {}
                used_doc_versions: List[str] = []
                student_has_missing_doc = False
                student_failed = False
                usable_fields_count = 0

                # Identify trusted profile fields available in database profile
                available_profile_fields = set()
                for field_key in final_canonical_fields:
                    prof_val = unit.get_profile_value(field_key)
                    if prof_val is not None and str(prof_val).strip() != "":
                        available_profile_fields.add(field_key)

                non_roster_fields = [
                    f for f in final_canonical_fields
                    if f not in available_profile_fields
                    and f not in ("register_number", "register_no", "reg_no", "roll_no", "student_id")
                ]

                # Ensure stored document file paths are robustly resolved to disk
                for d in stud_docs:
                    if d.active_version and d.active_version.file_path and not os.path.exists(d.active_version.file_path):
                        res_p = resolve_document_file_path(
                            d.active_version.file_path,
                            batch_id=str(d.batch_id),
                            register_number=str(d.student_id),
                            document_name=d.document_name,
                        )
                        if res_p and res_p.is_file():
                            d.active_version.file_path = str(res_p.resolve())
                            try:
                                await d.save()
                            except Exception:
                                pass

                # Identify stored documents with valid active files and passing classification validation
                valid_stored_docs = [
                    d for d in stud_docs
                    if d.active_version and d.active_version.file_path and os.path.exists(d.active_version.file_path)
                    and (d.active_version.validation_status in ("VALID", "PENDING", None) or d.reclassification_history)
                    and d.active_version.validation_status not in ("WRONG_DOCUMENT", "UNKNOWN", "CLASSIFICATION_FAILED", "NEEDS_REVIEW", "INVALID")
                ]

                for d in valid_stored_docs:
                    d_type = resolve_canonical_document_type(d.document_type, d.document_name)
                    active_v = d.active_version

                    doc_fields_to_extract: List[str] = []
                    allowed_for_doc = ALLOWED_CANONICAL_FIELDS_BY_DOC_TYPE.get(d_type)
                    for field_key in non_roster_fields:
                        canon_f = resolve_canonical_field_key(field_key) or field_key.strip().lower()
                        if allowed_for_doc is not None and canon_f not in allowed_for_doc:
                            continue

                        configured_types = field_to_configured_doc_types.get(field_key, [])
                        default_types = self._get_target_doc_types_for_field(field_key)
                        candidate_types = list(configured_types) + [
                            dt for dt in default_types if dt not in configured_types
                        ]
                        if not candidate_types and field_to_configured_doc_type.get(field_key):
                            candidate_types = [field_to_configured_doc_type[field_key]]

                        canon_candidates = [resolve_canonical_document_type(ct) for ct in candidate_types]
                        if d_type in canon_candidates or d.document_type in candidate_types or d_type in ("UNKNOWN", "OTHER"):
                            doc_fields_to_extract.append(field_key)

                    extracted_data_map: Dict[str, Any] = {}
                    if doc_fields_to_extract:
                        try:
                            # Pre-extract all candidate fields in a single multimodal call for this document
                            doc_ext_req, doc_ext_res = await self.extraction_service.request_and_extract_fields(
                                student_document_id=str(d.id),
                                requested_fields=doc_fields_to_extract,
                                actor=actor,
                                version_id=active_v.version_id,
                            )
                            if doc_ext_res and doc_ext_res.extracted_data:
                                extracted_data_map = doc_ext_res.extracted_data
                            elif doc_ext_req and doc_ext_req.status == ExtractionRequestStatus.FAILED:
                                error_text = doc_ext_req.error_message or "Document extraction failed."
                                upper_error = error_text.upper()
                                if "DOCUMENT_INVALID" in upper_error or "EMPTY" in upper_error or "CORRUPTED" in upper_error:
                                    failure_state = "DOCUMENT_INVALID"
                                elif "OCR_LOW_QUALITY" in upper_error:
                                    failure_state = "OCR_LOW_QUALITY"
                                elif "AI_EXTRACTION_UNAVAILABLE" in upper_error or "429" in upper_error or "QUOTA" in upper_error:
                                    failure_state = "AI_EXTRACTION_UNAVAILABLE"
                                elif "OCR_FAILED" in upper_error:
                                    failure_state = "OCR_FAILED"
                                elif "AI_EXTRACTION_FAILED" in upper_error:
                                    failure_state = "AI_EXTRACTION_FAILED"
                                else:
                                    failure_state = "EXTRACTION_FAILED"
                                for field_key in doc_fields_to_extract:
                                    extractions_by_doc.setdefault(d_type, {})[field_key] = FieldExtractionResult(
                                        field_name=field_key,
                                        raw_value=None,
                                        normalized_value="NOT_AVAILABLE",
                                        confidence="LOW",
                                        confidence_score=0.0,
                                        field_state=failure_state,
                                        reason=error_text,
                                        source_document_type=d_type,
                                        source_document_id=str(d.id),
                                        source_document_version=active_v.version_id,
                                        source_document_name=None if failure_state in ("DOCUMENT_INVALID", "DOCUMENT_MISSING") else d.document_name,
                                    )
                                continue
                        except Exception as ex:
                            logger.error(f"[FIELD_EXTRACTION_EX] {ex}", exc_info=True)
                            error_text = str(ex)
                            upper_error = error_text.upper()
                            if "DOCUMENT_INVALID" in upper_error or "EMPTY" in upper_error or "CORRUPTED" in upper_error:
                                failure_state = "DOCUMENT_INVALID"
                            elif "OCR_LOW_QUALITY" in upper_error:
                                failure_state = "OCR_LOW_QUALITY"
                            elif "AI_EXTRACTION_UNAVAILABLE" in upper_error or "429" in upper_error or "QUOTA" in upper_error:
                                failure_state = "AI_EXTRACTION_UNAVAILABLE"
                            elif "OCR_FAILED" in upper_error:
                                failure_state = "OCR_FAILED"
                            elif "AI_EXTRACTION_FAILED" in upper_error:
                                failure_state = "AI_EXTRACTION_FAILED"
                            else:
                                failure_state = "EXTRACTION_FAILED"
                            logger.warning(
                                "[FIELD_EXTRACTION] student=%s source_document=%s fields=%s request_failed=%s",
                                _mask_student_id(student_id),
                                d_type,
                                ",".join(doc_fields_to_extract),
                                failure_state,
                            )
                            for field_key in doc_fields_to_extract:
                                logger.info(
                                    "[FIELD_EXTRACTION] FIELD_MATCH field=%s matched=false failure_state=%s",
                                    field_key,
                                    failure_state,
                                )
                                extractions_by_doc.setdefault(d_type, {})[field_key] = FieldExtractionResult(
                                    field_name=field_key,
                                    raw_value=None,
                                    normalized_value="NOT_AVAILABLE",
                                    confidence="LOW",
                                    confidence_score=0.0,
                                    field_state=failure_state,
                                    reason=error_text,
                                    source_document_type=d_type,
                                    source_document_id=str(d.id),
                                    source_document_version=active_v.version_id if active_v else None,
                                    source_document_name=None if failure_state in ("DOCUMENT_INVALID", "DOCUMENT_MISSING") else d.document_name,
                                )
                            continue

                        file_path = active_v.file_path if active_v else None
                        file_loaded = bool(file_path and os.path.isfile(file_path))
                        logger.info(
                            "[FIELD_EXTRACTION] student=%s source_document=%s document_version=%s file_loaded=%s mime_type=%s file_size=%d fields=%s",
                            _mask_student_id(student_id),
                            d_type,
                            active_v.version_number if active_v else "UNKNOWN",
                            file_loaded,
                            active_v.mime_type if active_v else "UNKNOWN",
                            os.path.getsize(file_path) if file_loaded else 0,
                            ",".join(doc_fields_to_extract),
                        )

                        for field_key in doc_fields_to_extract:
                            try:
                                try:
                                    field_res = await self._extract_field_with_accuracy(
                                        doc=d,
                                        version=active_v,
                                        field_key=field_key,
                                        actor=actor,
                                        extracted_data_override=extracted_data_map,
                                    )
                                except TypeError:
                                    field_res = await self._extract_field_with_accuracy(
                                        doc=d,
                                        version=active_v,
                                        field_key=field_key,
                                        actor=actor,
                                    )
                                extractions_by_doc.setdefault(d_type, {})[field_key] = field_res
                                logger.info(
                                    "[FIELD_EXTRACTION] FIELD_MATCH field=%s matched=%s",
                                    field_key,
                                    field_res.normalized_value not in (None, "", "NOT_AVAILABLE"),
                                )
                            except Exception as ex:
                                logger.error(f"[BatchExtraction] Error extracting {field_key} from doc {d.id}: {ex}")

                # Fuse candidate extractions across documents with soft authority & conflict detection
                fused_results = self.accuracy_engine.detect_cross_document_conflicts(
                    extractions_by_doc_type=extractions_by_doc,
                    field_to_configured_doc_type=field_to_configured_doc_type,
                )

                student_coverage_matrix: List[Dict[str, Any]] = []

                for field_key in final_canonical_fields:
                    # 1. Profile fields (name, roll_number, email, mobile_number) from database profile
                    if field_key in available_profile_fields:
                        prof_val = unit.get_profile_value(field_key)
                        prof_res = FieldExtractionResult(
                            field_name=field_key,
                            raw_value=prof_val,
                            normalized_value=prof_val,
                            confidence="HIGH",
                            confidence_score=1.0,
                            field_state="EXTRACTED",
                            evidence_snippet=f"Retrieved from student profile: {prof_val}",
                            source_document_type="STUDENT_PROFILE",
                            source_document_name="Student Profile",
                            source_document_id=unit.student_submission_id or "STUDENT_PROFILE",
                            source_document_version="1",
                        )
                        student_field_results[field_key] = prof_res
                        student_extracted_fields[field_key] = prof_val
                        usable_fields_count += 1
                        coverage_rec = {
                            "field_key": field_key,
                            "excel_header": field_to_target_header.get(field_key) or field_key.replace("_", " ").title(),
                            "requested": True,
                            "source_document_type": "STUDENT_PROFILE",
                            "student_document_found": True,
                            "document_version_found": True,
                            "file_exists": True,
                            "file_size": 0,
                            "mime_type": "text/plain",
                            "ocr_status": "NOT_NEEDED",
                            "ocr_text_length": len(str(prof_val)),
                            "ocr_text_preview": str(prof_val),
                            "gemini_called": False,
                            "gemini_status": "NOT_NEEDED",
                            "gemini_raw_field_present": True,
                            "normalized_value": prof_val,
                            "final_value": prof_val,
                            "failure_reason": None,
                        }
                        student_coverage_matrix.append(coverage_rec)
                        logger.info(
                            f"[ExtractionEngine] Student: {student_id} | Field: {field_key} | "
                            f"Configured Source: STUDENT_PROFILE | Resolved Document: Student Profile | "
                            f"Document ID: {prof_res.source_document_id} | Extraction Result: {mask_sensitive_value(prof_val)} | Status: EXTRACTED"
                        )
                        continue

                    # 2. Roster Register Number / Student ID (fallback)
                    if field_key in ("register_number", "register_no", "reg_no", "roll_no", "student_id"):
                        reg_res = FieldExtractionResult(
                            field_name=field_key,
                            raw_value=student_id,
                            normalized_value=student_id,
                            confidence="HIGH",
                            confidence_score=1.0,
                            field_state="EXTRACTED",
                            evidence_snippet=f"Register Number: {student_id}",
                            source_document_type="STUDENT_RECORD",
                        )
                        student_field_results[field_key] = reg_res
                        student_extracted_fields[field_key] = student_id
                        usable_fields_count += 1
                        coverage_rec = {
                            "field_key": field_key,
                            "excel_header": field_to_target_header.get(field_key) or field_key.replace("_", " ").title(),
                            "requested": True,
                            "source_document_type": "STUDENT_RECORD",
                            "student_document_found": True,
                            "document_version_found": True,
                            "file_exists": True,
                            "file_size": 0,
                            "mime_type": "text/plain",
                            "ocr_status": "NOT_NEEDED",
                            "ocr_text_length": len(student_id),
                            "ocr_text_preview": student_id,
                            "gemini_called": False,
                            "gemini_status": "NOT_NEEDED",
                            "gemini_raw_field_present": True,
                            "normalized_value": student_id,
                            "final_value": student_id,
                            "failure_reason": None,
                        }
                        student_coverage_matrix.append(coverage_rec)
                        logger.info(
                            f"[ExtractionEngine] Student: {student_id} | Field: {field_key} | "
                            f"Configured Source: STUDENT_RECORD | Resolved Document: Roster | "
                            f"Document ID: N/A | Extraction Result: {student_id} | Status: EXTRACTED"
                        )
                        continue

                    f_res = fused_results.get(field_key)
                    is_already_extracted = bool(
                        f_res
                        and f_res.normalized_value not in (None, "", "NOT_AVAILABLE")
                        and f_res.field_state not in (
                            "DOCUMENT_MISSING",
                            "DOCUMENT_INVALID",
                            "OCR_FAILED",
                            "OCR_LOW_QUALITY",
                            "AI_EXTRACTION_FAILED",
                            "EXTRACTION_FAILED",
                            "NOT_FOUND",
                        )
                    )

                    configured_types = field_to_configured_doc_types.get(field_key, [])
                    default_types = self._get_target_doc_types_for_field(field_key)
                    candidate_types = list(configured_types) + [
                        dt for dt in default_types if dt not in configured_types
                    ]
                    if not candidate_types and field_to_configured_doc_type.get(field_key):
                        candidate_types = [field_to_configured_doc_type[field_key]]

                    if is_already_extracted:
                        target_doc_type = f_res.source_document_type or resolve_canonical_document_type(candidate_types[0] if candidate_types else "OTHER")
                        doc_for_target = docs_by_type.get(f_res.source_document_type) or docs_by_type.get(target_doc_type)
                        doc_found = True
                        version_found = bool(doc_for_target and doc_for_target.active_version)
                        file_path = doc_for_target.active_version.file_path if version_found else None
                        file_exists = bool(file_path and os.path.exists(file_path))
                        file_size = os.path.getsize(file_path) if file_exists else 0
                        mime_type = doc_for_target.active_version.mime_type if version_found else None
                        ocr_status_val = "OCR_SUCCESS"
                        ocr_len_val = 0
                        ocr_prev_val = ""

                        extracted_val = f_res.normalized_value
                        student_extracted_fields[field_key] = extracted_val
                        student_field_results[field_key] = f_res
                        usable_fields_count += 1
                        f_state = f_res.field_state if f_res.field_state in ("HIGH_CONFIDENCE", "CONFLICTING_VALUES", "REVIEW_REQUIRED") else "EXTRACTED"
                        fail_reason = None
                        if f_res.source_document_type and f_res.source_document_version:
                            ver_tag = f"{f_res.source_document_type}:v{f_res.source_document_version}"
                            if ver_tag not in used_doc_versions:
                                used_doc_versions.append(ver_tag)
                    else:
                        # Find the highest-priority candidate document that the student actually has uploaded
                        doc_for_target = None
                        target_doc_type = None
                        for ct in candidate_types:
                            canon_ct = resolve_canonical_document_type(ct)
                            if canon_ct in docs_by_type:
                                doc_for_target = docs_by_type[canon_ct]
                                target_doc_type = canon_ct
                                break

                        if not doc_for_target:
                            target_doc_type = resolve_canonical_document_type(candidate_types[0]) if candidate_types else "OTHER"
                            is_profile_source = target_doc_type == "STUDENT_PROFILE"
                            if is_profile_source or target_doc_type in ("OTHER", "UNKNOWN"):
                                student_extracted_fields[field_key] = None
                                f_state = "NOT_FOUND"
                                fail_reason = f"NOT_FOUND: Value for '{field_key}' not found in admission records or documents."
                                doc_found = False
                                version_found = False
                                file_path = None
                                file_exists = False
                                file_size = 0
                                mime_type = None
                                ocr_status_val = "NOT_FOUND"
                                ocr_len_val = 0
                                ocr_prev_val = ""
                                f_res = FieldExtractionResult(
                                    field_name=field_key,
                                    raw_value=None,
                                    normalized_value=None,
                                    confidence="LOW",
                                    confidence_score=0.0,
                                    field_state="NOT_FOUND",
                                    reason=fail_reason,
                                    source_document_type="STUDENT_PROFILE" if is_profile_source else "OTHER",
                                    source_document_name="Admission Record" if is_profile_source else None,
                                )
                                student_field_results[field_key] = f_res
                            else:
                                student_has_missing_doc = True
                                student_extracted_fields[field_key] = "NOT_AVAILABLE"
                                f_state = "SOURCE_DOCUMENT_MISSING"
                                fail_reason = f"SOURCE_DOCUMENT_MISSING: Configured source document '{target_doc_type}' not found for student."
                                doc_found = False
                                version_found = False
                                file_path = None
                                file_exists = False
                                file_size = 0
                                mime_type = None
                                ocr_status_val = "SOURCE_DOCUMENT_MISSING"
                                ocr_len_val = 0
                                ocr_prev_val = ""
                                f_res = FieldExtractionResult(
                                    field_name=field_key,
                                    raw_value=None,
                                    normalized_value="NOT_AVAILABLE",
                                    confidence="LOW",
                                    confidence_score=0.0,
                                    field_state="SOURCE_DOCUMENT_MISSING",
                                    reason=fail_reason,
                                    source_document_type=target_doc_type,
                                )
                                student_field_results[field_key] = f_res
                        else:
                            doc_found = True
                            version_found = bool(doc_for_target.active_version)
                            file_path = doc_for_target.active_version.file_path if version_found else None
                            file_exists = bool(file_path and os.path.exists(file_path))
                            file_size = os.path.getsize(file_path) if file_exists else 0
                            mime_type = doc_for_target.active_version.mime_type if version_found else None
                            ocr_status_val = "OCR_SUCCESS" if file_exists else "OCR_FAILED"
                            ocr_len_val = 0
                            ocr_prev_val = ""

                            if not file_exists or file_size == 0:
                                student_has_missing_doc = True
                                student_extracted_fields[field_key] = "NOT_AVAILABLE"
                                f_state = "SOURCE_DOCUMENT_MISSING"
                                fail_reason = "SOURCE_DOCUMENT_MISSING: Stored document file does not exist or is 0 bytes."
                                f_res = FieldExtractionResult(
                                    field_name=field_key,
                                    raw_value=None,
                                    normalized_value="NOT_AVAILABLE",
                                    confidence="LOW",
                                    confidence_score=0.0,
                                    field_state="SOURCE_DOCUMENT_MISSING",
                                    reason=fail_reason,
                                    source_document_type=target_doc_type,
                                )
                                student_field_results[field_key] = f_res
                            elif f_res and f_res.field_state == "DOCUMENT_INVALID":
                                student_extracted_fields[field_key] = "NOT_AVAILABLE"
                                student_field_results[field_key] = f_res
                                f_state = "DOCUMENT_INVALID"
                                ocr_status_val = "DOCUMENT_INVALID"
                                fail_reason = f_res.reason or "DOCUMENT_INVALID: Stored document is empty or invalid placeholder."
                            elif f_res and f_res.field_state in ("OCR_FAILED", "OCR_LOW_QUALITY"):
                                student_extracted_fields[field_key] = "NOT_AVAILABLE"
                                student_field_results[field_key] = f_res
                                f_state = f_res.field_state
                                ocr_status_val = f_res.field_state
                                fail_reason = f"{f_res.field_state}: OCR did not produce usable text."
                            elif f_res and f_res.field_state in ("AI_EXTRACTION_UNAVAILABLE", "AI_EXTRACTION_FAILED", "EXTRACTION_FAILED"):
                                student_extracted_fields[field_key] = None
                                student_field_results[field_key] = f_res
                                student_failed = True
                                f_state = "AI_EXTRACTION_FAILED"
                                fail_reason = f_res.reason or "AI_EXTRACTION_FAILED: Gemini extraction call failed."
                            else:
                                student_extracted_fields[field_key] = "NOT_AVAILABLE"
                                f_state = "NOT_FOUND"
                                fail_reason = "FIELD_NOT_FOUND: Field not present in document."
                                if not f_res:
                                    f_res = FieldExtractionResult(
                                        field_name=field_key,
                                        raw_value=None,
                                        normalized_value="NOT_AVAILABLE",
                                        confidence="LOW",
                                        confidence_score=0.0,
                                        field_state="NOT_FOUND",
                                        reason=fail_reason,
                                        source_document_type=target_doc_type,
                                    )
                                else:
                                    f_res.field_state = "NOT_FOUND"
                                    f_res.reason = fail_reason
                                student_field_results[field_key] = f_res

                    coverage_rec = {
                        "field_key": field_key,
                        "excel_header": field_to_target_header.get(field_key) or field_key.replace("_", " ").title(),
                        "requested": True,
                        "source_document_type": target_doc_type,
                        "student_document_found": doc_found,
                        "document_version_found": version_found,
                        "file_exists": file_exists,
                        "file_size": file_size,
                        "mime_type": mime_type,
                        "ocr_status": ocr_status_val,
                        "ocr_text_length": ocr_len_val,
                        "ocr_text_preview": ocr_prev_val,
                        "gemini_called": bool(file_exists and f_state != "DOCUMENT_INVALID"),
                        "gemini_status": "SUCCESS" if f_state in ("EXTRACTED", "NOT_FOUND") else ("NOT_CALLED" if not file_exists else "FAILED"),
                        "gemini_raw_field_present": bool(f_res and f_res.raw_value is not None),
                        "normalized_value": f_res.normalized_value if f_state == "EXTRACTED" else None,
                        "final_value": f_res.normalized_value if f_state == "EXTRACTED" else None,
                        "failure_reason": fail_reason,
                    }
                    student_coverage_matrix.append(coverage_rec)

                    logger.info(
                        "[FIELD_EXTRACTION] FIELD_VALUE_PERSISTED field=%s success=%s state=%s failure_reason=%s",
                        field_key,
                        f_state == "EXTRACTED",
                        f_state,
                        fail_reason,
                    )
                    logger.info(
                        f"[ExtractionEngine] Student: {student_id} | Field: {field_key} | "
                        f"Configured Source: {target_doc_type} | "
                        f"Resolved Document: {f_res.source_document_name or f_res.source_document_type} v{f_res.source_document_version} | "
                        f"Document ID: {f_res.source_document_id} | Extraction Result: {mask_sensitive_value(f_res.normalized_value)} | "
                        f"Status: {f_state}"
                    )

                # Update count tallies
                processed_count += 1
                has_usable_data = (usable_fields_count > 0)
                has_missing_doc = student_has_missing_doc

                if student_failed and not has_usable_data:
                    failed_count += 1
                elif has_usable_data and has_missing_doc:
                    partial_count += 1
                    missing_docs_count += 1
                    pending_verification_students += 1
                elif has_usable_data and not has_missing_doc:
                    successful_count += 1
                    pending_verification_students += 1
                elif not has_usable_data and has_missing_doc:
                    missing_docs_count += 1
                    failed_count += 1
                else:
                    failed_count += 1

                first_doc = stud_docs[0] if stud_docs else None
                first_doc_id = str(first_doc.id) if first_doc else f"placeholder_{student_id}"
                first_v_id = first_doc.active_version.version_id if (first_doc and first_doc.active_version) else "v1"
                extraction_result_id = f"res_{batch_req.extraction_request_id}_{student_id}"

                # Clean prior verifications for this student under this extraction request to prevent duplicate records
                verif_delete_query: Dict[str, Any] = {
                    "extraction_request_id": batch_req.extraction_request_id,
                    "$or": [
                        {"student_id": unit.canonical_id},
                        {"student_id": {"$in": list(unit.aliases)}},
                    ] + ([{"student_submission_id": unit.student_submission_id}] if unit.student_submission_id else []),
                }
                await DocumentFieldVerification.find(verif_delete_query).delete()

                verif_records: List[DocumentFieldVerification] = []
                for f_name, f_val in student_extracted_fields.items():
                    target_doc_type = field_to_configured_doc_type.get(f_name)
                    if not target_doc_type:
                        default_types = self._get_target_doc_types_for_field(f_name)
                        target_doc_type = resolve_canonical_document_type(default_types[0]) if default_types else "OTHER"

                    f_res = student_field_results.get(f_name)
                    doc_for_field: Optional[StudentDocument] = docs_by_type.get(target_doc_type)

                    res_raw = f_res.raw_value if f_res else f_val
                    res_norm = f_res.normalized_value if f_res else f_val
                    res_conf = f_res.confidence if f_res else "HIGH"
                    res_score = f_res.confidence_score if f_res else 1.0
                    res_state = f_res.field_state if f_res else "EXTRACTED"
                    res_evidence = f_res.evidence_snippet if f_res else None
                    res_page = f_res.page_number if f_res else 1
                    res_reason = f_res.reason if f_res else None
                    res_conflicts = f_res.conflicts if f_res else []
                    res_doc_id = (f_res.source_document_id if f_res and f_res.source_document_id else (str(doc_for_field.id) if doc_for_field else f"missing_{target_doc_type}"))
                    res_doc_ver = (f_res.source_document_version if f_res and f_res.source_document_version else (doc_for_field.active_version.version_id if doc_for_field and doc_for_field.active_version else first_v_id))
                    res_doc_name = (f_res.source_document_name if f_res and f_res.source_document_name else (doc_for_field.document_name if doc_for_field else None))
                    if res_state in ("DOCUMENT_INVALID", "DOCUMENT_MISSING", "SOURCE_DOCUMENT_MISSING"):
                        res_doc_name = None
                    res_doc_type = (f_res.source_document_type if f_res and f_res.source_document_type else target_doc_type)

                    verif_rec = DocumentFieldVerification(
                        extraction_result_id=extraction_result_id,
                        extraction_request_id=batch_req.extraction_request_id,
                        student_id=unit.canonical_id,
                        student_submission_id=unit.student_submission_id,
                        document_id=res_doc_id,
                        document_version_id=res_doc_ver,
                        source_document_name=res_doc_name,
                        department_id=batch.department_id,
                        batch_id=batch_id_str,
                        class_id=unit.class_id or clean_class_id or (doc_for_field.class_id if doc_for_field else None),
                        document_type=res_doc_type,
                        field_name=f_name,
                        ai_value=None if res_norm in ("NOT_AVAILABLE", "NOT_FOUND", None) else res_norm,
                        raw_value=None if res_raw in ("NOT_AVAILABLE", "NOT_FOUND", None) else res_raw,
                        student_value=None,
                        final_value=None if res_norm in ("NOT_AVAILABLE", "NOT_FOUND", None) else res_norm,
                        status=VerificationFieldStatus.AI_EXTRACTED,
                        confidence=res_conf,
                        confidence_score=res_score,
                        field_state=res_state,
                        evidence_snippet=res_evidence,
                        page_number=res_page,
                        reason=res_reason,
                        conflicts=res_conflicts,
                        history=[
                            VerificationHistoryEntry(
                                actor="AI_ENGINE",
                                actor_role="SYSTEM",
                                action="AI_EXTRACTION",
                                old_value=None,
                                new_value=None if res_norm in ("NOT_AVAILABLE", "NOT_FOUND", None) else res_norm,
                                document_version_id=res_doc_ver,
                                timestamp=now,
                            )
                        ],
                        created_at=now,
                        updated_at=now,
                    )
                    verif_records.append(verif_rec)

                if verif_records:
                    await self.verif_repository.bulk_create(verif_records)
                    all_student_data[student_id] = {r.field_name: r for r in verif_records}

                # Initialize verification token ONLY when student has usable extracted data
                if has_usable_data:
                    try:
                        v_service = VerificationTokenService()
                        await v_service.create_or_get_token(
                            student_id=student_id,
                            batch_id=batch_id_str,
                            student_name=unit.student_name,
                            batch_name=batch.name,
                            class_id=clean_class_id,
                            department_id=batch.department_id,
                            extraction_request_id=batch_req.extraction_request_id,
                        )
                    except Exception as tok_err:
                        logger.debug(f"[BatchExtraction] Token init notice for {student_id}: {tok_err}")

                source_versions_summary.append({
                    "student_id": student_id,
                    "versions_used": used_doc_versions,
                })

            # Generate and persist the final updated Excel file directly upon extraction completion
            alias_to_unit = {alias: u for u in canonical_units for alias in u.aliases}
            saved_file_path, exported_filename = await self._generate_and_save_final_excel(
                batch_req=batch_req,
                canonical_units=canonical_units,
                student_data=all_student_data,
                alias_to_unit=alias_to_unit,
            )
            batch_req.exported_file_path = saved_file_path
            batch_req.exported_filename = exported_filename
            batch_req.export_status = BatchExportStatus.READY.value

            # Extraction results required for student verification remain available until verification and staff review are complete.
            # Temporary processing data is retained for verification access.

            # Retain historical batch extractions (do not delete coexisting extraction requests)
            # Ephemeral file cleanup if needed
            pass

            # Determine overall batch status (Partial batch success supported)
            if failed_count > 0 and (successful_count > 0 or partial_count > 0):
                overall_status = BatchExtractionStatus.PARTIAL.value
            elif failed_count == len(canonical_units) and len(canonical_units) > 0:
                overall_status = BatchExtractionStatus.FAILED.value
            else:
                overall_status = BatchExtractionStatus.COMPLETED.value

            batch_req.status = overall_status
            batch_req.verification_status = BatchVerificationStatus.PENDING.value
            batch_req.total_students = len(canonical_units)
            batch_req.result_count = processed_count
            batch_req.processed_count = processed_count
            batch_req.successful_count = successful_count
            batch_req.partial_count = partial_count
            batch_req.missing_docs_count = missing_docs_count
            batch_req.failed_count = failed_count
            batch_req.verified_count = 0
            batch_req.pending_verification_count = pending_verification_students
            batch_req.source_document_versions = source_versions_summary
            batch_req.completed_at = datetime.now(timezone.utc)
            await self.repository.save(batch_req)

            return self._to_summary_response(batch_req)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[BatchExtraction] Extraction failed for batch {batch_id}: {e}", exc_info=True)
            batch_req.status = BatchExtractionStatus.FAILED.value
            batch_req.failed_at = datetime.now(timezone.utc)
            batch_req.error_message = str(e) or "Batch extraction failed."
            await self.repository.save(batch_req)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Batch extraction encountered an error: {str(e)}",
            )

    async def get_extraction_details(
        self,
        extraction_request_id: str,
        actor: User,
        status_filter: Optional[str] = "ALL",
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> BatchExtractionDetailResponse:
        """
        Get full details of a batch extraction request including summary metrics,
        paginated student extraction rows, and correction queue.
        """
        req = await self.repository.get_by_request_id(extraction_request_id)
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Extraction request '{extraction_request_id}' not found.",
            )

        batch = await self.batch_repository.get_batch_by_id(req.batch_id)
        if batch:
            self.verify_batch_access(batch, actor)

        verif_records = await DocumentFieldVerification.find(
            DocumentFieldVerification.extraction_request_id == req.extraction_request_id
        ).to_list()

        # Query stored documents and canonical units for students in this batch
        batch_id_str = str(req.batch_id)
        batch_ids = [batch_id_str]
        if batch:
            batch_ids.append(str(batch.id))
            if hasattr(batch, "name") and batch.name and batch.name not in batch_ids:
                batch_ids.append(batch.name)
            if isinstance(batch.id, PydanticObjectId) and batch.id not in batch_ids:
                batch_ids.append(batch.id)

        canonical_units = await self._build_canonical_student_units(batch_ids, req.class_id)
        alias_to_unit: Dict[str, CanonicalStudentUnit] = {}
        for u in canonical_units:
            for alias in u.aliases:
                alias_to_unit[alias] = u

        if req.extraction_request_id:
            tokens_for_req = await VerificationToken.find(
                {"extraction_request_id": req.extraction_request_id}
            ).to_list()
            if not tokens_for_req:
                tokens_for_req = await VerificationToken.find(
                    {"batch_id": req.batch_id, "extraction_request_id": {"$in": [None, ""]}}
                ).to_list()
        else:
            tokens_for_req = await VerificationToken.find(
                {"batch_id": req.batch_id}
            ).to_list()
        completed_token_ids = {
            t.student_id.strip().upper()
            for t in tokens_for_req
            if t.status == VerificationTokenStatus.COMPLETED.value
        }

        def _is_student_token_completed(stud_id_val: str, u_val: Optional[CanonicalStudentUnit]) -> bool:
            if stud_id_val and stud_id_val.strip().upper() in completed_token_ids:
                return True
            if u_val:
                for al in u_val.aliases:
                    if al and al.strip().upper() in completed_token_ids:
                        return True
            return False

        # Group and deduplicate verification records by canonical student identity
        canonical_student_verifs: Dict[str, Dict[str, DocumentFieldVerification]] = {}
        for vr in verif_records:
            u = alias_to_unit.get(vr.student_id) or (alias_to_unit.get(vr.student_submission_id) if vr.student_submission_id else None)
            canon_id = u.canonical_id if u else vr.student_id.strip().upper()

            existing_v = canonical_student_verifs.setdefault(canon_id, {}).get(vr.field_name)
            if not existing_v:
                canonical_student_verifs[canon_id][vr.field_name] = vr
            else:
                def get_priority(v: DocumentFieldVerification) -> int:
                    if v.status in (VerificationFieldStatus.STAFF_APPROVED, VerificationFieldStatus.STAFF_REJECTED):
                        return 4
                    if v.status in (VerificationFieldStatus.STUDENT_CONFIRMED, VerificationFieldStatus.STUDENT_VERIFIED, VerificationFieldStatus.CORRECTION_REQUESTED):
                        return 3
                    if v.ai_value not in ("NOT_AVAILABLE", None):
                        return 2
                    return 1
                if get_priority(vr) > get_priority(existing_v) or (
                    get_priority(vr) == get_priority(existing_v)
                    and (vr.updated_at or vr.created_at) > (existing_v.updated_at or existing_v.created_at)
                ):
                    canonical_student_verifs[canon_id][vr.field_name] = vr

        # Map available documents per canonical student
        docs_by_student: Dict[str, Dict[str, StudentDocument]] = {}
        for u in canonical_units:
            for d in u.documents:
                norm_t = resolve_canonical_document_type(d.document_type, d.document_name)
                if d.active_version and d.active_version.file_path and os.path.exists(d.active_version.file_path):
                    docs_by_student.setdefault(u.canonical_id, {})[norm_t] = d
                    if norm_t == "TRANSFER_CERTIFICATE":
                        docs_by_student[u.canonical_id]["TC"] = d
                    elif norm_t == "BANK_PASSBOOK":
                        docs_by_student[u.canonical_id]["PASSBOOK"] = d
                    elif norm_t == "SSLC":
                        docs_by_student[u.canonical_id]["10TH"] = d
                    elif norm_t == "HSC":
                        docs_by_student[u.canonical_id]["12TH"] = d

        # Calculate live verification counts on deduplicated records
        deduped_records: List[DocumentFieldVerification] = []
        for f_map in canonical_student_verifs.values():
            deduped_records.extend(f_map.values())

        total_fields = len(deduped_records)
        def _has_field_sub_evidence(v: DocumentFieldVerification) -> bool:
            return bool(getattr(v, "student_updated_at", None)) or getattr(v, "student_value", None) is not None or any(
                getattr(h, "action", None) in ("STUDENT_CONFIRM", "STUDENT_EDIT", "STUDENT_CORRECTION")
                or getattr(h, "actor_role", None) in ("student", "STUDENT_PUBLIC")
                for h in (getattr(v, "history", None) or [])
            )
        confirmed_count = sum(1 for v in deduped_records if v.status in (VerificationFieldStatus.STUDENT_CONFIRMED, VerificationFieldStatus.STUDENT_VERIFIED) and _has_field_sub_evidence(v))
        correction_count = sum(1 for v in deduped_records if v.status == VerificationFieldStatus.CORRECTION_REQUESTED)
        approved_count = sum(1 for v in deduped_records if v.status == VerificationFieldStatus.STAFF_APPROVED)
        rejected_count = sum(1 for v in deduped_records if v.status == VerificationFieldStatus.STAFF_REJECTED)
        ai_extracted_count = sum(1 for v in deduped_records if v.status == VerificationFieldStatus.AI_EXTRACTED)

        total_students_in_req = len(canonical_student_verifs)
        verified_students = 0
        correction_students = 0
        pending_students = 0
        successful_students = 0
        partial_students = 0
        missing_docs_students = 0
        failed_students = 0

        # Build correction queue items
        correction_queue: List[CorrectionQueueItem] = []

        all_student_rows: List[StudentExtractionRowResponse] = []
        for stud_id, field_verifs in canonical_student_verifs.items():
            u = alias_to_unit.get(stud_id)
            recs = list(field_verifs.values())
            field_items: Dict[str, StudentExtractionFieldItem] = {}
            has_pending_corrections = False
            has_missing_doc = False
            missing_docs_list: List[str] = []
            usable_fields_count = 0
            stud_available_docs = docs_by_student.get(stud_id, {})

            for r in recs:
                display_label = r.field_name.replace("_", " ").title()
                for col_name, canon_key in req.column_mapping.items():
                    if canon_key == r.field_name:
                        display_label = col_name
                        break

                if r.ai_value not in ("NOT_AVAILABLE", None):
                    usable_fields_count += 1

                if r.status == VerificationFieldStatus.CORRECTION_REQUESTED:
                    has_pending_corrections = True
                    correction_queue.append(
                        CorrectionQueueItem(
                            verification_id=str(r.id),
                            extraction_request_id=req.extraction_request_id,
                            student_id=stud_id,
                            register_number=u.register_number if u else stud_id,
                            document_type=r.document_type,
                            field_name=r.field_name,
                            field_label=display_label,
                            ai_value=r.ai_value,
                            student_value=r.student_value,
                            student_comment=r.student_comment,
                            submitted_at=r.student_updated_at or r.updated_at,
                        )
                    )

                if r.ai_value in ("NOT_AVAILABLE", None) or r.field_state in ("SOURCE_DOCUMENT_MISSING", "DOCUMENT_MISSING"):
                    # If field is already finalized / verified by student or staff, it is resolved
                    if r.status in (VerificationFieldStatus.STUDENT_VERIFIED, VerificationFieldStatus.STUDENT_CONFIRMED, VerificationFieldStatus.STAFF_APPROVED):
                        pass
                    else:
                        target_types = self._get_target_doc_types_for_field(r.field_name)
                        doc_types_only = [dt for dt in target_types if resolve_canonical_document_type(dt) not in ("STUDENT_PROFILE", "OTHER", "UNKNOWN")]
                        if doc_types_only:
                            doc_present = any(resolve_canonical_document_type(dt) in stud_available_docs for dt in doc_types_only)
                            if not doc_present:
                                has_missing_doc = True
                                for dt in doc_types_only:
                                    canon_dt = resolve_canonical_document_type(dt)
                                    if canon_dt not in missing_docs_list:
                                        missing_docs_list.append(canon_dt)
                                        break

                field_items[r.field_name] = StudentExtractionFieldItem(
                    field_name=r.field_name,
                    column_label=display_label,
                    ai_value=r.ai_value,
                    raw_value=getattr(r, "raw_value", None) or r.ai_value,
                    student_value=r.student_value,
                    final_value=r.final_value,
                    verification_status=r.status.value if hasattr(r.status, "value") else str(r.status),
                    verification_id=str(r.id),
                    is_available=(r.ai_value not in ("NOT_AVAILABLE", None)),
                    document_type=r.document_type,
                    source_document_type=r.document_type,
                    source_document_name=getattr(r, "source_document_name", None),
                    source_document_version=getattr(r, "document_version_id", None),
                    confidence=getattr(r, "confidence", "HIGH"),
                    confidence_score=getattr(r, "confidence_score", 1.0),
                    field_state=getattr(r, "field_state", "EXTRACTED"),
                    evidence_snippet=getattr(r, "evidence_snippet", None),
                    page_number=getattr(r, "page_number", 1),
                    reason=getattr(r, "reason", None),
                    conflicts=getattr(r, "conflicts", []) or [],
                )

            has_usable_data = (usable_fields_count > 0)

            is_student_token_completed = _is_student_token_completed(stud_id, u)

            # Determine genuine student verification submission evidence on the fields or completed token
            has_field_student_evidence = bool(recs) and any(
                bool(getattr(r, "student_updated_at", None))
                or getattr(r, "student_value", None) is not None
                or any(
                    getattr(h, "action", None) in ("STUDENT_CONFIRM", "STUDENT_EDIT", "STUDENT_CORRECTION")
                    or getattr(h, "actor_role", None) in ("student", "STUDENT_PUBLIC")
                    for h in (getattr(r, "history", None) or [])
                )
                for r in recs
            )
            has_student_submission = has_field_student_evidence or is_student_token_completed

            all_staff_approved = bool(recs) and all(
                r.status in (VerificationFieldStatus.STAFF_APPROVED, VerificationFieldStatus.STAFF_REJECTED)
                for r in recs
            )
            has_unfinalized_fields = any(
                r.status == VerificationFieldStatus.AI_EXTRACTED
                or r.status not in (
                    VerificationFieldStatus.STUDENT_CONFIRMED,
                    VerificationFieldStatus.STUDENT_VERIFIED,
                    VerificationFieldStatus.STAFF_APPROVED,
                    VerificationFieldStatus.STAFF_REJECTED,
                )
                for r in recs
            )
            all_fields_finalized = bool(recs) and not has_unfinalized_fields

            # STUDENT_VERIFIED strictly requires:
            # 1. Extraction data exists
            # 2. All fields finalized (none in AI_EXTRACTED or failed)
            # 3. No pending corrections
            # 4. Authoritative student submission evidence
            is_student_verified_completed = (
                bool(recs)
                and all_fields_finalized
                and (not has_pending_corrections)
                and has_student_submission
            )

            # Per-student status calculation
            if not has_usable_data:
                stud_verif_status = "EXTRACTION_INCOMPLETE" if has_missing_doc else "EXTRACTION_FAILED"
                ext_status = "FAILED"
                final_status = "MISSING_DOCUMENTS" if has_missing_doc else "FAILED"
                failed_students += 1
                if has_missing_doc:
                    missing_docs_students += 1
            elif has_missing_doc:
                ext_status = "PARTIAL"
                partial_students += 1
                missing_docs_students += 1
                if has_pending_corrections:
                    stud_verif_status = "CORRECTION_REQUESTED"
                    final_status = "CORRECTION_REQUESTED"
                    correction_students += 1
                elif all_staff_approved:
                    stud_verif_status = "VERIFIED"
                    final_status = "VERIFIED"
                    verified_students += 1
                elif is_student_verified_completed:
                    stud_verif_status = "STUDENT_VERIFIED"
                    final_status = "VERIFIED"
                    verified_students += 1
                else:
                    stud_verif_status = "PENDING_VERIFICATION"
                    final_status = "PENDING_VERIFICATION"
                    pending_students += 1
            else:
                ext_status = "COMPLETED"
                successful_students += 1
                if has_pending_corrections:
                    stud_verif_status = "CORRECTION_REQUESTED"
                    final_status = "CORRECTION_REQUESTED"
                    correction_students += 1
                elif all_staff_approved:
                    stud_verif_status = "VERIFIED"
                    final_status = "VERIFIED"
                    verified_students += 1
                elif is_student_verified_completed:
                    stud_verif_status = "STUDENT_VERIFIED"
                    final_status = "VERIFIED"
                    verified_students += 1
                else:
                    stud_verif_status = "PENDING_VERIFICATION"
                    final_status = "PENDING_VERIFICATION"
                    pending_students += 1

            doc_status_text = "Ready" if not has_missing_doc else f"Missing {', '.join(missing_docs_list[:2])}"

            student_name_val = u.student_name if (u and u.student_name) else None
            if not student_name_val and "student_name" in field_items and field_items["student_name"].ai_value != "NOT_AVAILABLE":
                student_name_val = str(field_items["student_name"].final_value or field_items["student_name"].ai_value)

            v_token = None
            v_link = None
            v_tok_status = None
            v_expires = None
            if has_usable_data:
                try:
                    v_service = VerificationTokenService()
                    tok = await v_service.create_or_get_token(
                        student_id=stud_id,
                        batch_id=req.batch_id,
                        student_name=student_name_val,
                        batch_name=req.batch_name,
                        class_id=req.class_id,
                        department_id=req.department_id,
                        extraction_request_id=req.extraction_request_id,
                    )
                    if tok:
                        v_token = tok.token
                        v_link = f"/verify-session/{tok.token}"
                        if tok.status == VerificationTokenStatus.COMPLETED.value:
                            v_tok_status = "COMPLETED"
                        elif tok.is_valid:
                            v_tok_status = tok.status
                        else:
                            v_tok_status = "EXPIRED"
                        v_expires = tok.expires_at
                except Exception as tok_err:
                    logger.debug(f"[BatchExtractionService] Could not generate verification token for {stud_id}: {tok_err}")

            all_student_rows.append(
                StudentExtractionRowResponse(
                    student_id=stud_id,
                    student_name=student_name_val,
                    register_number=u.register_number if u else stud_id,
                    document_status=doc_status_text,
                    extraction_status=ext_status,
                    verification_status=stud_verif_status,
                    final_status=final_status,
                    missing_documents=missing_docs_list,
                    fields=field_items,
                    has_corrections_pending=has_pending_corrections,
                    verification_token=v_token,
                    verification_link=v_link,
                    verification_token_status=v_tok_status,
                    verification_link_expires_at=v_expires,
                )
            )

        # Update summary counts and export status
        req.total_students = total_students_in_req
        req.processed_count = total_students_in_req
        req.result_count = total_students_in_req
        req.successful_count = successful_students
        req.partial_count = partial_students
        req.missing_docs_count = missing_docs_students
        req.failed_count = failed_students
        req.verified_count = verified_students
        req.correction_requested_count = correction_students
        req.pending_verification_count = pending_students

        if req.download_status == BatchDownloadStatus.DOWNLOADED.value:
            req.export_status = BatchExportStatus.EXPORTED.value
        elif verified_students == total_students_in_req and total_students_in_req > 0:
            req.export_status = BatchExportStatus.READY.value
            req.verification_status = BatchVerificationStatus.VERIFIED.value
        elif verified_students > 0 or approved_count > 0 or confirmed_count > 0:
            req.export_status = BatchExportStatus.PARTIALLY_VERIFIED.value
            req.verification_status = BatchVerificationStatus.PARTIALLY_VERIFIED.value
        else:
            req.export_status = BatchExportStatus.NOT_READY.value
            req.verification_status = BatchVerificationStatus.PENDING.value

        await self.repository.save(req)
        summary = self._to_summary_response(req)

        # Server-side Filtering
        filtered_rows = all_student_rows
        if status_filter and status_filter.upper() != "ALL":
            sf = status_filter.upper().replace(" ", "_")
            if sf == "COMPLETED":
                filtered_rows = [r for r in filtered_rows if r.extraction_status == "COMPLETED"]
            elif sf == "PARTIAL":
                filtered_rows = [r for r in filtered_rows if r.extraction_status == "PARTIAL"]
            elif sf == "FAILED":
                filtered_rows = [r for r in filtered_rows if r.extraction_status == "FAILED"]
            elif sf == "MISSING_DOCUMENTS":
                filtered_rows = [r for r in filtered_rows if len(r.missing_documents) > 0]
            elif sf == "PENDING_VERIFICATION":
                filtered_rows = [r for r in filtered_rows if r.verification_status in ("PENDING_VERIFICATION", "AI_EXTRACTED")]
            elif sf == "CORRECTION_REQUESTED":
                filtered_rows = [r for r in filtered_rows if r.has_corrections_pending or r.verification_status == "CORRECTION_REQUESTED"]
            elif sf in ("VERIFIED", "STUDENT_VERIFIED"):
                filtered_rows = [r for r in filtered_rows if r.verification_status in ("VERIFIED", "STUDENT_VERIFIED")]

        # Server-side Search
        if search and search.strip():
            term = search.strip().lower()
            filtered_rows = [
                r for r in filtered_rows
                if term in r.register_number.lower() or (r.student_name and term in r.student_name.lower())
            ]

        # Pagination
        filtered_rows.sort(key=lambda s: s.register_number)
        total_matching = len(filtered_rows)
        start_idx = max(0, (page - 1) * page_size)
        end_idx = start_idx + page_size
        paginated_rows = filtered_rows[start_idx:end_idx]

        progress = {
            "total_fields": total_fields,
            "confirmed": confirmed_count,
            "correction_requested": correction_count,
            "staff_approved": approved_count,
            "staff_rejected": rejected_count,
            "pending_review": correction_count,
            "verified_students": verified_students,
            "total_students": total_students_in_req,
        }

        return BatchExtractionDetailResponse(
            summary=summary,
            students=paginated_rows,
            total_matching_students=total_matching,
            page=page,
            page_size=page_size,
            verification_progress=progress,
            corrections_queue=correction_queue,
        )

    async def retry_student_extraction(
        self, extraction_request_id: str, student_id: str, actor: User
    ) -> StudentExtractionRowResponse:
        """
        Retry extraction for a specific student without duplicating final results
        or deleting stored documents.
        """
        req = await self.repository.get_by_request_id(extraction_request_id)
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Extraction request '{extraction_request_id}' not found.",
            )

        batch = await self.batch_repository.get_batch_by_id(req.batch_id)
        if batch:
            self.verify_batch_access(batch, actor)

        batch_ids = [req.batch_id]
        if batch:
            batch_ids.append(str(batch.id))
            if hasattr(batch, "name") and batch.name and batch.name not in batch_ids:
                batch_ids.append(batch.name)
            if isinstance(batch.id, PydanticObjectId) and batch.id not in batch_ids:
                batch_ids.append(batch.id)

        canonical_units = await self._build_canonical_student_units(batch_ids, req.class_id)
        target_unit = next(
            (u for u in canonical_units if student_id in u.aliases or compare_register_numbers(u.canonical_id, student_id)),
            None
        )

        stud_docs = target_unit.documents if target_unit else await StudentDocument.find(
            {"student_id": student_id, "batch_id": {"$in": batch_ids}}
        ).to_list()

        canonical_stud_id = target_unit.canonical_id if target_unit else student_id.strip().upper()
        sub_id = target_unit.student_submission_id if target_unit else None

        docs_by_type: Dict[str, StudentDocument] = {}
        for d in stud_docs:
            norm_type = resolve_canonical_document_type(d.document_type, d.document_name)
            docs_by_type[norm_type] = d
            if norm_type == "TRANSFER_CERTIFICATE":
                docs_by_type["TC"] = d
            elif norm_type == "BANK_PASSBOOK":
                docs_by_type["PASSBOOK"] = d
            elif norm_type == "SSLC":
                docs_by_type["10TH"] = d
            elif norm_type == "HSC":
                docs_by_type["12TH"] = d

        # Query configured wanted fields for this batch (+ Section override if applicable)
        doc_configs = await self.wanted_field_repository.list_by_batch(req.batch_id, class_id=req.class_id)
        field_to_configured_doc_types: Dict[str, List[str]] = {}
        for dc in doc_configs:
            canon_doc_type = resolve_canonical_document_type(dc.document_type, dc.display_name)
            for f in dc.fields:
                if f.enabled:
                    f_canon = resolve_canonical_field_key(f.field) or f.field.strip().lower().replace(" ", "_")
                    if f_canon not in field_to_configured_doc_types:
                        field_to_configured_doc_types[f_canon] = []
                    if canon_doc_type not in field_to_configured_doc_types[f_canon]:
                        field_to_configured_doc_types[f_canon].append(canon_doc_type)

        # Multi-document extraction and soft authority fusion for requested fields
        extractions_by_doc: Dict[str, Dict[str, FieldExtractionResult]] = {}
        student_extracted_fields: Dict[str, Any] = {}
        student_field_results: Dict[str, FieldExtractionResult] = {}

        # Check trusted profile fields from target unit profile data
        available_profile_fields = set()
        if target_unit and target_unit.profile_data:
            for field_key in req.requested_fields:
                prof_val = target_unit.get_profile_value(field_key)
                if prof_val is not None and str(prof_val).strip() != "":
                    available_profile_fields.add(field_key)

        non_roster_fields = [
            f for f in req.requested_fields
            if f not in available_profile_fields
            and f not in ("register_number", "register_no", "reg_no", "roll_no", "student_id")
        ]

        valid_stored_docs = [
            d for d in stud_docs
            if d.active_version and d.active_version.file_path and os.path.exists(d.active_version.file_path)
        ]

        # Build single field_to_configured_doc_type mapping
        field_to_configured_doc_type = {k: v[0] for k, v in field_to_configured_doc_types.items() if v}

        for d in valid_stored_docs:
            d_type = resolve_canonical_document_type(d.document_type, d.document_name)
            active_v = d.active_version
            for field_key in non_roster_fields:
                configured_types = field_to_configured_doc_types.get(field_key, [])
                default_types = self._get_target_doc_types_for_field(field_key)
                candidate_types = list(configured_types) + [
                    dt for dt in default_types if dt not in configured_types
                ]
                if not candidate_types and field_to_configured_doc_type.get(field_key):
                    candidate_types = [field_to_configured_doc_type[field_key]]

                canon_candidates = [resolve_canonical_document_type(ct) for ct in candidate_types]
                if d_type in canon_candidates or d.document_type in candidate_types or d_type in ("UNKNOWN", "OTHER"):
                    try:
                        field_res = await self._extract_field_with_accuracy(
                            doc=d,
                            version=active_v,
                            field_key=field_key,
                            actor=actor,
                            bypass_cache=True,
                        )
                        extractions_by_doc.setdefault(d_type, {})[field_key] = field_res
                    except Exception as ex:
                        logger.error(f"[BatchExtractionRetry] Error extracting {field_key} from doc {d.id}: {ex}")

        fused_results = self.accuracy_engine.detect_cross_document_conflicts(
            extractions_by_doc_type=extractions_by_doc,
            field_to_configured_doc_type=field_to_configured_doc_type,
        )

        for field_key in req.requested_fields:
            # 1. Profile fields
            if field_key in available_profile_fields and target_unit:
                prof_val = target_unit.get_profile_value(field_key)
                prof_res = FieldExtractionResult(
                    field_name=field_key,
                    raw_value=prof_val,
                    normalized_value=prof_val,
                    confidence="HIGH",
                    confidence_score=1.0,
                    field_state="EXTRACTED",
                    evidence_snippet=f"Retrieved from student profile: {prof_val}",
                    source_document_type="STUDENT_PROFILE",
                    source_document_name="Student Profile",
                    source_document_id=target_unit.student_submission_id or "STUDENT_PROFILE",
                    source_document_version="1",
                )
                student_field_results[field_key] = prof_res
                student_extracted_fields[field_key] = prof_val
                continue

            # 2. Roster Register Number / Student ID
            if field_key in ("register_number", "register_no", "reg_no", "roll_no", "student_id"):
                reg_res = FieldExtractionResult(
                    field_name=field_key,
                    raw_value=canonical_stud_id,
                    normalized_value=canonical_stud_id,
                    confidence="HIGH",
                    confidence_score=1.0,
                    field_state="EXTRACTED",
                    evidence_snippet=f"Register Number: {canonical_stud_id}",
                    source_document_type="STUDENT_RECORD",
                )
                student_field_results[field_key] = reg_res
                student_extracted_fields[field_key] = canonical_stud_id
                continue

            target_doc_type = field_to_configured_doc_type.get(field_key)
            if not target_doc_type:
                default_types = self._get_target_doc_types_for_field(field_key)
                target_doc_type = resolve_canonical_document_type(default_types[0]) if default_types else "OTHER"

            f_res = fused_results.get(field_key)
            if f_res and f_res.field_state in (
                "AI_EXTRACTION_UNAVAILABLE",
                "OCR_FAILED",
                "AI_EXTRACTION_FAILED",
                "EXTRACTION_FAILED",
            ):
                student_extracted_fields[field_key] = None
                student_field_results[field_key] = f_res
                continue
            if not f_res or f_res.normalized_value in (None, "", "NOT_AVAILABLE"):
                student_extracted_fields[field_key] = "NOT_AVAILABLE"
                if not f_res:
                    f_res = FieldExtractionResult(
                        field_name=field_key,
                        raw_value=None,
                        normalized_value="NOT_AVAILABLE",
                        confidence="LOW",
                        confidence_score=0.0,
                        field_state="SOURCE_DOCUMENT_MISSING",
                        reason=f"Configured source document '{target_doc_type}' not found for student.",
                        source_document_type=target_doc_type,
                    )
                student_field_results[field_key] = f_res
            else:
                student_extracted_fields[field_key] = f_res.normalized_value
                student_field_results[field_key] = f_res

        # Update verification records idempotently
        existing_verifs = await DocumentFieldVerification.find(
            DocumentFieldVerification.extraction_request_id == req.extraction_request_id,
            {"$or": [
                {"student_id": canonical_stud_id},
                {"student_id": student_id},
            ] + ([{"student_submission_id": sub_id}] if sub_id else [])},
        ).to_list()

        for v in existing_verifs:
            f_res = student_field_results.get(v.field_name)
            new_ai_val = f_res.normalized_value if f_res else student_extracted_fields.get(v.field_name)
            v.ai_value = new_ai_val
            v.student_id = canonical_stud_id
            v.student_submission_id = sub_id
            if f_res:
                v.raw_value = f_res.raw_value
                v.confidence = f_res.confidence
                v.confidence_score = f_res.confidence_score
                v.field_state = f_res.field_state
                v.evidence_snippet = f_res.evidence_snippet
                v.page_number = f_res.page_number
                v.reason = f_res.reason
                v.conflicts = f_res.conflicts
                if f_res.source_document_id:
                    v.document_id = f_res.source_document_id
                if f_res.source_document_version:
                    v.document_version_id = f_res.source_document_version
                if f_res.source_document_name:
                    v.source_document_name = f_res.source_document_name
                if f_res.source_document_type:
                    v.document_type = f_res.source_document_type
            if v.status == VerificationFieldStatus.AI_EXTRACTED:
                v.final_value = None if new_ai_val in ("NOT_AVAILABLE", None) else new_ai_val
            v.updated_at = datetime.now(timezone.utc)
            await v.save()

        detail_resp = await self.get_extraction_details(
            extraction_request_id=extraction_request_id,
            actor=actor,
            search=canonical_stud_id,
        )
        if detail_resp.students:
            return detail_resp.students[0]

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student record '{student_id}' not found after retry.",
        )

    def _build_student_verification_map(
        self,
        verif_records: List[DocumentFieldVerification],
        alias_to_unit: Dict[str, CanonicalStudentUnit],
        target_extraction_id: Optional[str] = None,
    ) -> Dict[str, Dict[str, DocumentFieldVerification]]:
        """Map verification records to student ID -> field_name / canonical_key -> DocumentFieldVerification."""
        student_data: Dict[str, Dict[str, DocumentFieldVerification]] = {}

        def get_export_priority(v: DocumentFieldVerification) -> int:
            base_score = 0
            if target_extraction_id and getattr(v, "extraction_request_id", None) == target_extraction_id:
                base_score += 10
            if v.status in (VerificationFieldStatus.STAFF_APPROVED, VerificationFieldStatus.STAFF_REJECTED):
                return base_score + 4
            if v.status == VerificationFieldStatus.STUDENT_VERIFIED:
                return base_score + 3
            if v.status == VerificationFieldStatus.STUDENT_CONFIRMED:
                return base_score + 3
            if v.status == VerificationFieldStatus.CORRECTION_REQUESTED:
                return base_score + 3
            if v.final_value not in ("NOT_AVAILABLE", "NOT_FOUND", None, ""):
                return base_score + 2
            if v.ai_value not in ("NOT_AVAILABLE", "NOT_FOUND", None, ""):
                return base_score + 2
            return base_score + 1

        for r in verif_records:
            u = (
                alias_to_unit.get(r.student_id)
                or alias_to_unit.get(str(r.student_id).strip())
                or alias_to_unit.get(str(r.student_id).strip().upper())
                or alias_to_unit.get(str(r.student_id).strip().lower())
                or (alias_to_unit.get(str(r.student_submission_id).strip()) if r.student_submission_id else None)
            )
            canon_id = u.canonical_id if u else str(r.student_id).strip().upper()

            stud_map = student_data.setdefault(canon_id, {})

            # Collect all possible keys under which this field can be addressed
            raw_field = str(r.field_name).strip()
            clean_field = re.sub(r'[^a-zA-Z0-9]+', '_', raw_field.lower()).strip('_')
            canon_k = resolve_canonical_field_key(raw_field)

            keys_to_register = {raw_field, raw_field.lower(), clean_field}
            if canon_k:
                keys_to_register.add(canon_k)
                keys_to_register.add(canon_k.lower())

            for k in keys_to_register:
                if not k:
                    continue
                existing_r = stud_map.get(k)
                if not existing_r:
                    stud_map[k] = r
                else:
                    if get_export_priority(r) > get_export_priority(existing_r) or (
                        get_export_priority(r) == get_export_priority(existing_r)
                        and (r.updated_at or r.created_at) > (existing_r.updated_at or existing_r.created_at)
                    ):
                        stud_map[k] = r

        return student_data

    def _find_field_verification_rec(
        self,
        fields_map: Dict[str, Any],
        canon_key: str,
        col_header: str = "",
    ) -> Optional[DocumentFieldVerification]:
        """
        Robustly locate a DocumentFieldVerification record for the requested column/field:
        - Exact match on canon_key
        - Canonical key match using resolve_canonical_field_key
        - Normalized snake_case match
        - Col_header match (raw, canonical, snake_case)
        - Iterative scan comparing canonical forms
        """
        if not fields_map:
            return None

        # 1. Exact match on canon_key
        if canon_key in fields_map and isinstance(fields_map[canon_key], DocumentFieldVerification):
            return fields_map[canon_key]

        # 2. Canonical form of canon_key
        canon_target = resolve_canonical_field_key(canon_key)
        if canon_target and canon_target in fields_map and isinstance(fields_map[canon_target], DocumentFieldVerification):
            return fields_map[canon_target]

        # 3. Clean snake_case of canon_key
        clean_key = re.sub(r'[^a-zA-Z0-9]+', '_', canon_key.strip().lower()).strip('_')
        if clean_key in fields_map and isinstance(fields_map[clean_key], DocumentFieldVerification):
            return fields_map[clean_key]

        # 4. Col header match if provided
        if col_header:
            if col_header in fields_map and isinstance(fields_map[col_header], DocumentFieldVerification):
                return fields_map[col_header]
            canon_col = resolve_canonical_field_key(col_header)
            if canon_col and canon_col in fields_map and isinstance(fields_map[canon_col], DocumentFieldVerification):
                return fields_map[canon_col]
            clean_col = re.sub(r'[^a-zA-Z0-9]+', '_', col_header.strip().lower()).strip('_')
            if clean_col in fields_map and isinstance(fields_map[clean_col], DocumentFieldVerification):
                return fields_map[clean_col]

        # 5. Exhaustive canonical / alias scan across all keys in fields_map
        all_targets = {k for k in (canon_key, canon_target, clean_key, col_header) if k}
        all_targets_lower = {t.lower().replace(" ", "_") for t in all_targets}
        for k, v in fields_map.items():
            if not isinstance(v, DocumentFieldVerification):
                continue
            k_lower = k.lower().replace(" ", "_")
            if k_lower in all_targets_lower:
                return v
            k_canon = resolve_canonical_field_key(k)
            if k_canon and (k_canon in all_targets or k_canon == canon_target):
                return v
            f_name = getattr(v, "field_name", "")
            if f_name:
                f_lower = f_name.lower().replace(" ", "_")
                if f_lower in all_targets_lower:
                    return v
                f_canon = resolve_canonical_field_key(f_name)
                if f_canon and (f_canon in all_targets or f_canon == canon_target):
                    return v

        return None

    def _compute_student_verification_status(
        self,
        fields_map: Dict[str, Any],
    ) -> str:
        """Compute the student's overall verification status for export display."""
        if not fields_map:
            return "PENDING_VERIFICATION"

        has_correction = any(
            getattr(v, "status", None) == VerificationFieldStatus.CORRECTION_REQUESTED
            for v in fields_map.values()
        )
        if has_correction:
            return "CORRECTION_REQUESTED"

        has_student_sub = any(
            bool(getattr(v, "student_updated_at", None))
            or getattr(v, "student_value", None) is not None
            or any(
                getattr(h, "action", None) in ("STUDENT_CONFIRM", "STUDENT_EDIT", "STUDENT_CORRECTION")
                or getattr(h, "actor_role", None) in ("student", "STUDENT_PUBLIC")
                for h in (getattr(v, "history", None) or [])
            )
            for v in fields_map.values()
        )
        all_staff_approved = all(
            getattr(v, "status", None) in (VerificationFieldStatus.STAFF_APPROVED, VerificationFieldStatus.STAFF_REJECTED)
            for v in fields_map.values()
        )

        verified_statuses = (
            VerificationFieldStatus.STAFF_APPROVED,
            VerificationFieldStatus.STUDENT_VERIFIED,
            VerificationFieldStatus.STUDENT_CONFIRMED,
        )
        verified_count = sum(
            1 for v in fields_map.values()
            if getattr(v, "status", None) in verified_statuses
        )

        if verified_count == len(fields_map) and verified_count > 0:
            if all_staff_approved or has_student_sub:
                return "VERIFIED"
            return "PENDING_VERIFICATION"
        elif verified_count > 0 and (has_student_sub or all_staff_approved):
            return "PARTIALLY_VERIFIED"
        else:
            return "PENDING_VERIFICATION"

    def _resolve_export_field_value(
        self,
        canon_key: str,
        fields_map: Dict[str, Any],
        u: Optional[CanonicalStudentUnit],
        student_id: str,
        col_header: str = "",
    ) -> Any:
        """
        Resolve field value for batch Excel export:
        - If student confirmed/edited, use verified final values only when a valid verification submission exists.
        - If unverified, use the latest successfully extracted AI value.
        - If missing or extraction failed, leave blank or use explicit status convention.
        - Never allow null to overwrite a valid value. Never invent data.
        """
        # 1. Identity / Register Number
        if canon_key in ("register_number", "register_no", "reg_no", "roll_no", "student_id"):
            return u.register_number if (u and u.register_number) else student_id

        # 2. Status column if present in template or requested
        if canon_key in ("verification_status", "verification_state", "status", "student_status"):
            return self._compute_student_verification_status(fields_map)

        # Check if valid student or staff verification submission exists for this field
        is_field_verified = False
        v_rec = self._find_field_verification_rec(fields_map, canon_key, col_header)
        if v_rec and hasattr(v_rec, "status"):
            if v_rec.status in (
                VerificationFieldStatus.STAFF_APPROVED,
                VerificationFieldStatus.STUDENT_VERIFIED,
                VerificationFieldStatus.STUDENT_CONFIRMED,
            ):
                has_student_action = bool(getattr(v_rec, "student_updated_at", None)) or getattr(v_rec, "student_value", None) is not None or any(
                    getattr(h, "action", None) in ("STUDENT_CONFIRM", "STUDENT_EDIT", "STUDENT_CORRECTION")
                    or getattr(h, "actor_role", None) in ("student", "STUDENT_PUBLIC")
                    for h in (getattr(v_rec, "history", None) or [])
                )
                if v_rec.status == VerificationFieldStatus.STAFF_APPROVED or has_student_action:
                    is_field_verified = True

        # 3. Student Name
        if canon_key in ("student_name", "name", "candidate_name"):
            if is_field_verified and v_rec.final_value not in (None, "", "NOT_AVAILABLE", "NOT_FOUND"):
                return v_rec.final_value
            if is_field_verified and getattr(v_rec, "student_value", None) not in (None, "", "NOT_AVAILABLE", "NOT_FOUND"):
                return v_rec.student_value
            if v_rec and getattr(v_rec, "ai_value", None) not in (None, "", "NOT_AVAILABLE", "NOT_FOUND"):
                return v_rec.ai_value
            if u and u.student_name:
                return u.student_name
            return ""

        # 4. General Extracted / Profile Fields
        val = None

        if v_rec is not None:
            if hasattr(v_rec, "status"):
                if is_field_verified:
                    val = v_rec.final_value if v_rec.final_value is not None else (
                        v_rec.student_value if v_rec.student_value is not None else (v_rec.ai_value or "")
                    )
                elif v_rec.status == VerificationFieldStatus.STAFF_REJECTED:
                    val = v_rec.final_value or v_rec.ai_value or ""
                else:
                    # Unverified (AI_EXTRACTED, CORRECTION_REQUESTED, unsubmitted): use latest successfully extracted AI value
                    val = v_rec.ai_value if v_rec.ai_value not in ("NOT_AVAILABLE", "NOT_FOUND", None) else (
                        v_rec.raw_value if (hasattr(v_rec, "raw_value") and v_rec.raw_value not in ("NOT_AVAILABLE", "NOT_FOUND", None)) else ""
                    )
            elif hasattr(v_rec, "normalized_value"):
                val = v_rec.normalized_value or v_rec.raw_value or ""
            else:
                val = str(v_rec) if v_rec is not None else ""

        # Fallback to trusted profile value from CanonicalStudentUnit if field was not in verification records
        if (val is None or val == "" or val in ("NOT_AVAILABLE", "NOT_FOUND")) and u:
            prof_val = u.get_profile_value(canon_key)
            if prof_val is not None and str(prof_val).strip() != "":
                val = str(prof_val).strip()

        # Format according to field type rules
        if is_yes_no_field(canon_key) or is_yes_no_field(col_header):
            return normalize_yes_no_not_found(val)

        if val in ("NOT_AVAILABLE", "NOT_FOUND", None):
            return ""

        return str(val).strip()

    async def _generate_and_save_final_excel(
        self,
        batch_req: BatchExtractionRequest,
        canonical_units: List[CanonicalStudentUnit],
        student_data: Dict[str, Dict[str, Any]],
        alias_to_unit: Dict[str, CanonicalStudentUnit],
    ) -> Tuple[str, str]:
        """
        Generate and persist the final updated Excel file to disk.
        Populates mapped columns with extracted and verified values.
        Returns (saved_file_path, exported_filename).
        """
        template_file_to_load = None
        if batch_req.template_file_path and os.path.exists(batch_req.template_file_path):
            template_file_to_load = batch_req.template_file_path
        elif batch_req.template_id:
            tmpl = await self.excel_template_service.get_template_by_batch(batch_req.batch_id, batch_req.class_id)
            if tmpl and tmpl.file_path and os.path.exists(tmpl.file_path):
                template_file_to_load = tmpl.file_path

        if not template_file_to_load:
            tmpl = await self.excel_template_service.get_template_by_batch(batch_req.batch_id, batch_req.class_id)
            if tmpl and tmpl.file_path and os.path.exists(tmpl.file_path):
                template_file_to_load = tmpl.file_path

        if not template_file_to_load:
            possible = list(TEMPLATES_DIR.glob(f"batch_{batch_req.batch_id}*.xlsx"))
            if possible and os.path.exists(possible[0]):
                template_file_to_load = str(possible[0])

        sorted_students = sorted(student_data.keys())

        if template_file_to_load:
            wb = openpyxl.load_workbook(template_file_to_load)
            sheet_name = batch_req.template_sheet_name
            if sheet_name and sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
            else:
                ws = wb.active or wb.worksheets[0]

            header_row_idx = batch_req.header_row_index or 1

            sheet_col_map: Dict[str, int] = {}
            for col_idx in range(1, ws.max_column + 1):
                cell_val = ws.cell(row=header_row_idx, column=col_idx).value
                if cell_val is not None and str(cell_val).strip():
                    sheet_col_map[str(cell_val).strip()] = col_idx

            col_to_field: Dict[int, str] = {}
            if batch_req.field_mappings:
                for fm in batch_req.field_mappings:
                    target_hdr = fm.get("target_excel_header")
                    f_key = fm.get("field_key")
                    col_idx = sheet_col_map.get(target_hdr) if target_hdr else fm.get("target_column_index")
                    if col_idx and f_key:
                        col_to_field[col_idx] = f_key

            if batch_req.column_mapping:
                for target_hdr, f_key in batch_req.column_mapping.items():
                    col_idx = sheet_col_map.get(target_hdr)
                    if not col_idx and batch_req.header_to_column_index:
                        col_idx = batch_req.header_to_column_index.get(target_hdr)
                    if col_idx and f_key and col_idx not in col_to_field:
                        col_to_field[col_idx] = f_key

            wanted_keys = set(batch_req.requested_fields or [])
            if batch_req.column_mapping:
                wanted_keys.update(batch_req.column_mapping.values())
            wanted_columns = set(batch_req.requested_columns or [])

            for hdr_text, col_idx in sheet_col_map.items():
                if col_idx not in col_to_field:
                    f_key = None
                    if batch_req.column_mapping and hdr_text in batch_req.column_mapping:
                        f_key = batch_req.column_mapping[hdr_text]
                    elif hdr_text in wanted_columns:
                        f_key = resolve_canonical_field_key(hdr_text)
                    else:
                        cand_key = resolve_canonical_field_key(hdr_text)
                        if cand_key and (cand_key in wanted_keys or not wanted_keys):
                            f_key = cand_key
                    if f_key and (not wanted_keys or f_key in wanted_keys or hdr_text in wanted_columns):
                        col_to_field[col_idx] = f_key

            # Preserve formulas, unrelated cell contents, and template layout
            if ws.max_row > header_row_idx:
                for r in range(header_row_idx + 1, ws.max_row + 1):
                    for col_idx in col_to_field.keys():
                        cell = ws.cell(row=r, column=col_idx)
                        # Do not erase formulas or unrelated cells
                        if isinstance(cell.value, str) and cell.value.startswith('='):
                            continue
                        cell.value = None

            for stud_idx, student_id in enumerate(sorted_students):
                current_row = header_row_idx + 1 + stud_idx
                fields_map = student_data.get(student_id, {})
                u = alias_to_unit.get(student_id)

                for col_idx, canon_key in col_to_field.items():
                    cell = ws.cell(row=current_row, column=col_idx)
                    # Preserve existing formula in cell if present
                    if isinstance(cell.value, str) and cell.value.startswith('='):
                        continue

                    cell.value = self._resolve_export_field_value(
                        canon_key=canon_key,
                        fields_map=fields_map,
                        u=u,
                        student_id=student_id,
                        col_header=str(ws.cell(row=header_row_idx, column=col_idx).value or ""),
                    )

        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Batch Extraction"
            columns_to_write = batch_req.requested_columns if batch_req.requested_columns else [
                f.replace("_", " ").title() for f in batch_req.requested_fields
            ]
            ws.append(columns_to_write)

            for student_id in sorted_students:
                fields_map = student_data.get(student_id, {})
                u = alias_to_unit.get(student_id)
                row_vals = []
                for col_header in columns_to_write:
                    canon_key = batch_req.column_mapping.get(col_header, resolve_canonical_field_key(col_header))
                    if not canon_key:
                        canon_key = col_header.strip().lower().replace(" ", "_")
                    val = self._resolve_export_field_value(
                        canon_key=canon_key,
                        fields_map=fields_map,
                        u=u,
                        student_id=student_id,
                        col_header=col_header,
                    )
                    row_vals.append(val)

                ws.append(row_vals)

        wb.properties.title = f"Data Extraction - {batch_req.batch_name or batch_req.batch_id}"
        wb.properties.subject = "ADMIEXTRACT Batch Extraction Export"
        wb.properties.creator = "ADMIEXTRACT"

        output_stream = io.BytesIO()
        wb.save(output_stream)
        output_stream.seek(0)

        export_dir = TEMPLATES_DIR / "extractions"
        export_dir.mkdir(parents=True, exist_ok=True)
        clean_batch_name = re.sub(r'[^a-zA-Z0-9_-]', '_', batch_req.batch_name or batch_req.batch_id)
        filename = f"{clean_batch_name}_Data_Extraction_{batch_req.extraction_request_id}.xlsx"
        dest_path = export_dir / filename
        saved_path_str = ""
        try:
            with open(dest_path, "wb") as f:
                f.write(output_stream.getvalue())
            saved_path_str = str(dest_path.resolve())
        except Exception as e:
            logger.warning(f"[_generate_and_save_final_excel] Could not cache to disk: {e}")

        output_stream.seek(0)
        return saved_path_str, filename

    async def export_verified_excel(
        self,
        extraction_request_id: str,
        actor: User,
        enforce_all_verified: bool = False,
    ) -> Tuple[io.BytesIO, str]:
        """
        Generate Excel export of FINAL VERIFIED DATA preserving the exact requested column structure.
        Strictly guarantees 1 student = 1 Excel row by canonical identity deduplication.
        If enforce_all_verified is True, blocks download if any eligible student is not yet verified.
        """
        req = await self.repository.get_by_request_id(extraction_request_id)
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Extraction request '{extraction_request_id}' not found.",
            )

        batch = await self.batch_repository.get_batch_by_id(req.batch_id)
        if batch:
            self.verify_batch_access(batch, actor)

        batch_ids = [str(req.batch_id)]
        if batch:
            batch_ids.append(str(batch.id))
            if hasattr(batch, "name") and batch.name and batch.name not in batch_ids:
                batch_ids.append(batch.name)
            if isinstance(batch.id, PydanticObjectId) and batch.id not in batch_ids:
                batch_ids.append(batch.id)

        canonical_units = await self._build_canonical_student_units(batch_ids, req.class_id)
        alias_to_unit: Dict[str, CanonicalStudentUnit] = {
            alias: u for u in canonical_units for alias in u.aliases
        }

        verif_query = {
            "$or": [
                {"extraction_request_id": req.extraction_request_id},
                {"batch_id": {"$in": batch_ids}, "extraction_request_id": None},
                {"batch_id": {"$in": batch_ids}, "extraction_request_id": ""},
            ]
        }
        verif_records = await DocumentFieldVerification.find(verif_query).to_list()

        student_data = self._build_student_verification_map(
            verif_records, alias_to_unit, target_extraction_id=req.extraction_request_id
        )
        for u in canonical_units:
            student_data.setdefault(u.canonical_id, {})

        for s_id, f_map in student_data.items():
            if s_id not in alias_to_unit:
                s_name = next(
                    (getattr(r, "student_name", None) for r in f_map.values() if getattr(r, "student_name", None)),
                    s_id,
                )
                from app.services.batch_extraction_service import CanonicalStudentUnit
                fallback_u = CanonicalStudentUnit(
                    canonical_id=s_id,
                    register_number=s_id,
                    student_name=s_name,
                    aliases=[s_id],
                )
                alias_to_unit[s_id] = fallback_u

        # Enforce all-students-verified rule:
        if enforce_all_verified:
            # 1. Authoritative lookup of completed verification tokens
            if req.extraction_request_id:
                tokens_for_req = await VerificationToken.find(
                    {"extraction_request_id": req.extraction_request_id}
                ).to_list()
                if not tokens_for_req:
                    tokens_for_req = await VerificationToken.find(
                        {"batch_id": req.batch_id, "extraction_request_id": {"$in": [None, ""]}}
                    ).to_list()
            else:
                tokens_for_req = await VerificationToken.find(
                    {"batch_id": req.batch_id}
                ).to_list()
            completed_token_ids = {
                t.student_id.strip().upper()
                for t in tokens_for_req
                if t.status == VerificationTokenStatus.COMPLETED.value
            }

            # 2. Determine all eligible students for this batch/extraction
            eligible_units = list(canonical_units)
            if not eligible_units:
                subs = await StudentSubmission.find({"batch_id": {"$in": batch_ids}}).to_list()
                for s in subs:
                    reg = (s.register_number or str(s.id)).strip()
                    fallback_u = CanonicalStudentUnit(
                        canonical_id=reg.upper(),
                        register_number=reg,
                        student_name=s.student_name,
                        submission_status=s.submission_status,
                        aliases=[reg, reg.upper(), str(s.id)],
                    )
                    eligible_units.append(fallback_u)

            if not eligible_units:
                for s_id in student_data.keys():
                    u_cand = alias_to_unit.get(s_id)
                    if u_cand and u_cand not in eligible_units:
                        eligible_units.append(u_cand)

            unverified_students = []
            for u in eligible_units:
                stud_id = u.canonical_id
                reg_no = u.register_number or stud_id
                stud_name = u.student_name or reg_no
                f_map = student_data.get(stud_id, {})

                # Check 1: Required extraction data must be available
                if not f_map:
                    unverified_students.append(f"{stud_name} ({reg_no}: extraction data unavailable)")
                    continue

                # Check 2: Unresolved extraction failures block download
                has_extraction_failure = any(
                    getattr(v, "status", None) in ("EXTRACTION_FAILED", "FAILED")
                    or getattr(v, "field_state", None) in ("FAILED", "EXTRACTION_FAILED", "ERROR")
                    for v in f_map.values()
                )
                if has_extraction_failure:
                    unverified_students.append(f"{stud_name} ({reg_no}: extraction failed)")
                    continue

                # Check 3: Pending corrections block download
                has_pending_corrections = any(
                    getattr(v, "status", None) == VerificationFieldStatus.CORRECTION_REQUESTED
                    for v in f_map.values()
                )
                if has_pending_corrections:
                    unverified_students.append(f"{stud_name} ({reg_no}: correction requested/unresolved)")
                    continue

                # Check 4: Unverified or raw AI extracted fields block download
                unverified_fields = [
                    v.field_name for v in f_map.values()
                    if getattr(v, "status", None) not in (
                        VerificationFieldStatus.STUDENT_VERIFIED,
                        VerificationFieldStatus.STUDENT_CONFIRMED,
                        VerificationFieldStatus.STAFF_APPROVED,
                    )
                ]
                if unverified_fields:
                    unverified_students.append(f"{stud_name} ({reg_no}: unverified fields: {', '.join(unverified_fields[:2])})")
                    continue

                # Check 5: Explicit student submission must be authoritative in DB.
                # Merely opening the portal, dispatching link, or OTP entry alone does not count.
                is_token_completed = (
                    stud_id in completed_token_ids
                    or any(alias.strip().upper() in completed_token_ids for alias in u.aliases if alias)
                )
                has_student_evidence = any(
                    bool(getattr(v, "student_updated_at", None))
                    or getattr(v, "student_value", None) is not None
                    or any(
                        getattr(h, "action", None) in ("STUDENT_CONFIRM", "STUDENT_EDIT", "STUDENT_CORRECTION")
                        or getattr(h, "actor_role", None) in ("student", "STUDENT_PUBLIC")
                        for h in (getattr(v, "history", None) or [])
                    )
                    for v in f_map.values()
                )
                all_staff_approved = all(
                    getattr(v, "status", None) == VerificationFieldStatus.STAFF_APPROVED
                    for v in f_map.values()
                )

                if not (is_token_completed or has_student_evidence or all_staff_approved):
                    unverified_students.append(f"{stud_name} ({reg_no}: pending student submission)")
                    continue

            if unverified_students:
                sample_names = ", ".join(unverified_students[:3])
                total_eligible = len(eligible_units)
                verified_count = total_eligible - len(unverified_students)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot export final Excel: All eligible students must complete verification before export. "
                        f"{len(unverified_students)} student(s) still pending verification "
                        f"({verified_count} / {total_eligible} students verified: {sample_names})."
                    ),
                )

        saved_path, filename = await self._generate_and_save_final_excel(
            req, canonical_units, student_data, alias_to_unit
        )
        if saved_path:
            req.exported_file_path = saved_path
            req.exported_filename = filename

        output_stream = io.BytesIO()
        if saved_path and os.path.exists(saved_path):
            with open(saved_path, "rb") as f:
                output_stream.write(f.read())
            output_stream.seek(0)
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Generated verified Excel file could not be read from disk.",
            )

        now = datetime.now(timezone.utc)
        req.download_status = BatchDownloadStatus.DOWNLOADED.value
        req.export_status = BatchExportStatus.EXPORTED.value
        req.download_count += 1
        req.last_downloaded_at = now
        await self.repository.save(req)

        return output_stream, filename

    async def cancel_batch_extraction(
        self, extraction_request_id: str, actor: User
    ) -> BatchExtractionSummaryResponse:
        """
        Cancel a running or pending extraction request safely.
        Does NOT delete stored source documents or previous successful extraction results.
        Only the current extraction request status is changed to CANCELLED.
        """
        req = await self.repository.get_by_request_id(extraction_request_id)
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Extraction request '{extraction_request_id}' not found.",
            )

        batch = await self.batch_repository.get_batch_by_id(req.batch_id)
        if batch:
            self.verify_batch_access(batch, actor)

        req.status = BatchExtractionStatus.CANCELLED.value
        req.updated_at = datetime.now(timezone.utc)
        await self.repository.save(req)
        return self._to_summary_response(req)

    async def get_corrections_queue(
        self, extraction_request_id: str, actor: User
    ) -> List[CorrectionQueueItem]:
        """
        Retrieve all pending correction requests for an extraction request.
        """
        detail = await self.get_extraction_details(
            extraction_request_id=extraction_request_id,
            actor=actor,
            page_size=10000,
        )
        return detail.corrections_queue

    def _get_target_doc_types_for_field(self, field_key: str) -> List[str]:
        """Determine authoritative target document types in priority order."""
        from app.services.document_extraction_service import resolve_canonical_field_key
        norm_key = resolve_canonical_field_key(field_key) or field_key.lower().replace(" ", "_")
        for check_key in [norm_key, field_key, field_key.lower().replace(" ", "_"), field_key.lower()]:
            if check_key in FIELD_SOURCE_RULES:
                rule = FIELD_SOURCE_RULES[check_key]
                sources = rule.get("sources", [])
                types = [s.get("document_type") for s in sources if s.get("document_type")]
                if types:
                    return types

        field_lower = field_key.lower()
        if any(k in field_lower for k in ["academic_year", "academic year", "year of joining", "year_of_joining", "joining"]):
            return ["STUDENT_PROFILE", "TRANSFER_CERTIFICATE", "BONAFIDE", "ALLOTMENT_ORDER", "HSC", "SSLC"]
        if any(k in field_lower for k in ["aadhaar", "uid"]):
            return ["AADHAAR"]
        if any(k in field_lower for k in ["community", "caste", "religion", "social"]):
            return ["COMMUNITY"]
        if any(k in field_lower for k in ["income", "salary"]):
            return ["INCOME"]
        if any(k in field_lower for k in ["account", "ifsc", "bank", "branch", "passbook", "micr"]):
            return ["BANK_PASSBOOK"]
        if any(k in field_lower for k in ["10th", "sslc"]):
            return ["SSLC", "HSC"]
        if any(k in field_lower for k in ["12th", "hsc"]):
            return ["HSC", "SSLC"]
        if any(k in field_lower for k in ["tc", "transfer", "emis", "leaving"]):
            return ["TRANSFER_CERTIFICATE", "SSLC"]
        if any(k in field_lower for k in ["dob", "birth", "place_of_birth", "birth_place", "date_of_birth"]):
            return ["AADHAAR", "SSLC", "BIRTH_CERTIFICATE", "HSC", "TRANSFER_CERTIFICATE"]
        if any(k in field_lower for k in ["gender", "sex"]):
            return ["AADHAAR", "BIRTH_CERTIFICATE", "SSLC", "COMMUNITY"]
        if any(k in field_lower for k in ["address", "pincode", "district", "taluk", "state"]):
            return ["AADHAAR", "NATIVITY", "COMMUNITY"]
        if any(k in field_lower for k in ["father", "guardian"]):
            return ["TRANSFER_CERTIFICATE", "COMMUNITY", "AADHAAR", "BIRTH_CERTIFICATE", "SSLC"]
        if any(k in field_lower for k in ["mother"]):
            return ["TRANSFER_CERTIFICATE", "BIRTH_CERTIFICATE", "AADHAAR", "COMMUNITY"]
        if any(k in field_lower for k in ["nationality", "country"]):
            return ["TRANSFER_CERTIFICATE", "AADHAAR", "PASSPORT", "COMMUNITY"]
        if any(k in field_lower for k in ["salutation"]):
            return ["TRANSFER_CERTIFICATE", "AADHAAR", "SSLC", "HSC", "COMMUNITY"]
        if any(k in field_lower for k in ["passport"]):
            return ["PASSPORT"]
        if any(k in field_lower for k in ["first_graduate", "first graduate"]):
            return ["FIRST_GRADUATE", "BONAFIDE", "TRANSFER_CERTIFICATE", "COMMUNITY", "INCOME"]
        if any(k in field_lower for k in ["differently_abled", "differently abled", "disability", "pwd", "physically"]):
            return ["DISABILITY_CERTIFICATE", "COMMUNITY", "TRANSFER_CERTIFICATE", "AADHAAR"]
        if any(k in field_lower for k in ["orphan"]):
            return ["TRANSFER_CERTIFICATE", "COMMUNITY", "BONAFIDE"]
        if any(k in field_lower for k in ["special_admission", "special_quota", "special quota"]):
            return ["ALLOTMENT_ORDER", "TRANSFER_CERTIFICATE"]
        if any(k in field_lower for k in ["same as", "communication_address_same"]):
            return ["AADHAAR", "TRANSFER_CERTIFICATE", "NATIVITY"]

        return ["AADHAAR", "SSLC", "HSC", "COMMUNITY", "TRANSFER_CERTIFICATE", "INCOME", "BANK_PASSBOOK", "BIRTH_CERTIFICATE"]

    async def _extract_field_with_accuracy(
        self,
        doc: StudentDocument,
        version: DocumentVersion,
        field_key: str,
        actor: User,
        extracted_data_override: Optional[Dict[str, Any]] = None,
        bypass_cache: bool = False,
    ) -> FieldExtractionResult:
        """
        Extract and validate a field using accuracy-first pipeline:
        1. Document quality inspection (detect blur / corrupted file).
        2. Multi-page text / structure extraction.
        3. Document type mismatch protection (reject wrong document uploads).
        4. Field extraction via DocumentExtractionService / Gemini.
        5. Strict zero-guessing structural validation.
        """
        if not version.file_path or not os.path.exists(version.file_path):
            return FieldExtractionResult(
                field_name=field_key,
                raw_value=None,
                normalized_value="NOT_AVAILABLE",
                confidence="LOW",
                confidence_score=0.0,
                field_state="SOURCE_DOCUMENT_MISSING",
                reason="SOURCE_DOCUMENT_MISSING",
                source_document_type=doc.document_type,
            )

        # 1. Inspect quality
        quality = self.accuracy_engine.inspect_document_quality(version.file_path)
        if not quality.get("is_usable", True):
            reason_str = quality.get("reason", "DOCUMENT_INVALID")
            f_state = "DOCUMENT_INVALID" if (quality.get("is_invalid") or "DOCUMENT_INVALID" in reason_str or "EMPTY" in reason_str or "CORRUPTED" in reason_str) else "LOW_QUALITY_DOCUMENT"
            return FieldExtractionResult(
                field_name=field_key,
                raw_value=None,
                normalized_value="NOT_AVAILABLE",
                confidence="LOW",
                confidence_score=0.0,
                field_state=f_state,
                reason=reason_str,
                source_document_type=doc.document_type,
            )

        # 2. Extract multi-page text
        pages_content = self.accuracy_engine.extract_all_pages_text(version.file_path)
        full_doc_text = "\n".join([p.get("text", "") for p in pages_content])

        # 3. Only reclassify records that have not already passed upload/staff validation.
        validation_status = (version.validation_status or "PENDING").upper()
        is_match, detected_type, mismatch_reason = (True, doc.document_type, None)
        if validation_status not in ("VALID", "PENDING") and not doc.reclassification_history and not version.reclassification_history:
            is_match, detected_type, mismatch_reason = self.accuracy_engine.verify_document_type(
                document_text=full_doc_text,
                expected_type=doc.document_type,
                filename=version.original_filename or "",
            )
        if not is_match:
            logger.warning(f"[AccuracyGuard] Document type mismatch for doc {doc.id}: {mismatch_reason}")
            return FieldExtractionResult(
                field_name=field_key,
                raw_value=None,
                normalized_value="NOT_AVAILABLE",
                confidence="LOW",
                confidence_score=0.0,
                field_state="DOCUMENT_TYPE_MISMATCH",
                reason=mismatch_reason,
                source_document_type=doc.document_type,
            )

        # 4. Extract raw field value
        raw_val = None
        f_canon = resolve_canonical_field_key(field_key) or field_key
        if extracted_data_override is not None and len(extracted_data_override) > 0:
            raw_val = extracted_data_override.get(f_canon)
            if raw_val is None:
                raw_val = extracted_data_override.get(field_key)
            if raw_val is None:
                for ov_k, ov_v in extracted_data_override.items():
                    if resolve_canonical_field_key(ov_k) == f_canon:
                        raw_val = ov_v
                        break
        else:
            try:
                cached = None
                if not bypass_cache:
                    cached = await self.extraction_service.repository.find_existing_result(
                        student_document_id=str(doc.id),
                        document_version_id=version.version_id,
                        requested_fields=[field_key],
                    )
                if cached and (f_canon in cached.extracted_data or field_key in cached.extracted_data):
                    raw_val = cached.extracted_data.get(f_canon) or cached.extracted_data.get(field_key)
                elif cached and cached.extracted_data:
                    for c_k, c_v in cached.extracted_data.items():
                        if resolve_canonical_field_key(c_k) == f_canon:
                            raw_val = c_v
                            break

                if raw_val is None:
                    req, result = await self.extraction_service.request_and_extract_fields(
                        student_document_id=str(doc.id),
                        requested_fields=[field_key],
                        actor=actor,
                        version_id=version.version_id,
                        bypass_cache=bypass_cache,
                    )
                    if result and (f_canon in result.extracted_data or field_key in result.extracted_data):
                        raw_val = result.extracted_data.get(f_canon) or result.extracted_data.get(field_key)
                    elif result and result.extracted_data:
                        for r_k, r_v in result.extracted_data.items():
                            if resolve_canonical_field_key(r_k) == f_canon:
                                raw_val = r_v
                                break
            except Exception as e:
                logger.warning(f"[BatchExtraction] Extraction call warning for doc {doc.id}, field {field_key}: {e}")
                err_str = str(e)
                err_upper = err_str.upper()
                if "AI_EXTRACTION_UNAVAILABLE" in err_upper or "QUOTA" in err_upper or "429" in err_str or "GEMINI_UNAVAILABLE" in err_upper or "GEMINI IS NOT AVAILABLE" in err_upper:
                    f_state = "AI_EXTRACTION_UNAVAILABLE"
                elif "OCR_FAILED" in err_upper or "OCR YIELDED" in err_upper:
                    f_state = "OCR_FAILED"
                elif "AI_EXTRACTION_FAILED" in err_upper:
                    f_state = "AI_EXTRACTION_FAILED"
                elif "FILE NOT FOUND" in err_upper or "SOURCE_DOCUMENT_MISSING" in err_upper:
                    f_state = "SOURCE_DOCUMENT_MISSING"
                else:
                    f_state = "EXTRACTION_FAILED"
                return FieldExtractionResult(
                    field_name=field_key,
                    raw_value=None,
                    normalized_value="NOT_AVAILABLE",
                    confidence="LOW",
                    confidence_score=0.0,
                    field_state=f_state,
                    reason=err_str,
                    source_document_type=doc.document_type,
                )

        # 5. Strict accuracy validation
        validated = self.accuracy_engine.validate_field_accuracy(
            field_key=field_key,
            raw_val=raw_val,
            document_text=full_doc_text,
            source_doc_type=doc.document_type,
            all_extracted_fields=extracted_data_override or {},
        )
        validated.source_document_id = str(doc.id)
        validated.source_document_version = version.version_id
        validated.source_document_name = None if validated.field_state in ("DOCUMENT_INVALID", "DOCUMENT_MISSING", "SOURCE_DOCUMENT_MISSING") else doc.document_name
        validated.source_document_type = doc.document_type
        return validated

    async def _extract_single_field_from_doc(
        self,
        doc: StudentDocument,
        version: DocumentVersion,
        field_key: str,
        actor: User,
    ) -> Any:
        """Extract single field and return normalized value."""
        res = await self._extract_field_with_accuracy(doc, version, field_key, actor)
        return res.normalized_value

    def _to_summary_response(self, req: BatchExtractionRequest) -> BatchExtractionSummaryResponse:
        return BatchExtractionSummaryResponse(
            extraction_request_id=req.extraction_request_id,
            batch_id=req.batch_id,
            batch_name=req.batch_name,
            academic_year=req.academic_year,
            department_id=req.department_id,
            template_filename=req.template_filename,
            requested_fields=req.requested_fields,
            requested_columns=req.requested_columns,
            status=req.status,
            result_count=req.result_count,
            total_students=req.total_students,
            processed_count=req.processed_count or req.result_count,
            successful_count=req.successful_count,
            partial_count=getattr(req, "partial_count", 0),
            missing_docs_count=req.missing_docs_count,
            failed_count=req.failed_count,
            verified_count=req.verified_count,
            correction_requested_count=req.correction_requested_count,
            pending_verification_count=req.pending_verification_count,
            verification_status=req.verification_status,
            export_status=getattr(req, "export_status", "NOT_READY"),
            download_status=req.download_status,
            download_count=req.download_count,
            last_downloaded_at=req.last_downloaded_at,
            exported_filename=getattr(req, "exported_filename", None),
            created_by=req.created_by,
            created_at=req.created_at,
            started_at=req.started_at,
            completed_at=req.completed_at,
            failed_at=req.failed_at,
            error_message=req.error_message,
        )
