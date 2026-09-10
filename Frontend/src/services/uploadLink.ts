import { api } from './api'
import type { UploadLink } from '../types'

export interface UploadLinkCreateInput {
  department_id: string
  title: string
  description?: string
  expires_at?: string
  max_submissions?: number
}

export interface UploadLinkUpdateInput {
  title?: string
  description?: string
  is_active?: boolean
  expires_at?: string
  max_submissions?: number
}

export const uploadLinkService = {
  getAll: async (): Promise<UploadLink[]> => {
    // Service layer prepared, currently not connected in UI as requested
    const response = await api.get<UploadLink[]>('/upload-links')
    return response.data
  },

  getById: async (id: string): Promise<UploadLink> => {
    const response = await api.get<UploadLink>(`/upload-links/${id}`)
    return response.data
  },

  create: async (data: UploadLinkCreateInput): Promise<UploadLink> => {
    const response = await api.post<UploadLink>('/upload-links', data)
    return response.data
  },

  update: async (id: string, data: UploadLinkUpdateInput): Promise<UploadLink> => {
    const response = await api.put<UploadLink>(`/upload-links/${id}`, data)
    return response.data
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/upload-links/${id}`)
  },
}
