/**
 * Utility for resolving the authoritative public frontend application URL
 * and constructing cross-network student upload links.
 */

export const getPublicFrontendUrl = (): string => {
  // 1. Primary: configured public app URL in environment
  const envUrl =
    import.meta.env.VITE_PUBLIC_APP_URL ||
    import.meta.env.VITE_APP_URL

  if (envUrl && typeof envUrl === 'string' && envUrl.trim()) {
    return envUrl.trim().replace(/\/+$/, '')
  }

  // 2. Secondary fallback: current browser location origin (if not SSR)
  if (typeof window !== 'undefined' && window.location && window.location.origin) {
    return window.location.origin.replace(/\/+$/, '')
  }

  // 3. Ultimate development fallback
  return 'http://localhost:5173'
}

/**
 * Returns the public Student Upload Link formatted as:
 *   PUBLIC_FRONTEND_URL + "/student/" + TOKEN
 *
 * Guaranteed never to return localhost or internal LAN IP when
 * VITE_PUBLIC_APP_URL is configured with a public URL.
 */
export const getStudentUploadUrl = (tokenOrSlug: string): string => {
  if (!tokenOrSlug) return ''
  const baseUrl = getPublicFrontendUrl()
  const cleanToken = encodeURIComponent(tokenOrSlug.trim())
  return `${baseUrl}/student/${cleanToken}`
}
