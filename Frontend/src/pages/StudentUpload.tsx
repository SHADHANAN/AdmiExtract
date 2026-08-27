import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useToastStore } from '../store/useToastStore'
import { useAuthStore } from '../store/useAuthStore'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card'
import { api } from '../services/api'
import {
  GraduationCap,
  X,
  Lock,
  Loader2,
  ChevronRight,
  UserCheck,
} from 'lucide-react'
import {
  verifyStudentIdentity,
  writeSubmissionSession,
  getStudentMe,
} from '../services/studentIdentity'

/**
 * StudentUpload — public identification form at /upload/:token
 *
 * If a student is logged in, their details (Student Name, Register Number,
 * Mobile Number, Email) are automatically fetched via GET /students/me and pre-filled.
 * Students cannot edit pre-filled profile fields (Read Only).
 */
export const StudentUpload: React.FC = () => {
  const { token } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const { addToast } = useToastStore()

  // Portal metadata resolved from the public API
  const [portalTitle, setPortalTitle] = useState<string>('')
  const [batchName, setBatchName] = useState<string>('')
  const [isLoadingToken, setIsLoadingToken] = useState(true)
  const [errorStatus, setErrorStatus] = useState<number | null>(null)
  const [errorMessage, setErrorMessage] = useState<string>('')
 
  // Student identity form fields
  const [studentName, setStudentName] = useState('')
  const [registerNum, setRegisterNum] = useState('')
  const [mobileNum, setMobileNum] = useState('')
  const [email, setEmail] = useState('')
  const [isPreFilled, setIsPreFilled] = useState(false)
 
  // Submission state
  const [isVerifying, setIsVerifying] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  // Auto-fill student profile if authenticated user is logged in
  useEffect(() => {
    const fetchStudentProfile = async () => {
      const tokenInStore = useAuthStore.getState().token
      const currentUser = useAuthStore.getState().user
      if (tokenInStore && currentUser?.role === 'student') {
        try {
          const profile = await getStudentMe()
          if (profile) {
            if (profile.student_name) setStudentName(profile.student_name)
            if (profile.register_number) setRegisterNum(profile.register_number)
            if (profile.mobile_number) setMobileNum(profile.mobile_number)
            if (profile.email) setEmail(profile.email)
            setIsPreFilled(true)
          }
        } catch {
          // Token is invalid — do NOT auto-fill
          setIsPreFilled(false)
          setStudentName('')
          setRegisterNum('')
          setMobileNum('')
          setEmail('')
        }
      }
    }
    fetchStudentProfile()
  }, [])
 
  // Resolve the upload link on mount to get the portal title and validate it is active
  useEffect(() => {
    const resolveToken = async () => {
      setIsLoadingToken(true)
      try {
        const linkRes = await api.get(`/upload-links/${token}`)
        const linkData = linkRes.data
        setPortalTitle(linkData.title || 'Student Document Upload Portal')
        setBatchName(linkData.batch_name || '')
        setErrorStatus(null)
      } catch (err: any) {
        if (!err.response) {
          setErrorStatus(0)
          setErrorMessage('Unable to connect to the server.')
        } else {
          const status = err.response.status
          const detail = err.response.data?.detail
          setErrorStatus(status || 500)
          setErrorMessage(detail || 'Internal server error.')
        }
      } finally {
        setIsLoadingToken(false)
      }
    }
 
    if (token) resolveToken()
  }, [token])
 
  // --- Validation helpers ---
  const validate = (): boolean => {
    const errors: Record<string, string> = {}
    if (!studentName.trim()) errors.name = 'Full name is required.'
    if (!registerNum.trim()) errors.register = 'Register number is required.'
    if (!mobileNum.trim() || mobileNum.trim().length < 10)
      errors.mobile = 'Enter a valid 10-digit mobile number.'
    setFieldErrors(errors)
    return Object.keys(errors).length === 0
  }
 
  // --- Continue handler — calls backend verify, then writes session ---
  const handleContinue = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate() || !token) return
 
    setIsVerifying(true)
    try {
      const result = await verifyStudentIdentity({
        token,
        student_name: studentName.trim(),
        register_number: registerNum.trim(),
        mobile_number: mobileNum.trim(),
      })
 
      // Write temporary submission session to sessionStorage (no JWT, no login)
      writeSubmissionSession({
        batch_id: result.batch_id,
        batch_name: result.batch_name,
        class_id: result.class_id,
        class_name: result.class_name,
        register_number: registerNum.trim(),
        student_name: studentName.trim(),
        mobile_number: mobileNum.trim(),
      })
 
      const batchId = result.batch_id
      if (!batchId || batchId === 'undefined' || batchId === 'null' || !batchId.trim()) {
        addToast('Upload link could not be generated.', 'error')
        return
      }

      // Navigate to documents upload page
      navigate(`/upload/${batchId}/documents`)
    } catch (err: any) {
      const message: string =
        err?.message ||
        'Verification failed. Please check your details and try again.'
      addToast(`❌ ${message}`, 'error')
    } finally {
      setIsVerifying(false)
    }
  }
 
  // --- Loading skeleton ---
  if (isLoadingToken) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-[#f9fafb] dark:bg-[#0b0f19] px-4">
        <Loader2 className="h-10 w-10 text-primary animate-spin" />
        <p className="text-sm text-muted-foreground mt-4 font-medium">
          Loading admissions portal...
        </p>
      </div>
    )
  }
 
  // --- Expired / invalid / disabled link ---
  if (errorStatus !== null) {
    let errorTitle = 'Upload Link Expired'
    let errorDesc = errorMessage
    
    if (errorStatus === 404) {
      errorTitle = 'Invalid Link'
      errorDesc = errorMessage || 'Invalid upload link.'
    } else if (errorStatus === 403) {
      errorTitle = 'Link Disabled'
      errorDesc = errorMessage || 'Upload link has been disabled.'
    } else if (errorStatus === 410) {
      errorTitle = 'Upload Link Expired'
      errorDesc = errorMessage || 'Upload link has expired.'
    } else if (errorStatus === 0) {
      errorTitle = 'Connection Error'
      errorDesc = errorMessage || 'Unable to connect to the server.'
    } else {
      errorTitle = 'Server Error'
      errorDesc = errorMessage || 'Internal server error.'
    }
 
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-[#f9fafb] dark:bg-[#0b0f19] px-4 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-destructive/10 text-destructive mb-6 shadow-sm border border-destructive/20 animate-pulse">
          <X className="h-7 w-7" />
        </div>
        <h2 className="text-3xl font-extrabold tracking-tight text-foreground">
          {errorTitle}
        </h2>
        <p className="text-sm text-muted-foreground mt-2 max-w-sm">
          {errorDesc}
        </p>
      </div>
    )
  }

  // --- Identification form ---
  return (
    <div className="flex min-h-screen flex-col bg-[#f9fafb] dark:bg-[#080d16] transition-colors duration-300">
      {/* Header */}
      <header className="sticky top-0 z-50 flex h-16 w-full items-center justify-between border-b border-border bg-card/80 backdrop-blur-md px-6 md:px-8 shadow-2xs">
        <div className="flex items-center gap-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-md shadow-primary/20">
            <GraduationCap className="h-5 w-5" />
          </div>
          <div>
            <span className="text-base font-extrabold tracking-tight text-foreground">
              Smart Admissions
            </span>
            <span className="ml-2 text-xs font-semibold px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/15">
              Document Portal
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs font-bold text-muted-foreground bg-secondary/80 px-3 py-1.5 rounded-xl border border-border/80">
          <Lock className="h-3.5 w-3.5 text-primary shrink-0" />
          <span>Secure Upload Gateway</span>
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 flex items-center justify-center px-4 py-12 sm:px-6 lg:px-8">
        <Card className="border border-border bg-card shadow-xl w-full max-w-md overflow-hidden rounded-2xl">
          <div className="h-2 bg-gradient-to-r from-primary to-indigo-500" />

          <CardHeader className="text-center pt-8 pb-4">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary mb-4 border border-primary/10">
              <UserCheck className="h-7 w-7" />
            </div>
            <CardTitle className="text-2xl font-black text-foreground">
              Student Identification
            </CardTitle>
            <CardDescription className="mt-1.5 leading-relaxed">
              {portalTitle || 'Document Upload Portal'}
              {batchName && (
                <>
                  {' '}— <span className="font-semibold text-primary">{batchName}</span>
                </>
              )}
            </CardDescription>
          </CardHeader>

          <CardContent className="px-6 pb-8">
            {/* Info note */}
            <div className="flex items-start gap-3 bg-primary/5 border border-primary/15 rounded-xl px-4 py-3 mb-6 text-xs text-muted-foreground">
              <Lock className="h-3.5 w-3.5 text-primary shrink-0 mt-0.5" />
              <p className="leading-relaxed">
                {isPreFilled ? (
                  <span className="font-medium text-foreground">
                    Your account details have been automatically populated from your profile (Read Only).
                  </span>
                ) : (
                  <span>
                    Enter your details exactly as registered. Your register number will be verified
                    against the admission batch student list.
                  </span>
                )}
              </p>
            </div>

            <form onSubmit={handleContinue} className="space-y-5" noValidate>
              {/* Student Name */}
              <div className="space-y-1.5">
                <Input
                  id="student-name"
                  label="Student Name"
                  type="text"
                  placeholder="e.g. Rahul Sharma"
                  value={studentName}
                  readOnly={isPreFilled}
                  onChange={(e) => {
                    if (isPreFilled) return
                    setStudentName(e.target.value)
                    if (fieldErrors.name) setFieldErrors((p) => ({ ...p, name: '' }))
                  }}
                  helperText={
                    isPreFilled
                      ? 'Automatically populated from logged-in profile (Read Only)'
                      : 'Enter your name exactly as in your admission records.'
                  }
                  required
                  className={isPreFilled ? 'bg-muted/40 cursor-not-allowed font-medium text-foreground' : ''}
                />
                {fieldErrors.name && (
                  <p className="text-xs text-destructive font-medium pl-1">{fieldErrors.name}</p>
                )}
              </div>

              {/* Register Number */}
              <div className="space-y-1.5">
                <Input
                  id="register-number"
                  label="Register Number"
                  type="text"
                  placeholder="e.g. 24AM076"
                  value={registerNum}
                  readOnly={isPreFilled}
                  onChange={(e) => {
                    if (isPreFilled) return
                    setRegisterNum(e.target.value)
                    if (fieldErrors.register) setFieldErrors((p) => ({ ...p, register: '' }))
                  }}
                  helperText={
                    isPreFilled
                      ? 'Automatically populated from logged-in profile (Read Only)'
                      : 'Your official admission number from the offer letter.'
                  }
                  required
                  className={isPreFilled ? 'bg-muted/40 cursor-not-allowed font-medium text-foreground' : ''}
                />
                {fieldErrors.register && (
                  <p className="text-xs text-destructive font-medium pl-1">
                    {fieldErrors.register}
                  </p>
                )}
              </div>

              {/* Mobile Number */}
              <div className="space-y-1.5">
                <Input
                  id="mobile-number"
                  label="Mobile Number"
                  type="tel"
                  placeholder="e.g. 9876543210"
                  value={mobileNum}
                  readOnly={isPreFilled}
                  onChange={(e) => {
                    if (isPreFilled) return
                    setMobileNum(e.target.value)
                    if (fieldErrors.mobile) setFieldErrors((p) => ({ ...p, mobile: '' }))
                  }}
                  helperText={
                    isPreFilled
                      ? 'Automatically populated from logged-in profile (Read Only)'
                      : '10-digit mobile number for submission confirmation.'
                  }
                  required
                  className={isPreFilled ? 'bg-muted/40 cursor-not-allowed font-medium text-foreground' : ''}
                />
                {fieldErrors.mobile && (
                  <p className="text-xs text-destructive font-medium pl-1">
                    {fieldErrors.mobile}
                  </p>
                )}
              </div>

              {/* Email (Read Only if present/pre-filled) */}
              {(email || isPreFilled) && (
                <div className="space-y-1.5">
                  <Input
                    id="email-address"
                    label="Email"
                    type="email"
                    placeholder="student@example.com"
                    value={email}
                    readOnly={isPreFilled}
                    onChange={(e) => {
                      if (isPreFilled) return
                      setEmail(e.target.value)
                    }}
                    helperText="Automatically populated from logged-in profile (Read Only)"
                    className={isPreFilled ? 'bg-muted/40 cursor-not-allowed font-medium text-foreground' : ''}
                  />
                </div>
              )}

              <Button
                id="continue-btn"
                type="submit"
                variant="primary"
                className="w-full mt-2 gap-2 py-6 rounded-xl text-base shadow-md shadow-primary/10 hover:shadow-lg transition-all cursor-pointer"
                disabled={isVerifying}
              >
                {isVerifying ? (
                  <>
                    <Loader2 className="h-4.5 w-4.5 animate-spin" />
                    Verifying...
                  </>
                ) : (
                  <>
                    Continue
                    <ChevronRight className="h-5 w-5" />
                  </>
                )}
              </Button>
            </form>
          </CardContent>
        </Card>
      </main>
    </div>
  )
}
