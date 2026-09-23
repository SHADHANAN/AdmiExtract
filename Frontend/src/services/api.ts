import axios from 'axios'
import { useAuthStore } from '../store/useAuthStore'

const resolveApiBaseUrl = (): string => {
  const envUrl = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL
  if (envUrl && typeof envUrl === 'string' && envUrl.trim()) {
    return envUrl.trim().replace(/\/+$/, '')
  }
  if (typeof window !== 'undefined' && window.location.hostname) {
    return `http://${window.location.hostname}:8000`
  }
  return 'http://localhost:8000'
}

export const API_BASE_URL = resolveApiBaseUrl()

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
    // Network or connection failure
    if (!error.response) {
      const errMsg = error?.message || ''
      const isCorsOrNetwork =
        errMsg.toLowerCase().includes('network error') ||
        errMsg.toLowerCase().includes('failed to fetch') ||
        error.code === 'ERR_NETWORK'

      if (isCorsOrNetwork) {
        const currentOrigin = typeof window !== 'undefined' ? window.location.origin : ''
        return Promise.reject(
          new Error(
            `Unable to connect to backend at ${API_BASE_URL}. If the server is running, check CORS configuration for origin '${currentOrigin}'.`
          )
        )
      }

      return Promise.reject(
        new Error(errMsg || `Connection failure to backend at ${API_BASE_URL}.`)
      )
    }

    const status = error.response.status

    if (status === 401) {
      // Clear credentials on unauthorized access
      useAuthStore.getState().logout()
      // Only redirect if not already on the login or public upload page
      if (
        window.location.pathname !== '/login' &&
        !window.location.pathname.startsWith('/upload') &&
        !window.location.pathname.startsWith('/student')
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

