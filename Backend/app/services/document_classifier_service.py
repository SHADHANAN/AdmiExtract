"""
Intelligent Hybrid Document Classification Engine
==================================================

Production-grade AI Document Classification & Validation Service.

Features:
1. Multimodal AI Classification (Gemini Vision) using original PDF / Image bytes.
2. Deep Semantic & Structural Pattern Classifier (OCR + Document Layout).
3. Document-Specific Evidence Generation (Issuing Authority, ID Patterns, Layout).
4. Configured Requirement vs Detected Type Validation (Expected vs Actual).
5. Strict anti-misclassification heuristics (e.g. TC containing "Refer Community Certificate").
6. Sensitive PII masking in diagnostic logs.
"""

import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.config import settings
from app.services.field_source_rules import resolve_canonical_document_type, DOCUMENT_TYPE_ALIASES
from app.utils.logger_masking import mask_sensitive_text

logger = logging.getLogger("app.services.document_classifier_service")


def _safe_log(msg: str) -> None:
    """Dev-mode stdout logger with PII masking and Unicode fallback."""
    masked = mask_sensitive_text(msg)
    if getattr(settings, "APP_ENV", "development") == "development":
        try:
            print(masked, flush=True)
        except UnicodeEncodeError:
            try:
                print(masked.encode("ascii", errors="replace").decode("ascii"), flush=True)
            except Exception:
                pass


# Canonical Document Type Definitions
SUPPORTED_DOCUMENT_TYPES = [
    "AADHAAR",
    "COMMUNITY_CERTIFICATE",
    "INCOME_CERTIFICATE",
    "NATIVITY_CERTIFICATE",
    "SSLC",
    "HSC",
    "TRANSFER_CERTIFICATE",
    "BANK_PASSBOOK",
    "BIRTH_CERTIFICATE",
    "ALLOTMENT_ORDER",
    "BONAFIDE",
]

DOCUMENT_TYPE_ALIASES: Dict[str, List[str]] = {
    "AADHAAR": ["aadhaar", "aadhar", "uidai"],
    "BANK_PASSBOOK": ["passbook", "bank", "bank_passbook"],
    "TRANSFER_CERTIFICATE": ["transfer", "transfer_certificate", "tc"],
    "COMMUNITY_CERTIFICATE": ["community", "community_certificate", "caste"],
    "INCOME_CERTIFICATE": ["income", "income_certificate"],
    "NATIVITY_CERTIFICATE": ["nativity", "nativity_certificate", "residence"],
    "SSLC": ["sslc", "10th", "tenth", "sslc_marksheet"],
    "HSC": ["hsc", "12th", "twelfth", "plus two", "hsc_marksheet"],
    "BIRTH_CERTIFICATE": ["birth", "birth_certificate"],
    "BONAFIDE": ["bonafide", "bonafide_certificate"],
    "ALLOTMENT_ORDER": ["allotment", "allotment_order"],
}


class DocumentClassifierService:
    """
    Unified AI & Structural Document Classifier.
    """

    def __init__(self):
        self.version = "v2.0-ai-hybrid"

    def classify(
        self,
        ocr_text: str = "",
        filename: str = "",
        file_bytes: Optional[bytes] = None,
        file_path: Optional[str] = None,
        mime_type: Optional[str] = None,
        expected_document_type: Optional[str] = None,
        allowed_document_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Classifies a document using multimodal AI (primary) and deep structural OCR semantics (fallback).
        Validates Expected vs Actual document types and returns structured confidence & evidence.
        """
        canon_expected = resolve_canonical_document_type(expected_document_type) if expected_document_type else None
        canon_allowed = [resolve_canonical_document_type(t) for t in (allowed_document_types or SUPPORTED_DOCUMENT_TYPES)]

        # Read file bytes if file_path given but bytes not provided
        if not file_bytes and file_path and os.path.isfile(file_path):
            try:
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
            except Exception as e:
                logger.warning(f"[DocumentClassifier] Could not read file at {file_path}: {e}")

        # Resolve MIME type
        if not mime_type and filename:
            ext = Path(filename).suffix.lower()
            mime_type = "application/pdf" if ext == ".pdf" else "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"
        elif not mime_type:
            mime_type = "application/pdf"

        # Strategy 1: Multimodal Vision AI Classification (Gemini)
        multimodal_result = None
        if file_bytes and len(file_bytes) > 0:
            try:
                from app.services.gemini_service import GeminiService
                gemini = GeminiService()
                if gemini.is_available():
                    multimodal_result = gemini.classify_document(
                        file_bytes=file_bytes,
                        mime_type=mime_type,
                        filename=filename,
                        allowed_document_types=canon_allowed,
                    )
            except Exception as e:
                logger.warning(f"[DocumentClassifier] Multimodal AI exception: {e}")

        # Strategy 2: Deep Semantic & Structural Classification on OCR Text
        structural_result = self._classify_by_structure_and_ocr(
            ocr_text=ocr_text,
            filename=filename,
            allowed_types=canon_allowed,
        )

        # Merge & Decide Final Classification
        final_doc_type = "UNKNOWN"
        final_confidence = 0.0
        final_evidence = []

        if multimodal_result and multimodal_result.get("success") and multimodal_result.get("document_type") != "UNKNOWN":
            mm_type = resolve_canonical_document_type(multimodal_result["document_type"])
            mm_conf = float(multimodal_result.get("confidence", 0.90))
            mm_ev = multimodal_result.get("evidence", [])

            # Cross-validate with structural signals if available
            struct_type = structural_result.get("document_type")
            struct_conf = float(structural_result.get("confidence", 0.0))

            if struct_type and struct_type != "UNKNOWN" and struct_type == mm_type:
                # Strong multi-modal agreement
                final_doc_type = mm_type
                final_confidence = min(1.0, max(mm_conf, struct_conf) + 0.05)
                final_evidence = list(dict.fromkeys(mm_ev + structural_result.get("evidence", [])))
            else:
                final_doc_type = mm_type
                final_confidence = mm_conf
                final_evidence = mm_ev
        elif structural_result.get("document_type") != "UNKNOWN":
            final_doc_type = structural_result["document_type"]
            final_confidence = structural_result["confidence"]
            final_evidence = structural_result["evidence"]
        else:
            # Low confidence / unrecognized
            final_doc_type = "UNKNOWN"
            final_confidence = max(
                structural_result.get("confidence", 0.0),
                multimodal_result.get("confidence", 0.0) if multimodal_result else 0.0
            )
            final_evidence = structural_result.get("evidence", []) or ["Unrecognized document structure or insufficient text"]

        # Final Document Type Canonicalization
        final_doc_type = resolve_canonical_document_type(final_doc_type)

        # Expected vs Actual Validation Evaluation
        validation_status, validation_reason = self.evaluate_validation_status(
            expected_type=canon_expected,
            detected_type=final_doc_type,
            confidence=final_confidence,
        )

        result = {
            "success": final_doc_type != "UNKNOWN" or bool(canon_expected),
            "expected_document_type": canon_expected,
            "detected_document_type": final_doc_type,
            "document_type": final_doc_type,  # Backwards compatibility
            "confidence": round(final_confidence, 3),
            "evidence": final_evidence,
            "validation_status": validation_status,
            "validation_reason": validation_reason,
            "classifier_version": self.version,
            "classified_at": datetime.now(timezone.utc),
        }

        _safe_log(
            f"[Classification] File='{filename}' | Expected='{canon_expected}' | Detected='{final_doc_type}' | "
            f"Confidence={result['confidence']:.2f} | Status='{validation_status}'"
        )
        return result

    def evaluate_validation_status(
        self,
        expected_type: Optional[str],
        detected_type: str,
        confidence: float,
    ) -> Tuple[str, Optional[str]]:
        """
        Evaluate expected vs detected validation status.
        Returns (validation_status, validation_reason).
        """
        canon_expected = resolve_canonical_document_type(expected_type) if expected_type else None
        canon_detected = resolve_canonical_document_type(detected_type)

        if not canon_expected:
            if canon_detected == "UNKNOWN" or confidence < 0.60:
                return "NEEDS_REVIEW", "Unrecognized document type or low confidence."
            return "VALID", f"Classified as {canon_detected} with confidence {confidence:.0%}."

        if canon_detected == "UNKNOWN" or confidence < 0.60:
            return "NEEDS_REVIEW", f"Expected {canon_expected}, but document could not be confidently identified (confidence: {confidence:.0%})."

        if canon_expected == canon_detected:
            return "VALID", f"Document matches expected requirement '{canon_expected}' (confidence: {confidence:.0%})."

        # Explicit Mismatch
        return "WRONG_DOCUMENT", f"Expected requirement '{canon_expected}', but uploaded document is '{canon_detected}' (confidence: {confidence:.0%})."

    def _classify_by_structure_and_ocr(
        self,
        ocr_text: str,
        filename: str,
        allowed_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Deep structural and semantic rule-based classifier using evidence scoring.
        """
        text = (ocr_text or "").lower()
        fn = (filename or "").lower()

        scores: Dict[str, float] = {}
        evidences: Dict[str, List[str]] = {}

        for dt in SUPPORTED_DOCUMENT_TYPES:
            scores[dt] = 0.0
            evidences[dt] = []

        # ---------------------------------------------------------------------
        # 1. AADHAAR CARD
        # ---------------------------------------------------------------------
        aadhaar_strong_kw = [
            "unique identification authority of india",
            "uidai",
            "mera aadhaar meri pehchan",
            "bharat vishishta pehchan pradhikaran",
            "ஆதார்",
            "help@uidai.gov.in",
            "www.uidai.gov.in",
            "enrollment no",
            "enrolment no",
            "aadhaar card",
            "aadhar card",
            "aadhaar",
            "aadhar",
        ]
        aadhaar_medium_kw = ["vid:", "unique identification", "father's name", "dob:", "year of birth"]

        # 12-digit UID pattern check
        has_uid_pattern = bool(re.search(r"\b\d{4}\s\d{4}\s\d{4}\b", ocr_text)) or bool(re.search(r"\b\d{12}\b", ocr_text))
        has_dob = bool(re.search(r"(?:dob|birth|பிறந்த)\s*[:/.-]?\s*\d{2}[/.-]\d{2}[/.-]\d{4}", text))
        has_gender = bool(re.search(r"\b(?:male|female|transgender|ஆண்|பெண்)\b", text))

        for kw in aadhaar_strong_kw:
            if kw in text:
                scores["AADHAAR"] += 40
                evidences["AADHAAR"].append(f"Strong Aadhaar keyword: '{kw}'")
        for kw in aadhaar_medium_kw:
            if kw in text:
                scores["AADHAAR"] += 15
                evidences["AADHAAR"].append(f"Aadhaar attribute: '{kw}'")
        if has_uid_pattern:
            scores["AADHAAR"] += 35
            evidences["AADHAAR"].append("12-digit Aadhaar UID number pattern detected")
        if has_dob and has_gender:
            scores["AADHAAR"] += 20
            evidences["AADHAAR"].append("DOB and Gender demographic attributes detected")

        # ---------------------------------------------------------------------
        # 2. BANK PASSBOOK
        # ---------------------------------------------------------------------
        passbook_strong_kw = [
            "passbook",
            "savings bank",
            "bank passbook",
            "account no",
            "a/c no",
            "account number",
            "ifsc code",
            "micr code",
            "cif no",
            "customer id",
            "branch name",
            "bank of india",
            "state bank",
            "canara bank",
            "karur vysya bank",
            "kvb",
            "indian overseas bank",
            "punjab national bank",
            "hdfc bank",
            "icici bank",
            "union bank",
            "axis bank",
        ]
        has_ifsc = bool(re.search(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", ocr_text))
        has_acc_no = bool(re.search(r"(?:a/c|acc|account|ac)\s*(?:no|number)?\s*[:.-]?\s*(\d{9,18})", text))

        for kw in passbook_strong_kw:
            if kw in text:
                scores["BANK_PASSBOOK"] += 25
                evidences["BANK_PASSBOOK"].append(f"Bank Passbook keyword: '{kw}'")
        if has_ifsc:
            scores["BANK_PASSBOOK"] += 45
            evidences["BANK_PASSBOOK"].append("Valid Indian Bank IFSC code pattern detected")
        if has_acc_no:
            scores["BANK_PASSBOOK"] += 30
            evidences["BANK_PASSBOOK"].append("Bank Account number pattern detected")

        # ---------------------------------------------------------------------
        # 3. TRANSFER CERTIFICATE (TC)
        # ---------------------------------------------------------------------
        tc_strong_kw = [
            "transfer certificate",
            "date of admission",
            "date of leaving",
            "reason for leaving",
            "conduct and character",
            "name of the school",
            "higher secondary school",
            "matriculation higher secondary school",
            "school leaving certificate",
            "t.c. no",
            "tc no",
            "sl.no. of tc",
            "emis id",
            "emis number",
            "admission no",
        ]
        for kw in tc_strong_kw:
            if kw in text:
                scores["TRANSFER_CERTIFICATE"] += 35
                evidences["TRANSFER_CERTIFICATE"].append(f"Transfer Certificate keyword: '{kw}'")

        # Anti-misclassification for TC referencing Community Certificate
        if scores["TRANSFER_CERTIFICATE"] >= 40:
            # If document has strong TC keywords, suppress secondary community matches
            if "refer community certificate" in text or "as per community certificate" in text:
                scores["COMMUNITY_CERTIFICATE"] = 0
                scores["COMMUNITY"] = 0
                evidences["TRANSFER_CERTIFICATE"].append("Secondary community reference suppressed under primary Transfer Certificate")

        # ---------------------------------------------------------------------
        # 4. COMMUNITY CERTIFICATE / CASTE CERTIFICATE
        # ---------------------------------------------------------------------
        comm_strong_kw = [
            "community certificate",
            "caste certificate",
            "சாதிச் சான்றிதழ்",
            "வகுப்புச் சான்றிதழ்",
            "permanent community certificate",
            "backward class",
            "backward classes",
            "most backward class",
            "most backward classes",
            "scheduled caste",
            "scheduled tribe",
            "tahsildar",
            "revenue administration",
            "e-sevai",
            "tnedistrict",
            "sub-caste",
            "caste name",
        ]
        has_comm_cert_pattern = bool(re.search(r"tn-\d{10,25}", text)) or bool(re.search(r"certificate\s*no\s*[:.-]?\s*[A-Z0-9/-]+", text))

        for kw in comm_strong_kw:
            if kw in text:
                scores["COMMUNITY_CERTIFICATE"] += 35
                evidences["COMMUNITY_CERTIFICATE"].append(f"Community Certificate keyword: '{kw}'")
        if has_comm_cert_pattern:
            scores["COMMUNITY_CERTIFICATE"] += 20
            evidences["COMMUNITY_CERTIFICATE"].append("Official Government Certificate Number detected")

        # ---------------------------------------------------------------------
        # 5. INCOME CERTIFICATE
        # ---------------------------------------------------------------------
        income_strong_kw = [
            "income certificate",
            "annual income",
            "annual family income",
            "வருமானச் சான்றிதழ்",
            "family income",
            "revenue inspector",
            "tahsildar",
            "rupees per annum",
            "per annum",
        ]
        has_rupees = bool(re.search(r"(?:rs\.?|inr|ரூபாய்)\s*[\d,]+", text))

        for kw in income_strong_kw:
            if kw in text:
                scores["INCOME_CERTIFICATE"] += 35
                evidences["INCOME_CERTIFICATE"].append(f"Income Certificate keyword: '{kw}'")
        if has_rupees and any(k in text for k in ["income", "வருமானம்", "annum"]):
            scores["INCOME_CERTIFICATE"] += 25
            evidences["INCOME_CERTIFICATE"].append("Monetary income amount in Rupees detected")

        # ---------------------------------------------------------------------
        # 6. NATIVITY / RESIDENCE CERTIFICATE
        # ---------------------------------------------------------------------
        nativity_strong_kw = [
            "nativity certificate",
            "residence certificate",
            "இருப்பிடச் சான்றிதழ்",
            "native of",
            "ordinarily resides at",
            "permanent resident of",
        ]
        for kw in nativity_strong_kw:
            if kw in text:
                scores["NATIVITY_CERTIFICATE"] += 40
                evidences["NATIVITY_CERTIFICATE"].append(f"Nativity Certificate keyword: '{kw}'")

        # ---------------------------------------------------------------------
        # 7. SSLC / 10TH MARKSHEET
        # ---------------------------------------------------------------------
        sslc_strong_kw = [
            "secondary school leaving certificate",
            "sslc",
            "x standard",
            "10th standard",
            "board of secondary education",
            "sslc examination",
            "statement of marks",
            "tamil nadu state board of school examinations (sec.)",
        ]
        has_sslc_subjects = bool(re.search(r"\b(?:tamil|english|mathematics|science|social\s*science)\b", text))
        for kw in sslc_strong_kw:
            if kw in text:
                scores["SSLC"] += 35
                evidences["SSLC"].append(f"SSLC keyword: '{kw}'")
        if has_sslc_subjects:
            scores["SSLC"] += 25
            evidences["SSLC"].append("Standard 10th/SSLC academic subjects table detected")

        # ---------------------------------------------------------------------
        # 8. HSC / 12TH MARKSHEET
        # ---------------------------------------------------------------------
        hsc_strong_kw = [
            "higher secondary examination",
            "hsc",
            "higher secondary",
            "+2",
            "plus two",
            "xii standard",
            "12th standard",
            "board of higher secondary examination",
            "statement of marks - higher secondary",
        ]
        has_hsc_subjects = bool(re.search(r"\b(?:physics|chemistry|biology|computer\s*science|mathematics)\b", text))
        for kw in hsc_strong_kw:
            if kw in text:
                scores["HSC"] += 35
                evidences["HSC"].append(f"HSC keyword: '{kw}'")
        if has_hsc_subjects:
            scores["HSC"] += 25
            evidences["HSC"].append("Higher Secondary academic subjects table detected")

        # ---------------------------------------------------------------------
        # 9. BIRTH CERTIFICATE
        # ---------------------------------------------------------------------
        birth_strong_kw = [
            "birth certificate",
            "certificate of birth",
            "பிறப்புச் சான்றிதழ்",
            "form no. 5",
            "registration of births and deaths",
            "place of birth",
            "name of child",
        ]
        for kw in birth_strong_kw:
            if kw in text:
                scores["BIRTH_CERTIFICATE"] += 35
                evidences["BIRTH_CERTIFICATE"].append(f"Birth Certificate keyword: '{kw}'")

        # ---------------------------------------------------------------------
        # 10. ALLOTMENT ORDER
        # ---------------------------------------------------------------------
        allotment_strong_kw = [
            "provisional allotment",
            "allotment order",
            "tnea",
            "directorate of technical education",
            "tamil nadu engineering admissions",
            "admission allotment",
        ]
        for kw in allotment_strong_kw:
            if kw in text:
                scores["ALLOTMENT_ORDER"] += 35
                evidences["ALLOTMENT_ORDER"].append(f"Allotment Order keyword: '{kw}'")

        # ---------------------------------------------------------------------
        # 11. BONAFIDE CERTIFICATE
        # ---------------------------------------------------------------------
        bonafide_strong_kw = [
            "bonafide certificate",
            "is a bonafide student",
            "studying in our institution",
        ]
        for kw in bonafide_strong_kw:
            if kw in text:
                scores["BONAFIDE"] += 40
                evidences["BONAFIDE"].append(f"Bonafide Certificate keyword: '{kw}'")

        # Find maximum scoring document type
        best_type = "UNKNOWN"
        best_score = 0.0

        for dt, score in scores.items():
            if allowed_types and resolve_canonical_document_type(dt) not in allowed_types:
                continue
            if score > best_score:
                best_score = score
                best_type = resolve_canonical_document_type(dt)

        # Minimum threshold for confident classification
        if best_score >= 35.0:
            confidence = min(0.99, max(0.65, best_score / 80.0))
            return {
                "document_type": best_type,
                "confidence": round(confidence, 3),
                "evidence": evidences.get(best_type, []),
            }

        # Filename hints (weak secondary signal with strictly capped low confidence)
        for dt in SUPPORTED_DOCUMENT_TYPES:
            canon_dt = resolve_canonical_document_type(dt)
            if allowed_types and canon_dt not in allowed_types:
                continue
            aliases = DOCUMENT_TYPE_ALIASES.get(canon_dt, [])
            if any(alias in fn for alias in aliases if len(alias) >= 3):
                return {
                    "document_type": canon_dt,
                    "confidence": 0.50,  # Below 0.60 threshold -> triggers NEEDS_REVIEW
                    "evidence": [f"Filename pattern hint '{fn}', pending content review."],
                }

        return {
            "document_type": "UNKNOWN",
            "confidence": 0.0,
            "evidence": ["Insufficient structural patterns to identify document type."],
        }
