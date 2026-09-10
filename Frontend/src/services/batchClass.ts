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
}
