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

  // Safely delete student submission
  async deleteSubmission(id: string, batchId?: string, classId?: string): Promise<{ success: boolean; message: string; submission_id: string }> {
    const params = new URLSearchParams()
    if (batchId) params.append('batch_id', batchId)
    if (classId) params.append('class_id', classId)
    const queryString = params.toString() ? `?${params.toString()}` : ''
    const response = await api.delete(`/student-submissions/${id}${queryString}`)
    return response.data
  },

  // Download all uploaded documents for a student submission combined into a single PDF
  async downloadAllDocuments(submissionId: string, studentName?: string, registerNum?: string): Promise<void> {
    try {
      const response = await api.get(`/student-submissions/${submissionId}/documents/download-all`, {
        responseType: 'blob',
      })

      // Extract filename from Content-Disposition header if available
      let filename = ''
      const disposition = response.headers?.['content-disposition']
      if (disposition && disposition.includes('filename=')) {
        const filenameMatch = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
        if (filenameMatch && filenameMatch[1]) {
          filename = filenameMatch[1].replace(/['"]/g, '').trim()
        }
      }

      if (!filename) {
        const cleanName = (studentName || 'Student').replace(/[^a-zA-Z0-9_-]/g, '_')
        const cleanReg = (registerNum || 'Documents').replace(/[^a-zA-Z0-9_-]/g, '_')
        filename = `${cleanName}_${cleanReg}_All_Documents.pdf`
      }

      const blob = new Blob([response.data], { type: 'application/pdf' })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', filename)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err: any) {
      // If error payload is returned as a Blob (due to responseType: 'blob'), parse the error detail
      if (err.response?.data instanceof Blob) {
        try {
          const text = await err.response.data.text()
          const parsed = JSON.parse(text)
          if (parsed.detail) {
            throw new Error(parsed.detail)
          }
        } catch (e: any) {
          if (e.message && e.message !== err.message && !e.message.includes('JSON')) {
            throw e
          }
        }
      }
      throw err
    }
  },
}

// Convert backend response model to Frontend StudentSubmission format
function formatSubmissionResponse(item: any): StudentSubmission {
  return {
    id: item.id,
    batchId: item.batch_id,
    batchName: item.batch_name || item.batch_id,
    classId: item.class_id,
    className: item.class_name,
    registerNum: item.register_number,
    name: item.student_name,
    mobile: item.mobile_number,
    email: item.email || undefined,
    status: item.submission_status,
    aiStatus: item.ai_status || 'Complete',
    submittedAt: typeof item.submitted_at === 'string' ? item.submitted_at.replace('T', ' ').substring(0, 16) : item.submitted_at,
    extractedData: item.extracted_data || {},
    extracted_data: item.extracted_data || {},
    documents: (item.documents || []).map((d: any, index: number) => ({
      reqName: d.document_name,
      // fileName: expose only the bare filename, never the full path
      fileName: d.file_path ? d.file_path.split(/[\\/]/).pop() : undefined,
      fileSizeMb: d.file_size_mb || undefined,
      fileType: d.file_type || (d.file_path ? (d.file_path.split('.').pop() || '').toUpperCase() : undefined),
      status: d.status,
      uploadedAt: d.uploaded_at ? String(d.uploaded_at).replace('T', ' ').substring(0, 16) : undefined,
      // documentIndex enables the DocumentPreviewModal to construct the correct authenticated URL
      documentIndex: index,
    })),
  }
}
