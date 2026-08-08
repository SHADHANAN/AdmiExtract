import { api } from './api'
import type { StudentSubmission } from '../types'

export interface CreateSubmissionPayload {
  batch_id: string
  batch_name?: string
  student_name: string
  register_number: string
  mobile_number: string
  email?: string
  submission_status?: string
  documents: Array<{
    document_name: string
    status: string
    file_path?: string
    file_size_mb?: number
    file_type?: string
    uploaded_at?: string
  }>
}

export const studentSubmissionService = {
  // Create student submission
  async createSubmission(payload: CreateSubmissionPayload): Promise<StudentSubmission> {
    const response = await api.post('/student-submissions', payload)
    return formatSubmissionResponse(response.data)
  },

  // Get all submissions
  async getAllSubmissions(): Promise<StudentSubmission[]> {
    const response = await api.get('/student-submissions')
    return response.data.map(formatSubmissionResponse)
  },

  // Get submissions by batch ID
  async getSubmissionsByBatch(batchId: string): Promise<StudentSubmission[]> {
    const response = await api.get(`/student-submissions/batch/${batchId}`)
    return response.data.map(formatSubmissionResponse)
  },

  // Get submission by ID
  async getSubmissionById(id: string): Promise<StudentSubmission> {
    const response = await api.get(`/student-submissions/${id}`)
    return formatSubmissionResponse(response.data)
  },

  // Update submission status
  async updateStatus(id: string, status: string): Promise<StudentSubmission> {
    const response = await api.patch(`/student-submissions/${id}/status`, { submission_status: status })
    return formatSubmissionResponse(response.data)
  },
}

// Convert backend response model to Frontend StudentSubmission format
function formatSubmissionResponse(item: any): StudentSubmission {
  return {
    id: item.id,
    batchId: item.batch_id,
    batchName: item.batch_name || item.batch_id,
    registerNum: item.register_number,
    name: item.student_name,
    mobile: item.mobile_number,
    email: item.email || undefined,
    status: item.submission_status,
    aiStatus: item.ai_status || 'Complete',
    submittedAt: typeof item.submitted_at === 'string' ? item.submitted_at.replace('T', ' ').substring(0, 16) : item.submitted_at,
    documents: (item.documents || []).map((d: any) => ({
      reqName: d.document_name,
      fileName: d.file_path ? d.file_path.split('/').pop() : `${d.document_name.replace(/\s+/g, '_')}.pdf`,
      fileSizeMb: d.file_size_mb || 2.5,
      fileType: d.file_type || 'PDF',
      status: d.status,
      uploadedAt: d.uploaded_at ? String(d.uploaded_at).replace('T', ' ').substring(0, 16) : undefined,
      fileUrl: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=800',
    })),
  }
}
