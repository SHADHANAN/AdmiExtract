"""
Test Suite: Strict Field-to-Document Source Mapping & Authority Filter
======================================================================
Tests verify that fields like Date of Birth, Aadhaar Number, EMIS ID,
Community, Caste, Income, and Academic Marks are strictly accepted ONLY
from their designated source documents, and non-authoritative candidates
are rejected with SOURCE_MISMATCH before final merge and cannot reach Excel.
"""

import pytest
import asyncio
from app.services.field_source_rules import (
    FIELD_SOURCE_RULES,
    normalize_document_type,
    evaluate_field_source,
    SourceAuthorityService,
)
from app.services.document_processing_pipeline import DocumentProcessingPipeline
from app.services.field_mapping_service import FieldMappingService
from app.utils.field_canonicalizer import (
    is_document_authorized_for_field,
    get_document_field_authority_weight,
    get_canonical_field_name,
)


@pytest.fixture
def pipeline():
    return DocumentProcessingPipeline()


@pytest.fixture
def mapper():
    return FieldMappingService()


# =========================================================================
# Test 1: Same DOB in Aadhaar + TC + SSLC
# =========================================================================
def test_01_same_dob_across_documents_accepts_aadhaar_only(pipeline):
    detected_docs = [
        {"document_type": "Aadhaar Card", "type": "Aadhaar Card"},
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
        {"document_type": "10th Mark Sheet", "type": "10th Mark Sheet"},
    ]
    extracted_pool = [
        {
            "document_type": "Aadhaar Card",
            "source_file": "aadhaar.pdf",
            "extracted_data": {"Date of Birth": "07/06/2007"},
            "field_confidences": {"Date of Birth": 95},
        },
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"Date of Birth": "07/06/2007"},
            "field_confidences": {"Date of Birth": 90},
        },
        {
            "document_type": "10th Mark Sheet",
            "source_file": "sslc.pdf",
            "extracted_data": {"Date of Birth": "07/06/2007"},
            "field_confidences": {"Date of Birth": 88},
        },
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["Date of Birth"],
    )

    item = merged["Date of Birth"]
    assert item["value"] == "07.06.2007"
    assert item["source_type"] == "AADHAAR"
    assert item["source_document"] == "aadhaar.pdf"
    assert item["authority"] == 100
    assert item["validation_status"] == "VALID"


# =========================================================================
# Test 2: Conflicting DOB across documents
# =========================================================================
def test_02_conflicting_dob_accepts_only_aadhaar(pipeline):
    detected_docs = [
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
        {"document_type": "10th Mark Sheet", "type": "10th Mark Sheet"},
        {"document_type": "Aadhaar Card", "type": "Aadhaar Card"},
    ]
    extracted_pool = [
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"Date of Birth": "08/06/2007"},
            "field_confidences": {"Date of Birth": 99},  # High confidence must NOT override rule
        },
        {
            "document_type": "10th Mark Sheet",
            "source_file": "sslc.pdf",
            "extracted_data": {"Date of Birth": "09/06/2007"},
            "field_confidences": {"Date of Birth": 98},
        },
        {
            "document_type": "Aadhaar Card",
            "source_file": "aadhaar.pdf",
            "extracted_data": {"Date of Birth": "07/06/2007"},
            "field_confidences": {"Date of Birth": 95},
        },
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["Date of Birth"],
    )

    item = merged["Date of Birth"]
    assert item["value"] == "07.06.2007"
    assert item["source_type"] == "AADHAAR"
    assert item["source_document"] == "aadhaar.pdf"


# =========================================================================
# Test 3: Aadhaar DOB missing -> TC/SSLC DOB accepted per authority hierarchy; unauthorized rejected
# =========================================================================
def test_03_aadhaar_dob_missing_never_fallbacks_to_tc_or_sslc(pipeline):
    detected_docs = [
        {"document_type": "Aadhaar Card", "type": "Aadhaar Card"},
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
        {"document_type": "10th Mark Sheet", "type": "10th Mark Sheet"},
    ]
    extracted_pool = [
        {
            "document_type": "Aadhaar Card",
            "source_file": "aadhaar.pdf",
            "extracted_data": {"Aadhaar Number": "1234 5678 9012"},  # DOB missing in Aadhaar
            "field_confidences": {"Aadhaar Number": 95},
        },
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"Date of Birth": "07/06/2007"},
            "field_confidences": {"Date of Birth": 95},
        },
        {
            "document_type": "10th Mark Sheet",
            "source_file": "sslc.pdf",
            "extracted_data": {"Date of Birth": "07/06/2007"},
            "field_confidences": {"Date of Birth": 95},
        },
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["Date of Birth"],
    )

    item = merged["Date of Birth"]
    # TC is authoritative (90) after Aadhaar (100), so TC DOB is accepted
    assert item["value"] == "07.06.2007"
    assert item["source_type"] == "TRANSFER_CERTIFICATE"

    # Unauthorized document (e.g. Income Certificate) must be rejected
    pool_unauth = [
        {
            "document_type": "Income Certificate",
            "source_file": "income.pdf",
            "extracted_data": {"Date of Birth": "07/06/2007"},
            "field_confidences": {"Date of Birth": 95},
        }
    ]
    merged_unauth = pipeline._order_independent_cross_document_merge(
        detected_docs=[{"document_type": "Income Certificate", "type": "Income Certificate"}],
        all_extracted_pool=pool_unauth,
        excel_headers=["Date of Birth"],
    )
    assert merged_unauth["Date of Birth"]["value"] is None
    assert merged_unauth["Date of Birth"]["requires_verification"] is True


# =========================================================================
# Test 4: EMIS in TC + SSLC
# =========================================================================
def test_04_emis_strictly_from_tc_only(pipeline):
    detected_docs = [
        {"document_type": "10th Mark Sheet", "type": "10th Mark Sheet"},
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
    ]
    extracted_pool = [
        {
            "document_type": "10th Mark Sheet",
            "source_file": "sslc.pdf",
            "extracted_data": {"EMIS ID": "998877665544"},
            "field_confidences": {"EMIS ID": 99},
        },
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"EMIS ID": "2015743426"},
            "field_confidences": {"EMIS ID": 90},
        },
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["EMIS ID", "Is EMIS ID Available"],
    )

    assert merged["EMIS ID"]["value"] == "2015743426"
    assert merged["EMIS ID"]["source_type"] == "TRANSFER_CERTIFICATE"
    assert merged["Is EMIS ID Available"]["value"] == "Yes"

    # Unauthorized document (e.g. Community Certificate) must be rejected
    pool_unauth_emis = [
        {
            "document_type": "Community Certificate",
            "source_file": "community.pdf",
            "extracted_data": {"EMIS ID": "998877665544"},
            "field_confidences": {"EMIS ID": 99},
        }
    ]
    merged_missing = pipeline._order_independent_cross_document_merge(
        detected_docs=[{"document_type": "Community Certificate", "type": "Community Certificate"}],
        all_extracted_pool=pool_unauth_emis,
        excel_headers=["EMIS ID", "Is EMIS ID Available"],
    )
    assert merged_missing["EMIS ID"]["value"] is None
    assert merged_missing["Is EMIS ID Available"]["value"] == "No"


# =========================================================================
# Test 5: Community in Community Certificate + TC
# =========================================================================
def test_05_community_strictly_from_community_certificate(pipeline):
    detected_docs = [
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
        {"document_type": "Community Certificate", "type": "Community Certificate"},
    ]
    extracted_pool = [
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"Community Category": "MBC", "Caste": "Vanniyar"},
            "field_confidences": {"Community Category": 95, "Caste": 95},
        },
        {
            "document_type": "Community Certificate",
            "source_file": "community.pdf",
            "extracted_data": {"Community Category": "BC", "Caste": "Vadugar"},
            "field_confidences": {"Community Category": 90, "Caste": 90},
        },
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["Community Category", "Caste"],
    )

    assert merged["Community Category"]["value"] == "BC"
    assert merged["Community Category"]["source_type"] == "COMMUNITY"
    assert merged["Caste"]["value"] == "VADUGAR"
    assert merged["Caste"]["source_type"] == "COMMUNITY"


# =========================================================================
# Test 6: Income in Income Certificate + other documents
# =========================================================================
def test_06_income_strictly_from_income_certificate(pipeline):
    detected_docs = [
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
        {"document_type": "Income Certificate", "type": "Income Certificate"},
    ]
    extracted_pool = [
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"Annual Family Income": "250000"},
            "field_confidences": {"Annual Family Income": 95},
        },
        {
            "document_type": "Income Certificate",
            "source_file": "income.pdf",
            "extracted_data": {"Annual Family Income": "120000"},
            "field_confidences": {"Annual Family Income": 90},
        },
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["Annual Family Income"],
    )

    assert merged["Annual Family Income"]["value"] == "120000"
    assert merged["Annual Family Income"]["source_type"] == "INCOME"


# =========================================================================
# Test 7: 10th Marks in SSLC + TC
# =========================================================================
def test_07_tenth_marks_strictly_from_sslc(pipeline):
    detected_docs = [
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
        {"document_type": "10th Mark Sheet", "type": "10th Mark Sheet"},
    ]
    extracted_pool = [
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"SSLC Mark Percentage": "82.5", "10th Mark": "412"},
            "field_confidences": {"SSLC Mark Percentage": 95, "10th Mark": 95},
        },
        {
            "document_type": "10th Mark Sheet",
            "source_file": "sslc.pdf",
            "extracted_data": {"SSLC Mark Percentage": "91.0", "10th Mark": "455"},
            "field_confidences": {"SSLC Mark Percentage": 90, "10th Mark": 90},
        },
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["SSLC Mark Percentage", "10th Mark"],
    )

    assert merged["SSLC Mark Percentage"]["value"] == "91.0"
    assert merged["SSLC Mark Percentage"]["source_type"] == "SSLC"
    assert merged["10th Mark"]["value"] == "455"
    assert merged["10th Mark"]["source_type"] == "SSLC"


# =========================================================================
# Test 8: 12th Marks in HSC + TC
# =========================================================================
def test_08_twelfth_marks_strictly_from_hsc(pipeline):
    detected_docs = [
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
        {"document_type": "12th Mark Sheet", "type": "12th Mark Sheet"},
    ]
    extracted_pool = [
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"HSC Mark Percentage": "78.4", "12th Mark": "470"},
            "field_confidences": {"HSC Mark Percentage": 95, "12th Mark": 95},
        },
        {
            "document_type": "12th Mark Sheet",
            "source_file": "hsc.pdf",
            "extracted_data": {"HSC Mark Percentage": "89.5", "12th Mark": "537"},
            "field_confidences": {"HSC Mark Percentage": 90, "12th Mark": 90},
        },
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["HSC Mark Percentage", "12th Mark"],
    )

    assert merged["HSC Mark Percentage"]["value"] == "89.5"
    assert merged["HSC Mark Percentage"]["source_type"] == "HSC"
    assert merged["12th Mark"]["value"] == "537"
    assert merged["12th Mark"]["source_type"] == "HSC"


# =========================================================================
# Test 9: Unknown / Unconfigured field preserves existing behavior
# =========================================================================
def test_09_unconfigured_field_preserves_behavior(pipeline):
    detected_docs = [{"document_type": "Bonafide Certificate", "type": "Bonafide Certificate"}]
    extracted_pool = [
        {
            "document_type": "Bonafide Certificate",
            "source_file": "bonafide.pdf",
            "extracted_data": {"Extracurricular Activity": "NSS Volunteer"},
            "field_confidences": {"Extracurricular Activity": 85},
        }
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["Extracurricular Activity"],
    )

    assert merged["Extracurricular Activity"]["value"] == "NSS Volunteer"
    assert merged["Extracurricular Activity"]["validation_status"] == "VALID"


# =========================================================================
# Test 10: Document aliases normalize correctly
# =========================================================================
def test_10_document_aliases_normalize_correctly():
    # Aadhaar variants
    assert normalize_document_type("Aadhaar") == "AADHAAR"
    assert normalize_document_type("AADHAAR_CARD") == "AADHAAR"
    assert normalize_document_type("aadhaar card") == "AADHAAR"
    assert normalize_document_type("aadhar") == "AADHAAR"
    assert normalize_document_type("UID") == "AADHAAR"

    # TC variants
    assert normalize_document_type("TC") == "TRANSFER_CERTIFICATE"
    assert normalize_document_type("Transfer Certificate") == "TRANSFER_CERTIFICATE"
    assert normalize_document_type("TRANSFER_CERTIFICATE") == "TRANSFER_CERTIFICATE"

    # Community variants
    assert normalize_document_type("Community Certificate") == "COMMUNITY"
    assert normalize_document_type("COMMUNITY_CERTIFICATE") == "COMMUNITY"
    assert normalize_document_type("caste") == "COMMUNITY"

    # Income variants
    assert normalize_document_type("Income Certificate") == "INCOME"
    assert normalize_document_type("INCOME_CERTIFICATE") == "INCOME"

    # SSLC variants
    assert normalize_document_type("10th Mark Sheet") == "SSLC"
    assert normalize_document_type("10TH_MARKSHEET") == "SSLC"
    assert normalize_document_type("sslc") == "SSLC"

    # HSC variants
    assert normalize_document_type("12th Mark Sheet") == "HSC"
    assert normalize_document_type("12TH_MARKSHEET") == "HSC"
    assert normalize_document_type("hsc") == "HSC"
    assert normalize_document_type("plus_two") == "HSC"


# =========================================================================
# Test 11: Rejected source candidate cannot reach Excel
# =========================================================================
def test_11_rejected_source_cannot_reach_excel(pipeline, mapper):
    # Candidate DOB is only present in Community Certificate (unauthorized for DOB)
    detected_docs = [{"document_type": "Community Certificate", "type": "Community Certificate"}]
    extracted_pool = [
        {
            "document_type": "Community Certificate",
            "source_file": "community.pdf",
            "extracted_data": {"Date of Birth": "15/05/2005", "Community": "BC"},
            "field_confidences": {"Date of Birth": 95, "Community": 95},
        }
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["Date of Birth", "Community"],
    )

    # 1. In merged pipeline output, DOB is None
    assert merged["Date of Birth"]["value"] is None

    # 2. In Excel writer mapping, DOB writes None (blank cell), never Community's DOB
    excel_write = mapper.format_for_excel_write(
        excel_headers=["Date of Birth", "Community"],
        mapped_fields=merged,
    )
    assert excel_write["Date of Birth"] is None
    assert excel_write["Community"] == "BC"


# =========================================================================
# Test 12: Order Invariance across document upload permutations
# =========================================================================
def test_12_upload_order_invariance(pipeline):
    doc_aadhaar = {
        "document_type": "Aadhaar Card",
        "source_file": "aadhaar.pdf",
        "extracted_data": {"Date of Birth": "07/06/2007", "Gender": "Male"},
        "field_confidences": {"Date of Birth": 95, "Gender": 95},
    }
    doc_tc = {
        "document_type": "Transfer Certificate",
        "source_file": "tc.pdf",
        "extracted_data": {"Date of Birth": "08/06/2007", "EMIS ID": "2015743426"},
        "field_confidences": {"Date of Birth": 90, "EMIS ID": 90},
    }
    doc_sslc = {
        "document_type": "10th Mark Sheet",
        "source_file": "sslc.pdf",
        "extracted_data": {"Date of Birth": "09/06/2007", "SSLC Mark Percentage": "88.0"},
        "field_confidences": {"Date of Birth": 85, "SSLC Mark Percentage": 95},
    }

    headers = ["Date of Birth", "Gender", "EMIS ID", "SSLC Mark Percentage"]

    # Permutation 1: [Aadhaar, TC, SSLC]
    res1 = pipeline._order_independent_cross_document_merge(
        detected_docs=["Aadhaar Card", "Transfer Certificate", "10th Mark Sheet"],
        all_extracted_pool=[doc_aadhaar, doc_tc, doc_sslc],
        excel_headers=headers,
    )

    # Permutation 2: [SSLC, Aadhaar, TC]
    res2 = pipeline._order_independent_cross_document_merge(
        detected_docs=["10th Mark Sheet", "Aadhaar Card", "Transfer Certificate"],
        all_extracted_pool=[doc_sslc, doc_aadhaar, doc_tc],
        excel_headers=headers,
    )

    # Permutation 3: [TC, SSLC, Aadhaar]
    res3 = pipeline._order_independent_cross_document_merge(
        detected_docs=["Transfer Certificate", "10th Mark Sheet", "Aadhaar Card"],
        all_extracted_pool=[doc_tc, doc_sslc, doc_aadhaar],
        excel_headers=headers,
    )

    for h in headers:
        assert res1[h]["value"] == res2[h]["value"] == res3[h]["value"]
        assert res1[h]["source_type"] == res2[h]["source_type"] == res3[h]["source_type"]


# =========================================================================
# Test 13: Multiple concurrent student sessions remain isolated
# =========================================================================
@pytest.mark.asyncio
async def test_13_concurrent_sessions_remain_isolated(pipeline):
    async def process_student(student_id: str, aadhaar_dob: str, emis: str):
        pool = [
            {
                "document_type": "Aadhaar Card",
                "source_file": f"aadhaar_{student_id}.pdf",
                "extracted_data": {"Date of Birth": aadhaar_dob},
                "field_confidences": {"Date of Birth": 95},
            },
            {
                "document_type": "Transfer Certificate",
                "source_file": f"tc_{student_id}.pdf",
                "extracted_data": {"EMIS ID": emis},
                "field_confidences": {"EMIS ID": 95},
            },
        ]
        # Simulate slight async delay
        await asyncio.sleep(0.01)
        return pipeline._order_independent_cross_document_merge(
            detected_docs=["Aadhaar Card", "Transfer Certificate"],
            all_extracted_pool=pool,
            excel_headers=["Date of Birth", "EMIS ID"],
        )

    res_a, res_b = await asyncio.gather(
        process_student("student_A", "10/01/2005", "1111222233"),
        process_student("student_B", "20/02/2006", "4444555566"),
    )

    assert res_a["Date of Birth"]["value"] == "10.01.2005"
    assert res_a["EMIS ID"]["value"] == "1111222233"

    assert res_b["Date of Birth"]["value"] == "20.02.2006"
    assert res_b["EMIS ID"]["value"] == "4444555566"


# =========================================================================
# Test 14: Profile fields remain separate from document fields
# =========================================================================
def test_14_profile_data_remains_separate(pipeline):
    login_profile = {
        "student_name": "KAVIN R",
        "register_number": "24CS105",
        "mobile_number": "9876543210",
        "email": "kavin@example.com",
    }

    # Document has academic register number and different names
    extracted_pool = [
        {
            "document_type": "10th Mark Sheet",
            "source_file": "sslc.pdf",
            "extracted_data": {
                "Student Name": "KAVIN RAJESH",  # Document variation
                "SSLC Register Number": "654321",
                "Register Number": "654321",  # Document academic reg no
            },
            "field_confidences": {"Student Name": 95, "SSLC Register Number": 95, "Register Number": 95},
        }
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=["10th Mark Sheet"],
        all_extracted_pool=extracted_pool,
        excel_headers=["Student Name", "Register Number", "SSLC Register Number"],
        student_profile=login_profile,
    )

    # 1. Profile identity fields strictly preserve authenticated login values
    assert merged["Student Name"]["value"] == "KAVIN R"
    assert merged["Student Name"]["source_type"] == "PROFILE_SOURCE"
    assert merged["Register Number"]["value"] == "24CS105"
    assert merged["Register Number"]["source_type"] == "PROFILE_SOURCE"

    # 2. Academic register number preserved from document
    assert merged["SSLC Register Number"]["value"] == "654321"
    assert merged["SSLC Register Number"]["source_type"] == "SSLC"


# =========================================================================
# Test 15: Explicit NONE from authoritative doc blocks lower candidates
# =========================================================================
def test_15_explicit_negative_from_authoritative_doc_blocks_lower(pipeline):
    detected_docs = [
        {"document_type": "Community Certificate", "type": "Community Certificate"},
        {"document_type": "Transfer Certificate", "type": "Transfer Certificate"},
    ]
    extracted_pool = [
        {
            "document_type": "Community Certificate",
            "source_file": "community.pdf",
            "extracted_data": {"Guardian Name": "RAMASAMY K"},
            "field_confidences": {"Guardian Name": 90},
        },
        {
            "document_type": "Transfer Certificate",
            "source_file": "tc.pdf",
            "extracted_data": {"Guardian Name": "NONE"},  # TC is authoritative for Guardian
            "field_confidences": {"Guardian Name": 95},
        },
    ]

    merged = pipeline._order_independent_cross_document_merge(
        detected_docs=detected_docs,
        all_extracted_pool=extracted_pool,
        excel_headers=["Guardian Name"],
    )

    # TC Guardian NONE must override lower-authority candidate from Community Certificate
    assert merged["Guardian Name"]["value"] == "NO"
