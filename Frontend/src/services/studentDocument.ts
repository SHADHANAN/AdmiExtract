import { api } from './api'

export interface ReclassificationHistoryEntry {
  previous_type: string
  new_type: string
  reason: string
  reviewed_by: string
  timestamp: string
}

export interface DocumentVersion {
  version_id: string
  version_number: number
  file_path: string
  original_filename: string
  file_size_bytes: number
  mime_type: string
  uploaded_at: string
  uploaded_by?: string
  validation_status: 'VALID' | 'WRONG_DOCUMENT' | 'UNKNOWN' | 'CLASSIFICATION_FAILED' | 'NEEDS_REVIEW' | 'PENDING' | string
  validation_reason?: string
  expected_document_type?: string
  detected_document_type?: string
  classification_confidence?: number
  classification_evidence?: string[]
  classifier_version?: string
  classified_at?: string
  reclassification_history?: ReclassificationHistoryEntry[]
  is_active: boolean
  extraction_reference?: any
  created_at: string
}

export interface StudentDocument {
  id: string
  student_id: string
  batch_id: string
  class_id?: string
  section_id?: string
  department_id?: string
  document_type: string
  document_name: string
  expected_document_type?: string
  detected_document_type?: string
  classification_confidence?: number
  classification_evidence?: string[]
  reclassification_history?: ReclassificationHistoryEntry[]
  current_version: number
  active_version_id?: string
  status: 'UPLOADED' | 'AI_EXTRACTED' | 'VERIFIED' | 'REJECTED' | 'ARCHIVED' | string
  validation_status?: 'VALID' | 'WRONG_DOCUMENT' | 'UNKNOWN' | 'CLASSIFICATION_FAILED' | 'NEEDS_REVIEW' | 'PENDING' | string
  validation_reason?: string
  active_version?: DocumentVersion | null
  versions: DocumentVersion[]
  created_at: string
  updated_at: string
}

export interface DocumentClassificationResponse {
  document_id: string
  student_id: string
  student_name?: string
  register_number?: string
  batch_id?: string
  class_id?: string
  department_id?: string
  document_type: string
  document_name: string
  expected_document_type?: string
  detected_document_type?: string
  classification_confidence: number
  validation_status: 'VALID' | 'WRONG_DOCUMENT' | 'UNKNOWN' | 'CLASSIFICATION_FAILED' | 'NEEDS_REVIEW' | 'PENDING' | string
  validation_reason?: string
  classification_evidence: string[]
  classifier_version?: string
  classified_at?: string
  reclassification_history: ReclassificationHistoryEntry[]
  current_version: number
  active_version_id?: string
  original_filename?: string
  file_path?: string
  file_size_bytes?: number
  uploaded_at?: string
}

export interface BatchDocumentValidationItem {
  document_id: string
  student_id: string
  student_name?: string
  register_number?: string
  batch_id?: string
  class_id?: string
  department_id?: string
  document_type: string
  document_name: string
  expected_document_type?: string
  detected_document_type?: string
  classification_confidence: number
  validation_status: 'VALID' | 'WRONG_DOCUMENT' | 'UNKNOWN' | 'CLASSIFICATION_FAILED' | 'NEEDS_REVIEW' | 'PENDING' | string
  validation_reason?: string
  classification_evidence: string[]
  reclassification_history: ReclassificationHistoryEntry[]
  version_number: number
  active_version_id?: string
  original_filename?: string
  file_path?: string
  uploaded_at?: string
}

export interface BatchDocumentValidationSummary {
  total_documents: number
  valid: number
  wrong_documents: number
  needs_review: number
  classification_failed: number
  unknown: number
}

export interface BatchDocumentValidationResponse {
  batch_id: string
  summary: BatchDocumentValidationSummary
  documents: BatchDocumentValidationItem[]
}

export interface DocumentExtractionRequestResponse {
  extraction_request_id: string
  student_document_id: string
  document_version_id: string
  student_id: string
  document_type: string
  requested_fields: string[]
  status: 'REQUESTED' | 'PROCESSING' | 'COMPLETED' | 'FAILED' | string
  requested_by: string
  requested_at: string
  started_at?: string
  completed_at?: string
  failed_at?: string
  error_message?: string
  extraction_result_id?: string
  extracted_data?: Record<string, any>
  provenance?: string
  ocr_status?: string
  ai_provider?: string
}

export const studentDocumentService = {
  // Get all documents for a student
  async getStudentDocuments(studentId: string): Promise<StudentDocument[]> {
    const res = await api.get<StudentDocument[]>(`/student-documents/${encodeURIComponent(studentId)}`)
    return res.data
  },

  // Get specific document by type
  async getStudentDocumentByType(studentId: string, documentType: string): Promise<StudentDocument> {
    const res = await api.get<StudentDocument>(
      `/student-documents/${encodeURIComponent(studentId)}/${encodeURIComponent(documentType)}`
    )
    return res.data
  },

  // Get detailed classification & diagnostic evidence for a single document
  async getDocumentClassification(studentDocumentId: string): Promise<DocumentClassificationResponse> {
    const res = await api.get<DocumentClassificationResponse>(
      `/student-documents/${studentDocumentId}/classification`
    )
    return res.data
  },

  // Staff Reclassify Document
  async reclassifyDocument(
    studentDocumentId: string,
    documentType: string,
    reason: string = 'Manual staff reclassification',
    versionId?: string
  ): Promise<StudentDocument> {
    const res = await api.post<StudentDocument>(
      `/student-documents/${studentDocumentId}/reclassify`,
      {
        document_type: documentType,
        reason,
        version_id: versionId,
      }
    )
    return res.data
  },

  // Get Batch Document Validation overview & stats for staff
  async getBatchDocumentValidation(batchId: string, classId?: string): Promise<BatchDocumentValidationResponse> {
    const params = classId && classId !== 'all' ? { class_id: classId } : {}
    const res = await api.get<BatchDocumentValidationResponse>(
      `/batches/${batchId}/document-validation`,
      { params }
    )
    return res.data
  },

  // Get version history
  async getDocumentVersions(studentDocumentId: string): Promise<DocumentVersion[]> {
    const res = await api.get<DocumentVersion[]>(`/student-documents/${studentDocumentId}/versions`)
    return res.data
  },

  // Get extraction requests history
  async getDocumentExtractions(studentDocumentId: string): Promise<DocumentExtractionRequestResponse[]> {
    const res = await api.get<DocumentExtractionRequestResponse[]>(
      `/student-documents/${studentDocumentId}/extractions`
    )
    return res.data
  },

  // Trigger field extraction for a document
  async extractFields(
    studentDocumentId: string,
    requestedFields: string[],
    versionId?: string
  ): Promise<DocumentExtractionRequestResponse> {
    const res = await api.post<DocumentExtractionRequestResponse>(
      `/student-documents/${studentDocumentId}/extract`,
      {
        requested_fields: requestedFields,
        version_id: versionId,
      }
    )
    return res.data
  },

  // Direct upload of a new document version
  async uploadVersionFile(
    studentDocumentId: string,
    file: File,
    validationStatus: string = 'PENDING',
    validationReason?: string,
    setActive: boolean = true
  ): Promise<StudentDocument> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('validation_status', validationStatus)
    if (validationReason) {
      formData.append('validation_reason', validationReason)
    }
    formData.append('set_active', String(setActive))

    const res = await api.post<StudentDocument>(
      `/student-documents/${studentDocumentId}/upload-version`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    )
    return res.data
  },

  // Upload initial document or append version
  async uploadDocumentFile(payload: {
    studentId: string
    batchId: string
    documentType: string
    documentName: string
    classId?: string
    sectionId?: string
    departmentId?: string
    file: File
  }): Promise<StudentDocument> {
    const formData = new FormData()
    formData.append('file', payload.file)
    formData.append('student_id', payload.studentId)
    formData.append('batch_id', payload.batchId)
    formData.append('document_type', payload.documentType)
    formData.append('document_name', payload.documentName)
    if (payload.classId) formData.append('class_id', payload.classId)
    if (payload.sectionId) formData.append('section_id', payload.sectionId)
    if (payload.departmentId) formData.append('department_id', payload.departmentId)

    const res = await api.post<StudentDocument>('/student-documents/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return res.data
  },

  // Fetch document preview / file as Blob for authenticated display
  async fetchDocumentBlob(studentDocumentId: string, versionId?: string): Promise<{ blob: Blob; mimeType: string }> {
    const endpoint = versionId
      ? `/student-documents/${studentDocumentId}/versions/${versionId}/file`
      : `/student-documents/${studentDocumentId}/file`
    const res = await api.get(endpoint, {
      responseType: 'blob',
    })
    const rawMime = res.headers ? res.headers['content-type'] : undefined
    const mimeType = typeof rawMime === 'string' ? rawMime : 'application/pdf'
    return { blob: res.data, mimeType }
  },
}
