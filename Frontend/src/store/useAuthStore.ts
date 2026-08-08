import { create } from 'zustand'
import type { AuthState, User } from '../types'

export const useAuthStore = create<AuthState>((set) => {
  // Initialize from localStorage
  const storedToken = localStorage.getItem('token')
  const storedUser = localStorage.getItem('user')

  let parsedUser: User | null = null
  if (storedUser) {
    try {
      parsedUser = JSON.parse(storedUser)
    } catch {
      localStorage.removeItem('user')
    }
  }

  return {
    user: parsedUser,
    token: storedToken,
    isAuthenticated: !!storedToken && !!parsedUser,
    login: (token, user) => {
      localStorage.setItem('token', token)
      localStorage.setItem('user', JSON.stringify(user))
      set({ token, user, isAuthenticated: true })
    },
    logout: () => {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      set({ token: null, user: null, isAuthenticated: false })
    },
  }
})
