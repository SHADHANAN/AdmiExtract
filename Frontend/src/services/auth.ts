import { api } from './api'
import type { User } from '../types'

export interface LoginResponse {
  access_token: string
  token_type: string
  token?: string
  accessToken?: string
}

export const authService = {
  login: async (username: string, password: string): Promise<LoginResponse> => {
    const params = new URLSearchParams()
    params.append('username', username)
    params.append('password', password)
    
    const response = await api.post<any>('/auth/login', params, {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    })
    const data = response.data || {}
    const resolvedToken = data.access_token || data.token || data.accessToken || ''
    
    return {
      access_token: resolvedToken,
      token_type: data.token_type || 'bearer',
      token: resolvedToken,
      accessToken: resolvedToken,
    }
  },
  
  getMe: async (): Promise<User> => {
    const response = await api.get<User>('/auth/me')
    return response.data
  },
}
