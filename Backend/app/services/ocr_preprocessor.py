"""
OCR Preprocessor Service
========================

Responsibilities:
- Convert raw OCR text into clean structured text before sending to AI.
- Remove logos, markdown image tags, repeated instructions, terms, and duplicate sections.
- Normalize whitespace, multi-line label-value pairs, and line endings.
- Perform deterministic regex extraction for Aadhaar Number, VID, DOB, Mobile Number, PIN Code, Enrolment Number, Gender.
"""

import re
from typing import Dict, Any, Optional


# Noise & placeholder patterns to strip
NOISE_PATTERNS = [
    r"\[LOGO\]",
    r"!\[.*?\]\(.*?\)",  # Markdown image tags like ![img-0.jpeg](img-0.jpeg)
    r"[-–—]?\s*[■?]\s*.*",  # Bullet instructions starting with - ■ or - ?
    r"Aadhaar is proof of identity, not of citizenship.*",
    r"This Aadhaar letter should be verified through.*",
    r"Documents to support identity and address should be updated.*",
    r"Aadhaar helps you avail of various.*",
    r"Keep your mobile number and email id updated.*",
    r"Download mAadhaar app to avail.*",
    r"Use the feature of Lock/Unlock Aadhaar.*",
    r"Entities seeking Aadhaar are obligated to seek consent.*",
    r"Aadhaar is unique and secure.*",
    r"help@uidai\.gov\.in",
    r"www\.uidai\.gov\.in",
    r"\b1947\b",
]

# Field key aliases mapping to standard requested field names
FIELD_ALIASES = {
    "aadhaar number": "Aadhaar Number",
    "aadhaar card": "Aadhaar Number",
    "aadhaar card number": "Aadhaar Number",
    "aadhaar no": "Aadhaar Number",
    "aadhaar no.": "Aadhaar Number",
    "aadhaar": "Aadhaar Number",
    "vid": "VID",
    "virtual id": "VID",
    "dob": "DOB",
    "date of birth": "DOB",
    "gender": "Gender",
    "mobile": "Mobile Number",
    "mobile number": "Mobile Number",
    "mob": "Mobile Number",
    "pin code": "PIN Code",
    "pincode": "PIN Code",
    "pin": "PIN Code",
    "enrolment number": "Enrolment Number",
    "enrolment no": "Enrolment Number",
    "enrolment no.": "Enrolment Number",
}


class OCRPreprocessor:
    """
    OCR Preprocessor for text cleaning and deterministic regex extraction.
    """

    def clean_ocr_text(self, raw_text: str) -> str:
        """
        Clean raw OCR text:
        - Remove logos, images, repeated instruction bullets
        - Filter non-printable / garbage lines
        - Normalize line spacing and labels
        - Deduplicate lines
        """
        if not raw_text:
            return ""

        text = raw_text

        # 1. Remove noise patterns
        for pattern in NOISE_PATTERNS:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)

        # 2. Split lines and filter out empty / garbage lines (e.g., lines made entirely of ?)
        cleaned_lines = []
        seen_lines = set()

        for line in text.splitlines():
            clean_line = line.strip()

            # Skip lines that are empty or consist mostly of non-ASCII question marks/symbols
            if not clean_line:
                continue

            # Remove lines composed almost entirely of '?'
            question_ratio = clean_line.count('?') / float(len(clean_line)) if len(clean_line) > 0 else 0
            if question_ratio > 0.6:
                continue

            # Normalize spaces within the line
            clean_line = re.sub(r"\s+", " ", clean_line)

            # Simple deduplication for exact repeated header lines (e.g. repeated Government of India)
            line_lower = clean_line.lower()
            if line_lower in seen_lines and len(clean_line) > 5 and not any(kw in line_lower for kw in ["address", "to"]):
                continue

            seen_lines.add(line_lower)
            cleaned_lines.append(clean_line)

        cleaned_text = "\n".join(cleaned_lines)

        # 3. Merge broken label and value lines
        # e.g., "DOB:\n07/06/2007" -> "DOB: 07/06/2007"
        cleaned_text = re.sub(
            r"(DOB|Date of Birth|Aadhaar No\.?|Your Aadhaar No\.?|VID|Enrolment No\.?|Mobile|PIN Code)\s*:\s*\n\s*",
            r"\1: ",
            cleaned_text,
            flags=re.IGNORECASE,
        )

        return cleaned_text.strip()

    def extract_regex_fields(self, text: str) -> Dict[str, Dict[str, Any]]:
        """
        Deterministically extract fields using regular expressions.

        Returns:
            Dictionary mapping canonical field names to {"value": ..., "confidence": 100}
        """
        results: Dict[str, Dict[str, Any]] = {}

        if not text:
            return results

        # 1. Aadhaar Number (12 digits, format 1234 5678 9012, 1234-5678-9012, or 123456789012)
        aadhaar_matches = re.findall(r"\b([2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4})\b", text)
        for match in aadhaar_matches:
            clean_digits = re.sub(r"\D", "", match)
            if len(clean_digits) == 12:
                formatted_aadhaar = f"{clean_digits[:4]} {clean_digits[4:8]} {clean_digits[8:]}"
                aadhaar_obj = {"value": formatted_aadhaar, "confidence": 100}
                results["Aadhaar Card"] = aadhaar_obj
                break

        # 2. VID (16 digits, format 9183 9618 9309 8831)
        vid_match = re.search(r"\bVID\s*[:\-]?\s*([2-9]\d{3}\s?\d{4}\s?\d{4}\s?\d{4})\b", text, re.IGNORECASE)
        if not vid_match:
            vid_match = re.search(r"\b([2-9]\d{3}\s?\d{4}\s?\d{4}\s?\d{4})\b", text)
        if vid_match:
            results["VID"] = {"value": vid_match.group(1).strip(), "confidence": 100}

        # 3. DOB (Date of Birth format DD/MM/YYYY or DD-MM-YYYY)
        dob_match = re.search(r"(?:DOB|Date of Birth)\s*[:/\-]?\s*(\d{2}[/-]\d{2}[/-]\d{4})", text, re.IGNORECASE)
        if not dob_match:
            dob_match = re.search(r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b", text)
        if dob_match:
            results["DOB"] = {"value": dob_match.group(1).strip(), "confidence": 100}

        # 4. Gender (MALE, FEMALE, TRANSGENDER)
        gender_match = re.search(r"\b(MALE|FEMALE|TRANSGENDER)\b", text, re.IGNORECASE)
        if gender_match:
            results["Gender"] = {"value": gender_match.group(1).upper().strip(), "confidence": 100}

        # 5. Mobile Number (10 digits starting with 6-9)
        mobile_match = re.search(r"\b(?:Mobile|Mob|Phone)?\s*[:\-]?\s*([6-9]\d{9})\b", text, re.IGNORECASE)
        if mobile_match:
            results["Mobile Number"] = {"value": mobile_match.group(1).strip(), "confidence": 100}

        # 6. PIN Code (6 digits, e.g., 641016)
        pin_match = re.search(r"\b(?:PIN|PIN Code)?\s*[:\-]?\s*(\d{6})\b", text, re.IGNORECASE)
        if pin_match:
            results["PIN Code"] = {"value": pin_match.group(1).strip(), "confidence": 100}

        # 7. Enrolment Number (format 0000/00539/52008)
        enrolment_match = re.search(r"\b(?:Enrolment No\.?|Enrolment)?\s*[:\-]?\s*(\d{4}/\d{5}/\d{5})\b", text, re.IGNORECASE)
        if enrolment_match:
            results["Enrolment Number"] = {"value": enrolment_match.group(1).strip(), "confidence": 100}

        # 8. Community Certificate & Category & Code
        context_match = re.search(
            r"(?:recognised\s+as\s+a|belongs\s+to|Community\s*:|Category\s*:)\s*(Most\s+Backward\s+Class|Backward\s+Class|Scheduled\s+Caste|Scheduled\s+Tribe|BC\s*[-–]\s*Muslim|MBC/DNC|MBC|BCM|BC|SC|ST|OC|FC)",
            text,
            re.IGNORECASE
        )
        if context_match:
            exact_val = context_match.group(1).strip()
            results["Community Certificate"] = {"value": exact_val, "confidence": 100}
            results["Community Category"] = {"value": exact_val, "confidence": 100}
            if exact_val.upper() in ["BC", "MBC", "SC", "ST", "OC", "BCM", "MBC/DNC", "FC"]:
                results["Community Code"] = {"value": exact_val.upper(), "confidence": 100}

        code_match = re.search(
            r"\b(?:Community\s+Code|Category\s+Code|Caste\s+Code|Code)\s*[:\-]\s*(BC|MBC|SC|ST|OC|BCM|MBC/DNC|FC)\b",
            text,
            re.IGNORECASE
        )
        if code_match:
            results["Community Code"] = {"value": code_match.group(1).upper().strip(), "confidence": 100}

        # 9. Address Extraction
        addr_obj = self.extract_address_from_ocr(text)
        if addr_obj:
            results["Address"] = addr_obj
            results["Full Address"] = addr_obj
            results["Permanent Address"] = addr_obj

        return results

    def extract_address_from_ocr(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Extract the complete postal address from OCR text.
        Requirements:
        1. Extract complete postal address exactly as it appears.
        2. Preserve order of lines and join lines with commas.
        3. Do NOT drop House No, Street, Village, VTC, PO, District, State, PIN Code.
        4. If both Tamil and English addresses exist, prefer the English address.
        5. Never combine two different addresses.
        6. Return None if OCR does not contain an address.
        """
        if not text:
            return None

        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # 1. Search for explicit English "Address:" / "Address" start marker (Priority #1)
        english_start_idx = -1
        for idx, line in enumerate(lines):
            if re.search(r"\bAddress\s*[:\-]?\b", line, re.IGNORECASE) or line.strip().lower() == "address":
                english_start_idx = idx
                break

        # 2. Search for explicit Tamil Address start marker ("முகவரி")
        tamil_start_idx = -1
        if english_start_idx == -1:
            for idx, line in enumerate(lines):
                if "முகவரி" in line:
                    tamil_start_idx = idx
                    break

        # 3. Fallback: Search for "To", "S/O", "D/O", "W/O", "C/O" start markers
        fallback_start_idx = -1
        if english_start_idx == -1 and tamil_start_idx == -1:
            for idx, line in enumerate(lines):
                if re.search(r"^\s*To\b|\b(?:S/O|D/O|W/O|C/O|Res|Location)\b", line, re.IGNORECASE):
                    fallback_start_idx = idx
                    break

        start_idx = english_start_idx if english_start_idx != -1 else (tamil_start_idx if tamil_start_idx != -1 else fallback_start_idx)

        # 4. Fallback: Search for 6-digit Indian PIN Code line if no header marker was found
        if start_idx == -1:
            pin_line_idx = -1
            for idx, line in enumerate(lines):
                if re.search(r"\b[1-9]\d{2}\s?\d{3}\b", line) or re.search(r"\bPIN\s*Code\b", line, re.IGNORECASE):
                    pin_line_idx = idx
                    break
            if pin_line_idx != -1:
                start_idx = max(0, pin_line_idx - 5)

        if start_idx == -1:
            return None

        address_lines = []
        start_line = lines[start_idx]

        # Check if address text starts on the same line after "Address:" / "To:" / "முகவரி:"
        after_colon = re.sub(r"^.*?(?:Address|Addr|Add|S/O|D/O|W/O|C/O|To|முகவரி)\s*[:\-]?\s*", "", start_line, flags=re.IGNORECASE).strip()
        if after_colon and not re.match(r"^\d{4}\s?\d{4}\s?\d{4}$", after_colon):
            address_lines.append(after_colon)

        # Collect subsequent address lines
        for idx in range(start_idx + 1, len(lines)):
            line = lines[idx]
            line_clean = line.strip()

            if not line_clean or line_clean.startswith("![") or line_clean == "[LOGO]":
                continue

            # Skip pure 12-digit Aadhaar number lines or VID lines encountered before address lines
            if re.match(r"^\d{4}\s?\d{4}\s?\d{4}$", line_clean) or re.search(r"\bVID\s*[:\-]?\s*\d{4}", line_clean, re.IGNORECASE):
                continue

            # Stop markers: UIDAI disclaimers or instructions
            if any(kw in line_clean.lower() for kw in ["www.uidai.gov.in", "help@uidai.gov.in", "1947", "unique identification authority", "aadhaar is proof"]):
                break

            # Stop if another English Address starts while we started on Tamil
            if start_idx == tamil_start_idx and re.search(r"\bAddress\s*[:\-]", line_clean, re.IGNORECASE):
                break

            # Add line
            address_lines.append(line_clean)

            # If this line contains a PIN code (6 digits), it's the final line of an Aadhaar address!
            if re.search(r"\b\d{6}\b", line_clean) or re.search(r"\bPIN\s*Code\s*[:\-]?\s*\d{6}\b", line_clean, re.IGNORECASE):
                break

        if not address_lines:
            return None

        # Clean and format address lines
        cleaned_address_parts = []
        for part in address_lines:
            part_clean = re.sub(r"!\[.*?\]\(.*?\)", "", part).strip()
            part_clean = part_clean.rstrip(",")
            if part_clean:
                cleaned_address_parts.append(part_clean)

        if not cleaned_address_parts:
            return None

        # Check if final part is standalone PIN code (6 digits) and format with hyphen "State - 641016"
        last_part = cleaned_address_parts[-1]
        pin_match = re.search(r"^(?:PIN\s*Code\s*[:\-]?)?\s*(\d{6})$", last_part, re.IGNORECASE)
        if pin_match and len(cleaned_address_parts) > 1:
            pin_str = pin_match.group(1)
            formatted_address = ", ".join(cleaned_address_parts[:-1]) + f" - {pin_str}"
        else:
            formatted_address = ", ".join(cleaned_address_parts)

        formatted_address = re.sub(r"\s*,\s*", ", ", formatted_address)
        formatted_address = re.sub(r"(,\s*)+", ", ", formatted_address).strip()

        if len(formatted_address) < 8:
            return None

        return {"value": formatted_address, "confidence": 100}

    @staticmethod
    def get_canonical_field_name(requested_field: str) -> str:
        """Map user requested field to canonical key."""
        from app.utils.field_canonicalizer import get_canonical_field_name
        return get_canonical_field_name(requested_field)
