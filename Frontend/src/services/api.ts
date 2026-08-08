import axios from 'axios'
import { useAuthStore } from '../store/useAuthStore'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor to attach JWT token
api.interceptors.request.use(
  (config) => {
    const token = useAuthStore.getState().token
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor to handle authentication and format errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token expired or invalid — clear session and redirect to login
      useAuthStore.getState().logout()
      // Hard redirect so all in-flight requests are cancelled
      if (!window.location.pathname.startsWith('/upload')) {
        window.location.href = '/login'
      }
    }
    
    // Extract backend validation or HTTP exceptions if available
    const message =
      error.response?.data?.detail ||
      error.message ||
      'An unexpected error occurred'
      
    return Promise.reject(new Error(message))
  }
)
