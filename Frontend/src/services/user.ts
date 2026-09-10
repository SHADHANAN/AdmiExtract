import { api } from './api'
import type { User, UserRole } from '../types'

export interface CreateUserData {
  username: string;
  name: string;
  email?: string;
  password: string;
  role?: UserRole;
  department_code?: string;
}

export const userService = {
  getAll: async (): Promise<User[]> => {
    const response = await api.get<User[]>('/users')
    return response.data
  },

  create: async (data: {
    username: string
    name: string
    email?: string
    password: string
    role?: UserRole
    department_code?: string
  }): Promise<User> => {
    const response = await api.post<User>('/users', data)
    return response.data
  },

  resetPassword: async (userId: string, newPassword: string): Promise<User> => {
    const response = await api.put<User>(`/users/${userId}/reset-password`, {
      new_password: newPassword,
    })
    return response.data
  },

  toggleStatus: async (userId: string, isActive: boolean): Promise<User> => {
    const response = await api.patch<User>(`/users/${userId}/toggle-status`, {
      is_active: isActive,
    })
    return response.data
  },

  delete: async (userId: string): Promise<void> => {
    await api.delete(`/users/${userId}`)
  },
}
