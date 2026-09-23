import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useToastStore } from '../store/useToastStore'
import { useAuthStore } from '../store/useAuthStore'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card'
import { ThemeToggle } from '../components/ui/ThemeToggle'
import { api } from '../services/api'
import {
  GraduationCap,
  X,
  Lock,
  Loader2,
  UserCheck,
  ArrowRight,
  Check,
} from 'lucide-react'
import {
  verifyStudentIdentity,
  writeSubmissionSession,
  getStudentMe,
} from '../services/studentIdentity'

const STEPS = [
  { number: 1, label: 'Student Details' },
  { number: 2, label: 'Documents' },
  { number: 3, label: 'Processing' },
  { number: 4, label: 'Verification' },
  { number: 5, label: 'Complete' },
]

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
    const cleanEmail = email.trim().toLowerCase()
    if (!cleanEmail) {
      errors.email = 'Email address is required.'
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      errors.email = 'Enter a valid email address.'
    }
    setFieldErrors(errors)
    return Object.keys(errors).length === 0
  }
 
  // --- Continue handler — calls backend verify, then writes session ---
  const handleContinue = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate() || !token) return
 
    setIsVerifying(true)
    try {
      const cleanEmail = email.trim().toLowerCase()
      const result = await verifyStudentIdentity({
        token,
        student_name: studentName.trim(),
        register_number: registerNum.trim(),
        mobile_number: mobileNum.trim(),
        email: cleanEmail,
      })
 
      // Write temporary submission session to sessionStorage (no JWT, no login)
      writeSubmissionSession({
        batch_id: result.batch_id,
        batch_name: result.batch_name,
        class_id: result.class_id,
        class_name: result.class_name,
        upload_link_id: result.upload_link_id,
        token: result.token || token,
        register_number: registerNum.trim(),
        student_name: studentName.trim(),
        mobile_number: mobileNum.trim(),
        email: cleanEmail,
      })
 
      const batchId = result.batch_id
      if (!batchId || batchId === 'undefined' || batchId === 'null' || !batchId.trim()) {
        addToast('Upload link could not be generated.', 'error')
        return
      }

      // Navigate to documents upload page
      const isStudentPrefix = window.location.pathname.startsWith('/student')
      navigate(isStudentPrefix ? `/student/${batchId}/documents` : `/upload/${batchId}/documents`)
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
      <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4">
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
      <div className="flex min-h-screen flex-col bg-background text-foreground transition-colors duration-300">
        <header className="sticky top-0 z-50 flex h-16 w-full items-center justify-between border-b border-border bg-card/90 backdrop-blur-md px-4 sm:px-8 shadow-2xs">
          <div className="flex items-center gap-2.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary border border-primary/20 shadow-2xs">
              <GraduationCap className="h-5 w-5" />
            </div>
            <div>
              <span className="text-base font-extrabold tracking-tight text-foreground block leading-tight">
                ADMIEXTRACT
              </span>
              <span className="text-xs text-muted-foreground font-medium">
                Student Admission Portal
              </span>
            </div>
          </div>
          <ThemeToggle />
        </header>
        <div className="flex flex-1 flex-col items-center justify-center px-4 text-center">
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
      </div>
    )
  }

  // --- Identification form ---
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground transition-colors duration-300">
      {/* Header */}
      <header className="sticky top-0 z-50 flex h-16 w-full items-center justify-between border-b border-border bg-card/90 backdrop-blur-md px-4 sm:px-8 shadow-2xs">
        <div className="flex items-center gap-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary border border-primary/20 shadow-2xs">
            <GraduationCap className="h-5 w-5" />
          </div>
          <div>
            <span className="text-base font-extrabold tracking-tight text-foreground block leading-tight">
              ADMIEXTRACT
            </span>
            <span className="text-xs text-muted-foreground font-medium">
              Student Admission Portal
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <div className="hidden xs:flex items-center gap-2 text-xs font-semibold text-muted-foreground bg-secondary/80 px-3 py-1.5 rounded-lg border border-border shadow-2xs">
            <Lock className="h-3.5 w-3.5 text-primary shrink-0" />
            <span>Secure Upload Gateway</span>
          </div>
        </div>
      </header>

      {/* 5-Step Guided Flow Progress Stepper */}
      <div className="w-full max-w-2xl mx-auto px-4 pt-6 sm:pt-8 pb-4">
        <div className="relative flex items-center justify-between">
          <div className="absolute left-0 top-5 sm:top-5.5 h-0.5 w-full -translate-y-1/2 bg-border dark:bg-border/60" />
          <div
            className="absolute left-0 top-5 sm:top-5.5 h-0.5 -translate-y-1/2 bg-primary transition-all duration-300"
            style={{ width: '0%' }}
          />
          {STEPS.map((s) => {
            const active = s.number === 1
            const done = false
            return (
              <div key={s.number} className="relative z-10 flex flex-col items-center">
                <div
                  className={`flex h-10 w-10 sm:h-11 sm:w-11 items-center justify-center rounded-full border-2 font-bold text-xs sm:text-sm transition-all duration-200 ${
                    done
                      ? 'bg-primary border-primary text-primary-foreground'
                      : active
                      ? 'bg-primary border-primary text-primary-foreground shadow-md ring-4 ring-primary/20 dark:ring-primary/30'
                      : 'bg-card border-border text-muted-foreground'
                  }`}
                >
                  {done ? <Check className="h-5 w-5 stroke-[2.5]" /> : s.number}
                </div>
                <span
                  className={`hidden sm:block text-xs font-semibold mt-2 transition-colors ${
                    active ? 'text-primary font-bold' : 'text-muted-foreground'
                  }`}
                >
                  {s.label}
                </span>
              </div>
            )
          })}
        </div>
        {/* Mobile current step indicator badge */}
        <div className="sm:hidden text-center mt-3">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-primary/10 text-primary text-xs font-semibold border border-primary/20">
            <span>Step 1 of 5:</span>
            <span className="font-bold">Student Details</span>
          </span>
        </div>
      </div>

      {/* Main */}
      <main className="flex-1 flex items-center justify-center px-4 py-6 sm:py-10 sm:px-6 lg:px-8">
        <Card className="border border-border bg-card shadow-xl shadow-black/5 dark:shadow-black/30 w-full max-w-[580px] overflow-hidden rounded-2xl transition-colors duration-200">
          <div className="h-1.5 bg-gradient-to-r from-primary to-emerald-400 dark:to-lime-400" />

          <CardHeader className="text-center pt-7 sm:pt-8 pb-4 px-6 sm:px-8">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary mb-4 border border-primary/15 shadow-2xs">
              <UserCheck className="h-7 w-7" />
            </div>
            <CardTitle className="text-2xl sm:text-[1.65rem] font-bold text-foreground tracking-tight">
              Student Details
            </CardTitle>
            <CardDescription className="mt-2 text-sm text-muted-foreground leading-relaxed">
              {portalTitle || 'Document Upload Portal'}
              {batchName && (
                <>
                  {' '}— <span className="font-semibold text-primary">{batchName}</span>
                </>
              )}
            </CardDescription>
          </CardHeader>

          <CardContent className="px-6 sm:px-8 pb-8 sm:pb-9">
            {/* Info note */}
            <div className="flex items-start gap-3 bg-emerald-500/[0.08] dark:bg-emerald-950/30 border border-emerald-600/20 dark:border-emerald-700/40 rounded-xl p-3.5 sm:p-4 mb-6 text-xs sm:text-[13px] text-foreground/80 leading-relaxed shadow-2xs">
              <div className="p-1 rounded-md bg-emerald-500/15 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 shrink-0 mt-0.5">
                <Lock className="h-3.5 w-3.5" />
              </div>
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

            <form onSubmit={handleContinue} className="space-y-4 sm:space-y-5" noValidate>
              {/* Name */}
              <Input
                id="student-name"
                label="Student Name *"
                type="text"
                placeholder="e.g. Rahul Sharma"
                value={studentName}
                readOnly={isPreFilled}
                error={fieldErrors.name}
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
                className={isPreFilled ? 'bg-muted/50 cursor-not-allowed font-medium text-foreground' : ''}
              />

              {/* Register Number */}
              <Input
                id="register-number"
                label="Register Number *"
                type="text"
                placeholder="e.g. 24AM076"
                value={registerNum}
                readOnly={isPreFilled}
                error={fieldErrors.register}
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
                className={isPreFilled ? 'bg-muted/50 cursor-not-allowed font-medium text-foreground' : ''}
              />

              {/* Mobile Number */}
              <Input
                id="mobile-number"
                label="Mobile Number *"
                type="tel"
                placeholder="e.g. 9876543210"
                value={mobileNum}
                readOnly={isPreFilled}
                error={fieldErrors.mobile}
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
                className={isPreFilled ? 'bg-muted/50 cursor-not-allowed font-medium text-foreground' : ''}
              />

              {/* Email Address */}
              <Input
                id="email-address"
                label="Email Address *"
                type="email"
                placeholder="e.g. student@example.com"
                value={email}
                readOnly={isPreFilled}
                error={fieldErrors.email}
                onChange={(e) => {
                  if (isPreFilled) return
                  setEmail(e.target.value)
                  if (fieldErrors.email) setFieldErrors((p) => ({ ...p, email: '' }))
                }}
                helperText={
                  isPreFilled
                    ? 'Automatically populated from logged-in profile (Read Only)'
                    : 'Active email address for application updates.'
                }
                required
                className={isPreFilled ? 'bg-muted/50 cursor-not-allowed font-medium text-foreground' : ''}
              />

              <Button
                id="continue-btn"
                type="submit"
                variant="primary"
                className="w-full mt-2 sm:mt-3 h-12 rounded-xl text-base font-semibold shadow-md shadow-primary/20 hover:shadow-lg hover:shadow-primary/25 transition-all cursor-pointer flex items-center justify-center gap-2"
                disabled={isVerifying}
              >
                {isVerifying ? (
                  <>
                    <Loader2 className="h-5 w-5 animate-spin" />
                    <span>Verifying...</span>
                  </>
                ) : (
                  <>
                    <span>Continue</span>
                    <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-0.5" />
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
