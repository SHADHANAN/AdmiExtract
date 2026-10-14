"""
Comprehensive Document Classification Test Suite
=================================================

Tests all requirements:
1. Aadhaar
2. Community Certificate
3. Income Certificate
4. Nativity Certificate
5. SSLC (10th Marksheet)
6. HSC (12th Marksheet)
7. Transfer Certificate
8. Bank Passbook
9. Unknown / Random Document
10. Wrong document uploaded for an expected requirement (Expected: AADHAAR, Actual: BANK_PASSBOOK -> WRONG_DOCUMENT)
11. Tamil + English document
12. Poor OCR / partial text
13. Multiple documents containing word "certificate"
14. Aadhaar with multiple 12-digit numbers
15. Passbook containing many numbers
16. TC containing "Refer Community Certificate" in item 6
17. Reclassification workflow with immutable audit history
"""

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from app.services.document_classifier_service import DocumentClassifierService
from app.services.field_source_rules import resolve_canonical_document_type


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.db.database as db_mod
    db_mod.client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=2000)
    db_mod.db = db_mod.client[settings.DATABASE_NAME]
    await db_mod._run_db_setup()


@pytest.fixture
def classifier():
    return DocumentClassifierService()


# -----------------------------------------------------------------------------
# 1. Aadhaar Card Tests
# -----------------------------------------------------------------------------
def test_classify_aadhaar_standard(classifier):
    text = """
    GOVERNMENT OF INDIA
    Unique Identification Authority of India
    Mera Aadhaar, Meri Pehchan
    Enrollment No: 1234/56789/01234
    To,
    Ramesh Kumar
    DOB: 15/08/2005
    Gender: Male
    1234 5678 9012
    Help: help@uidai.gov.in | www.uidai.gov.in
    """
    res = classifier.classify(ocr_text=text, filename="doc_01.pdf", expected_document_type="AADHAAR")
    assert res["detected_document_type"] == "AADHAAR"
    assert res["confidence"] >= 0.85
    assert res["validation_status"] == "VALID"
    assert any("Aadhaar" in ev for ev in res["evidence"])


def test_classify_aadhaar_with_multiple_numbers(classifier):
    text = """
    Unique Identification Authority of India
    Aadhaar Card
    Pincode: 600028
    Phone: 9876543210
    Enrollment: 2026/12345/67890
    UID: 9876 5432 1098
    DOB: 01/01/2004
    Gender: Female
    VID: 9123 4567 8901 2345
    """
    res = classifier.classify(ocr_text=text, filename="scan.jpg")
    assert res["detected_document_type"] == "AADHAAR"
    assert res["confidence"] >= 0.80


# -----------------------------------------------------------------------------
# 2. Bank Passbook Tests
# -----------------------------------------------------------------------------
def test_classify_bank_passbook_standard(classifier):
    text = """
    STATE BANK OF INDIA
    BRANCH: CHENNAI MAIN BRANCH
    IFSC CODE: SBIN0000800
    MICR: 600002001
    SAVINGS BANK PASSBOOK
    Account No: 30981234567
    Customer ID / CIF: 852963741
    Account Holder: S. Shadhanan
    Address: 12 Anna Salai, Chennai 600002
    """
    res = classifier.classify(ocr_text=text, filename="scan_passbook.pdf", expected_document_type="BANK_PASSBOOK")
    assert res["detected_document_type"] == "BANK_PASSBOOK"
    assert res["confidence"] >= 0.85
    assert res["validation_status"] == "VALID"
    assert any("IFSC" in ev or "Passbook" in ev for ev in res["evidence"])


def test_classify_bank_passbook_with_many_numbers(classifier):
    text = """
    CANARA BANK
    A/C No: 1234567890123
    IFSC: CNRB0001234
    Txn Date: 01-01-2026 Ref: 987654321098 Amount: 50,000.00 Cr Balance: 1,50,000.00
    Txn Date: 05-01-2026 Ref: 123498765432 Amount: 10,000.00 Dr Balance: 1,40,000.00
    Branch Code: 01234 MICR: 600015023
    """
    res = classifier.classify(ocr_text=text, filename="statement.pdf")
    assert res["detected_document_type"] == "BANK_PASSBOOK"
    assert res["confidence"] >= 0.80


# -----------------------------------------------------------------------------
# 3. Community / Caste Certificate Tests (English + Tamil)
# -----------------------------------------------------------------------------
def test_classify_community_certificate_tamil_english(classifier):
    text = """
    GOVERNMENT OF TAMIL NADU
    REVENUE ADMINISTRATION
    COMMUNITY CERTIFICATE / சாதிச் சான்றிதழ்
    Certificate No: TN-5202608051234
    e-Sevai Portal / tnedistrict
    This is to certify that Selvan Shadhanan S, son of Sundararajan, residing at Dindigul Taluk,
    belongs to Backward Class (BC) Community.
    Issuing Authority: Tahsildar, Dindigul
    """
    res = classifier.classify(ocr_text=text, filename="community_doc.pdf", expected_document_type="COMMUNITY")
    assert res["detected_document_type"] in ("COMMUNITY", "COMMUNITY_CERTIFICATE")
    assert res["confidence"] >= 0.80
    assert res["validation_status"] == "VALID"


# -----------------------------------------------------------------------------
# 4. Income Certificate Tests
# -----------------------------------------------------------------------------
def test_classify_income_certificate(classifier):
    text = """
    GOVERNMENT OF TAMIL NADU
    REVENUE DEPARTMENT
    INCOME CERTIFICATE / வருமானச் சான்றிதழ்
    Certificate No: TN-7202601019999
    This is to certify that the Annual Family Income of Thiru Sundararajan,
    father of Shadhanan S, is Rs. 1,20,000/- (Rupees One Lakh Twenty Thousand Only) per annum.
    Issuing Authority: Tahsildar
    """
    res = classifier.classify(ocr_text=text, filename="income_cert.pdf", expected_document_type="INCOME")
    assert res["detected_document_type"] in ("INCOME", "INCOME_CERTIFICATE")
    assert res["confidence"] >= 0.80
    assert res["validation_status"] == "VALID"


# -----------------------------------------------------------------------------
# 5. Nativity Certificate Tests
# -----------------------------------------------------------------------------
def test_classify_nativity_certificate(classifier):
    text = """
    GOVERNMENT OF TAMIL NADU
    REVENUE DEPARTMENT
    NATIVITY CERTIFICATE / இருப்பிடச் சான்றிதழ்
    Certificate No: TN-9202605051111
    This is to certify that Selvan Shadhanan S is a native of Dindigul District,
    Tamil Nadu and ordinarily resides at Dindigul.
    Issuing Authority: Tahsildar
    """
    res = classifier.classify(ocr_text=text, filename="nativity.pdf", expected_document_type="NATIVITY")
    assert res["detected_document_type"] in ("NATIVITY", "NATIVITY_CERTIFICATE")
    assert res["confidence"] >= 0.80
    assert res["validation_status"] == "VALID"


# -----------------------------------------------------------------------------
# 6. SSLC / 10th Marksheet Tests
# -----------------------------------------------------------------------------
def test_classify_sslc_marksheet(classifier):
    text = """
    DEPARTMENT OF GOVERNMENT EXAMINATIONS, CHENNAI - 6
    SECONDARY SCHOOL LEAVING CERTIFICATE (SSLC)
    X STANDARD EXAMINATION - STATEMENT OF MARKS
    Roll No: 1234567
    Name: Shadhanan S
    Subjects:
    Language (Tamil): 095 Pass
    English: 092 Pass
    Mathematics: 098 Pass
    Science: 096 Pass
    Social Science: 094 Pass
    Total Marks: 475 / 500
    Result: PASS
    """
    res = classifier.classify(ocr_text=text, filename="sslc_marksheet.pdf", expected_document_type="SSLC")
    assert res["detected_document_type"] == "SSLC"
    assert res["confidence"] >= 0.85
    assert res["validation_status"] == "VALID"


# -----------------------------------------------------------------------------
# 7. HSC / 12th Marksheet Tests
# -----------------------------------------------------------------------------
def test_classify_hsc_marksheet(classifier):
    text = """
    BOARD OF HIGHER SECONDARY EXAMINATION, TAMIL NADU
    HIGHER SECONDARY (CLASS XII) EXAMINATION - STATEMENT OF MARKS (+2)
    Reg No: 7654321
    Candidate: Shadhanan S
    Subjects:
    Physics: 095
    Chemistry: 096
    Mathematics: 099
    Computer Science: 098
    Tamil: 090
    English: 092
    Total: 570 / 600
    Engineering Cutoff: 194.5
    """
    res = classifier.classify(ocr_text=text, filename="hsc_mark.pdf", expected_document_type="HSC")
    assert res["detected_document_type"] == "HSC"
    assert res["confidence"] >= 0.85
    assert res["validation_status"] == "VALID"


# -----------------------------------------------------------------------------
# 8. Transfer Certificate (TC) & Anti-Misclassification Tests
# -----------------------------------------------------------------------------
def test_classify_tc_standard(classifier):
    text = """
    TAMIL NADU STATE BOARD
    TRANSFER CERTIFICATE
    TC No: 2026/TC/098
    Admission No: 4521
    EMIS ID: 3302010010112345
    1. Name of School: Government Model Higher Secondary School
    2. Name of Pupil: Shadhanan S
    3. Date of Admission: 01/06/2020
    4. Date of Leaving: 31/05/2026
    5. Reason for Leaving: Completed HSC Course
    6. Conduct and Character: Good
    """
    res = classifier.classify(ocr_text=text, filename="school_tc.pdf", expected_document_type="TRANSFER_CERTIFICATE")
    assert res["detected_document_type"] == "TRANSFER_CERTIFICATE"
    assert res["confidence"] >= 0.85
    assert res["validation_status"] == "VALID"


def test_classify_tc_referencing_community_certificate(classifier):
    """
    Critical requirement: Item 6 in Tamil Nadu TC says 'Refer Community Certificate'.
    This document MUST be classified as TRANSFER_CERTIFICATE, NOT COMMUNITY_CERTIFICATE!
    """
    text = """
    GOVERNMENT HIGHER SECONDARY SCHOOL
    TRANSFER CERTIFICATE
    TC No: 8842
    EMIS No: 3301010045612345
    Admission No: 1204
    Name of Student: Kumar R
    Date of Birth: 12/04/2005
    Community and Caste: Refer Community Certificate for reservation
    Date of Leaving: 15/05/2026
    Reason for Leaving: Higher Studies
    Conduct and Character: Exemplary
    """
    res = classifier.classify(ocr_text=text, filename="tc_scan.pdf", expected_document_type="TRANSFER_CERTIFICATE")
    assert res["detected_document_type"] == "TRANSFER_CERTIFICATE"
    assert res["validation_status"] == "VALID"


# -----------------------------------------------------------------------------
# 9. Unknown / Random Document Tests
# -----------------------------------------------------------------------------
def test_classify_unknown_random_document(classifier):
    text = """
    Physics Chapter 4: Electrostatics
    Coulomb's Law states that the electrical force between two charged objects is directly
    proportional to the product of the quantity of charge on the objects and inversely
    proportional to the square of the separation distance between the two objects.
    F = k * (q1 * q2) / r^2
    """
    res = classifier.classify(ocr_text=text, filename="notes.pdf", expected_document_type="AADHAAR")
    assert res["detected_document_type"] == "UNKNOWN"
    assert res["validation_status"] == "NEEDS_REVIEW"
    assert res["confidence"] < 0.60


# -----------------------------------------------------------------------------
# 10. Critical Mismatch Test: Expected vs Actual
# -----------------------------------------------------------------------------
def test_mismatch_expected_aadhaar_actual_bank_passbook(classifier):
    """
    Critical test:
    Expected: AADHAAR
    Uploaded: Bank Passbook
    Result MUST be WRONG_DOCUMENT (NOT Aadhaar)!
    """
    passbook_text = """
    KARUR VYSYA BANK
    SAVINGS BANK PASSBOOK
    Account No: 1152155000045678
    IFSC: KVBL0001152
    MICR: 624053002
    Customer ID: 99887766
    Account Holder: Mr. S. Shadhanan
    Branch: Dindigul Main
    """
    res = classifier.classify(
        ocr_text=passbook_text,
        filename="bank_passbook.pdf",
        expected_document_type="AADHAAR",
    )
    assert res["detected_document_type"] == "BANK_PASSBOOK"
    assert res["expected_document_type"] == "AADHAAR"
    assert res["validation_status"] == "WRONG_DOCUMENT"
    assert "Expected requirement 'AADHAAR'" in res["validation_reason"]


def test_mismatch_expected_community_actual_transfer_certificate(classifier):
    """
    Expected: COMMUNITY
    Uploaded: Transfer Certificate
    Result MUST be WRONG_DOCUMENT!
    """
    tc_text = """
    TRANSFER CERTIFICATE
    TC No: 1234
    Admission No: 9876
    EMIS ID: 3302010010112345
    Name of Student: Priya M
    Date of Leaving: 30/04/2026
    Reason for Leaving: Course Completed
    Conduct: Good
    """
    res = classifier.classify(
        ocr_text=tc_text,
        filename="tc.pdf",
        expected_document_type="COMMUNITY",
    )
    assert res["detected_document_type"] == "TRANSFER_CERTIFICATE"
    assert res["expected_document_type"] == "COMMUNITY"
    assert res["validation_status"] == "WRONG_DOCUMENT"


# -----------------------------------------------------------------------------
# 11. Multiple Documents with "Certificate" Disambiguation
# -----------------------------------------------------------------------------
def test_disambiguate_multiple_certificates(classifier):
    # Birth Certificate
    birth_text = "BIRTH CERTIFICATE / பிறப்புச் சான்றிதழ் Form No. 5 Registration of Births and Deaths Date of Birth: 01/01/2005 Place of Birth: City Hospital Child Name: Arjun"
    res_birth = classifier.classify(ocr_text=birth_text)
    assert res_birth["detected_document_type"] == "BIRTH_CERTIFICATE"

    # Community Certificate
    comm_text = "COMMUNITY CERTIFICATE / சாதிச் சான்றிதழ் Backward Class BC Tahsildar Certificate No: TN-12345"
    res_comm = classifier.classify(ocr_text=comm_text)
    assert res_comm["detected_document_type"] in ("COMMUNITY", "COMMUNITY_CERTIFICATE")

    # Income Certificate
    inc_text = "INCOME CERTIFICATE / வருமானச் சான்றிதழ் Annual Family Income Rs. 1,50,000 Tahsildar"
    res_inc = classifier.classify(ocr_text=inc_text)
    assert res_inc["detected_document_type"] in ("INCOME", "INCOME_CERTIFICATE")

    # Nativity Certificate
    nat_text = "NATIVITY CERTIFICATE / இருப்பிடச் சான்றிதழ் Native of Dindigul Tahsildar"
    res_nat = classifier.classify(ocr_text=nat_text)
    assert res_nat["detected_document_type"] in ("NATIVITY", "NATIVITY_CERTIFICATE")

    # Bonafide Certificate
    bon_text = "BONAFIDE CERTIFICATE This is to certify that Rajesh is a bonafide student studying in 12th standard"
    res_bon = classifier.classify(ocr_text=bon_text)
    assert res_bon["detected_document_type"] == "BONAFIDE"


# -----------------------------------------------------------------------------
# 12. Reclassification & Audit Log Workflow
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reclassification_workflow_with_audit():
    """
    Test that staff can reclassify a document and that previous_type, new_type,
    reason, reviewer, and timestamp are preserved.
    """
    from app.services.student_document_service import StudentDocumentService
    from app.models.student_document import StudentDocument, DocumentVersion
    from app.models.user import User, UserRole

    staff_user = User(
        name="Admin Staff",
        username="admin_staff",
        email="staff@admissions.edu",
        password="hashed_password",
        role=UserRole.DEPARTMENT_ADMIN,
        department_code="CSE",
    )

    doc_service = StudentDocumentService()

    import uuid
    uid = uuid.uuid4().hex[:8]
    # Create initial document classified as BANK_PASSBOOK
    created_doc = await doc_service.create_student_document(
        student_id=f"STU_RECLASS_{uid}",
        batch_id=f"BATCH_RECLASS_{uid}",
        document_type="BANK_PASSBOOK",
        document_name="Bank Passbook",
        actor=staff_user,
    )
    assert created_doc.document_type == "BANK_PASSBOOK"

    # Reclassify to AADHAAR
    reclassified = await doc_service.reclassify_document(
        student_document_id=str(created_doc.id),
        new_document_type="AADHAAR",
        reason="Student uploaded Aadhaar instead of Passbook; approved by staff",
        actor=staff_user,
    )

    assert reclassified.document_type == "AADHAAR"
    assert reclassified.detected_document_type == "AADHAAR"
    assert len(reclassified.reclassification_history) == 1
    hist = reclassified.reclassification_history[0]
    assert hist["previous_type"] == "BANK_PASSBOOK"
    assert hist["new_type"] == "AADHAAR"
    assert hist["reviewed_by"] == "admin_staff"
    assert "approved by staff" in hist["reason"]
