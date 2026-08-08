import { api } from './api'
import type { UploadLink } from '../types'

export interface CreateBatchInput {
  name: string
  department_id: string
  academic_year: string
  description?: string
  start_date?: string
  end_date?: string
  status?: string
}

export interface CreateUploadLinkInput {
  department_id: string
  batch_id?: string
  title: string
  description?: string
  expires_at?: string
  max_submissions?: number
}

export const batchService = {
  // Batches
  getAll: async (): Promise<any[]> => {
    const response = await api.get('/batches')
    return response.data
  },

  getById: async (id: string): Promise<any> => {
    const response = await api.get(`/batches/${id}`)
    return response.data
  },

  create: async (data: CreateBatchInput): Promise<any> => {
    const response = await api.post('/batches', data)
    return response.data
  },

  update: async (id: string, data: Partial<CreateBatchInput>): Promise<any> => {
    const response = await api.put(`/batches/${id}`, data)
    return response.data
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/batches/${id}`)
  },

  // Document Config Version (for batches)
  getCurrentDocVersion: async (batchId: string): Promise<any> => {
    const response = await api.get(`/batches/${batchId}/doc-versions/current`)
    return response.data
  },

  updateDocRequirements: async (batchId: string, payload: { documents: any[], change_summary?: string }): Promise<any> => {
    const response = await api.post(`/batches/${batchId}/doc-versions`, payload)
    return response.data
  },

  getBatchExtractionFields: async (batchId: string): Promise<string[]> => {
    const response = await api.get(`/batches/${batchId}/extraction-fields`)
    return response.data.extraction_fields || []
  },

  // Upload Links
  getAllUploadLinks: async (): Promise<UploadLink[]> => {
    const response = await api.get('/upload-links')
    return response.data.map(formatUploadLinkResponse)
  },

  createUploadLink: async (data: CreateUploadLinkInput): Promise<UploadLink> => {
    const response = await api.post('/upload-links', data)
    return formatUploadLinkResponse(response.data)
  },

  toggleUploadLink: async (id: string, isActive: boolean): Promise<UploadLink> => {
    const response = await api.put(`/upload-links/${id}`, { is_active: isActive })
    return formatUploadLinkResponse(response.data)
  },

  updateUploadLink: async (id: string, data: { expires_at: string | null }): Promise<UploadLink> => {
    const response = await api.put(`/upload-links/${id}`, data)
    return formatUploadLinkResponse(response.data)
  },

  deleteUploadLink: async (id: string): Promise<void> => {
    await api.delete(`/upload-links/${id}`)
  },
}

function formatUploadLinkResponse(item: any): UploadLink {
  return {
    id: item.id,
    batchId: item.batch_id || 'batch_1', // fallback/default mapping since backend has department_id
    token: item.token,
    slug: item.slug || item.token,
    title: item.title,
    expiresAt: item.expires_at ? item.expires_at.split('T')[0] : '',
    isActive: item.is_active,
    submissionCount: item.submission_count || 0,
  }
}
