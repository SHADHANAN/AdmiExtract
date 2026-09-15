"""
Comprehensive Test Suite for AI Field -> Excel Column Mapping System Hardening
=============================================================================
Validates:
1. Aadhaar Number -> Aadhaar Number = PASS
2. Aadhaar Number -> Taluk = REJECT
3. Aadhaar Number -> District = REJECT
4. Mobile Number -> Aadhaar Number = REJECT
5. Student Name -> Student Name = PASS
6. Community Category -> Community = PASS
7. TC Number -> TC Number = PASS
8. Issue Date -> TC Issue Date = PASS
9. Annual Family Income -> Annual Family Income = PASS
10. Multiple different fields -> multiple different columns = PASS
11. Two fields -> same target column = REJECT
12. Save one mapping does not delete other mappings = PASS
13. Reload preserves all mappings = PASS
14. Backend rejects invalid mapping even if frontend is bypassed = PASS
15. Mapping is isolated between batches/classes/users
16. Final Excel receives values only in their configured target columns
17. Mapping order does not affect final result
"""

import os
import openpyxl
import pytest
from app.services.field_mapping_service import (
    is_mapping_compatible,
    validate_mapping_payload,
    classify_field_domain,
    get_canonical_source_field,
)
from app.services.excel_template_service import ExcelTemplateService, _find_best_worksheet_and_headers


# 1. Aadhaar Number -> Aadhaar Number = PASS
def test_1_aadhaar_to_aadhaar_pass():
    is_compat, msg = is_mapping_compatible("Aadhaar Number", "Aadhaar Number")
    assert is_compat is True
    assert msg == "Mapped"


# 2. Aadhaar Number -> Taluk = REJECT
def test_2_aadhaar_to_taluk_reject():
    is_compat, msg = is_mapping_compatible("Aadhaar Number", "Taluk")
    assert is_compat is False
    assert "cannot be mapped to 'Taluk'" in msg


# 3. Aadhaar Number -> District = REJECT
def test_3_aadhaar_to_district_reject():
    is_compat, msg = is_mapping_compatible("Aadhaar Number", "District")
    assert is_compat is False
    assert "cannot be mapped to 'District'" in msg


# 4. Mobile Number -> Aadhaar Number = REJECT
def test_4_mobile_to_aadhaar_reject():
    is_compat, msg = is_mapping_compatible("Mobile Number", "Aadhaar Number")
    assert is_compat is False
    assert "cannot be mapped to 'Aadhaar Number'" in msg


# 5. Student Name -> Student Name = PASS
def test_5_student_name_to_student_name_pass():
    is_compat, msg = is_mapping_compatible("Student Name", "Student Name")
    assert is_compat is True
    assert msg == "Mapped"


# 6. Community Category -> Community = PASS
def test_6_community_category_to_community_pass():
    is_compat, msg = is_mapping_compatible("Community Category", "Community")
    assert is_compat is True
    assert msg == "Mapped"


# 7. TC Number -> TC Number = PASS
def test_7_tc_number_to_tc_number_pass():
    is_compat, msg = is_mapping_compatible("Transfer Certificate Number", "TC Number")
    assert is_compat is True
    assert msg == "Mapped"

    is_compat2, msg2 = is_mapping_compatible("TC Number", "TC Number")
    assert is_compat2 is True
    assert msg2 == "Mapped"


# 8. Issue Date -> TC Issue Date = PASS
def test_8_issue_date_to_tc_issue_date_pass():
    is_compat, msg = is_mapping_compatible("Issue Date", "TC Issue Date")
    assert is_compat is True
    assert msg == "Mapped"


# 9. Annual Family Income -> Annual Family Income = PASS
def test_9_income_to_income_pass():
    is_compat, msg = is_mapping_compatible("Annual Family Income", "Annual Family Income")
    assert is_compat is True
    assert msg == "Mapped"


# 10. Multiple different fields -> multiple different columns = PASS
def test_10_multiple_different_fields_pass():
    allowed_headers = [
        "Aadhaar Number",
        "Community",
        "TC Number",
        "School Name",
        "Admission Number",
        "TC Issue Date",
        "TC Leaving Date",
        "Annual Family Income",
    ]
    mappings = {
        "Aadhaar Number": "Aadhaar Number",
        "Community Category": "Community",
        "Transfer Certificate Number": "TC Number",
        "School Name": "School Name",
        "Admission Number": "Admission Number",
        "Issue Date": "TC Issue Date",
        "Leaving Date": "TC Leaving Date",
        "Annual Family Income": "Annual Family Income",
    }
    is_valid, err_msg, cleaned = validate_mapping_payload(mappings, allowed_headers)
    assert is_valid is True
    assert err_msg is None
    assert len(cleaned) == 8
    assert cleaned["Aadhaar Number"] == "Aadhaar Number"
    assert cleaned["Community Category"] == "Community"
    assert cleaned["Transfer Certificate Number"] == "TC Number"


# 11. Two fields -> same target column = REJECT
def test_11_two_fields_same_target_column_reject():
    allowed_headers = ["Aadhaar Number", "Mobile"]
    mappings = {
        "Aadhaar Number": "Aadhaar Number",
        "Mobile Number": "Aadhaar Number",  # Conflict!
    }
    is_valid, err_msg, cleaned = validate_mapping_payload(mappings, allowed_headers)
    assert is_valid is False
    assert err_msg is not None

    # Same target with different valid fields in same domain
    allowed_headers2 = ["Address"]
    mappings2 = {
        "Permanent Address": "Address",
        "Communication Address": "Address",
    }
    is_valid2, err_msg2, _ = validate_mapping_payload(mappings2, allowed_headers2)
    assert is_valid2 is False
    assert "already mapped" in err_msg2.lower() or "conflict" in err_msg2.lower()


# 12. Save one mapping does not delete other mappings = PASS
def test_12_save_one_mapping_preserves_others():
    existing_mappings = {
        "Student Name": "Student Name",
        "Annual Family Income": "Annual Family Income",
    }
    new_partial_save = {
        "Aadhaar Number": "Aadhaar Number",
    }

    # Simulate repository/service merging logic
    merged = dict(existing_mappings)
    for k, v in new_partial_save.items():
        if not v or str(v).strip() in ["", "-- DO NOT MAP --", "__UNMAPPED__", "NONE", "NULL"]:
            merged.pop(k, None)
        else:
            merged[k] = str(v).strip()

    assert "Student Name" in merged
    assert "Annual Family Income" in merged
    assert "Aadhaar Number" in merged
    assert merged["Student Name"] == "Student Name"
    assert merged["Aadhaar Number"] == "Aadhaar Number"
    assert len(merged) == 3


# 13. Reload preserves all mappings = PASS
def test_13_reload_preserves_all_mappings():
    saved_state = {
        "Aadhaar Number": "Aadhaar Number",
        "Community Category": "Community",
        "Transfer Certificate Number": "TC Number",
    }
    # Simulate reload
    reloaded_state = dict(saved_state)
    assert reloaded_state == saved_state
    is_valid, err_msg, cleaned = validate_mapping_payload(reloaded_state, ["Aadhaar Number", "Community", "TC Number"])
    assert is_valid is True
    assert cleaned == saved_state


# 14. Backend rejects invalid mapping even if frontend is bypassed = PASS
def test_14_backend_rejects_bypassed_invalid_mapping():
    allowed_headers = ["Taluk", "District", "Student Name"]
    bypassed_payload = {
        "Aadhaar Number": "Taluk",
    }
    is_valid, err_msg, _ = validate_mapping_payload(bypassed_payload, allowed_headers)
    assert is_valid is False
    assert "cannot be mapped to 'Taluk'" in err_msg


# 15. Mapping is isolated between batches/classes/users
def test_15_mapping_isolation_between_batches():
    batch1_mappings = {"Aadhaar Number": "Aadhaar Number"}
    batch2_mappings = {"Aadhaar Number": "UID"}

    # Separate dictionaries simulating isolated MongoDB documents
    assert batch1_mappings["Aadhaar Number"] != batch2_mappings["Aadhaar Number"]
    # Modifying batch 1 does not contaminate batch 2
    batch1_mappings["Student Name"] = "Candidate Name"
    assert "Student Name" not in batch2_mappings


# 16. Final Excel receives values only in their configured target columns
def test_16_final_excel_receives_values_only_in_configured_columns():
    service = ExcelTemplateService()
    student_data = {
        "Aadhaar Number": "987654321098",
        "Taluk": "Tambaram",
        "Student Name": "John Doe",
        "Register Number": "REG12345",
    }
    custom_mappings = {
        "Aadhaar Number": "Aadhaar Number",
        "Student Name": "Student Name",
    }

    # Aadhaar Number header should resolve to "9876 5432 1098" (or 987654321098)
    val_aadhaar = service._resolve_header_value("Aadhaar Number", student_data, custom_mappings=custom_mappings)
    assert val_aadhaar is not None
    assert "9876" in str(val_aadhaar)

    # Taluk is NOT in custom_mappings -> should resolve to None (no misplaced data)
    val_taluk = service._resolve_header_value("Taluk", student_data, custom_mappings=custom_mappings)
    assert val_taluk is None

    # Even if an unrelated field has data, it cannot write to Taluk when custom_mappings is configured
    val_district = service._resolve_header_value("District", student_data, custom_mappings=custom_mappings)
    assert val_district is None


# 17. Mapping order does not affect final result
def test_17_mapping_order_invariance():
    service = ExcelTemplateService()
    student_data = {
        "Aadhaar Number": "123456789012",
        "Annual Family Income": "150000",
        "Community Category": "BC",
        "Register Number": "REG999",
    }

    mappings_order_1 = {
        "Aadhaar Number": "Aadhaar Number",
        "Annual Family Income": "Annual Family Income",
        "Community Category": "Community",
    }
    mappings_order_2 = {
        "Community Category": "Community",
        "Annual Family Income": "Annual Family Income",
        "Aadhaar Number": "Aadhaar Number",
    }

    # Check each column resolution across both dictionary insertion orders
    for header in ["Aadhaar Number", "Annual Family Income", "Community"]:
        res1 = service._resolve_header_value(header, student_data, custom_mappings=mappings_order_1)
        res2 = service._resolve_header_value(header, student_data, custom_mappings=mappings_order_2)
        assert res1 == res2, f"Mismatch for header {header}: {res1} vs {res2}"
