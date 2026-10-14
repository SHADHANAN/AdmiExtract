import asyncio
from datetime import datetime, timezone, timedelta
import logging
import re
import time
import secrets
from typing import Dict, List, Optional, Tuple, Any
import os
from fastapi import HTTPException, status
from beanie import PydanticObjectId

from app.core.config import settings

from app.models.verification_token import VerificationToken, VerificationTokenStatus
from app.models.document_verification import (
    DocumentFieldVerification,
    VerificationFieldStatus,
    VerificationHistoryEntry,
)
from app.models.document_extraction_result import DocumentExtractionResult
from app.models.batch import AdmissionBatch
from app.models.batch_extraction import BatchExtractionRequest, BatchExtractionStatus
from app.models.student_submission import StudentSubmission
from app.models.student_document import StudentDocument
from app.schemas.verification_token import (
    PublicVerificationTokenResponse,
    PublicVerificationSubmitRequest,
    PublicVerificationSessionResponse,
    ValidateStudentIdentityRequest,
    GenerateVerificationTokenResponse,
    CommonStudentIdentifyRequest,
    CommonStudentIdentifyResponse,
    CommonStudentVerifyCodeRequest,
    CommonStudentSubmitRequest,
    CommonStudentResendCodeRequest,
    CommonStudentResendCodeResponse,
)
from app.schemas.document_verification import (
    DocumentFieldVerificationResponse,
    VerificationHistoryEntryResponse,
)

logger = logging.getLogger("app.services.verification_token_service")

SUCCESSFUL_EXTRACTION_STATUSES = [
    BatchExtractionStatus.COMPLETED.value,
    BatchExtractionStatus.PARTIAL.value,
    BatchExtractionStatus.VERIFIED.value,
    BatchExtractionStatus.EXPORTED.value,
]


def _to_history_response(h: VerificationHistoryEntry) -> VerificationHistoryEntryResponse:
    return VerificationHistoryEntryResponse(
        entry_id=h.entry_id,
        actor=h.actor,
        actor_role=h.actor_role,
        action=h.action,
        old_value=h.old_value,
        new_value=h.new_value,
        comment=h.comment,
        document_version_id=h.document_version_id,
        timestamp=h.timestamp,
    )


def _to_verification_response(r: DocumentFieldVerification) -> DocumentFieldVerificationResponse:
    # Ensure raw_value/ai_value is not the literal string "NOT_AVAILABLE" in the response
    display_ai = None if r.ai_value in ("NOT_AVAILABLE", "NOT_FOUND", None) else r.ai_value
    display_raw = None if r.raw_value in ("NOT_AVAILABLE", "NOT_FOUND", None) else r.raw_value
    display_state = r.field_state
    if display_state == "EXTRACTED" and display_ai is None:
        display_state = "NOT_FOUND"

    return DocumentFieldVerificationResponse(
        id=str(r.id),
        extraction_result_id=r.extraction_result_id,
        extraction_request_id=r.extraction_request_id,
        student_id=r.student_id,
        document_id=r.document_id,
        document_version_id=r.document_version_id,
        department_id=r.department_id,
        batch_id=r.batch_id,
        class_id=r.class_id,
        document_type=r.document_type,
        source_document_name=r.source_document_name,
        field_name=r.field_name,
        ai_value=display_ai,
        raw_value=display_raw,
        student_value=r.student_value,
        final_value=r.final_value,
        status=r.status.value if isinstance(r.status, VerificationFieldStatus) else str(r.status),
        confidence=r.confidence,
        confidence_score=r.confidence_score,
        field_state=display_state,
        evidence_snippet=r.evidence_snippet,
        page_number=r.page_number,
        reason=r.reason,
        student_updated_at=r.student_updated_at,
        staff_reviewed_at=r.staff_reviewed_at,
        reviewed_by=r.reviewed_by,
        staff_comment=r.staff_comment,
        student_comment=r.student_comment,
        history=[_to_history_response(h) for h in r.history],
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


class VerificationTokenService:
    """
    Service managing cryptographically secure, scoped tokens for public
    student verification sessions.
    """

    _failed_attempts: Dict[str, List[float]] = {}
    _failed_lock = asyncio.Lock()

    async def resolve_latest_successful_batch_extraction(
        self,
        batch_id: str,
        student_id: Optional[str] = None,
    ) -> Optional[BatchExtractionRequest]:
        """
        Authoritatively resolve the latest successfully completed extraction request for a batch (and student).
        Guarantees:
        - Status must be in [COMPLETED, PARTIAL, VERIFIED, EXPORTED] (never FAILED, CANCELLED, PROCESSING, DRAFT).
        - Sorted by -created_at so the newest successful run is prioritized.
        - If student_id is given, checks if that student has verification records in the candidate run.
        - Preserves historical records; returns the authoritative latest successful BatchExtractionRequest.
        """
        clean_reg = (student_id or "").strip().upper() if student_id else None

        candidate_reqs = await BatchExtractionRequest.find(
            {
                "batch_id": str(batch_id),
                "status": {"$in": SUCCESSFUL_EXTRACTION_STATUSES},
            }
        ).sort("-created_at").to_list()

        if not candidate_reqs:
            # Check string vs ObjectId format if batch_id type varies
            all_successful = await BatchExtractionRequest.find(
                {
                    "status": {"$in": SUCCESSFUL_EXTRACTION_STATUSES},
                }
            ).sort("-created_at").to_list()
            candidate_reqs = [r for r in all_successful if str(r.batch_id) == str(batch_id)]

        if not candidate_reqs:
            return None

        # Sort candidate requests authoritatively by completion timestamp (or creation timestamp)
        candidate_reqs.sort(
            key=lambda r: (r.completed_at or r.created_at or datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )

        if clean_reg:
            # Check which completed run actually extracted this student using all identifier aliases
            aliases = {clean_reg, student_id.strip(), student_id.strip().lower()}
            sub = await StudentSubmission.find_one(
                {"$or": [
                    {"batch_id": str(batch_id), "register_number": clean_reg},
                    {"batch_id": str(batch_id), "register_number": student_id.strip()},
                    {"batch_id": str(batch_id), "student_id": clean_reg},
                    {"register_number": clean_reg},
                    {"register_number": student_id.strip()},
                    {"student_id": student_id.strip()},
                ]}
            )
            if sub:
                if sub.register_number:
                    aliases.update({sub.register_number.strip(), sub.register_number.strip().upper(), sub.register_number.strip().lower()})
                s_id = getattr(sub, "student_id", None)
                if s_id:
                    aliases.update({s_id.strip(), s_id.strip().upper(), s_id.strip().lower()})
                aliases.add(str(sub.id))

            alias_list = list(aliases)
            for req in candidate_reqs:
                has_student_records = await DocumentFieldVerification.find(
                    {
                        "extraction_request_id": req.extraction_request_id,
                        "$or": [
                            {"student_id": {"$in": alias_list}},
                            {"student_submission_id": {"$in": alias_list}},
                        ]
                    }
                ).count()
                if has_student_records > 0:
                    return req

        # Return latest completed extraction for the batch
        return candidate_reqs[0]

    async def refresh_or_resolve_token_extraction(
        self, token_doc: VerificationToken
    ) -> VerificationToken:
        """
        Policy for active verification sessions:
        - If the token is already COMPLETED (submitted), its historical extraction is preserved and locked.
        - If active (unsubmitted), refresh to the newest successfully completed extraction for that student and batch.
        - Never silently mix fields or display outdated extractions when a newer successful run completed.
        - Merely loading or refreshing data NEVER marks a student as verified.
        """
        if token_doc.status != VerificationTokenStatus.ACTIVE.value:
            return token_doc

        latest_req = await self.resolve_latest_successful_batch_extraction(
            batch_id=token_doc.batch_id, student_id=token_doc.student_id
        )

        if latest_req and latest_req.extraction_request_id:
            new_ext_id = latest_req.extraction_request_id
            if token_doc.extraction_request_id != new_ext_id:
                logger.info(
                    f"[VerificationToken] Refreshing active token {token_doc.token} from "
                    f"'{token_doc.extraction_request_id}' to latest completed extraction '{new_ext_id}'"
                )
                token_doc.extraction_request_id = new_ext_id
                token_doc.updated_at = datetime.now(timezone.utc)
                await token_doc.save()

        return token_doc

    async def create_or_get_token(
        self,
        student_id: str,
        batch_id: str,
        student_name: Optional[str] = None,
        batch_name: Optional[str] = None,
        class_id: Optional[str] = None,
        department_id: Optional[str] = None,
        extraction_request_id: Optional[str] = None,
        submission_id: Optional[str] = None,
        expires_in_days: int = 7,
        force_refresh: bool = False,
    ) -> VerificationToken:
        """
        Generate or retrieve an active, non-expired verification token
        for a specific student and extraction/batch scope.
        Always resolves to the latest successfully completed extraction if not explicitly provided.
        """
        now = datetime.now(timezone.utc)

        # Resolve latest completed extraction request if extraction_request_id was not explicitly specified
        # or if the specified one is not successful
        latest_req = await self.resolve_latest_successful_batch_extraction(
            batch_id=batch_id, student_id=student_id
        )
        if latest_req:
            if not extraction_request_id:
                extraction_request_id = latest_req.extraction_request_id
            else:
                specified_req = await BatchExtractionRequest.find_one(
                    BatchExtractionRequest.extraction_request_id == extraction_request_id
                )
                if not specified_req or specified_req.status not in SUCCESSFUL_EXTRACTION_STATUSES:
                    extraction_request_id = latest_req.extraction_request_id

        # Check if an already completed token exists for this exact scope and student
        if not force_refresh:
            comp_query: Dict[str, Any] = {
                "student_id": student_id,
                "batch_id": batch_id,
                "status": VerificationTokenStatus.COMPLETED.value,
            }
            if extraction_request_id:
                comp_query["extraction_request_id"] = extraction_request_id
            existing_comp = await VerificationToken.find(comp_query).sort("-completed_at").first_or_none()
            if existing_comp:
                return existing_comp

        # Check for existing active, valid token for this exact student and scope
        query = {
            "student_id": student_id,
            "batch_id": batch_id,
            "status": VerificationTokenStatus.ACTIVE.value,
        }
        if extraction_request_id:
            exact_query = {**query, "extraction_request_id": extraction_request_id}
            existing = await VerificationToken.find(exact_query).sort("-created_at").first_or_none()
            if existing and existing.is_valid and not force_refresh:
                return existing

        # Check if an active token exists without matching extraction_request_id
        existing = await VerificationToken.find(query).sort("-created_at").first_or_none()
        if existing and existing.is_valid and not force_refresh:
            # Upgrade existing active session if a newer extraction completed
            if extraction_request_id and existing.extraction_request_id != extraction_request_id:
                logger.info(
                    f"[VerificationToken] Upgrading active token {existing.token} to latest extraction '{extraction_request_id}'"
                )
                existing.extraction_request_id = extraction_request_id
                existing.updated_at = now
                await existing.save()
            return existing

        # If force refreshing, revoke old active tokens for this student scope to avoid duplicate active links
        if force_refresh and existing:
            active_tokens = await VerificationToken.find(query).to_list()
            for old_t in active_tokens:
                old_t.status = VerificationTokenStatus.REVOKED.value
                await old_t.save()

        # Resolve student name & batch name if not provided
        if not student_name:
            sub = await StudentSubmission.find_one(
                StudentSubmission.batch_id == batch_id,
                StudentSubmission.register_number == student_id,
            )
            if sub:
                student_name = sub.student_name
                class_id = class_id or sub.class_id
            else:
                student_name = student_id

        if not batch_name:
            batch = await AdmissionBatch.get(batch_id)
            if batch:
                batch_name = batch.name
                department_id = department_id or batch.department_id

        token_doc = VerificationToken(
            student_id=student_id,
            student_name=student_name or student_id,
            batch_id=batch_id,
            batch_name=batch_name,
            class_id=class_id,
            department_id=department_id,
            extraction_request_id=extraction_request_id,
            submission_id=submission_id,
            status=VerificationTokenStatus.ACTIVE.value,
            expires_at=now + timedelta(days=expires_in_days),
            created_at=now,
            updated_at=now,
        )
        await token_doc.insert()
        logger.info(
            f"[VerificationToken] Created verification token for student '{student_id}' in batch '{batch_id}' "
            f"(extraction: {extraction_request_id}, expires: {token_doc.expires_at})"
        )
        return token_doc

    async def validate_token(self, token_str: str) -> VerificationToken:
        """
        Validate token existence, active status, and expiry.
        Raises 404, 403, or 410 if invalid.
        """
        if not token_str or not token_str.strip():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid verification token.",
            )

        token_doc = await VerificationToken.find_one(
            VerificationToken.token == token_str.strip()
        )
        if not token_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid or unrecognized verification token.",
            )

        if token_doc.status == VerificationTokenStatus.REVOKED.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This verification link has been revoked by admissions staff.",
            )

        now = datetime.now(timezone.utc)
        exp = (
            token_doc.expires_at.replace(tzinfo=timezone.utc)
            if token_doc.expires_at.tzinfo is None
            else token_doc.expires_at
        )
        if token_doc.status == VerificationTokenStatus.EXPIRED.value or exp <= now:
            if token_doc.status != VerificationTokenStatus.EXPIRED.value:
                token_doc.status = VerificationTokenStatus.EXPIRED.value
                await token_doc.save()
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This verification link has expired. Please contact your admissions office for a fresh link.",
            )

        token_doc.last_accessed_at = now
        await token_doc.save()
        return token_doc

    async def revoke_token(self, token_str: str) -> VerificationToken:
        """Revoke a verification token."""
        token_doc = await VerificationToken.find_one(
            VerificationToken.token == token_str.strip()
        )
        if not token_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Verification token not found.",
            )
        token_doc.status = VerificationTokenStatus.REVOKED.value
        await token_doc.save()
        return token_doc

    async def get_session_info(self, token_str: str) -> PublicVerificationSessionResponse:
        """
        Public endpoint: Retrieve public metadata about a verification session token.
        Does NOT expose student name, student register number, or extraction records.
        """
        token_doc = await self.validate_token(token_str)
        token_doc = await self.refresh_or_resolve_token_extraction(token_doc)
        return PublicVerificationSessionResponse(
            valid=True,
            token=token_doc.token,
            status=token_doc.status,
            batch_name=token_doc.batch_name,
            department_id=token_doc.department_id,
            expires_at=token_doc.expires_at,
            is_completed=(token_doc.status == VerificationTokenStatus.COMPLETED.value),
            requires_identity_verification=True,
            extraction_request_id=token_doc.extraction_request_id,
        )

    async def validate_student_identity(
        self, token_str: str, student_name: str, register_number: str
    ) -> PublicVerificationTokenResponse:
        """
        Validate student credentials against the exact token record with:
        - Rate limiting & brute force attempt thresholds (5 failed attempts per 15 mins).
        - Whitespace and case-insensitive normalization.
        - Strict cross-student isolation.
        """
        token_doc = await self.validate_token(token_str)
        token_doc = await self.refresh_or_resolve_token_extraction(token_doc)
        now_ts = time.time()
        window_seconds = 900  # 15 minutes
        max_failures = 5

        async with self._failed_lock:
            failures = [
                t for t in self._failed_attempts.get(token_doc.token, [])
                if t > (now_ts - window_seconds)
            ]
            self._failed_attempts[token_doc.token] = failures
            if len(failures) >= max_failures:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many failed verification attempts. Please wait 15 minutes before trying again or contact admissions staff.",
                )

        input_name = re.sub(r"\s+", " ", (student_name or "").strip()).lower()
        input_reg = re.sub(r"\s+", " ", (register_number or "").strip()).lower()

        if not input_name or not input_reg:
            async with self._failed_lock:
                self._failed_attempts[token_doc.token].append(now_ts)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both student name and register number are required for verification.",
            )

        # Expected normalized name candidates
        expected_names = {re.sub(r"\s+", " ", (token_doc.student_name or "").strip()).lower()}
        # Expected normalized register number candidates
        expected_regs = {re.sub(r"\s+", " ", (token_doc.student_id or "").strip()).lower()}

        if token_doc.batch_id:
            sub = await StudentSubmission.find_one(
                StudentSubmission.batch_id == token_doc.batch_id,
                {"$or": [
                    {"register_number": token_doc.student_id},
                    {"student_name": token_doc.student_name},
                ]}
            )
            if sub:
                if sub.student_name:
                    expected_names.add(re.sub(r"\s+", " ", sub.student_name.strip()).lower())
                if sub.register_number:
                    expected_regs.add(re.sub(r"\s+", " ", sub.register_number.strip()).lower())

        name_match = (input_name in expected_names)
        reg_match = (input_reg in expected_regs)

        if not name_match or not reg_match:
            async with self._failed_lock:
                self._failed_attempts[token_doc.token].append(now_ts)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Student name or register number does not match this verification link. Please verify your details.",
            )

        # Success - reset failure counter and mark session verified
        async with self._failed_lock:
            self._failed_attempts.pop(token_doc.token, None)

        token_doc.is_verified = True
        await token_doc.save()

        return await self.get_public_verification_data(token_str)

    async def get_public_verification_data(
        self, token_str: str
    ) -> PublicVerificationTokenResponse:
        """
        Fetch verification records strictly scoped to the student and extraction/batch
        associated with this verification token.
        Reuses existing extraction result records and canonical field mappings:
        - Resolves actual extracted values from DocumentExtractionResult and StudentSubmission.
        - Never substitutes NOT_AVAILABLE when a valid stored value exists.
        - Distinguishes NOT FOUND, DOCUMENT MISSING, and EXTRACTION FAILED.
        - Enforces strict cross-student isolation.
        """
        from app.services.document_extraction_service import resolve_canonical_field_key

        token_doc = await self.validate_token(token_str)
        token_doc = await self.refresh_or_resolve_token_extraction(token_doc)

        # Issue 3: Common session tokens require completed verification before exposing extraction data
        if token_doc.verification_code and not token_doc.is_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Verification code required: Please enter and verify the 6-digit code to access extraction data.",
            )

        clean_reg = (token_doc.student_id or "").strip().upper()
        sub_id = str(token_doc.submission_id).strip() if token_doc.submission_id else None

        # Build comprehensive student identifier match clauses (case-insensitive & aliases)
        student_id_matches = [
            {"student_id": clean_reg},
            {"student_id": token_doc.student_id},
            {"student_id": token_doc.student_id.lower()},
            {"student_id": token_doc.student_id.strip()},
        ]
        if sub_id:
            student_id_matches.append({"student_submission_id": sub_id})

        base_student_query = {"$or": student_id_matches}
        target_ext_id = token_doc.extraction_request_id

        # Query existing DocumentFieldVerification records
        raw_records = []
        if target_ext_id:
            raw_records = await DocumentFieldVerification.find(
                base_student_query,
                DocumentFieldVerification.extraction_request_id == target_ext_id,
            ).sort("-created_at").to_list()

        # ONLY fallback to batch-wide query if no target_ext_id was specified
        if not raw_records and not target_ext_id and token_doc.batch_id:
            raw_records = await DocumentFieldVerification.find(
                base_student_query,
                DocumentFieldVerification.batch_id == token_doc.batch_id,
            ).sort("-created_at").to_list()

        if not raw_records and not target_ext_id:
            raw_records = await DocumentFieldVerification.find(base_student_query).sort("-created_at").to_list()

        # Deterministic field deduplication by canonical key
        deduped_records_map: Dict[str, DocumentFieldVerification] = {}
        for r in raw_records:
            canon_k = resolve_canonical_field_key(r.field_name) or r.field_name.strip().lower().replace(" ", "_")
            if canon_k not in deduped_records_map:
                deduped_records_map[canon_k] = r
            else:
                existing_r = deduped_records_map[canon_k]
                def _score(item: DocumentFieldVerification) -> Tuple[int, float, int, int]:
                    ext_match = 1 if (target_ext_id and item.extraction_request_id == target_ext_id) else 0
                    ts = (item.updated_at or item.created_at or datetime.min.replace(tzinfo=timezone.utc)).timestamp()
                    verif_pri = 2 if item.status in (
                        VerificationFieldStatus.STUDENT_VERIFIED,
                        VerificationFieldStatus.STUDENT_CONFIRMED,
                        VerificationFieldStatus.STAFF_APPROVED,
                    ) else (1 if item.status == VerificationFieldStatus.CORRECTION_REQUESTED else 0)
                    has_val = 1 if item.final_value or item.student_value or (item.ai_value and item.ai_value not in ("NOT_AVAILABLE", "NOT_FOUND")) else 0
                    return (ext_match, ts, verif_pri, has_val)

                if _score(r) > _score(existing_r):
                    deduped_records_map[canon_k] = r

        records = list(deduped_records_map.values())

        # Load Student Documents to locate underlying DocumentExtractionResults
        stud_doc_query = [{"student_id": clean_reg}, {"student_id": token_doc.student_id}]
        if sub_id:
            stud_doc_query.append({"submission_id": sub_id})
        stud_docs = await StudentDocument.find({"$or": stud_doc_query}).to_list()
        doc_ids = [str(d.id) for d in stud_docs]
        doc_meta_map = {str(d.id): (d.document_name, d.document_type) for d in stud_docs}

        # Load DocumentExtractionResult records strictly for this extraction if target_ext_id is specified
        ext_results = []
        if target_ext_id:
            ext_results = await DocumentExtractionResult.find({
                "extraction_request_id": target_ext_id,
            }).to_list()
            if doc_ids:
                ext_results = [er for er in ext_results if er.student_document_id in doc_ids]
        elif doc_ids:
            ext_results = await DocumentExtractionResult.find({
                "student_document_id": {"$in": doc_ids}
            }).to_list()

        # Load StudentSubmission for this student
        sub_rec = None
        if sub_id:
            try:
                sub_rec = await StudentSubmission.get(PydanticObjectId(sub_id) if len(sub_id) == 24 else sub_id)
            except Exception:
                sub_rec = None
        if not sub_rec and token_doc.batch_id:
            sub_rec = await StudentSubmission.find_one(
                StudentSubmission.batch_id == token_doc.batch_id,
                {"$or": [{"register_number": clean_reg}, {"register_number": token_doc.student_id}]},
            )
        if not sub_rec:
            sub_rec = await StudentSubmission.find_one(
                {"$or": [{"register_number": clean_reg}, {"register_number": token_doc.student_id}]},
            )

        # Build stored canonical value pool from all valid student extraction sources
        stored_extracted_pool: Dict[str, Tuple[Any, Optional[str], Optional[str]]] = {}

        # 1. From DocumentExtractionResults
        for er in ext_results:
            d_name, d_type = doc_meta_map.get(er.student_document_id, (None, None))
            meta_type = (er.pipeline_metadata or {}).get("document_type") if hasattr(er, "pipeline_metadata") else None
            for k, v in (er.extracted_data or {}).items():
                if v not in (None, "", "NOT_AVAILABLE", "NOT_FOUND"):
                    canon_k = resolve_canonical_field_key(k) or k.strip().lower().replace(" ", "_")
                    if canon_k not in stored_extracted_pool:
                        stored_extracted_pool[canon_k] = (v, d_name, d_type or meta_type)

        # 2. From StudentSubmission.extracted_data (only when target_ext_id is not specified)
        if sub_rec and sub_rec.extracted_data and not target_ext_id:
            for k, v in sub_rec.extracted_data.items():
                if v not in (None, "", "NOT_AVAILABLE", "NOT_FOUND"):
                    canon_k = resolve_canonical_field_key(k) or k.strip().lower().replace(" ", "_")
                    if canon_k not in stored_extracted_pool:
                        stored_extracted_pool[canon_k] = (v, "Student Application", "SUBMISSION")

        # 3. From Student Profile data
        if sub_rec:
            if sub_rec.student_name and "student_name" not in stored_extracted_pool:
                stored_extracted_pool["student_name"] = (sub_rec.student_name, "Student Profile", "STUDENT_PROFILE")
            if sub_rec.register_number and "register_number" not in stored_extracted_pool:
                stored_extracted_pool["register_number"] = (sub_rec.register_number, "Student Profile", "STUDENT_PROFILE")
            if sub_rec.email and "email" not in stored_extracted_pool:
                stored_extracted_pool["email"] = (sub_rec.email, "Student Profile", "STUDENT_PROFILE")
            if sub_rec.mobile_number and "mobile_number" not in stored_extracted_pool:
                stored_extracted_pool["mobile_number"] = (sub_rec.mobile_number, "Student Profile", "STUDENT_PROFILE")

        # 4. From Batch / Admission Profile data
        batch_obj = None
        if token_doc.batch_id:
            try:
                from app.models.batch import Batch
                batch_obj = await Batch.get(token_doc.batch_id)
            except Exception:
                batch_obj = None

        if batch_obj and getattr(batch_obj, "academic_year", None):
            for ay_key in ["academic_year_of_joining", "academic_year", "year_of_joining"]:
                if ay_key not in stored_extracted_pool:
                    stored_extracted_pool[ay_key] = (batch_obj.academic_year, "Batch / Admission Profile", "STUDENT_PROFILE")

        # If no verification records exist yet, auto-initialize from stored extraction pool
        if not records and stored_extracted_pool:
            now = datetime.now(timezone.utc)
            first_doc = stud_docs[0] if stud_docs else None
            created_recs = []
            for canon_k, (val, d_name, d_type) in stored_extracted_pool.items():
                rec = DocumentFieldVerification(
                    extraction_result_id=f"ext_{token_doc.token[:8]}_{canon_k}",
                    extraction_request_id=token_doc.extraction_request_id,
                    student_id=clean_reg,
                    student_submission_id=sub_id or (str(sub_rec.id) if sub_rec else None),
                    document_id=str(first_doc.id) if first_doc else "stored",
                    document_version_id=first_doc.active_version.version_id if (first_doc and first_doc.active_version) else "v1",
                    source_document_name=d_name,
                    department_id=token_doc.department_id,
                    batch_id=token_doc.batch_id,
                    class_id=token_doc.class_id,
                    document_type=d_type or "OTHER",
                    field_name=canon_k,
                    ai_value=val,
                    raw_value=val,
                    student_value=None,
                    final_value=val,
                    status=VerificationFieldStatus.AI_EXTRACTED,
                    field_state="EXTRACTED",
                    confidence="HIGH",
                    created_at=now,
                    updated_at=now,
                )
                await rec.insert()
                created_recs.append(rec)
            records = created_recs

        # Reconcile existing records against stored extraction pool
        for r in records:
            canon_name = resolve_canonical_field_key(r.field_name) or r.field_name.strip().lower().replace(" ", "_")
            is_academic_year = any(k in canon_name for k in ["academic_year", "year_of_joining", "academic year", "joining"])

            # Heal misconfigured source routing for academic year (must never blame AADHAAR)
            if is_academic_year and r.document_type == "AADHAAR":
                r.document_type = "STUDENT_PROFILE"
                if r.source_document_name == "Aadhaar" or not r.source_document_name:
                    r.source_document_name = "Student Profile"
                if r.field_state in ("DOCUMENT_MISSING", "SOURCE_DOCUMENT_MISSING") and ("AADHAAR" in (r.reason or "").upper() or not r.reason):
                    if canon_name in stored_extracted_pool:
                        val, s_name, s_type = stored_extracted_pool[canon_name]
                        r.ai_value = val
                        r.raw_value = val
                        r.field_state = "EXTRACTED"
                        r.source_document_name = s_name or "Student Profile"
                        r.document_type = s_type or "STUDENT_PROFILE"
                        r.reason = None
                    else:
                        r.field_state = "NOT_FOUND"
                        r.reason = "Academic year of joining not found in student admission records or documents"
                await r.save()

            # If already verified/confirmed by student or staff, preserve student/staff final state and original AI values
            if r.status in (VerificationFieldStatus.STUDENT_VERIFIED, VerificationFieldStatus.STUDENT_CONFIRMED, VerificationFieldStatus.STAFF_APPROVED) or r.field_state == "MANUALLY_ENTERED":
                continue

            needs_recovery = r.ai_value in (None, "", "NOT_AVAILABLE", "NOT_FOUND")
            if needs_recovery:
                is_profile_field = canon_name in (
                    "student_name", "register_number", "email", "mobile_number",
                    "academic_year", "academic_year_of_joining", "year_of_joining"
                )
                if is_profile_field and canon_name in stored_extracted_pool:
                    recovered_val, rec_doc_name, rec_doc_type = stored_extracted_pool[canon_name]
                    r.ai_value = recovered_val
                    if r.raw_value in (None, "", "NOT_AVAILABLE", "NOT_FOUND"):
                        r.raw_value = recovered_val
                    r.field_state = "EXTRACTED"
                    if rec_doc_name and not r.source_document_name:
                        r.source_document_name = rec_doc_name
                    if rec_doc_type and (not r.document_type or r.document_type in ("UNKNOWN", "OTHER", "AADHAAR" if is_academic_year else "")):
                        r.document_type = rec_doc_type
                    await r.save()
                elif not is_profile_field and target_ext_id and canon_name in stored_extracted_pool:
                    recovered_val, rec_doc_name, rec_doc_type = stored_extracted_pool[canon_name]
                    r.ai_value = recovered_val
                    if r.raw_value in (None, "", "NOT_AVAILABLE", "NOT_FOUND"):
                        r.raw_value = recovered_val
                    r.field_state = "EXTRACTED"
                    if rec_doc_name and not r.source_document_name:
                        r.source_document_name = rec_doc_name
                    if rec_doc_type and (not r.document_type or r.document_type in ("UNKNOWN", "OTHER")):
                        r.document_type = rec_doc_type
                    await r.save()
                else:
                    # Genuinely has no value: Never leave literal NOT_AVAILABLE as the value
                    r.ai_value = None
                    if r.raw_value in ("NOT_AVAILABLE", "NOT_FOUND"):
                        r.raw_value = None
                    if not r.field_state or r.field_state in ("EXTRACTED", "HIGH_CONFIDENCE"):
                        r.field_state = "NOT_FOUND"
                    await r.save()
            else:
                # Valid value exists: ensure source document is populated if missing
                if not r.source_document_name and canon_name in stored_extracted_pool:
                    _, rec_doc_name, _ = stored_extracted_pool[canon_name]
                    if rec_doc_name:
                        r.source_document_name = rec_doc_name
                        await r.save()

        extracted_at = None
        if token_doc.extraction_request_id:
            try:
                from app.models.batch_extraction import BatchExtractionRequest
                ext_req = await BatchExtractionRequest.find_one(
                    BatchExtractionRequest.extraction_request_id == token_doc.extraction_request_id
                )
                if ext_req:
                    extracted_at = ext_req.completed_at or ext_req.created_at
            except Exception:
                pass
        if not extracted_at and records:
            extracted_at = max(
                (r.updated_at or r.created_at for r in records if (r.updated_at or r.created_at)),
                default=None,
            )

        field_responses = [_to_verification_response(r) for r in records]

        return PublicVerificationTokenResponse(
            valid=True,
            token=token_doc.token,
            student_id=token_doc.student_id,
            student_name=token_doc.student_name,
            batch_id=token_doc.batch_id,
            batch_name=token_doc.batch_name,
            class_id=token_doc.class_id,
            department_id=token_doc.department_id,
            extraction_request_id=token_doc.extraction_request_id,
            extracted_at=extracted_at,
            status=token_doc.status,
            expires_at=token_doc.expires_at,
            fields=field_responses,
        )

    async def submit_public_verification(
        self, token_str: str, submit_req: PublicVerificationSubmitRequest
    ) -> PublicVerificationTokenResponse:
        """
        Public student submission of confirmations & corrections:
        - Strict token scope enforcement (cannot modify other students' fields).
        - AI raw value is NEVER mutated or destroyed.
        - Appends immutable verification history entry with actor role 'STUDENT_PUBLIC'.
        """
        token_doc = await self.validate_token(token_str)
        now = datetime.now(timezone.utc)

        # Idempotent completion protection
        if token_doc.status == VerificationTokenStatus.COMPLETED.value:
            is_idempotent = True
            for item in submit_req.fields:
                rec = await DocumentFieldVerification.get(item.verification_id)
                if not rec or rec.student_id != token_doc.student_id:
                    is_idempotent = False
                    break
                target_val = item.corrected_value if (not item.is_confirmed and item.corrected_value is not None) else rec.ai_value
                existing_final = rec.final_value if rec.final_value is not None else rec.student_value
                if str(target_val or "").strip() != str(existing_final or "").strip():
                    is_idempotent = False
                    break

            if is_idempotent:
                return await self.get_public_verification_data(token_str)
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Verification session is already completed. Unauthorized changes are prevented unless an explicit new verification session is issued.",
                )

        if not submit_req.fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification submission must contain at least one field.",
            )

        # Pre-validate all submitted fields and check security scoping before making any modifications
        validated_items: List[Tuple[DocumentFieldVerification, Any, bool, Optional[str]]] = []
        for item in submit_req.fields:
            rec = None
            try:
                if len(item.verification_id) == 24:
                    rec = await DocumentFieldVerification.get(PydanticObjectId(item.verification_id))
                else:
                    rec = await DocumentFieldVerification.find_one({"_id": item.verification_id})
            except Exception:
                rec = None
            if not rec:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Verification field record '{item.verification_id}' not found.",
                )

            # Strict Security Scope Check
            if rec.student_id != token_doc.student_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: Cannot modify another student's verification records.",
                )
            if token_doc.batch_id and rec.batch_id and rec.batch_id != token_doc.batch_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: Cross-batch modification is not permitted.",
                )

            # If already finalized by staff, retain staff decision
            if rec.status in (VerificationFieldStatus.STAFF_APPROVED, VerificationFieldStatus.STAFF_REJECTED):
                continue

            comment_text = item.comment or submit_req.general_comment

            # Check if student confirmed existing AI value or provided an edit
            is_confirmed = item.is_confirmed or (
                item.corrected_value is not None
                and str(item.corrected_value).strip() == str(rec.ai_value or "").strip()
            )
            validated_items.append((rec, item, is_confirmed, comment_text))

        actor_label = f"Student ({token_doc.student_name})"

        for rec, item, is_confirmed, comment_text in validated_items:

            if is_confirmed:
                rec.status = VerificationFieldStatus.STUDENT_CONFIRMED
                rec.student_value = rec.ai_value
                rec.final_value = rec.ai_value
                rec.student_updated_at = now
                rec.student_comment = comment_text

                rec.history.append(
                    VerificationHistoryEntry(
                        actor=actor_label,
                        actor_role="STUDENT_PUBLIC",
                        action="STUDENT_CONFIRM",
                        old_value=rec.ai_value,
                        new_value=rec.ai_value,
                        comment=comment_text or "Confirmed by student via verification link",
                        document_version_id=rec.document_version_id,
                        timestamp=now,
                    )
                )
            else:
                # Student submitted an edit - directly saved as final verified data without staff approval
                new_val = item.corrected_value
                rec.status = VerificationFieldStatus.STUDENT_VERIFIED
                rec.student_value = new_val
                rec.final_value = new_val
                rec.student_updated_at = now
                rec.student_comment = comment_text
                rec.field_state = "MANUALLY_ENTERED"

                rec.history.append(
                    VerificationHistoryEntry(
                        actor=actor_label,
                        actor_role="STUDENT_PUBLIC",
                        action="STUDENT_EDIT",
                        old_value=rec.ai_value,
                        new_value=new_val,
                        comment=comment_text or "Edited by student via verification link",
                        document_version_id=rec.document_version_id,
                        timestamp=now,
                    )
                )

            if not rec.extraction_request_id and token_doc.extraction_request_id:
                rec.extraction_request_id = token_doc.extraction_request_id
            if not rec.batch_id and token_doc.batch_id:
                rec.batch_id = token_doc.batch_id
            rec.updated_at = now
            await rec.save()

        token_doc.status = VerificationTokenStatus.COMPLETED.value
        token_doc.completed_at = now
        await token_doc.save()

        # Also finalize any remaining unedited AI_EXTRACTED records for this student in this extraction scope
        # so that the entire student extraction is finalized (implicit confirmation of unedited fields)
        try:
            rem_filter: Dict[str, Any] = {
                "student_id": token_doc.student_id,
                "status": VerificationFieldStatus.AI_EXTRACTED.value,
            }
            if token_doc.extraction_request_id:
                rem_filter["extraction_request_id"] = token_doc.extraction_request_id
            elif token_doc.batch_id:
                rem_filter["batch_id"] = token_doc.batch_id

            remaining_records = await DocumentFieldVerification.find(rem_filter).to_list()
            for rem_rec in remaining_records:
                if any(str(rem_rec.id) == str(v_item[0].id) for v_item in validated_items):
                    continue
                rem_rec.status = VerificationFieldStatus.STUDENT_CONFIRMED
                rem_rec.student_value = rem_rec.ai_value
                rem_rec.final_value = rem_rec.ai_value
                rem_rec.student_updated_at = now
                rem_rec.history.append(
                    VerificationHistoryEntry(
                        actor=actor_label,
                        actor_role="STUDENT_PUBLIC",
                        action="STUDENT_CONFIRM",
                        old_value=rem_rec.ai_value,
                        new_value=rem_rec.ai_value,
                        comment="Confirmed by student on verification completion",
                        document_version_id=rem_rec.document_version_id,
                        timestamp=now,
                    )
                )
                rem_rec.updated_at = now
                await rem_rec.save()
        except Exception as rem_err:
            logger.warning(f"[submit_public_verification] Failed to finalize remaining AI_EXTRACTED fields: {rem_err}")

        # Update corresponding StudentSubmission if present
        try:
            sub_rec = None
            if token_doc.submission_id:
                try:
                    sub_obj_id = (
                        PydanticObjectId(token_doc.submission_id)
                        if len(token_doc.submission_id) == 24
                        else token_doc.submission_id
                    )
                    sub_rec = await StudentSubmission.get(sub_obj_id)
                except Exception:
                    sub_rec = await StudentSubmission.get(token_doc.submission_id)
            if not sub_rec:
                clean_student_id = token_doc.student_id.strip() if token_doc.student_id else ""
                batch_filter = {"batch_id": token_doc.batch_id} if token_doc.batch_id else {}
                sub_rec = await StudentSubmission.find_one({
                    **batch_filter,
                    "$or": [
                        {"register_number": clean_student_id},
                        {"register_number": clean_student_id.upper()},
                        {"register_number": clean_student_id.lower()},
                        {"student_name": token_doc.student_name},
                    ],
                })
            if sub_rec:
                sub_rec.submission_status = "Student Verified"
                if sub_rec.extracted_data is None:
                    sub_rec.extracted_data = {}
                for item in submit_req.fields:
                    r_saved = None
                    try:
                        v_id = (
                            PydanticObjectId(item.verification_id)
                            if len(item.verification_id) == 24
                            else item.verification_id
                        )
                        r_saved = await DocumentFieldVerification.get(v_id)
                    except Exception:
                        r_saved = await DocumentFieldVerification.get(item.verification_id)
                    if r_saved and r_saved.final_value is not None:
                        sub_rec.extracted_data[r_saved.field_name] = str(r_saved.final_value)
                        from app.services.document_extraction_service import resolve_canonical_field_key
                        canon_f = resolve_canonical_field_key(r_saved.field_name)
                        if canon_f:
                            sub_rec.extracted_data[canon_f] = str(r_saved.final_value)
                await sub_rec.save()
        except Exception as e:
            logger.warning(f"[submit_public_verification] Failed to update StudentSubmission status: {e}")

        return await self.get_public_verification_data(token_str)

    async def identify_common_student(
        self, req: CommonStudentIdentifyRequest
    ) -> CommonStudentIdentifyResponse:
        """
        Validate student credentials using Common Verification URL:
        - Rate limiting & brute force thresholds (5 failed attempts per 15 mins).
        - Scoped to batch if provided.
        - Safely detects ambiguous/duplicate register numbers across batches and rejects guessing.
        - Validates student full name.
        - Verifies that eligible extraction results exist.
        - Issues short-lived one-time code challenge and session token.
        """
        clean_name = re.sub(r"\s+", " ", (req.student_name or "").strip()).lower()
        clean_reg = re.sub(r"\s+", " ", (req.register_number or "").strip()).upper()

        if not clean_name or not clean_reg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both student name and register number are required for verification.",
            )

        now_ts = time.time()
        window_seconds = 900  # 15 minutes
        max_failures = 5
        rate_key = f"identify:{clean_reg}"

        async with self._failed_lock:
            failures = [
                t for t in self._failed_attempts.get(rate_key, [])
                if t > (now_ts - window_seconds)
            ]
            self._failed_attempts[rate_key] = failures
            if len(failures) >= max_failures:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many failed verification attempts. Please wait 15 minutes before trying again or contact admissions staff.",
                )

        # 1. Search candidate student submissions
        candidate = None
        candidate_batch = None

        if req.batch_id:
            # Explicit batch context provided
            sub_matches = await StudentSubmission.find(
                StudentSubmission.batch_id == req.batch_id,
            ).to_list()
            # Match register number case-insensitively
            matched_subs = [
                s for s in sub_matches
                if s.register_number and s.register_number.strip().upper() == clean_reg
            ]
            if matched_subs:
                candidate = matched_subs[0]
            else:
                # Check DocumentFieldVerification in that batch
                v_matches = await DocumentFieldVerification.find(
                    DocumentFieldVerification.batch_id == req.batch_id,
                ).to_list()
                matched_v = [
                    v for v in v_matches
                    if v.student_id and v.student_id.strip().upper() == clean_reg
                ]
                if not matched_v:
                    async with self._failed_lock:
                        self._failed_attempts[rate_key].append(now_ts)
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="No student record found matching the provided register number in this admission batch.",
                    )
            candidate_batch = await AdmissionBatch.get(req.batch_id)
        else:
            # Batch context not provided in URL: check across all submissions
            all_subs = await StudentSubmission.find().to_list()
            matched_subs = [
                s for s in all_subs
                if s.register_number and s.register_number.strip().upper() == clean_reg
            ]

            matched_verifs = await DocumentFieldVerification.find(
                {"student_id": clean_reg}
            ).to_list()

            distinct_batches = set()
            for s in matched_subs:
                if s.batch_id:
                    distinct_batches.add(s.batch_id)
            for v in matched_verifs:
                if v.batch_id:
                    distinct_batches.add(v.batch_id)

            if len(distinct_batches) > 1:
                # Ambiguous duplicate register number across multiple batches: NEVER GUESS!
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Duplicate register number found across multiple admission batches. Please provide your Admission Batch ID to continue.",
                )
            elif len(distinct_batches) == 0:
                async with self._failed_lock:
                    self._failed_attempts[rate_key].append(now_ts)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="No student record found matching the provided register number.",
                )
            else:
                chosen_batch_id = list(distinct_batches)[0]
                candidate_batch = await AdmissionBatch.get(chosen_batch_id)
                candidate = matched_subs[0] if matched_subs else None

        # 2. Validate Student Full Name
        expected_names = set()
        if candidate and candidate.student_name:
            expected_names.add(re.sub(r"\s+", " ", candidate.student_name.strip()).lower())

        target_batch_id = req.batch_id or (candidate_batch.id if candidate_batch else (candidate.batch_id if candidate else None))

        # Also check verifications for student name / student_id
        verifs = await DocumentFieldVerification.find(
            DocumentFieldVerification.batch_id == target_batch_id,
        ).to_list()
        student_verifs = [
            v for v in verifs
            if (v.student_id and v.student_id.strip().upper() == clean_reg)
            or (candidate and v.student_submission_id == str(candidate.id))
            or (candidate and candidate.register_number and v.student_id and v.student_id.strip().upper() == candidate.register_number.strip().upper())
        ]

        if not student_verifs:
            # Check if DocumentExtractionResult or StudentSubmission.extracted_data exists
            has_sub_data = bool(candidate and candidate.extracted_data)
            docs = await StudentDocument.find({"$or": [{"student_id": clean_reg}, {"submission_id": str(candidate.id) if candidate else "none"}]}).to_list()
            has_doc_data = False
            if docs:
                ext_res = await DocumentExtractionResult.find({"student_document_id": {"$in": [str(d.id) for d in docs]}}).first_or_none()
                has_doc_data = bool(ext_res)

            if not has_sub_data and not has_doc_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No extraction results are ready for verification for this student in this batch.",
                )

        name_match = (clean_name in expected_names)
        if not name_match:
            # Allow matching if names match as exact words or prefix with at least 3 characters to prevent probing
            for en in expected_names:
                if clean_name == en:
                    name_match = True
                    break
                if len(clean_name) >= 3:
                    clean_words = set(clean_name.split())
                    en_words = set(en.split())
                    if en.startswith(clean_name) or clean_name.startswith(en) or (clean_words and clean_words.issubset(en_words)):
                        name_match = True
                        break

        if not name_match:
            async with self._failed_lock:
                self._failed_attempts[rate_key].append(now_ts)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Student name does not match the register number. Please verify your details.",
            )

        # 3. Success on identity: Reset failed attempts
        async with self._failed_lock:
            self._failed_attempts.pop(rate_key, None)

        # 4. Generate 6-digit one-time verification code & session token
        code = f"{secrets.randbelow(900000) + 100000}"
        now = datetime.now(timezone.utc)
        resolved_name = (candidate.student_name if candidate else req.student_name).strip()
        resolved_batch_name = candidate_batch.name if candidate_batch else (candidate.batch_name if candidate else None)

        # Authoritatively resolve the extraction request ID for this student and batch
        ext_req_id = req.extraction_request_id
        latest_req = await self.resolve_latest_successful_batch_extraction(
            batch_id=str(target_batch_id), student_id=clean_reg
        )
        if latest_req:
            if not ext_req_id:
                ext_req_id = latest_req.extraction_request_id
            else:
                supplied_req = await BatchExtractionRequest.find_one(
                    BatchExtractionRequest.extraction_request_id == ext_req_id
                )
                if not supplied_req or supplied_req.status not in SUCCESSFUL_EXTRACTION_STATUSES or latest_req.extraction_request_id != ext_req_id:
                    ext_req_id = latest_req.extraction_request_id
        elif not ext_req_id and student_verifs:
            sorted_verifs = sorted(
                student_verifs,
                key=lambda v: (v.created_at or datetime.min.replace(tzinfo=timezone.utc)),
                reverse=True,
            )
            ext_req_id = sorted_verifs[0].extraction_request_id

        token_doc = VerificationToken(
            student_id=clean_reg,
            student_name=resolved_name,
            batch_id=str(target_batch_id),
            batch_name=resolved_batch_name,
            class_id=candidate.class_id if candidate else None,
            department_id=candidate.department_id if candidate else (candidate_batch.department_id if candidate_batch else None),
            extraction_request_id=ext_req_id,
            submission_id=str(candidate.id) if candidate else None,
            verification_code=None,
            code_attempts=0,
            is_verified=True,
            status=VerificationTokenStatus.ACTIVE.value,
            expires_at=now + timedelta(minutes=30),
            last_code_sent_at=None,
            resend_count=0,
            created_at=now,
            updated_at=now,
        )
        await token_doc.insert()

        return CommonStudentIdentifyResponse(
            session_token=token_doc.token,
            requires_code=False,
            contact_hint=None,
            dev_code=None,
            batch_name=resolved_batch_name,
            expires_at=token_doc.expires_at,
        )

    async def _deliver_otp(
        self,
        student_name: str,
        code: str,
        candidate: Optional[StudentSubmission] = None,
        candidate_email: Optional[str] = None,
        candidate_mobile: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        """
        Deliver 6-digit OTP to configured student contact channels (email or SMS).
        Gracefully resolves recipient from submission profile, extracted metadata, or parameters.
        Returns (contact_hint, delivered_channel).
        """
        email = (candidate_email or "").strip()
        mobile = (candidate_mobile or "").strip()

        if candidate:
            if not email and candidate.email and "@" in candidate.email:
                email = candidate.email.strip()
            if not mobile and candidate.mobile_number:
                mobile = candidate.mobile_number.strip()
            if not email and candidate.extracted_data:
                for k, v in candidate.extracted_data.items():
                    if "email" in k.lower() and v and "@" in str(v):
                        email = str(v).strip()
                        break
            if not mobile and candidate.extracted_data:
                for k, v in candidate.extracted_data.items():
                    if any(term in k.lower() for term in ["mobile", "phone", "contact"]) and v:
                        digits = re.sub(r"\D", "", str(v))
                        if len(digits) >= 10:
                            mobile = str(v).strip()
                            break

        delivered_channel = None
        contact_hint = None

        try:
            from app.services.notification import get_notification_provider
            from app.models.verification_notification import NotificationChannel

            if email and "@" in email:
                provider = get_notification_provider(NotificationChannel.EMAIL)
                if not provider.is_configured():
                    provider = get_notification_provider(NotificationChannel.EMAIL, force_mock=True)
                await provider.send(
                    recipient=email,
                    subject="Your AdmiExtract Verification Code",
                    message=f"Hello {student_name},\n\nYour 6-digit verification code is: {code}\n\nThis code expires in 30 minutes.",
                )
                delivered_channel = "EMAIL"
                parts = email.split("@")
                u = parts[0]
                masked_u = (u[0] + "***" + u[-1]) if len(u) > 2 else (u[0] + "***")
                contact_hint = f"Verification code sent to {masked_u}@{parts[1]}"
            elif mobile:
                provider = get_notification_provider(NotificationChannel.SMS)
                if not provider.is_configured():
                    provider = get_notification_provider(NotificationChannel.SMS, force_mock=True)
                await provider.send(
                    recipient=mobile,
                    subject="AdmiExtract Verification Code",
                    message=f"Your AdmiExtract verification code is {code}. Valid for 30 mins.",
                )
                delivered_channel = "SMS"
                masked_m = ("*" * max(0, len(mobile) - 4)) + mobile[-4:] if len(mobile) >= 4 else mobile
                contact_hint = f"Verification code sent to {masked_m}"
            else:
                contact_hint = "Enter the 6-digit verification code"
        except Exception as notify_err:
            logger.warning(f"[deliver_otp] Notification delivery error: {notify_err}")
            contact_hint = "Enter the 6-digit verification code"

        return contact_hint or "Enter the 6-digit verification code", delivered_channel

    async def resend_common_code(
        self, req: CommonStudentResendCodeRequest
    ) -> CommonStudentResendCodeResponse:
        """
        Public endpoint: Resend a fresh 6-digit one-time code for an active student verification session.
        Enforces:
        - 30-second cooldown between requests.
        - Max 5 code requests per session.
        - Generates fresh secure 6-digit code, invalidating previous code.
        - Delivers code to student's verified contact channel.
        """
        token_doc = await self.validate_token(req.session_token)

        if token_doc.status == VerificationTokenStatus.COMPLETED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification session is already completed.",
            )

        COOLDOWN_SECONDS = 30
        MAX_RESENDS = 5
        now = datetime.now(timezone.utc)

        if token_doc.last_code_sent_at:
            last_sent = (
                token_doc.last_code_sent_at.replace(tzinfo=timezone.utc)
                if token_doc.last_code_sent_at.tzinfo is None
                else token_doc.last_code_sent_at
            )
            elapsed = (now - last_sent).total_seconds()
            if elapsed < COOLDOWN_SECONDS:
                remaining = int(COOLDOWN_SECONDS - elapsed)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Please wait {remaining} seconds before requesting a new verification code.",
                )

        if getattr(token_doc, "resend_count", 0) >= MAX_RESENDS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Maximum verification code requests exceeded for this session. Please contact admissions staff or start over.",
            )

        # Generate fresh 6-digit code
        new_code = f"{secrets.randbelow(900000) + 100000}"
        token_doc.verification_code = new_code
        token_doc.code_attempts = 0
        token_doc.is_verified = False
        token_doc.resend_count = getattr(token_doc, "resend_count", 0) + 1
        token_doc.last_code_sent_at = now
        token_doc.expires_at = now + timedelta(minutes=30)
        await token_doc.save()

        # Locate candidate for delivery
        candidate = None
        if token_doc.submission_id:
            try:
                candidate = await StudentSubmission.get(
                    PydanticObjectId(token_doc.submission_id)
                    if len(token_doc.submission_id) == 24
                    else token_doc.submission_id
                )
            except Exception:
                candidate = None
        if not candidate and token_doc.batch_id:
            candidate = await StudentSubmission.find_one(
                StudentSubmission.batch_id == token_doc.batch_id,
                {"$or": [{"register_number": token_doc.student_id}, {"student_name": token_doc.student_name}]},
            )

        contact_hint, _ = await self._deliver_otp(token_doc.student_name, new_code, candidate)

        # Only expose dev_code in development/testing environments, NEVER in production or staging
        is_dev = settings.APP_ENV in ("development", "testing") and not bool(os.getenv("RENDER"))

        return CommonStudentResendCodeResponse(
            success=True,
            message="A fresh verification code has been dispatched.",
            contact_hint=contact_hint,
            dev_code=new_code if is_dev else None,
            expires_at=token_doc.expires_at,
            cooldown_seconds=COOLDOWN_SECONDS,
        )

    async def verify_common_code(
        self, req: CommonStudentVerifyCodeRequest
    ) -> PublicVerificationTokenResponse:
        """
        Validate 6-digit one-time code for common student verification session.
        Enforces expiry, max attempt limits, and single-use protection against code reuse.
        Returns only the matched student's extraction records upon success.
        """
        token_doc = await self.validate_token(req.session_token)
        token_doc = await self.refresh_or_resolve_token_extraction(token_doc)

        # Return if already verified
        if token_doc.is_verified:
            return await self.get_public_verification_data(token_doc.token)

        now = datetime.now(timezone.utc)
        if token_doc.expires_at:
            exp = (
                token_doc.expires_at.replace(tzinfo=timezone.utc)
                if token_doc.expires_at.tzinfo is None
                else token_doc.expires_at
            )
            if exp <= now:
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail="Verification code has expired. Please request a new verification code.",
                )

        if token_doc.code_attempts >= 3:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many invalid code attempts. Please request a new verification session or resend code.",
            )

        if not token_doc.verification_code or token_doc.verification_code.strip() != req.code.strip():
            token_doc.code_attempts += 1
            await token_doc.save()
            remaining = max(0, 3 - token_doc.code_attempts)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid verification code. {remaining} attempt(s) remaining.",
            )

        # Successfully verified: consume code to protect against reuse
        token_doc.is_verified = True
        token_doc.verification_code = None
        token_doc.code_attempts = 0
        await token_doc.save()

        return await self.get_public_verification_data(token_doc.token)

    async def submit_common_verification(
        self, req: CommonStudentSubmitRequest
    ) -> PublicVerificationTokenResponse:
        """
        Submit student confirmations and corrections via common verification session.
        Enforces one-time code verification check and completion protection.
        """
        token_doc = await self.validate_token(req.session_token)

        if not token_doc.is_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session code has not been verified.",
            )

        return await self.submit_public_verification(
            token_str=req.session_token,
            submit_req=PublicVerificationSubmitRequest(
                fields=req.fields,
                general_comment=req.general_comment,
            ),
        )
