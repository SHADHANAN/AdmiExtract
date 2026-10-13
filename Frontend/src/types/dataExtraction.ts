export type BatchExportStatus = 'NOT_READY' | 'PARTIALLY_VERIFIED' | 'READY' | 'EXPORTED';

export interface BatchExtractionSummary {
  extraction_request_id: string;
  batch_id: string;
  batch_name?: string;
  academic_year?: string;
  department_id?: string;
  template_filename?: string;
  requested_fields: string[];
  requested_columns: string[];
  status: 'DRAFT' | 'PROCESSING' | 'COMPLETED' | 'PARTIAL' | 'FAILED' | 'VERIFICATION_PENDING' | 'VERIFIED' | 'EXPORTED' | 'CANCELLED';
  result_count: number;
  total_students: number;
  processed_count: number;
  successful_count: number;
  partial_count?: number;
  missing_docs_count: number;
  failed_count: number;
  verified_count: number;
  correction_requested_count: number;
  pending_verification_count: number;
  verification_status: 'DRAFT' | 'PENDING' | 'PARTIALLY_VERIFIED' | 'VERIFIED';
  export_status: BatchExportStatus;
  download_status: 'NOT_DOWNLOADED' | 'DOWNLOADED';
  download_count: number;
  last_downloaded_at?: string;
  exported_filename?: string;
  created_by: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  failed_at?: string;
  error_message?: string;
}

export interface BatchExtractionStats {
  batch_id: string;
  batch_name: string;
  academic_year: string;
  department_id: string;
  students_count: number;
  stored_documents_count: number;
  extractions_count: number;
  latest_extraction?: BatchExtractionSummary | null;
  verification_status: string;
  download_history_count: number;
}

export interface TemplatePreviewData {
  template_id?: string;
  template_filename?: string;
  sheet_name?: string;
  sheet_names?: string[];
  header_row_index?: number;
  requested_columns: string[];
  canonical_fields: string[];
  column_mapping: Record<string, string>;
  column_indices?: Record<string, number>;
  detected_students_count: number;
  sample_rows: Record<string, any>[];
}

export interface CreateBatchExtractionPayload {
  template_id?: string;
  template_filename?: string;
  sheet_name?: string;
  requested_fields?: string[];
  requested_columns?: string[];
  column_mapping?: Record<string, string>;
  field_mappings?: any[];
  class_id?: string;
}

export interface StudentExtractionField {
  field_name: string;
  column_label: string;
  ai_value?: any;
  raw_value?: any;
  student_value?: any;
  final_value?: any;
  verification_status: string;
  verification_id?: string;
  is_available: boolean;
  source_document_type?: string;
  source_document_name?: string;
  source_document_version?: string;
  confidence?: 'HIGH' | 'MEDIUM' | 'LOW';
  confidence_score?: number;
  field_state?: string;
  evidence_snippet?: string;
  page_number?: number;
  reason?: string;
  conflicts?: Array<{ document_type: string; document_name?: string; value: any; raw?: any; authority?: number }>;
}

export interface StudentExtractionRow {
  student_id: string;
  student_name?: string;
  register_number: string;
  document_status: string;
  extraction_status: string;
  verification_status: string;
  final_status: string;
  missing_documents: string[];
  failure_reason?: string;
  fields: Record<string, StudentExtractionField>;
  has_corrections_pending: boolean;
  verification_token?: string;
  verification_link?: string;
  verification_token_status?: string;
  verification_link_expires_at?: string;
}

export interface CorrectionQueueItem {
  verification_id: string;
  extraction_request_id: string;
  student_id: string;
  student_name?: string;
  register_number: string;
  document_type: string;
  field_name: string;
  field_label: string;
  ai_value?: any;
  student_value?: any;
  student_comment?: string;
  submitted_at?: string;
}

export interface BatchExtractionDetail {
  summary: BatchExtractionSummary;
  students: StudentExtractionRow[];
  total_matching_students: number;
  page: number;
  page_size: number;
  verification_progress: {
    total_fields: number;
    confirmed: number;
    correction_requested: number;
    staff_approved: number;
    staff_rejected: number;
    pending_review: number;
    verified_students?: number;
    total_students?: number;
  };
  corrections_queue: CorrectionQueueItem[];
}
