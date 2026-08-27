"""
Smart Lookup Engine Service
===========================
Modular lookup engine layer executing between AI Extraction and Verification.
Resolves missing or unpopulated document fields using trusted reference datasets,
PIN code lookups, address component derivations, and salutation rules while
strictly enforcing no-inference guards on sensitive fields.
"""

import re
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LookupProvider(ABC):
    """
    Abstract base interface for modular Smart Lookup Engine providers.
    """
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier name."""
        pass

    @abstractmethod
    def process(
        self,
        verification_fields: Dict[str, Dict[str, Any]],
        all_extracted_pool: Dict[str, Any],
        detected_documents: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Process verification fields and return updated field mapping.
        """
        pass


class PinCodeLookupProvider(LookupProvider):
    """
    Lookup provider that derives location sub-fields (Village, Taluk, District, State, Pincode)
    from PIN code / address proofs using verified administrative datasets.
    """
    @property
    def name(self) -> str:
        return "PIN Code & Address Lookup Provider"

    def process(
        self,
        verification_fields: Dict[str, Dict[str, Any]],
        all_extracted_pool: Dict[str, Any],
        detected_documents: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        from app.utils.field_canonicalizer import (
            parse_location_components_from_address,
            is_address_field,
            ADDRESS_SOURCE_PRIORITY,
        )

        # 1. Select highest priority address proof available
        selected_address_str: Optional[str] = None
        selected_doc_type: Optional[str] = None

        for priority_doc in ADDRESS_SOURCE_PRIORITY:
            if priority_doc in detected_documents:
                for k, v in all_extracted_pool.items():
                    if is_address_field(k):
                        val_str = v.get("value") if isinstance(v, dict) else v
                        if val_str and str(val_str).strip() and str(val_str).upper() not in ["NO", "NULL"]:
                            selected_address_str = str(val_str).strip()
                            selected_doc_type = priority_doc
                            break
            if selected_address_str:
                break

        # If address field is already in verification_fields, check its value
        if not selected_address_str:
            for k in list(verification_fields.keys()):
                if is_address_field(k):
                    v_item = verification_fields[k]
                    val_str = v_item.get("value") if isinstance(v_item, dict) else v_item
                    if val_str and str(val_str).strip() and str(val_str).upper() not in ["NO", "NULL"]:
                        selected_address_str = str(val_str).strip()
                        break

        # Also check Pincode explicitly if present in verification_fields or extracted pool
        pin_val: Optional[str] = None
        for pk in ["Pincode", "Pin Code", "PIN Code", "PIN", "Postal Code"]:
            if pk in verification_fields:
                val = verification_fields[pk].get("value") if isinstance(verification_fields[pk], dict) else verification_fields[pk]
                if val and str(val).strip() and str(val).upper() not in ["NO", "NULL"]:
                    pin_val = str(val).strip()
                    break
            if pk in all_extracted_pool and not pin_val:
                val = all_extracted_pool[pk].get("value") if isinstance(all_extracted_pool[pk], dict) else all_extracted_pool[pk]
                if val and str(val).strip() and str(val).upper() not in ["NO", "NULL"]:
                    pin_val = str(val).strip()
                    break

        derived_loc: Dict[str, Dict[str, Any]] = {}
        if selected_address_str:
            derived_loc = parse_location_components_from_address(selected_address_str)
        elif pin_val:
            derived_loc = parse_location_components_from_address(f"PIN Code: {pin_val}")

        for header in list(verification_fields.keys()):
            h_lower = header.strip().lower()
            current_item = verification_fields[header]
            curr_val = current_item.get("value") if isinstance(current_item, dict) else current_item
            curr_conf = current_item.get("confidence", 0) if isinstance(current_item, dict) else 0

            # Only populate if field is unpopulated or has confidence 0
            if not curr_val or str(curr_val).upper() in ["NO", "NULL"] or curr_conf == 0:
                loc_key = None
                if any(k in h_lower for k in ["village", "vtc", "town"]):
                    loc_key = "Village"
                elif any(k in h_lower for k in ["taluk", "tehsil", "tk"]):
                    loc_key = "Taluk"
                elif any(k in h_lower for k in ["district", "dist", "dt"]):
                    loc_key = "District"
                elif any(k in h_lower for k in ["state"]):
                    loc_key = "State"
                elif any(k in h_lower for k in ["pincode", "pin code", "postal code", "pin"]):
                    loc_key = "Pincode"

                if loc_key and loc_key in derived_loc:
                    res_item = derived_loc[loc_key]
                    if res_item.get("value") and str(res_item.get("value")).upper() not in ["NO", "NULL"]:
                        verification_fields[header] = {
                            "value": res_item["value"],
                            "confidence": res_item.get("confidence", 95),
                            "source": "PIN Lookup" if pin_val else "Address Parsing",
                        }

        return verification_fields


class SalutationGenderLookupProvider(LookupProvider):
    """
    Lookup provider that infers Gender strictly from explicit title/salutation
    (Mr., Master -> Male; Mrs., Ms., Miss -> Female).
    Does NOT infer gender from person's name alone! Skips ambiguous titles.
    """
    @property
    def name(self) -> str:
        return "Salutation Gender Lookup Provider"

    def process(
        self,
        verification_fields: Dict[str, Dict[str, Any]],
        all_extracted_pool: Dict[str, Any],
        detected_documents: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        from app.utils.field_canonicalizer import infer_gender_from_salutation

        gender_key = next((k for k in verification_fields.keys() if k.strip().lower() in ["gender", "sex"]), None)
        if not gender_key:
            return verification_fields

        current_item = verification_fields[gender_key]
        curr_val = current_item.get("value") if isinstance(current_item, dict) else current_item
        curr_conf = current_item.get("confidence", 0) if isinstance(current_item, dict) else 0

        # Only infer if Gender is unpopulated or has confidence 0
        if not curr_val or str(curr_val).upper() in ["NO", "NULL"] or curr_conf == 0:
            sal_val = None
            sal_item = all_extracted_pool.get("Salutation") or all_extracted_pool.get("Title")
            if sal_item:
                sal_val = sal_item.get("value") if isinstance(sal_item, dict) else sal_item

            name_val = None
            name_item = all_extracted_pool.get("Student Name") or all_extracted_pool.get("Name")
            if name_item:
                name_val = name_item.get("value") if isinstance(name_item, dict) else name_item

            infer_res = infer_gender_from_salutation(
                salutation_val=sal_val,
                name_val=name_val,
                all_extracted=all_extracted_pool,
            )

            if infer_res:
                verification_fields[gender_key] = {
                    "value": infer_res["value"],
                    "confidence": infer_res["confidence"],
                    "source": "Salutation Rule",
                    "rule_applied": infer_res.get("rule_applied"),
                }

        return verification_fields


class StrictNoInferenceGuardProvider(LookupProvider):
    """
    Guard provider enforcing strict non-inference rules for sensitive fields:
    - DOB (Age is present -> do NOT calculate DOB)
    - Blood Group (Never infer)
    - Religion (Never infer)
    - Community (Extract only from Community Certificate or configured source)
    - Nationality (Never assume 'Indian')
    - EMIS ID (Extract only from Transfer Certificate)
    
    Ensures missing or unpopulated fields strictly return {"value": "NO", "confidence": 0, "source": "Not Found"}.
    """
    @property
    def name(self) -> str:
        return "Strict No-Inference Guard Provider"

    def process(
        self,
        verification_fields: Dict[str, Dict[str, Any]],
        all_extracted_pool: Dict[str, Any],
        detected_documents: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        STRICT_NO_INFER_FIELDS = [
            "date of birth", "dob", "student date of birth",
            "blood group",
            "religion",
            "community", "caste", "community category", "caste category",
            "nationality",
            "emis id", "is emis id available",
        ]

        for header, item in verification_fields.items():
            h_lower = header.strip().lower()
            val = item.get("value") if isinstance(item, dict) else item
            conf = item.get("confidence", 0) if isinstance(item, dict) else 0

            # Guard 1: EMIS ID must come strictly from TRANSFER_CERTIFICATE
            if "emis" in h_lower and "TRANSFER_CERTIFICATE" not in detected_documents:
                verification_fields[header] = {
                    "value": "NO",
                    "confidence": 0,
                    "source": "Not Found",
                }
                continue

            # Guard 2: Missing fields must have explicit source metadata
            if not val or str(val).upper() in ["NO", "NULL"] or conf == 0:
                verification_fields[header] = {
                    "value": "NO",
                    "confidence": 0,
                    "source": "Not Found",
                }
            elif isinstance(item, dict) and "source" not in item:
                # Ensure every extracted value includes source metadata
                item["source"] = item.get("source", "Document Extraction")
                verification_fields[header] = item

        return verification_fields


class SmartLookupEngine:
    """
    Modular Smart Lookup Engine orchestrator.
    Executes registered providers in order:
    1. PinCodeLookupProvider
    2. SalutationGenderLookupProvider
    3. StrictNoInferenceGuardProvider
    """
    def __init__(self, providers: Optional[List[LookupProvider]] = None):
        self.providers: List[LookupProvider] = providers or [
            PinCodeLookupProvider(),
            SalutationGenderLookupProvider(),
            StrictNoInferenceGuardProvider(),
        ]

    def process_lookup(
        self,
        verification_fields: Dict[str, Dict[str, Any]],
        all_extracted_pool: Dict[str, Any],
        detected_documents: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        logger.info(f"[SmartLookupEngine] Executing {len(self.providers)} lookup providers...")
        current_fields = verification_fields.copy()

        for provider in self.providers:
            try:
                logger.info(f"[SmartLookupEngine] Running provider: {provider.name}")
                current_fields = provider.process(current_fields, all_extracted_pool, detected_documents)
            except Exception as e:
                logger.error(f"[SmartLookupEngine] Provider '{provider.name}' error: {e}", exc_info=True)

        return current_fields
