import os
import re
import mimetypes
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from fastapi import HTTPException, status
from beanie import PydanticObjectId

from app.models.student_document import StudentDocument, DocumentVersion
from app.models.document_extraction_request import (
    DocumentExtractionRequest,
    ExtractionRequestStatus,
)
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog
from app.repositories.document_extraction_repository import DocumentExtractionRepository
from app.repositories.student_document_repository import StudentDocumentRepository
from app.services.gemini_service import GeminiService
from app.utils.field_canonicalizer import get_canonical_field_name
from app.utils.logger_masking import mask_sensitive_value
from app.utils.evidence_yes_no import (
    is_yes_no_field,
    normalize_yes_no_not_found,
    evaluate_evidence_based_yes_no,
)

logger = logging.getLogger("app.services.document_extraction_service")

AI_EXTRACTION_UNAVAILABLE = "AI_EXTRACTION_UNAVAILABLE"
OCR_FAILED = "OCR_FAILED"
AI_EXTRACTION_FAILED = "AI_EXTRACTION_FAILED"


class ExtractionAiResult(tuple):
    """5-element tuple subclass that also attaches answers_map for evidence-based fields."""
    def __new__(cls, extracted_data, confidence, provenance, ocr_status, ai_provider, answers_map=None):
        instance = super().__new__(cls, (extracted_data, confidence, provenance, ocr_status, ai_provider))
        instance.answers_map = answers_map or {}
        return instance




def _mask_student_identifier(value: Optional[str]) -> str:
    clean = str(value or "").strip()
    if len(clean) <= 4:
        return "[MASKED]"
    return f"{clean[:2]}...{clean[-2:]}"


# Canonical snake_case keys mapped to all known aliases
FIELD_ALIAS_TO_CANONICAL_KEY: Dict[str, str] = {
    # Student Name
    "student_name": "student_name",
    "student name": "student_name",
    "name": "student_name",
    "candidate name": "student_name",
    "applicant name": "student_name",
    "name of the student": "student_name",
    "name of candidate": "student_name",
    "student's name": "student_name",

    # Date of Birth
    "date_of_birth": "date_of_birth",
    "dob": "date_of_birth",
    "date of birth": "date_of_birth",
    "birth date": "date_of_birth",
    "birth_date": "date_of_birth",
    "student date of birth": "date_of_birth",
    "student date of birth(dd.mm.yyyy)": "date_of_birth",
    "d.o.b": "date_of_birth",
    "d.o.b.": "date_of_birth",

    # Gender
    "gender": "gender",
    "sex": "gender",

    # Aadhaar Number
    "aadhaar_number": "aadhaar_number",
    "aadhaar number": "aadhaar_number",
    "aadhaar": "aadhaar_number",
    "aadhar": "aadhaar_number",
    "aadhar number": "aadhaar_number",
    "aadhaar card": "aadhaar_number",
    "aadhaar card number": "aadhaar_number",
    "aadhaar no": "aadhaar_number",
    "aadhaar no.": "aadhaar_number",
    "aadhaar id": "aadhaar_number",
    "aadhaar number (without space)": "aadhaar_number",
    "aadhaar number without space": "aadhaar_number",
    "uid": "aadhaar_number",

    # Parents
    "father_name": "father_name",
    "father name": "father_name",
    "father's name": "father_name",
    "father_s_name": "father_name",
    "father": "father_name",
    "name of father": "father_name",
    "father / guardian name": "father_name",
    "guardian name": "father_name",
    "guardian's name": "father_name",
    "guardian": "father_name",
    "mother_name": "mother_name",
    "mother name": "mother_name",
    "mother's name": "mother_name",
    "mother_s_name": "mother_name",
    "mother": "mother_name",
    "name of mother": "mother_name",

    # Address & Location
    "permanent_address": "permanent_address",
    "permanent address": "permanent_address",
    "address": "permanent_address",
    "full address": "permanent_address",
    "full_address": "permanent_address",
    "residential address": "permanent_address",
    "postal address": "permanent_address",
    "home address": "permanent_address",
    "native address": "permanent_address",
    "district": "district",
    "taluk": "taluk",
    "state": "state",
    "pincode": "pincode",
    "pin": "pincode",
    "postal code": "pincode",
    "pin code": "pincode",
    "mobile_number": "mobile_number",
    "mobile number": "mobile_number",
    "mobile": "mobile_number",
    "phone": "mobile_number",
    "phone number": "mobile_number",
    "contact number": "mobile_number",
    "contact_number": "mobile_number",

    # Email
    "email": "email",
    "email_id": "email",
    "email id": "email",
    "email address": "email",
    "email_address": "email",
    "student email": "email",
    "student_email": "email",
    "candidate email": "email",
    "candidate_email": "email",
    "applicant email": "email",
    "applicant_email": "email",
    "mail": "email",
    "mail_id": "email",
    "country": "country",
    "nationality": "nationality",
    "religion": "religion",

    # Bank Passbook
    "account_number": "account_number",
    "account number": "account_number",
    "acc no": "account_number",
    "account no": "account_number",
    "a/c no": "account_number",
    "ifsc_code": "ifsc_code",
    "ifsc code": "ifsc_code",
    "ifsc": "ifsc_code",
    "bank_name": "bank_name",
    "bank name": "bank_name",
    "branch": "branch",
    "bank branch": "branch",
    "bank_branch": "branch",
    "branch_name": "branch",
    "branch name": "branch",
    "city": "city",
    "bank city": "city",
    "account_holder_name": "account_holder_name",
    "account holder name": "account_holder_name",
    "account holder": "account_holder_name",
    "micr_code": "micr_code",
    "micr code": "micr_code",
    "micr": "micr_code",

    # EMIS & School/TC Identifiers
    "emis_id": "emis_id",
    "emis id": "emis_id",
    "emis": "emis_id",
    "emis number": "emis_id",
    "emis no": "emis_id",
    "student emis id": "emis_id",
    "admission_number": "admission_number",
    "admission number": "admission_number",
    "admission no": "admission_number",
    "adm no": "admission_number",
    "tc_number": "tc_number",
    "transfer certificate number": "tc_number",
    "tc no": "tc_number",
    "transfer certificate no": "tc_number",
    "school_name": "school_name",
    "school name": "school_name",
    "name of the school": "school_name",
    "institution name": "school_name",
    "institution": "school_name",
    "course": "course",
    "date_of_leaving": "date_of_leaving",
    "date of leaving": "date_of_leaving",
    "leaving date": "date_of_leaving",

    # Community & Caste
    "community_category": "community_category",
    "community category": "community_category",
    "community": "community_category",
    "category": "community_category",
    "social status": "community_category",
    "reservation category": "community_category",
    "caste category": "community_category",
    "caste": "caste",
    "caste name": "caste",
    "sub caste": "caste",
    "sub_caste": "caste",
    "subcaste": "caste",
    "community name": "caste",
    "community_name": "caste",
    "community_certificate_number": "community_certificate_number",
    "community certificate number": "community_certificate_number",
    "community certificate no": "community_certificate_number",
    "caste certificate number": "community_certificate_number",

    # Income
    "annual_income": "annual_income",
    "annual family income": "annual_income",
    "annual_family_income": "annual_income",
    "family income": "annual_income",
    "income": "annual_income",
    "income_certificate_number": "income_certificate_number",
    "income certificate number": "income_certificate_number",
    "income certificate no": "income_certificate_number",

    # Birth Certificate / General Dates
    "place_of_birth": "place_of_birth",
    "place of birth": "place_of_birth",
    "birth place": "place_of_birth",
    "registration_number": "registration_number",
    "registration number": "registration_number",
    "issue_date": "issue_date",
    "issue date": "issue_date",
    "date of issue": "issue_date",
    "application_number": "application_number",
    "application number": "application_number",
    "application no": "application_number",

    # Academic & Marksheet (SSLC / HSC)
    "register_number": "register_number",
    "register number": "register_number",
    "reg no": "register_number",
    "register no": "register_number",
    "registration number": "register_number",
    "roll no": "register_number",
    "roll number": "register_number",
    "roll_no": "register_number",
    "roll_number": "register_number",

    "sslc_register_number": "sslc_register_number",
    "sslc register number": "sslc_register_number",
    "sslc reg no": "sslc_register_number",
    "10th register number": "sslc_register_number",

    "sslc_total_marks": "sslc_total_marks",
    "sslc total marks": "sslc_total_marks",
    "10th total marks": "sslc_total_marks",
    "sslc marks": "sslc_total_marks",

    "sslc_mark_percentage": "sslc_mark_percentage",
    "sslc mark percentage": "sslc_mark_percentage",
    "sslc percentage": "sslc_mark_percentage",
    "10th percentage": "sslc_mark_percentage",

    "sslc_year_of_passing": "sslc_year_of_passing",
    "sslc year of passing": "sslc_year_of_passing",

    "hsc_register_number": "hsc_register_number",
    "hsc register number": "hsc_register_number",
    "hsc reg no": "hsc_register_number",
    "12th register number": "hsc_register_number",

    "hsc_total_marks": "hsc_total_marks",
    "hsc total marks": "hsc_total_marks",
    "12th total marks": "hsc_total_marks",
    "hsc marks": "hsc_total_marks",

    "hsc_mark_percentage": "hsc_mark_percentage",
    "hsc mark percentage": "hsc_mark_percentage",
    "hsc percentage": "hsc_mark_percentage",
    "12th percentage": "hsc_mark_percentage",

    "hsc_cutoff": "hsc_cutoff",
    "hsc cutoff": "hsc_cutoff",
    "cutoff": "hsc_cutoff",
    "cut off": "hsc_cutoff",
    "engineering cutoff": "hsc_cutoff",

    "hsc_year_of_passing": "hsc_year_of_passing",
    "hsc year of passing": "hsc_year_of_passing",

    "year_of_passing": "year_of_passing",
    "year of passing": "year_of_passing",
    "passing year": "year_of_passing",

    # Nativity / Bonafide / Migration
    "nativity": "nativity",
    "nativity certificate": "nativity",
    "migration_number": "migration_number",
    "migration number": "migration_number",
    "migration certificate number": "migration_number",
    "university": "university",
    "board / university": "university",
    "year": "year",

    # Document-Evidence-Based Yes/No Questions
    "is_emis_id_available": "is_emis_id_available",
    "is emis id available": "is_emis_id_available",
    "is emis id available?": "is_emis_id_available",
    "is emis available": "is_emis_id_available",
    "emis id available": "is_emis_id_available",
    "emis id available (yes/no)": "is_emis_id_available",
    "emis available": "is_emis_id_available",
    "whether emis id available": "is_emis_id_available",

    "is_first_graduate": "is_first_graduate",
    "is first graduate": "is_first_graduate",
    "is first graduate?": "is_first_graduate",
    "first graduate": "is_first_graduate",
    "first graduate (yes/no)": "is_first_graduate",
    "first graduate yes/no": "is_first_graduate",
    "is the student the first graduate in the family": "is_first_graduate",
    "is the student the first graduate in the family?": "is_first_graduate",

    "special_admission_quota": "special_admission_quota",
    "special admission quota": "special_admission_quota",
    "special admission quota (yes/no)": "special_admission_quota",
    "special quota": "special_admission_quota",
    "did you come under any special admission quota": "special_admission_quota",
    "did you come under any special admission quota?": "special_admission_quota",

    "differently_abled": "differently_abled",
    "differently abled": "differently_abled",
    "is differently abled": "differently_abled",
    "differently abled (yes/no)": "differently_abled",
    "differently abled category": "differently_abled",
    "did you belong to differently abled category": "differently_abled",
    "did you belong to differently abled category?": "differently_abled",
    "is_pwd": "differently_abled",
    "pwd": "differently_abled",

    "communication_address_same": "communication_address_same",
    "communication address same": "communication_address_same",
    "communication address same as permanent address": "communication_address_same",
    "is communication address same as permanent address": "communication_address_same",
    "is communication address same as permanent address?": "communication_address_same",
    "communication address same as permanent": "communication_address_same",
    "same as permanent address": "communication_address_same",
    "same as permanent address (yes/no)": "communication_address_same",

    "orphan_category": "orphan_category",
    "orphan category": "orphan_category",
    "orphan category (yes/no)": "orphan_category",
    "orphan category yes/no": "orphan_category",
    "orphan": "orphan_category",
    "is orphan": "orphan_category",
    "is orphan?": "orphan_category",
}

# Allowed canonical fields per document type
ALLOWED_CANONICAL_FIELDS_BY_DOC_TYPE: Dict[str, Set[str]] = {
    "AADHAAR": {
        "aadhaar_number",
        "date_of_birth",
        "dob",
        "student_name",
        "gender",
        "permanent_address",
        "address",
        "full_address",
        "district",
        "taluk",
        "state",
        "pincode",
        "mobile_number",
        "email",
        "father_name",
        "mother_name",
        "country",
        "religion",
        "nationality",
    },
    "TRANSFER_CERTIFICATE": {
        "emis_id",
        "student_name",
        "father_name",
        "mother_name",
        "email",
        "mobile_number",
        "admission_number",
        "issue_date",
        "date_of_leaving",
        "school_name",
        "date_of_birth",
        "dob",
        "community_category",
        "caste",
        "community",
        "community_name",
        "tc_number",
        "register_number",
        "course",
        "gender",
        "is_emis_id_available",
        "is_first_graduate",
        "differently_abled",
        "orphan_category",
        "special_admission_quota",
        "communication_address_same",
        "academic_information",
        "academic_info",
        "nationality",
        "country",
        "salutation",
    },
    "COMMUNITY": {
        "community_category",
        "caste",
        "community",
        "community_name",
        "community_certificate_number",
        "student_name",
        "father_name",
        "mother_name",
        "email",
        "mobile_number",
        "issue_date",
        "district",
        "taluk",
        "state",
        "religion",
        "nationality",
        "country",
        "is_first_graduate",
        "differently_abled",
        "orphan_category",
    },
    "INCOME": {
        "annual_income",
        "student_name",
        "father_name",
        "mother_name",
        "income_certificate_number",
        "issue_date",
        "district",
        "taluk",
    },
    "BANK_PASSBOOK": {
        "account_number",
        "ifsc_code",
        "bank_name",
        "branch",
        "bank_branch",
        "city",
        "bank_city",
        "account_holder_name",
        "micr_code",
        "student_name",
    },
    "BIRTH_CERTIFICATE": {
        "student_name",
        "date_of_birth",
        "gender",
        "father_name",
        "mother_name",
        "place_of_birth",
        "registration_number",
        "district",
        "state",
        "issue_date",
    },
    "SSLC": {
        "student_name",
        "register_number",
        "sslc_register_number",
        "sslc_total_marks",
        "sslc_mark_percentage",
        "sslc_year_of_passing",
        "date_of_birth",
        "school_name",
        "father_name",
        "mother_name",
        "gender",
        "email",
        "mobile_number",
    },
    "HSC": {
        "student_name",
        "register_number",
        "roll_number",
        "hsc_register_number",
        "hsc_total_marks",
        "hsc_mark_percentage",
        "hsc_cutoff",
        "hsc_year_of_passing",
        "school_name",
        "father_name",
        "mother_name",
        "gender",
        "email",
        "mobile_number",
    },
    "NATIVITY": {
        "student_name",
        "father_name",
        "mother_name",
        "state",
        "district",
        "taluk",
        "permanent_address",
        "nativity",
        "issue_date",
    },
    "BONAFIDE": {
        "student_name",
        "school_name",
        "admission_number",
        "course",
        "year",
    },
    "MIGRATION": {
        "migration_number",
        "university",
        "year",
        "student_name",
    },
    "ALLOTMENT_ORDER": {
        "application_number",
        "student_name",
        "register_number",
        "roll_number",
        "email",
        "mobile_number",
        "course",
        "school_name",
        "community_category",
        "rank",
    },
    "PASSPORT": {
        "student_name",
        "date_of_birth",
        "gender",
        "nationality",
        "permanent_address",
    },
}


def normalize_doc_type(raw_type: str) -> str:
    """Normalize document type string to uppercase canonical key using resolve_canonical_document_type."""
    from app.services.field_source_rules import resolve_canonical_document_type
    return resolve_canonical_document_type(raw_type)


def resolve_canonical_field_key(field_name: str) -> Optional[str]:
    """
    Resolve raw alias or display string to standard canonical snake_case key.
    Uses FIELD_ALIAS_TO_CANONICAL_KEY and field_canonicalizer.
    """
    if not field_name:
        return None
    raw = str(field_name).strip()
    raw_lower = raw.lower()

    if raw_lower in FIELD_ALIAS_TO_CANONICAL_KEY:
        return FIELD_ALIAS_TO_CANONICAL_KEY[raw_lower]

    # Try mapping via field_canonicalizer
    canon_display = get_canonical_field_name(raw)
    canon_display_lower = canon_display.lower()
    if canon_display_lower in FIELD_ALIAS_TO_CANONICAL_KEY:
        return FIELD_ALIAS_TO_CANONICAL_KEY[canon_display_lower]

    # Convert to snake_case identifier
    snake = re.sub(r'[^a-zA-Z0-9]+', '_', raw_lower).strip('_')
    if snake in FIELD_ALIAS_TO_CANONICAL_KEY:
        return FIELD_ALIAS_TO_CANONICAL_KEY[snake]

    # Fallback to general snake_case if looks valid
    if snake:
        return snake
    return None


def _masked_identifier(value: Optional[str]) -> str:
    if not value:
        return "[MASKED]"
    clean = str(value).strip()
    if len(clean) <= 8:
        return "[MASKED]"
    return f"{clean[:4]}...{clean[-4:]}"


class DocumentExtractionService:
    """
    Service layer orchestrating on-demand, requested-field AI document extraction,
    deterministic version referencing, security isolation, and immutable snapshots.
    """

    def __init__(
        self,
        extraction_repo: Optional[DocumentExtractionRepository] = None,
        doc_repo: Optional[StudentDocumentRepository] = None,
        gemini_service: Optional[GeminiService] = None,
    ):
        self.repository = extraction_repo or DocumentExtractionRepository()
        self.doc_repository = doc_repo or StudentDocumentRepository()
        self.gemini_service = gemini_service or GeminiService()

    def validate_and_canonicalize_requested_fields(
        self, document_type: str, requested_fields: List[str]
    ) -> List[str]:
        """
        Validates that requested_fields is non-empty, canonicalizes all aliases,
        deduplicates, and ensures fields are valid for the given document type.
        """
        if not requested_fields or not isinstance(requested_fields, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="requested_fields must not be empty.",
            )

        norm_type = normalize_doc_type(document_type)
        allowed_set = ALLOWED_CANONICAL_FIELDS_BY_DOC_TYPE.get(norm_type)

        canonical_fields: List[str] = []
        seen: Set[str] = set()

        for raw_f in requested_fields:
            if not raw_f or not str(raw_f).strip():
                continue
            canon = resolve_canonical_field_key(str(raw_f))
            if not canon:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown or invalid field: '{raw_f}'.",
                )

            # Check validity for document type if catalog exists
            if allowed_set is not None and canon not in allowed_set and not is_yes_no_field(canon):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Field '{raw_f}' (canonical: '{canon}') is not valid for document type '{document_type}'.",
                )

            if canon not in seen:
                canonical_fields.append(canon)
                seen.add(canon)

        if not canonical_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields found in requested_fields.",
            )

        return canonical_fields

    def verify_isolation(
        self,
        doc: StudentDocument,
        actor: User,
    ) -> None:
        """
        Enforce strict RBAC, department isolation, and role restrictions.
        Students cannot trigger staff-only extraction.
        """
        if actor.role == UserRole.SUPER_ADMIN:
            return

        if actor.role == UserRole.STUDENT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Students are not authorized to trigger on-demand staff extraction.",
            )

        if actor.role == UserRole.DEPARTMENT_ADMIN:
            doc_dept = doc.department_id
            user_dept = getattr(actor, "department_code", None) or getattr(actor, "department_id", None)
            if user_dept and doc_dept and user_dept != doc_dept:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cross-department document extraction is forbidden.",
                )
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for document extraction.",
        )

    async def request_and_extract_fields(
        self,
        student_document_id: str,
        requested_fields: List[str],
        actor: User,
        version_id: Optional[str] = None,
        bypass_cache: bool = False,
    ) -> Tuple[DocumentExtractionRequest, Optional[DocumentExtractionResult]]:
        """
        Perform requested-field extraction for a specific document version.
        Reuses stored file without re-upload.
        """
        doc = await self.doc_repository.get_by_id(student_document_id)
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"StudentDocument '{student_document_id}' not found.",
            )

        # Enforce security / tenancy isolation
        self.verify_isolation(doc, actor)

        # Canonicalize and validate requested fields against document type
        canonical_fields = self.validate_and_canonicalize_requested_fields(
            document_type=doc.document_type,
            requested_fields=requested_fields,
        )

        # Resolve targeted document version
        target_version: Optional[DocumentVersion] = None
        if version_id:
            for v in doc.versions:
                if v.version_id == version_id:
                    target_version = v
                    break
            if not target_version:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Version '{version_id}' not found in StudentDocument '{student_document_id}'.",
                )
        else:
            target_version = doc.active_version
            if not target_version:
                # If no active version flagged, fallback to latest version
                target_version = doc.versions[-1] if doc.versions else None

        if not target_version:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No document version available for extraction.",
            )

        # Classification Extraction Gate:
        # Only correctly classified documents (VALID or staff-reclassified) are eligible for field extraction.
        v_status = target_version.validation_status or "PENDING"
        if v_status in ("WRONG_DOCUMENT", "UNKNOWN", "CLASSIFICATION_FAILED", "NEEDS_REVIEW", "INVALID"):
            reason = target_version.validation_reason or f"Document classification status is '{v_status}'."
            logger.warning(
                f"[ExtractionGate] Extraction blocked for document {doc.id} (v{target_version.version_number}): status='{v_status}' reason='{reason}'"
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Extraction blocked: Document classification status is '{v_status}'. Only correctly classified or staff-approved (VALID) documents are eligible for field extraction. Reason: {reason}",
            )

        # Create extraction request record
        req = DocumentExtractionRequest(
            student_document_id=str(doc.id),
            document_version_id=target_version.version_id,
            student_id=doc.student_id,
            document_type=doc.document_type,
            requested_fields=canonical_fields,
            status=ExtractionRequestStatus.REQUESTED,
            requested_by=actor.username,
            requested_at=datetime.now(timezone.utc),
        )
        await self.repository.create_request(req)

        logger.info(
            "[FIELD_EXTRACTION] student=%s field=%s source_document=%s document_version=%s",
            _mask_student_identifier(doc.student_id),
            ",".join(canonical_fields),
            normalize_doc_type(doc.document_type),
            target_version.version_number,
        )

        # Temporary Development Diagnostic Logging
        v_ocr = getattr(target_version, "ocr_text", None)
        logger.info(
            "[FIELD_EXTRACTION] student=%s field=%s source_document=%s document_version=%s",
            _masked_identifier(doc.student_id),
            ",".join(canonical_fields),
            normalize_doc_type(doc.document_type),
            target_version.version_number,
        )

        # Check Cache/Reuse: Check if exact extraction already exists
        existing_result = None
        if not bypass_cache:
            existing_result = await self.repository.find_existing_result(
                student_document_id=str(doc.id),
                document_version_id=target_version.version_id,
                requested_fields=canonical_fields,
            )

        if existing_result:
            # If all extracted fields in existing_result are None or NOT_AVAILABLE, do not blindly reuse
            extracted_vals = existing_result.extracted_data or {}
            has_useful_val = any(
                v not in (None, "", "NOT_AVAILABLE") for v in extracted_vals.values()
            )
            if has_useful_val or not bypass_cache:
                logger.info(
                    f"[ExtractionService] Reusing existing extraction result {existing_result.id} for doc {doc.id} v{target_version.version_number}"
                )
                now = datetime.now(timezone.utc)
                await self.repository.update_request_status(
                    request_id=str(req.id),
                    status=ExtractionRequestStatus.COMPLETED,
                    started_at=now,
                    completed_at=now,
                    extraction_result_id=str(existing_result.id),
                )
                req.status = ExtractionRequestStatus.COMPLETED
                req.completed_at = now
                req.extraction_result_id = str(existing_result.id)
                return req, existing_result

        # Update status to PROCESSING
        now_started = datetime.now(timezone.utc)
        await self.repository.update_request_status(
            request_id=str(req.id),
            status=ExtractionRequestStatus.PROCESSING,
            started_at=now_started,
        )
        req.status = ExtractionRequestStatus.PROCESSING
        req.started_at = now_started

        # Perform extraction on stored file
        try:
            from app.utils.storage_resolver import resolve_document_file_path
            effective_file_path = target_version.file_path
            if not effective_file_path or not os.path.exists(effective_file_path):
                res_p = resolve_document_file_path(
                    target_version.file_path,
                    batch_id=str(doc.batch_id),
                    register_number=str(doc.student_id),
                    document_name=doc.document_name,
                )
                if res_p and res_p.is_file():
                    effective_file_path = str(res_p.resolve())
                    target_version.file_path = effective_file_path
                    try:
                        await doc.save()
                    except Exception:
                        pass

            ai_res = await self._run_ai_extraction(
                file_path=effective_file_path,
                document_type=doc.document_type,
                requested_fields=canonical_fields,
                student_document_id=str(doc.id),
                student_id=doc.student_id,
                version_id=target_version.version_id,
            )
            answers_map = getattr(ai_res, "answers_map", {})
            if isinstance(ai_res, tuple) and len(ai_res) == 6:
                extracted_dict, conf, prov, ocr_stat, ai_prov, answers_map = ai_res
            elif isinstance(ai_res, tuple) and len(ai_res) == 5:
                extracted_dict, conf, prov, ocr_stat, ai_prov = ai_res
            elif isinstance(ai_res, tuple) and len(ai_res) >= 2:
                extracted_dict, conf = ai_res[0], ai_res[1]
                prov = "LOCAL_OCR_GEMINI"
                ocr_stat = "OCR_SUCCESS"
                ai_prov = "gemini"
            else:
                raise ValueError(f"Unexpected extraction result format: {ai_res}")

            # Persist immutable extraction result with ONLY requested fields
            result = DocumentExtractionResult(
                extraction_request_id=str(req.id),
                student_document_id=str(doc.id),
                document_version_id=target_version.version_id,
                requested_fields=canonical_fields,
                extracted_data=extracted_dict,
                validation_results={"status": "VALID", "reason": None},
                confidence=conf,
                provenance=prov,
                ocr_status=ocr_stat,
                ai_provider=ai_prov,
                pipeline_metadata={
                    "provenance": prov,
                    "ocr_status": ocr_stat,
                    "ai_provider": ai_prov,
                    "document_type": doc.document_type,
                    "answers": answers_map,
                },
                created_at=datetime.now(timezone.utc),
            )
            await self.repository.create_result(result)
            for field_name in canonical_fields:
                logger.info(
                    "[FIELD_EXTRACTION] FIELD_VALUE_PERSISTED field=%s success=true",
                    field_name,
                )

            # Mark request COMPLETED
            now_completed = datetime.now(timezone.utc)
            await self.repository.update_request_status(
                request_id=str(req.id),
                status=ExtractionRequestStatus.COMPLETED,
                completed_at=now_completed,
                extraction_result_id=str(result.id),
            )
            req.status = ExtractionRequestStatus.COMPLETED
            req.completed_at = now_completed
            req.extraction_result_id = str(result.id)

            # Initialize verification records for student verification
            try:
                from app.services.document_verification_service import DocumentVerificationService
                verif_service = DocumentVerificationService()
                await verif_service.initialize_verification_from_extraction(
                    extraction_result=result,
                    student_doc=doc,
                    extraction_req=req,
                )
            except Exception as verif_err:
                logger.warning(f"[ExtractionService] Verification init warning: {verif_err}")

            # Audit Log
            await self._log_audit(
                action="DOCUMENT_EXTRACTION_COMPLETED",
                doc=doc,
                actor=actor,
                req=req,
                result_status="SUCCESS",
            )

            return req, result

        except Exception as exc:
            logger.error(
                f"[ExtractionService] Extraction failed for doc {doc.id}: {exc}",
                exc_info=True,
            )
            now_failed = datetime.now(timezone.utc)
            error_msg = str(exc) or "Extraction processing error."
            await self.repository.update_request_status(
                request_id=str(req.id),
                status=ExtractionRequestStatus.FAILED,
                failed_at=now_failed,
                error_message=error_msg,
            )
            req.status = ExtractionRequestStatus.FAILED
            req.failed_at = now_failed
            req.error_message = error_msg

            # Audit Log for failure
            await self._log_audit(
                action="DOCUMENT_EXTRACTION_FAILED",
                doc=doc,
                actor=actor,
                req=req,
                result_status="FAILED",
                failure_info=error_msg,
            )

            return req, None

    async def _log_audit(
        self,
        action: str,
        doc: StudentDocument,
        actor: Optional[User],
        req: DocumentExtractionRequest,
        result_status: str = "SUCCESS",
        failure_info: Optional[str] = None,
    ):
        """Record an immutable audit log entry."""
        actor_id = str(actor.id) if actor and hasattr(actor, "id") and actor.id else "system"
        actor_username = actor.username if actor and hasattr(actor, "username") else "system"
        actor_role = (
            actor.role.value if actor and hasattr(actor, "role") and hasattr(actor.role, "value")
            else str(getattr(actor, "role", "SYSTEM"))
        )
        try:
            audit = AuditLog(
                action=action,
                actor_user_id=actor_id,
                actor_username=actor_username,
                actor_role=actor_role,
                submission_id=str(doc.id or doc.student_id),
                student_name=f"Student_{doc.student_id}",
                register_number=str(doc.student_id),
                batch_id=doc.batch_id,
                class_id=doc.class_id,
                documents_count=len(doc.versions),
                result=result_status,
                failure_info=failure_info or f"Requested fields: {req.requested_fields}",
            )
            await audit.insert()
        except Exception:
            pass

    async def _run_ai_extraction(
        self,
        file_path: str,
        document_type: str,
        requested_fields: List[str],
        student_document_id: Optional[str] = None,
        student_id: Optional[str] = None,
        version_id: Optional[str] = None,
        bypass_cache: bool = False,
        **kwargs,
    ) -> Tuple[Dict[str, Any], float, str, str, str]:
        """
        Execute Free-First extraction pipeline:
        1. Try Local OCR (RapidOCR / pypdf) first.
        2. If Local OCR succeeds: send OCR text + original document context to Gemini (LOCAL_OCR_GEMINI).
        3. If Local OCR fails/unavailable/rate-limited: send original document directly to Gemini Multimodal (GEMINI_MULTIMODAL).
        4. Extract ONLY requested canonical keys.
        5. Return (extracted_dict, confidence, provenance, ocr_status, ai_provider).
        """
        # Validate file exists
        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"DOCUMENT_MISSING: Stored document file not found at: {file_path}")

        file_size = os.path.getsize(file_path)
        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        for field_name in requested_fields:
            logger.info(
                "[FIELD_EXTRACTION] student=%s field=%s original_file_loaded=true mime_type=%s file_size=%d",
                _mask_student_identifier(student_id),
                field_name,
                mime_type,
                file_size,
            )

        # Document Quality & Validity Gate (reject stubs/empty/corrupted files before OCR or Gemini)
        from app.services.accuracy_extraction_engine import AccuracyExtractionEngine
        quality = AccuracyExtractionEngine().inspect_document_quality(file_path)
        if not quality.get("is_usable", True):
            reason_str = quality.get("reason") or "DOCUMENT_INVALID"
            f_state = "DOCUMENT_INVALID" if (quality.get("is_invalid") or "DOCUMENT_INVALID" in reason_str or "EMPTY" in reason_str or "CORRUPTED" in reason_str) else "OCR_LOW_QUALITY"
            logger.warning(
                "[FIELD_EXTRACTION] Document quality gate failed for %s: %s (state=%s). Skipping Gemini call.",
                file_path,
                reason_str,
                f_state,
            )
            extracted_dict = {f: None for f in requested_fields}
            return ExtractionAiResult(
                extracted_dict,
                0.0,
                f_state,
                f_state,
                "document_quality_gate",
                {},
            )

        # 1. Free-First: Attempt Local OCR
        ocr_text = ""
        ocr_success = False
        ocr_status = "OCR_UNAVAILABLE"
        ocr_provider = "LOCAL_RAPIDOCR"
        ocr_error = None
        ocr_start = datetime.now(timezone.utc)

        for field_name in requested_fields:
            logger.info("[FIELD_EXTRACTION] OCR_STARTED field=%s", field_name)

        try:
            from app.services.ocr_service import OCRService
            ocr_svc = OCRService()
            ocr_res = ocr_svc.extract_text(file_path, prefer_local=True)
            ocr_status = ocr_res.get("status") or ("OCR_SUCCESS" if ocr_res.get("success") else "OCR_FAILED")
            ocr_provider = ocr_res.get("provider", "LOCAL_RAPIDOCR")
            if ocr_res and ocr_res.get("success"):
                ocr_text = ocr_res.get("text") or ""
                ocr_success = bool(ocr_text.strip())
            else:
                ocr_error = ocr_res.get("message") if ocr_res else "OCR produced no text."
        except Exception as ocr_ex:
            ocr_error = str(ocr_ex)
            ocr_status = "OCR_FAILED"
            logger.warning(f"[OCR] OCR notice for {file_path}: {ocr_ex}")

        ocr_end = datetime.now(timezone.utc)
        for field_name in requested_fields:
            logger.info(
                "[FIELD_EXTRACTION] OCR_RESULT field=%s success=%s text_length=%d status=%s provider=%s",
                field_name,
                ocr_success,
                len(ocr_text),
                ocr_status,
                ocr_provider,
            )

        # 2. Pipeline Path Selection & Provenance Determination
        if ocr_success:
            if "MISTRAL" in str(ocr_provider).upper():
                provenance = "MISTRAL_OCR_GEMINI"
            else:
                provenance = "LOCAL_OCR_GEMINI"
            effective_ocr_text = ocr_text
            ocr_status = "OCR_SUCCESS"
        else:
            # Free-First Fallback: Local OCR failed/unavailable -> Gemini Multimodal directly on original document
            provenance = "GEMINI_MULTIMODAL"
            effective_ocr_text = None
            if not ocr_status or ocr_status == "OCR_SUCCESS":
                ocr_status = "OCR_FAILED"
            logger.info(
                "[FIELD_EXTRACTION] Local OCR unavailable/failed (status=%s). Engaging GEMINI_MULTIMODAL directly on original document bytes.",
                ocr_status,
            )

        # 3. AI Extraction via Gemini
        for field_name in requested_fields:
            logger.info("[FIELD_EXTRACTION] GEMINI_STARTED field=%s provenance=%s", field_name, provenance)

        now_ai_start = datetime.now(timezone.utc)
        raw_res = self.gemini_service.extract_from_file(
            file_path=file_path,
            target_fields=requested_fields,
            document_hint=normalize_doc_type(document_type),
            ocr_text=effective_ocr_text,
            student_id=student_id,
            document_id=student_document_id,
            document_version=version_id,
            bypass_cache=bypass_cache,
        )
        now_ai_end = datetime.now(timezone.utc)

        ai_success = raw_res.get("success", False)
        ai_error = raw_res.get("error") or ""
        ai_error_type = raw_res.get("error_type", "")
        ai_error_str = str(ai_error).lower()
        is_quota = (
            "quota" in ai_error_str
            or "429" in ai_error_str
            or "resource_exhausted" in ai_error_str
            or ai_error_type in ("QUOTA_EXCEEDED",)
        )
        is_unavailable = (
            "ai_extraction_unavailable" in ai_error_str
            or ai_error_type in ("GEMINI_UNAVAILABLE", "QUOTA_EXCEEDED")
        )

        for field_name in requested_fields:
            logger.info(
                "[FIELD_EXTRACTION] GEMINI_RESULT field=%s success=%s fields=%d",
                field_name,
                ai_success,
                len(raw_res.get("fields", {})) if isinstance(raw_res.get("fields"), dict) else 0,
            )

        if not ai_success and not raw_res.get("fields") and not raw_res.get("extracted_summary"):
            if is_quota:
                retry_after = raw_res.get("retry_after")
                raise RuntimeError(
                    f"AI_RATE_LIMITED: Gemini rate limit / quota exceeded "
                    f"(retry_after={retry_after}). Reason: {ai_error}"
                )
            if is_unavailable:
                raise RuntimeError(f"AI_EXTRACTION_UNAVAILABLE: Gemini service is unavailable: {ai_error}")
            raise RuntimeError(f"AI_EXTRACTION_FAILED: {ai_error or 'AI returned empty result'}")

        if not ai_success:
            if is_quota:
                raise RuntimeError(f"AI_RATE_LIMITED: {ai_error}")
            if is_unavailable:
                raise RuntimeError(f"AI_EXTRACTION_UNAVAILABLE: {ai_error}")
            raise RuntimeError(f"AI_EXTRACTION_FAILED: {ai_error or 'Gemini returned an unsuccessful response'}")

        fields = raw_res.get("fields", {}) or {}
        summary = raw_res.get("extracted_summary", {}) or {}
        if not isinstance(fields, dict) or not isinstance(summary, dict):
            raise RuntimeError("AI_EXTRACTION_FAILED: Gemini returned malformed structured fields.")
        confidence = float(raw_res.get("confidence", 95.0))

        # Filter strictly so ONLY requested canonical keys are preserved
        extracted_data: Dict[str, Any] = {}
        answers_map: Dict[str, Any] = {}
        for canon_key in requested_fields:
            val = None
            # 1. Check summary direct key
            if canon_key in summary and summary[canon_key] is not None:
                val = summary[canon_key]
            # 2. Check summary aliases
            if val is None:
                for sk, sv in summary.items():
                    if sv is not None and resolve_canonical_field_key(sk) == canon_key:
                        val = sv
                        break
            # 3. Search fields dictionary by matching keys
            if val is None:
                for f_name, f_info in fields.items():
                    f_canon = resolve_canonical_field_key(f_name)
                    if f_canon == canon_key:
                        if isinstance(f_info, dict):
                            val = f_info.get("value")
                        else:
                            val = f_info
                        if val is not None:
                            break

            # If field is a Yes/No question, strictly evaluate evidence
            if is_yes_no_field(canon_key):
                eval_ans = evaluate_evidence_based_yes_no(
                    field_key=canon_key,
                    raw_val=val,
                    document_text=effective_ocr_text or ocr_text or "",
                    document_type=normalize_doc_type(document_type),
                    all_extracted_fields=extracted_data,
                )
                val = eval_ans["value"]
                answers_map[canon_key] = eval_ans
            # If field genuinely absent, value is None (FIELD_NOT_FOUND)
            elif val is not None and str(val).strip().upper() in ("NONE", "NULL", "NOT_FOUND", "FIELD_NOT_FOUND", "N/A", "NOT AVAILABLE"):
                val = None

            extracted_data[canon_key] = val
            logger.info(
                "[FIELD_EXTRACTION] FIELD_MATCH field=%s matched=%s provenance=%s",
                canon_key,
                val is not None and str(val).strip() != "",
                provenance,
            )

        return ExtractionAiResult(
            extracted_data,
            confidence,
            provenance,
            ocr_status,
            "gemini",
            answers_map,
        )

    async def get_document_extractions(
        self,
        student_document_id: str,
        actor: User,
    ) -> List[DocumentExtractionRequest]:
        """Retrieve all historical extraction requests for a given student document."""
        doc = await self.doc_repository.get_by_id(student_document_id)
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"StudentDocument '{student_document_id}' not found.",
            )
        self.verify_isolation(doc, actor)
        return await self.repository.get_requests_by_document_id(student_document_id)

    async def get_extraction_details(
        self,
        extraction_request_id: str,
        actor: User,
    ) -> Tuple[DocumentExtractionRequest, Optional[DocumentExtractionResult]]:
        """Retrieve full details for an extraction request and its linked result."""
        req = await self.repository.get_request_by_id(extraction_request_id)
        if not req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Extraction request '{extraction_request_id}' not found.",
            )

        doc = await self.doc_repository.get_by_id(req.student_document_id)
        if doc:
            self.verify_isolation(doc, actor)

        result = None
        if req.extraction_result_id:
            result = await self.repository.get_result_by_id(req.extraction_result_id)
        elif req.status == ExtractionRequestStatus.COMPLETED:
            result = await self.repository.get_result_by_request_id(extraction_request_id)

        return req, result
