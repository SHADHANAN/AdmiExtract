import { api } from './api'
import type { BatchClass } from '../types'

export interface ClassCreatePayload {
  class_name: string
  department: string
  section: string
  academic_year: string
}

export interface ClassUpdatePayload {
  class_name?: string
  department?: string
  section?: string
  academic_year?: string
}

export const batchClassService = {
  async createClass(batchId: string, payload: ClassCreatePayload): Promise<BatchClass> {
    const res = await api.post(`/batches/${batchId}/classes`, payload)
    return res.data
  },

  async getClassesByBatch(batchId: string): Promise<BatchClass[]> {
    const res = await api.get(`/batches/${batchId}/classes`)
    return res.data
  },

  async getClassById(classId: string): Promise<BatchClass> {
    const res = await api.get(`/classes/${classId}`)
    return res.data
  },

  async updateClass(classId: string, payload: ClassUpdatePayload): Promise<BatchClass> {
    const res = await api.put(`/classes/${classId}`, payload)
    return res.data
  },

  async deleteClass(classId: string): Promise<{ message: string }> {
    const res = await api.delete(`/classes/${classId}`)
    return res.data
  },

  async getClassStats(classId: string): Promise<{ students: number; pending: number; verified: number; rejected: number }> {
    const res = await api.get(`/classes/${classId}/stats`)
    return res.data
  },

  async getClassStudents(classId: string): Promise<any[]> {
    const res = await api.get(`/classes/${classId}/students`)
    return res.data.map((s: any) => ({
      id: s.id,
      name: s.student_name,
      studentName: s.student_name,
      registerNum: s.register_number,
      registerNumber: s.register_number,
      mobile: s.mobile_number,
      mobileNumber: s.mobile_number,
      email: s.email,
      batchId: s.batch_id,
      batchName: s.batch_name,
      classId: s.class_id,
      className: s.class_name,
      uploadLinkId: s.upload_link_id,
      status: s.submission_status,
      aiStatus: s.ai_status,
      submittedAt: s.submitted_at,
      updatedAt: s.updated_at,
      documents: (s.documents || []).map((d: any, index: number) => ({
        id: d.document_name,
        reqName: d.document_name,
        document_name: d.document_name,
        status: d.status,
        fileName: d.file_path ? d.file_path.split(/[\\/]/).pop() : undefined,
        fileType: d.file_type || (d.file_path ? (d.file_path.split('.').pop() || '').toUpperCase() : undefined),
        fileSizeMb: d.file_size_mb,
        uploadedAt: d.uploaded_at ? String(d.uploaded_at).replace('T', ' ').substring(0, 16) : undefined,
        documentIndex: index,
      })),
      extractedData: s.extracted_data || {},
    }))
  },

  async getClassUploadLinks(classId: string): Promise<any[]> {
    const res = await api.get(`/classes/${classId}/upload-links`)
    return res.data.map((l: any) => ({
      id: l.id,
      batchId: l.batch_id,
      class_id: l.class_id,
      token: l.token,
      slug: l.slug || l.token,
      title: l.title,
      description: l.description,
      expiresAt: l.expires_at ? l.expires_at.split('T')[0] : '',
      isActive: l.is_active,
      submissionCount: l.submission_count || 0,
      createdAt: l.created_at,
    }))
  },
}
