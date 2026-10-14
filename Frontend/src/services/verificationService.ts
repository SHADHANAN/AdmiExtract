import { api } from './api'

export interface VerificationHistoryEntry {
  entry_id: string
  actor: string
  actor_role: string
  action: string
  old_value?: any
  new_value?: any
  comment?: string
  document_version_id?: string
  timestamp: string
}

export interface DocumentFieldVerification {
  id: string
  extraction_result_id: string
  extraction_request_id?: string
  student_id: string
  document_id: string
  document_version_id: string
  department_id?: string
  batch_id?: string
  class_id?: string
  document_type: string
  source_document_name?: string
  field_name: string
  ai_value?: any
  raw_value?: any
  student_value?: any
  final_value?: any
  status: 'AI_EXTRACTED' | 'STUDENT_CONFIRMED' | 'STUDENT_VERIFIED' | 'CORRECTION_REQUESTED' | 'STAFF_APPROVED' | 'STAFF_REJECTED'
  confidence?: 'HIGH' | 'MEDIUM' | 'LOW'
  confidence_score?: number
  field_state?: string
  evidence_snippet?: string
  page_number?: number
  reason?: string
  conflicts?: Array<{ document_type: string; value: any; raw?: any }>
  student_updated_at?: string
  staff_reviewed_at?: string
  reviewed_by?: string
  staff_comment?: string
  student_comment?: string
  history: VerificationHistoryEntry[]
  created_at: string
  updated_at: string
}

export interface StudentFieldVerificationItem {
  verification_id: string
  is_confirmed?: boolean
  corrected_value?: any
  comment?: string
}

export interface StudentVerificationSubmitRequest {
  fields: StudentFieldVerificationItem[]
  general_comment?: string
}

export interface StaffReviewCorrectionRequest {
  action: 'APPROVE' | 'REJECT'
  staff_comment?: string
}

export interface PublicVerificationSessionResponse {
  valid: boolean
  token: string
  status: string
  batch_name?: string
  department_id?: string
  expires_at: string
  is_completed?: boolean
  requires_identity_verification?: boolean
  extraction_request_id?: string
}

export interface ValidateStudentIdentityRequest {
  student_name: string
  register_number: string
}

export interface GenerateVerificationTokenRequest {
  student_id: string
  batch_id: string
  student_name?: string
  extraction_request_id?: string
  class_id?: string
  department_id?: string
  expires_in_days?: number
  force_refresh?: boolean
}

export interface GenerateVerificationTokenResponse {
  token: string
  student_id: string
  student_name: string
  batch_id: string
  extraction_request_id?: string
  verification_url: string
  status: string
  expires_at: string
}

export interface PublicVerificationTokenResponse {
  valid: boolean
  token: string
  student_id: string
  student_name: string
  batch_id: string
  batch_name?: string
  class_id?: string
  department_id?: string
  extraction_request_id?: string
  extracted_at?: string
  status: string
  expires_at: string
  fields: DocumentFieldVerification[]
}

export interface CommonStudentIdentifyRequest {
  student_name: string
  register_number: string
  batch_id?: string
  batch_name?: string
  extraction_request_id?: string
}

export interface CommonStudentIdentifyResponse {
  session_token: string
  requires_code: boolean
  contact_hint?: string
  dev_code?: string
  batch_name?: string
  expires_at: string
}

export interface CommonStudentVerifyCodeRequest {
  session_token: string
  code: string
}

export interface CommonStudentSubmitRequest {
  session_token: string
  fields: StudentFieldVerificationItem[]
  general_comment?: string
}

export interface CommonStudentResendCodeRequest {
  session_token: string
}

export interface CommonStudentResendCodeResponse {
  success: boolean
  message: string
  contact_hint?: string
  dev_code?: string
  expires_at?: string
  cooldown_seconds: number
}

export const verificationService = {
  // Common Verification URL endpoints (Public, shared link for all students in batch)
  identifyCommonStudent: async (
    req: CommonStudentIdentifyRequest
  ): Promise<CommonStudentIdentifyResponse> => {
    const res = await api.post<CommonStudentIdentifyResponse>(
      '/public/student-verification/identify',
      req
    )
    return res.data
  },

  resendCommonCode: async (
    req: CommonStudentResendCodeRequest
  ): Promise<CommonStudentResendCodeResponse> => {
    const res = await api.post<CommonStudentResendCodeResponse>(
      '/public/student-verification/resend-code',
      req
    )
    return res.data
  },

  verifyCommonCode: async (
    req: CommonStudentVerifyCodeRequest
  ): Promise<PublicVerificationTokenResponse> => {
    const res = await api.post<PublicVerificationTokenResponse>(
      '/public/student-verification/verify-code',
      req
    )
    return res.data
  },

  submitCommonVerification: async (
    req: CommonStudentSubmitRequest
  ): Promise<PublicVerificationTokenResponse> => {
    const res = await api.post<PublicVerificationTokenResponse>(
      '/public/student-verification/submit',
      req
    )
    return res.data
  },

  // Public token-based student endpoints (NO JWT/LOGIN required)
  getSessionInfo: async (token: string): Promise<PublicVerificationSessionResponse> => {
    const res = await api.get<PublicVerificationSessionResponse>(
      `/public/verification/${encodeURIComponent(token)}/session`
    )
    return res.data

  },

  validateIdentity: async (
    token: string,
    req: ValidateStudentIdentityRequest
  ): Promise<PublicVerificationTokenResponse> => {
    const res = await api.post<PublicVerificationTokenResponse>(
      `/public/verification/${encodeURIComponent(token)}/validate-identity`,
      req
    )
    return res.data
  },

  getPublicVerification: async (token: string): Promise<PublicVerificationTokenResponse> => {
    const res = await api.get<PublicVerificationTokenResponse>(`/public/verification/${encodeURIComponent(token)}`)
    return res.data
  },

  submitPublicVerification: async (
    token: string,
    req: StudentVerificationSubmitRequest
  ): Promise<PublicVerificationTokenResponse> => {
    const res = await api.post<PublicVerificationTokenResponse>(
      `/public/verification/${encodeURIComponent(token)}/submit`,
      req
    )
    return res.data
  },

  generateVerificationToken: async (
    req: GenerateVerificationTokenRequest
  ): Promise<GenerateVerificationTokenResponse> => {
    const res = await api.post<GenerateVerificationTokenResponse>(
      '/staff/verifications/generate-token',
      req
    )
    return res.data
  },


  // Student endpoints (JWT user session)
  getStudentVerifications: async (
    documentId?: string,
    batchId?: string,
    extractionRequestId?: string
  ): Promise<DocumentFieldVerification[]> => {
    const url = documentId ? `/student/verifications/${documentId}` : '/student/verifications'
    const params: Record<string, string> = {}
    if (batchId) params.batch_id = batchId
    if (extractionRequestId) params.extraction_request_id = extractionRequestId
    const res = await api.get<DocumentFieldVerification[]>(url, { params })
    return res.data
  },

  submitStudentVerification: async (
    req: StudentVerificationSubmitRequest
  ): Promise<DocumentFieldVerification[]> => {
    const res = await api.post<DocumentFieldVerification[]>('/student/verifications', req)
    return res.data
  },

  // Staff endpoints
  getPendingCorrections: async (
    batchId?: string,
    classId?: string
  ): Promise<DocumentFieldVerification[]> => {
    const params: Record<string, string> = {}
    if (batchId) params.batch_id = batchId
    if (classId) params.class_id = classId
    const res = await api.get<DocumentFieldVerification[]>('/staff/verifications/pending', { params })
    return res.data
  },

  getStudentVerificationHistory: async (
    studentId: string
  ): Promise<DocumentFieldVerification[]> => {
    const res = await api.get<DocumentFieldVerification[]>(`/staff/verifications/${studentId}`)
    return res.data
  },

  reviewCorrection: async (
    verificationId: string,
    action: 'APPROVE' | 'REJECT',
    staffComment?: string
  ): Promise<DocumentFieldVerification> => {
    const res = await api.post<DocumentFieldVerification>(
      `/staff/verifications/${verificationId}/review`,
      { action, staff_comment: staffComment }
    )
    return res.data
  },
}
