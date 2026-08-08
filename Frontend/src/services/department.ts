import { api } from './api'
import type { Department } from '../types'

export interface DepartmentCreateInput {
  name: string
  code: string
  description?: string
}

export interface DepartmentUpdateInput {
  name?: string
  code?: string
  description?: string
  is_active?: boolean
}

export const departmentService = {
  getAll: async (): Promise<Department[]> => {
    const response = await api.get<Department[]>('/departments')
    return response.data
  },

  getById: async (id: string): Promise<Department> => {
    const response = await api.get<Department>(`/departments/${id}`)
    return response.data
  },

  create: async (data: DepartmentCreateInput): Promise<Department> => {
    const response = await api.post<Department>('/departments', data)
    return response.data
  },

  update: async (id: string, data: DepartmentUpdateInput): Promise<Department> => {
    const response = await api.put<Department>(`/departments/${id}`, data)
    return response.data
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/departments/${id}`)
  },
}
