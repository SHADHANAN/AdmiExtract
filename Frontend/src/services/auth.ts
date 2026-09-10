import { api } from './api'
import type { User } from '../types'

export interface LoginResponse {
  access_token: string
  token_type: string
}

export const authService = {
  login: async (username: string, password: string): Promise<LoginResponse> => {
    const params = new URLSearchParams()
    params.append('username', username)
    params.append('password', password)
    
    const response = await api.post<LoginResponse>('/auth/login', params, {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    })
    return response.data
  },
  
  getMe: async (): Promise<User> => {
    const response = await api.get<User>('/auth/me')
    return response.data
  },
}
