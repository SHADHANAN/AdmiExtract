import axios from 'axios'
import { useAuthStore } from '../store/useAuthStore'

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_URL ||
  (typeof window !== 'undefined' && window.location.hostname
    ? `http://${window.location.hostname}:8000`
    : 'http://localhost:8000')

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
    // Network or connection failure (backend unreachable)
    if (!error.response) {
      return Promise.reject(
        new Error(`Backend unreachable at ${API_BASE_URL}. Please ensure the server is running.`)
      )
    }

    const status = error.response.status

    if (status === 401) {
      // Clear credentials on unauthorized access
      useAuthStore.getState().logout()
      // Only redirect if not already on the login or public upload page
      if (
        window.location.pathname !== '/login' &&
        !window.location.pathname.startsWith('/upload')
      ) {
        window.location.href = '/login'
      }
    }

    // Preserve useful backend distinction
    let message = ''
    if (typeof error.response.data?.detail === 'string') {
      message = error.response.data.detail
    } else if (Array.isArray(error.response.data?.detail)) {
      message = error.response.data.detail
        .map((d: any) => d.msg || JSON.stringify(d))
        .join(', ')
    } else if (status === 401) {
      message = 'Invalid username or password'
    } else if (status === 403) {
      message = 'Not authorized to perform this action'
    } else if (status === 404) {
      message = 'Requested endpoint not found'
    } else if (status === 422) {
      message = 'Validation error: please check input format'
    } else if (status >= 500) {
      message = 'Internal server error occurred'
    } else {
      message = error.message || 'An unexpected error occurred'
    }

    return Promise.reject(new Error(message))
  }
)

