# Storage & Database Audit Report
Generated: 2026-09-16 08:46:11

## 1. MongoDB Collection Report
| Collection Name | Record Count | Data Size | Storage Size | Recommended Action |
| :--- | :--- | :--- | :--- | :--- |
| `admission_batches` | 6 | 1.33 KB | 36.00 KB | KEEP (Active / Audit) |
| `batch_classes` | 3 | 617 bytes | 32.00 KB | KEEP (Active / Audit) |
| `departments` | 6 | 1.10 KB | 36.00 KB | KEEP (Active / Audit) |
| `doc_config_versions` | 12 | 19.07 KB | 32.00 KB | KEEP (Active / Audit) |
| `document_field_configurations` | 7 | 7.18 KB | 32.00 KB | KEEP (Active / Audit) |
| `document_processing_jobs` | 10 | 17.18 KB | 40.00 KB | KEEP (Active / Audit) |
| `excel_batch_templates` | 6 | 5.35 KB | 36.00 KB | KEEP (Active / Audit) |
| `student_submissions` | 52 | 95.59 KB | 60.00 KB | KEEP (Active / Audit) |
| `submission_sessions` | 2 | 24.93 KB | 40.00 KB | KEEP (Active / Audit) |
| `upload_links` | 4 | 1.38 KB | 36.00 KB | KEEP (Active / Audit) |
| `users` | 4 | 1.06 KB | 32.00 KB | KEEP (Active / Audit) |

## 2. File Storage Summary
- **Total Files:** 549 (29.99 MB)
- **Active Referenced Files (Protected):** 33
- **Unreferenced / Orphaned Files:** 516
- **Duplicate Hash Groups (SHA-256):** 64
- **Orphaned Session Dirs:** 148

## 3. Safe Cleanup Items
- **Protected Items:** 46 files (18.57 MB)
- **Safe Cleanup Candidates:** 651 items (11.41 MB)

| Category | Item Count | Reclaimable Space | Recommended Action |
| :--- | :--- | :--- | :--- |
| Debug / Test Artifact | 41 | 10.29 MB | DELETE (Safe) |
| Excess Excel Backup | 40 | 268.32 KB | DELETE (Safe) |
| Orphaned Excel Backup | 174 | 881.31 KB | DELETE (Safe) |
| Orphaned Session Directory | 148 | 0 bytes | DELETE (Safe) |
| Orphaned Session File | 248 | 4.96 KB | DELETE (Safe) |
