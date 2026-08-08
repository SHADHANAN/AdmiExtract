import { api } from './api'

export interface VerifyIdentityPayload {
  token: string
  student_name: string
  register_number: string
  mobile_number: string
}

export interface VerifyIdentityResponse {
  batch_id: string
  batch_name: string
}

/** Session key used to persist the student's temporary submission context in sessionStorage. */
export const STUDENT_SESSION_KEY = 'student_submission_session'

export interface StudentSubmissionSession {
  batch_id: string
  batch_name: string
  register_number: string
  student_name: string
  mobile_number: string
}

/**
 * Calls the public identity verification endpoint.
 * Does NOT create any authentication token or login session.
 * Returns batch_id and batch_name on success; throws with a descriptive message on failure.
 */
export async function verifyStudentIdentity(
  payload: VerifyIdentityPayload
): Promise<VerifyIdentityResponse> {
  const response = await api.post('/student/verify', payload)
  return response.data as VerifyIdentityResponse
}

/** Write the temporary submission session to sessionStorage (cleared on tab close). */
export function writeSubmissionSession(session: StudentSubmissionSession): void {
  sessionStorage.setItem(STUDENT_SESSION_KEY, JSON.stringify(session))
}

/** Read the temporary submission session from sessionStorage. Returns null if not present. */
export function readSubmissionSession(): StudentSubmissionSession | null {
  const raw = sessionStorage.getItem(STUDENT_SESSION_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as StudentSubmissionSession
  } catch {
    return null
  }
}

/** Clear the session (called after successful final submission). */
export function clearSubmissionSession(): void {
  sessionStorage.removeItem(STUDENT_SESSION_KEY)
}

export interface StudentProfile {
  student_name: string
  register_number: string
  mobile_number: string
  email?: string | null
}

/**
 * Fetches current authenticated student profile via GET /students/me.
 */
export async function getStudentMe(): Promise<StudentProfile> {
  const response = await api.get('/students/me')
  return response.data as StudentProfile
}

