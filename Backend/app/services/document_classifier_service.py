from typing import Dict


class DocumentClassifierService:
    """
    Document Classifier Service

    Responsibility:
    - Identify document type from OCR text and optional filename using prioritized keyword heuristics.
    - Prevent misclassification (e.g. TC containing "Refer Community Certificate").
    """

    def classify(self, ocr_text: str, filename: str = "") -> Dict:
        if not ocr_text and not filename:
            return {
                "success": False,
                "document_type": "UNKNOWN",
                "message": "OCR text is empty"
            }

        text = (ocr_text or "").lower()
        fn = (filename or "").lower()

        # 1. TRANSFER CERTIFICATE (Priority #1 to prevent "Refer Community Certificate" misclassification)
        tc_keywords = [
            "transfer certificate",
            "admission no",
            "emis id",
            "name of school",
            "school name",
            "reason for leaving",
            "date of leaving",
            "conduct and character",
            "date of birth as entered in",
            "higher secondary school",
            "matriculation school",
            "sl.no. of tc",
            "t.c.no",
            "tc no",
        ]
        if any(k in text for k in tc_keywords) or any(k in fn for k in ["transfer", "tc_"]):
            return {
                "success": True,
                "document_type": "TRANSFER_CERTIFICATE"
            }

        # 2. AADHAAR
        aadhaar_keywords = [
            "aadhaar",
            "aadhar",
            "uidai",
            "unique identification authority of india",
            "government of india",
            "vid:",
        ]
        if any(k in text for k in aadhaar_keywords) or any(k in fn for k in ["aadhaar", "aadhar", "adhar"]):
            return {
                "success": True,
                "document_type": "AADHAAR"
            }

        # 3. COMMUNITY CERTIFICATE
        # Ensure phrases like "refer community certificate" don't trigger community classification if TC keywords matched
        community_keywords = [
            "community certificate",
            "caste certificate",
            "வகுப்புச் சான்றிதழ்",
            "backward class",
            "backward classes",
            "most backward",
            "scheduled caste",
            "scheduled tribe",
        ]
        if any(k in text for k in community_keywords) or any(k in fn for k in ["community", "caste"]):
            return {
                "success": True,
                "document_type": "COMMUNITY"
            }
        if ("community" in text or "caste" in text) and "refer community" not in text:
            return {
                "success": True,
                "document_type": "COMMUNITY"
            }

        # 4. INCOME CERTIFICATE
        if (
            "income certificate" in text
            or "annual income" in text
            or "வருமானச் சான்றிதழ்" in text
            or "income" in fn
        ):
            return {
                "success": True,
                "document_type": "INCOME"
            }

        # 5. NATIVITY CERTIFICATE
        if (
            "nativity certificate" in text
            or "native of" in text
            or "இருப்பிடச் சான்றிதழ்" in text
            or "nativity" in fn
        ):
            return {
                "success": True,
                "document_type": "NATIVITY"
            }

        # 6. BONAFIDE CERTIFICATE
        if "bonafide certificate" in text or "bonafide" in text or "bonafide" in fn:
            return {
                "success": True,
                "document_type": "BONAFIDE"
            }

        # 7. SSLC / HSC MARKSHEET
        if (
            "secondary school leaving certificate" in text
            or "sslc" in text
            or "10th" in text
            or "sslc" in fn
        ):
            return {
                "success": True,
                "document_type": "SSLC"
            }

        if (
            "higher secondary" in text
            or "hsc" in text
            or "statement of marks" in text
            or "marksheet" in text
            or "hsc" in fn
            or "marksheet" in fn
        ):
            return {
                "success": True,
                "document_type": "HSC"
            }

        # Fallback keyword match on filename
        if "community" in fn or "caste" in fn:
            return {"success": True, "document_type": "COMMUNITY"}
        if "transfer" in fn or "tc" in fn:
            return {"success": True, "document_type": "TRANSFER_CERTIFICATE"}
        if "aadhaar" in fn or "aadhar" in fn or "adhar" in fn:
            return {"success": True, "document_type": "AADHAAR"}
        if "sslc" in fn or "10th" in fn:
            return {"success": True, "document_type": "SSLC"}
        if "hsc" in fn or "12th" in fn or "plus_two" in fn or "marksheet" in fn:
            return {"success": True, "document_type": "HSC"}
        if "income" in fn:
            return {"success": True, "document_type": "INCOME"}
        if "nativity" in fn or "residence" in fn:
            return {"success": True, "document_type": "NATIVITY"}

        # General student admission document fallback - NEVER drop or skip
        return {
            "success": True,
            "document_type": "STUDENT_DOCUMENT",
            "message": "Classified as student document"
        }