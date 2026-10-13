import React, { useState, useEffect, useCallback } from 'react'
import { useParams, useSearchParams, useNavigate } from 'react-router-dom'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { useToastStore } from '../store/useToastStore'
import { useAuthStore } from '../store/useAuthStore'
import {
  verificationService,
  type DocumentFieldVerification,
  type PublicVerificationTokenResponse,
  type PublicVerificationSessionResponse,
} from '../services/verificationService'
import {
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  Clock,
  Sparkles,
  Edit3,
  Check,
  RefreshCw,
  FileCheck2,
  GraduationCap,
  ArrowLeft,
  XCircle,
  Lock,
  ArrowRight,
  User,
  Hash,
} from 'lucide-react'

export const StudentVerification: React.FC = () => {
  const { token: routeToken } = useParams<{ token?: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { addToast } = useToastStore()

  // Common verification parameters from URL query
  const queryBatchId = searchParams.get('batch_id') || searchParams.get('batch') || ''
  const queryExtractionId = searchParams.get('extraction_id') || ''
  const isCommonMode = !routeToken && !searchParams.get('token')
  const urlToken = routeToken || searchParams.get('token') || null

  // Effective token from URL path, query param, or common verified session
  const [effectiveToken, setEffectiveToken] = useState<string | null>(urlToken)

  const [commonBatchId, setCommonBatchId] = useState(queryBatchId)
  const [showBatchInput, setShowBatchInput] = useState(!queryBatchId)

  const [loading, setLoading] = useState(!isCommonMode)
  const [submitting, setSubmitting] = useState(false)
  const [errorStatus, setErrorStatus] = useState<number | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Public Session metadata & Identity Verification Gate
  const [sessionInfo, setSessionInfo] = useState<PublicVerificationSessionResponse | null>(null)
  const [isIdentityVerified, setIsIdentityVerified] = useState<boolean>(false)
  const [identityName, setIdentityName] = useState('')
  const [identityRegisterNo, setIdentityRegisterNo] = useState('')
  const [identityError, setIdentityError] = useState<string | null>(null)
  const [identityLoading, setIdentityLoading] = useState(false)

  // Verified Session extraction details
  const [sessionMeta, setSessionMeta] = useState<PublicVerificationTokenResponse | null>(null)
  const [verifications, setVerifications] = useState<DocumentFieldVerification[]>([])
  const [editedValues, setEditedValues] = useState<Record<string, string>>({})
  const [generalComment, setGeneralComment] = useState('')
  const [isSubmittedSuccess, setIsSubmittedSuccess] = useState(false)

  // Post-submission navigation and tab closing states
  const [navigateCountdown, setNavigateCountdown] = useState<number | null>(null)
  const [tabCloseBlocked, setTabCloseBlocked] = useState<boolean>(false)

  // Check if navigating back to a safe internal page is possible
  const canNavigateBack = Boolean(
    window.history.length > 1 &&
    document.referrer &&
    document.referrer.startsWith(window.location.origin) &&
    !document.referrer.includes('/student-verification')
  )

  // Countdown timer for automatic navigation back after successful submission
  useEffect(() => {
    if (navigateCountdown === null || navigateCountdown <= 0) return
    const timer = setInterval(() => {
      setNavigateCountdown((prev) => {
        if (prev === null || prev <= 1) {
          clearInterval(timer)
          window.history.back()
          return 0
        }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [navigateCountdown])

  // Synchronize route/query token or batch scope changes from URL
  useEffect(() => {
    if (urlToken) {
      setEffectiveToken(urlToken)
      setVerifications([])
      setEditedValues({})
      setSessionMeta(null)
      setSessionInfo(null)
      setIsIdentityVerified(false)
      setIsSubmittedSuccess(false)
      setErrorMessage(null)
      setErrorStatus(null)
    } else {
      setCommonBatchId(queryBatchId)
      setShowBatchInput(!queryBatchId)
    }
  }, [urlToken, queryBatchId, queryExtractionId])

  const loadData = useCallback(async () => {
    // In Common Mode, if session is not yet identified in this browser, don't execute background session loading
    if (isCommonMode) {
      if (!effectiveToken || sessionStorage.getItem(`verify_common_verified_${effectiveToken}`) !== 'true') {
        setLoading(false)
        return
      }
    }

    try {
      setLoading(true)
      setErrorStatus(null)
      setErrorMessage(null)

      if (effectiveToken) {
        // Check if verified via common mode
        const isCommonVerified = sessionStorage.getItem(`verify_common_verified_${effectiveToken}`) === 'true'
        if (isCommonVerified) {
          try {
            const data = await verificationService.getPublicVerification(effectiveToken)
            setSessionMeta(data)
            setVerifications(data.fields || [])
            setIsIdentityVerified(true)
            const initialEdits: Record<string, string> = {}
            data.fields.forEach((item) => {
              const initialVal = item.student_value ?? (item.ai_value && item.ai_value !== 'NOT_AVAILABLE' && item.ai_value !== 'NOT_FOUND' ? item.ai_value : '')
              initialEdits[item.id] = String(initialVal ?? '')
            })
            setEditedValues(initialEdits)
            setLoading(false)
            return
          } catch {
            sessionStorage.removeItem(`verify_common_verified_${effectiveToken}`)
          }
        }

        // Check if credentials are already verified in the current browser session
        const cached = sessionStorage.getItem(`verify_identity_${effectiveToken}`)
        if (cached) {
          try {
            const parsed = JSON.parse(cached)
            if (parsed.student_name && parsed.register_number) {
              setIdentityName(parsed.student_name)
              setIdentityRegisterNo(parsed.register_number)
              const data = await verificationService.validateIdentity(effectiveToken, parsed)
              setSessionMeta(data)
              setVerifications(data.fields || [])
              setIsIdentityVerified(true)
              const initialEdits: Record<string, string> = {}
              data.fields.forEach((item) => {
                const initialVal = item.student_value ?? (item.ai_value && item.ai_value !== 'NOT_AVAILABLE' && item.ai_value !== 'NOT_FOUND' ? item.ai_value : '')
                initialEdits[item.id] = String(initialVal ?? '')
              })
              setEditedValues(initialEdits)
              setLoading(false)
              return
            }
          } catch {
            sessionStorage.removeItem(`verify_identity_${effectiveToken}`)
          }
        }

        // Validate token existence, expiry, and status without exposing sensitive personal info
        const session = await verificationService.getSessionInfo(effectiveToken)
        setSessionInfo(session)
        setIsIdentityVerified(false)
      } else {
        // Authenticated student user fallback
        const authUser = useAuthStore.getState().user
        if (authUser) {
          const data = await verificationService.getStudentVerifications(
            undefined,
            queryBatchId || undefined,
            queryExtractionId || undefined
          )
          setVerifications(data)
          setIsIdentityVerified(true)
          const initialEdits: Record<string, string> = {}
          data.forEach((item) => {
            const initialVal = item.student_value ?? (item.ai_value && item.ai_value !== 'NOT_AVAILABLE' && item.ai_value !== 'NOT_FOUND' ? item.ai_value : '')
            initialEdits[item.id] = String(initialVal ?? '')
          })
          setEditedValues(initialEdits)
        } else {
          setErrorStatus(400)
          setErrorMessage('No verification session token found. Please use the link provided on your admission receipt or email.')
        }
      }
    } catch (err: any) {
      const status = err?.response?.status || 500
      const detail = err?.response?.data?.detail || err?.message || 'Failed to load verification session.'
      setErrorStatus(status)
      setErrorMessage(detail)
    } finally {
      setLoading(false)
    }
  }, [effectiveToken, isCommonMode, queryBatchId, queryExtractionId])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Handler for Common Verification: Identify student (Name + Reg No + Batch Scope)
  // Directly validates identity on the backend without OTP
  const handleIdentifyCommonStudent = async (e: React.FormEvent) => {
    e.preventDefault()
    const nameTrimmed = identityName.trim()
    const regTrimmed = identityRegisterNo.trim()
    if (!nameTrimmed || !regTrimmed) {
      setIdentityError('Please enter both your Student Name and Register Number.')
      return
    }

    try {
      setIdentityLoading(true)
      setIdentityError(null)
      const res = await verificationService.identifyCommonStudent({
        student_name: nameTrimmed,
        register_number: regTrimmed,
        batch_id: commonBatchId.trim() || undefined,
        extraction_request_id: queryExtractionId.trim() || undefined,
      })

      setEffectiveToken(res.session_token)
      sessionStorage.setItem(`verify_common_verified_${res.session_token}`, 'true')

      // Directly load authenticated student's extracted fields
      const data = await verificationService.getPublicVerification(res.session_token)
      setSessionMeta(data)
      setVerifications(data.fields || [])
      const initialEdits: Record<string, string> = {}
      data.fields.forEach((item) => {
        const initialVal = item.student_value ?? (item.ai_value && item.ai_value !== 'NOT_AVAILABLE' && item.ai_value !== 'NOT_FOUND' ? item.ai_value : '')
        initialEdits[item.id] = String(initialVal ?? '')
      })
      setEditedValues(initialEdits)
      setIsIdentityVerified(true)
      addToast('Identity verified! Please review your extracted details.', 'success')
    } catch (err: any) {
      const status = err?.response?.status
      const detail = err?.response?.data?.detail || ''
      if (status === 429) {
        setIdentityError(
          'Too many failed verification attempts. Please wait 15 minutes before trying again or contact admissions staff.'
        )
      } else if (status === 400 && detail.toLowerCase().includes('duplicate register number')) {
        setShowBatchInput(true)
        setIdentityError(detail)
      } else if (status === 401) {
        setIdentityError(detail || 'Student name or register number does not match registered records.')
      } else if (status === 404) {
        setIdentityError(detail || 'No extraction records are available for verification for this student.')
      } else {
        setIdentityError(detail || 'Verification request failed. Please check your details.')
      }
    } finally {
      setIdentityLoading(false)
    }
  }

  // Handler for Legacy Token Identity Validation
  const handleValidateIdentity = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!effectiveToken) return
    const nameTrimmed = identityName.trim()
    const regTrimmed = identityRegisterNo.trim()
    if (!nameTrimmed || !regTrimmed) {
      setIdentityError('Please enter both your Student Name and Register Number.')
      return
    }

    try {
      setIdentityLoading(true)
      setIdentityError(null)
      const data = await verificationService.validateIdentity(effectiveToken, {
        student_name: nameTrimmed,
        register_number: regTrimmed,
      })
      setSessionMeta(data)
      setVerifications(data.fields || [])
      const initialEdits: Record<string, string> = {}
      data.fields.forEach((item) => {
        const initialVal = item.student_value ?? (item.ai_value && item.ai_value !== 'NOT_AVAILABLE' && item.ai_value !== 'NOT_FOUND' ? item.ai_value : '')
        initialEdits[item.id] = String(initialVal ?? '')
      })
      setEditedValues(initialEdits)
      setIsIdentityVerified(true)
      sessionStorage.setItem(
        `verify_identity_${effectiveToken}`,
        JSON.stringify({ student_name: nameTrimmed, register_number: regTrimmed })
      )
      addToast('Identity verified successfully! Please review your extracted details.', 'success')
    } catch (err: any) {
      const status = err?.response?.status
      if (status === 429) {
        setIdentityError(
          'Too many failed attempts. Please wait 15 minutes before trying again or contact admissions staff.'
        )
      } else if (status === 401) {
        setIdentityError(
          'Student name or register number does not match this verification link. Please check your details.'
        )
      } else {
        setIdentityError(err?.response?.data?.detail || 'Verification failed. Please check your credentials.')
      }
    } finally {
      setIdentityLoading(false)
    }
  }

  const handleInputChange = (id: string, val: string) => {
    setEditedValues((prev) => ({ ...prev, [id]: val }))
  }

  const handleCloseTab = () => {
    window.close()
    setTimeout(() => {
      if (!window.closed) {
        setTabCloseBlocked(true)
      }
    }, 400)
  }

  const handleConfirmAll = async () => {
    try {
      setSubmitting(true)
      const items = verifications.map((v) => ({
        verification_id: v.id,
        is_confirmed: true,
        corrected_value: v.ai_value,
      }))

      if (isCommonMode && effectiveToken) {
        const res = await verificationService.submitCommonVerification({
          session_token: effectiveToken,
          fields: items,
          general_comment: generalComment || 'Confirmed by student via verification link',
        })
        setSessionMeta(res)
        setVerifications(res.fields || [])
      } else if (effectiveToken) {
        const res = await verificationService.submitPublicVerification(effectiveToken, {
          fields: items,
          general_comment: generalComment || 'Confirmed by student via verification link',
        })
        setSessionMeta(res)
        setVerifications(res.fields || [])
      } else {
        const res = await verificationService.submitStudentVerification({
          fields: items,
          general_comment: generalComment || 'Confirmed by student',
        })
        setVerifications(res)
      }

      setIsSubmittedSuccess(true)
      if (canNavigateBack) {
        setNavigateCountdown(3)
      }
      addToast('Verification submitted successfully.', 'success')
    } catch (err: any) {
      addToast(err?.response?.data?.detail || 'Failed to submit confirmation.', 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSubmitCorrection = async () => {
    try {
      setSubmitting(true)
      const items = verifications.map((v) => {
        const currentVal = editedValues[v.id]
        const isSame = String(currentVal ?? '').trim() === String(v.ai_value ?? '').trim()
        return {
          verification_id: v.id,
          is_confirmed: isSame,
          corrected_value: isSame ? v.ai_value : currentVal,
        }
      })

      if (isCommonMode && effectiveToken) {
        const res = await verificationService.submitCommonVerification({
          session_token: effectiveToken,
          fields: items,
          general_comment: generalComment,
        })
        setSessionMeta(res)
        setVerifications(res.fields || [])
      } else if (effectiveToken) {
        const res = await verificationService.submitPublicVerification(effectiveToken, {
          fields: items,
          general_comment: generalComment,
        })
        setSessionMeta(res)
        setVerifications(res.fields || [])
      } else {
        const res = await verificationService.submitStudentVerification({
          fields: items,
          general_comment: generalComment,
        })
        setVerifications(res)
      }

      setIsSubmittedSuccess(true)
      if (canNavigateBack) {
        setNavigateCountdown(3)
      }
      addToast('Verification submitted successfully.', 'success')
    } catch (err: any) {
      addToast(err?.response?.data?.detail || 'Failed to submit verification.', 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const formatFieldName = (key?: string) => {
    if (!key) return '—'
    return key
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase())
  }

  const getStatusBadge = (status: string, fieldState?: string) => {
    if (status === 'STUDENT_VERIFIED') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
          <CheckCircle2 className="w-3.5 h-3.5" /> {fieldState === 'MANUALLY_ENTERED' ? 'Manually Supplied' : 'Verified by You'}
        </span>
      )
    }
    if (status === 'STUDENT_CONFIRMED') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20">
          <FileCheck2 className="w-3.5 h-3.5" /> Confirmed by You
        </span>
      )
    }
    if (status === 'STAFF_APPROVED') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
          <CheckCircle2 className="w-3.5 h-3.5" /> Staff Approved
        </span>
      )
    }
    if (status === 'CORRECTION_REQUESTED') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
          <Clock className="w-3.5 h-3.5" /> Correction Pending Review
        </span>
      )
    }
    if (status === 'STAFF_REJECTED') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20">
          <AlertCircle className="w-3.5 h-3.5" /> Staff Rejected
        </span>
      )
    }

    if (fieldState === 'MANUALLY_ENTERED') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-700 dark:text-blue-400 border border-blue-500/20">
          <CheckCircle2 className="w-3.5 h-3.5" /> Manually Supplied
        </span>
      )
    }
    if (fieldState === 'NOT_FOUND') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-600 dark:text-slate-400 border border-slate-500/20">
          <AlertCircle className="w-3.5 h-3.5 text-slate-500" /> Not Found
        </span>
      )
    }
    if (fieldState === 'DOCUMENT_MISSING' || fieldState === 'SOURCE_DOCUMENT_MISSING') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20">
          <AlertCircle className="w-3.5 h-3.5 text-amber-600" /> Document Missing
        </span>
      )
    }
    if (fieldState === 'EXTRACTION_FAILED' || fieldState === 'AI_EXTRACTION_FAILED' || fieldState === 'OCR_FAILED') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-700 dark:text-rose-400 border border-rose-500/20">
          <XCircle className="w-3.5 h-3.5 text-rose-600" /> Extraction Failed
        </span>
      )
    }

    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-600 dark:text-slate-400 border border-slate-500/20">
        <Sparkles className="w-3.5 h-3.5" /> AI Extracted
      </span>
    )
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950">
        <div className="flex flex-col items-center gap-3">
          <RefreshCw className="w-8 h-8 text-primary animate-spin" />
          <p className="text-sm font-medium text-slate-600 dark:text-slate-400">
            Loading secure verification session...
          </p>
        </div>
      </div>
    )
  }

  // Error Banner State
  if (errorStatus !== null && errorStatus !== 200) {
    let title = 'Verification Session Error'
    let desc = errorMessage || 'Unable to load verification session.'
    let isExpired = false

    if (errorStatus === 404) {
      title = 'Invalid Verification Link'
      desc = errorMessage || 'The verification link is invalid or could not be found.'
    } else if (errorStatus === 410) {
      title = 'Verification Link Expired'
      desc = errorMessage || 'This verification link has expired. Please contact admissions staff.'
      isExpired = true
    } else if (errorStatus === 403) {
      title = 'Verification Link Revoked'
      desc = errorMessage || 'This verification link has been disabled or revoked.'
    }

    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex flex-col justify-center items-center px-4">
        <div className="max-w-md w-full text-center space-y-4 p-8 bg-card rounded-2xl border border-border shadow-xl">
          <div className="w-14 h-14 rounded-2xl bg-destructive/10 text-destructive flex items-center justify-center mx-auto">
            {isExpired ? <Clock className="w-7 h-7" /> : <XCircle className="w-7 h-7" />}
          </div>
          <h2 className="text-2xl font-bold text-foreground">{title}</h2>
          <p className="text-sm text-muted-foreground leading-relaxed">{desc}</p>
          <div className="pt-4">
            <Button variant="outline" onClick={() => navigate('/')} className="cursor-pointer gap-2">
              <ArrowLeft className="w-4 h-4" /> Return to Home
            </Button>
          </div>
        </div>
      </div>
    )
  }

  // Identity Verification Gate (Protects student privacy before revealing extraction data)
  if (!isIdentityVerified) {
    if (isCommonMode) {
      return (
        <div className="min-h-screen bg-slate-50/50 dark:bg-slate-950 flex flex-col justify-center items-center py-12 px-4 sm:px-6 lg:px-8">
          <div className="max-w-md w-full space-y-6">
            <div className="text-center space-y-2">
              <div className="w-14 h-14 rounded-2xl bg-primary/10 text-primary flex items-center justify-center mx-auto shadow-xs border border-primary/20">
                <GraduationCap className="w-8 h-8" />
              </div>
              <h1 className="text-2xl font-bold tracking-tight text-foreground">
                Student Verification Portal
              </h1>
              <p className="text-xs text-muted-foreground max-w-sm mx-auto">
                Welcome to the student verification service. Enter your registered name and register number to review and verify your extracted documents.
              </p>
              {commonBatchId && (
                <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-muted text-foreground border border-border mt-1">
                  Batch: {commonBatchId}
                </div>
              )}
            </div>

            <Card className="border border-border/80 shadow-xl backdrop-blur-sm">
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-bold flex items-center gap-2 text-foreground">
                  <User className="w-4 h-4 text-primary" /> Student Identification
                </CardTitle>
                <CardDescription className="text-xs">
                  Enter your registered Student Name and Register Number.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleIdentifyCommonStudent} className="space-y-4">
                  {identityError && (
                    <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-700 dark:text-rose-400 text-xs flex items-start gap-2">
                      <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                      <span>{identityError}</span>
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <label htmlFor="student-name-input" className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                      <User className="w-3.5 h-3.5 text-muted-foreground" /> Student Name
                    </label>
                    <input
                      id="student-name-input"
                      type="text"
                      required
                      autoFocus
                      placeholder="e.g. Alice Smith"
                      value={identityName}
                      onChange={(e) => setIdentityName(e.target.value)}
                      className="w-full px-3.5 py-2 text-sm bg-background border border-input rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/30 text-foreground transition-all"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label htmlFor="student-reg-input" className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                      <Hash className="w-3.5 h-3.5 text-muted-foreground" /> Register Number
                    </label>
                    <input
                      id="student-reg-input"
                      type="text"
                      required
                      placeholder="e.g. 71762104076 or REG2026001"
                      value={identityRegisterNo}
                      onChange={(e) => setIdentityRegisterNo(e.target.value)}
                      className="w-full px-3.5 py-2 text-sm bg-background border border-input rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/30 text-foreground font-mono transition-all"
                    />
                  </div>

                  {showBatchInput && (
                    <div className="space-y-1.5">
                      <label htmlFor="student-batch-input" className="text-xs font-semibold text-foreground flex items-center justify-between">
                        <span className="flex items-center gap-1.5">
                          <GraduationCap className="w-3.5 h-3.5 text-muted-foreground" /> Admission Batch (Required if ambiguous)
                        </span>
                      </label>
                      <input
                        id="student-batch-input"
                        type="text"
                        placeholder="e.g. Batch 2026-A or Batch ID"
                        value={commonBatchId}
                        onChange={(e) => setCommonBatchId(e.target.value)}
                        className="w-full px-3.5 py-2 text-sm bg-background border border-input rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/30 text-foreground font-mono transition-all"
                      />
                    </div>
                  )}

                  <div className="pt-2">
                    <Button
                      id="continue-btn"
                      type="submit"
                      disabled={identityLoading || !identityName.trim() || !identityRegisterNo.trim()}
                      className="w-full justify-center gap-2 cursor-pointer font-bold shadow-xs py-2.5 rounded-xl"
                    >
                      {identityLoading ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" /> Verifying Credentials...
                        </>
                      ) : (
                        <>
                          Continue to Verification <ArrowRight className="w-4 h-4" />
                        </>
                      )}
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          </div>
        </div>
      )
    }

    // Legacy Token Mode: Validate Identity Gate
    return (
      <div className="min-h-screen bg-slate-50/50 dark:bg-slate-950 flex flex-col justify-center items-center py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-md w-full space-y-6">
          <div className="text-center space-y-2">
            <div className="w-14 h-14 rounded-2xl bg-primary/10 text-primary flex items-center justify-center mx-auto shadow-xs border border-primary/20">
              <ShieldCheck className="w-8 h-8" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              Student Identity Verification
            </h1>
            <p className="text-xs text-muted-foreground max-w-sm mx-auto">
              Please enter your full name and register number to access and verify your admission document extraction data.
            </p>
            {sessionInfo?.batch_name && (
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-muted text-foreground border border-border mt-1">
                Batch: {sessionInfo.batch_name}
              </div>
            )}
          </div>

          <Card className="border border-border/80 shadow-xl backdrop-blur-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-bold flex items-center gap-2 text-foreground">
                <Lock className="w-4 h-4 text-primary" /> Identity Credentials
              </CardTitle>
              <CardDescription className="text-xs">
                Credentials must match the registered admission records for this link.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleValidateIdentity} className="space-y-4">
                {identityError && (
                  <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-700 dark:text-rose-400 text-xs flex items-start gap-2">
                    <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                    <span>{identityError}</span>
                  </div>
                )}

                <div className="space-y-1.5">
                  <label htmlFor="student-name-input" className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                    <User className="w-3.5 h-3.5 text-muted-foreground" /> Student Name
                  </label>
                  <input
                    id="student-name-input"
                    type="text"
                    required
                    autoFocus
                    placeholder="e.g. Priya Sharma"
                    value={identityName}
                    onChange={(e) => setIdentityName(e.target.value)}
                    className="w-full px-3.5 py-2 text-sm bg-background border border-input rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/30 text-foreground transition-all"
                  />
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="student-reg-input" className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                    <Hash className="w-3.5 h-3.5 text-muted-foreground" /> Register / Roll Number
                  </label>
                  <input
                    id="student-reg-input"
                    type="text"
                    required
                    placeholder="e.g. 71762104076"
                    value={identityRegisterNo}
                    onChange={(e) => setIdentityRegisterNo(e.target.value)}
                    className="w-full px-3.5 py-2 text-sm bg-background border border-input rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/30 text-foreground font-mono transition-all"
                  />
                </div>

                <div className="pt-2">
                  <Button
                    type="submit"
                    disabled={identityLoading || !identityName.trim() || !identityRegisterNo.trim()}
                    className="w-full justify-center gap-2 cursor-pointer font-bold shadow-xs py-2.5 rounded-xl"
                  >
                    {identityLoading ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin" /> Verifying Credentials...
                      </>
                    ) : (
                      <>
                        Continue to Extraction Data <ArrowRight className="w-4 h-4" />
                      </>
                    )}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  const hasCorrectionsPending = verifications.some((v) => v.status === 'CORRECTION_REQUESTED')
  const isSessionCompleted = Boolean(sessionMeta?.status === 'COMPLETED' || isSubmittedSuccess)

  return (
    <div className="min-h-screen bg-slate-50/50 dark:bg-slate-950 py-10 px-4 sm:px-6 lg:px-8">
      <div className="max-w-4xl mx-auto space-y-8">
        {/* Post-Submission Success Card with Navigation & Tab Close Gate */}
        {isSubmittedSuccess && (
          <Card className="border-2 border-emerald-500/30 bg-emerald-500/5 shadow-xl backdrop-blur-sm overflow-hidden">
            <CardContent className="p-6 sm:p-8 text-center space-y-4">
              <div className="w-16 h-16 rounded-2xl bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 flex items-center justify-center mx-auto shadow-sm border border-emerald-500/30">
                <CheckCircle2 className="w-9 h-9" />
              </div>

              <div className="space-y-1">
                <h2 className="text-2xl sm:text-3xl font-extrabold text-foreground">
                  Verification submitted successfully.
                </h2>
                <p className="text-sm text-muted-foreground max-w-md mx-auto">
                  {canNavigateBack
                    ? `Your extracted values have been saved as verified data. Navigating back in ${navigateCountdown ?? 3}s...`
                    : 'Verification completed. You may close this tab.'}
                </p>
              </div>

              {tabCloseBlocked && (
                <div className="max-w-md mx-auto p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-400 text-xs text-left flex items-start gap-2.5">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
                  <span>
                    Your browser prevented closing this tab automatically. Please close this tab manually using your browser's tab close button (✕).
                  </span>
                </div>
              )}

              <div className="pt-2 flex flex-wrap items-center justify-center gap-3">
                {canNavigateBack ? (
                  <Button
                    id="back-previous-btn"
                    onClick={() => window.history.back()}
                    className="gap-2 font-bold cursor-pointer bg-emerald-600 hover:bg-emerald-700 text-white shadow-md shadow-emerald-600/20 px-6 py-2.5 rounded-xl"
                  >
                    <ArrowLeft className="w-4 h-4" /> Back to Previous Page {navigateCountdown !== null && `(${navigateCountdown}s)`}
                  </Button>
                ) : (
                  <Button
                    id="close-tab-btn"
                    onClick={handleCloseTab}
                    className="gap-2 font-bold cursor-pointer bg-emerald-600 hover:bg-emerald-700 text-white shadow-md shadow-emerald-600/20 px-6 py-2.5 rounded-xl"
                  >
                    <XCircle className="w-4 h-4" /> Close Tab
                  </Button>
                )}

                <Button
                  variant="outline"
                  onClick={() => navigate('/')}
                  className="gap-2 cursor-pointer border-border text-foreground rounded-xl"
                >
                  Return to Home
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Student Session Card */}
        {sessionMeta && (
          <div className="bg-card border border-border/80 rounded-2xl p-5 sm:p-6 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-primary/10 text-primary flex items-center justify-center font-bold text-lg border border-primary/20 shrink-0">
                <GraduationCap className="w-6 h-6" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-base sm:text-lg font-bold text-foreground">
                    {sessionMeta.student_name}
                  </h2>
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-mono bg-muted text-muted-foreground border border-border">
                    {sessionMeta.student_id}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1.5 flex-wrap">
                  <span>Batch: <strong className="text-foreground">{sessionMeta.batch_name || sessionMeta.batch_id}</strong></span>
                  {sessionMeta.class_id && <span>• Section: {sessionMeta.class_id}</span>}
                  {sessionMeta.extraction_request_id && (
                    <span>• Extraction ID: <strong className="font-mono text-foreground">{sessionMeta.extraction_request_id}</strong></span>
                  )}
                  {sessionMeta.extracted_at && (
                    <span>• Extracted: <strong className="text-foreground">{new Date(sessionMeta.extracted_at).toLocaleString()}</strong></span>
                  )}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 self-start md:self-auto">
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                <ShieldCheck className="w-3.5 h-3.5" /> Secure Verification Session
              </span>
            </div>
          </div>
        )}

        {/* Header banner */}
        {!isSubmittedSuccess && (
          <div className="text-center space-y-2">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-primary/10 text-primary text-xs font-semibold mb-2">
              <ShieldCheck className="w-4 h-4" /> Student Document Verification
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
              Verify Extracted Document Data
            </h1>
            <p className="text-sm text-slate-600 dark:text-slate-400 max-w-xl mx-auto">
              Review the data extracted from your certificates. You can confirm correct values or edit incorrect values directly. Your submitted values will be saved directly as final verified records.
            </p>
          </div>
        )}

        {/* Status notification */}
        {hasCorrectionsPending && (
          <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-800 dark:text-amber-300 flex items-start gap-3">
            <Clock className="w-5 h-5 flex-shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
            <div className="text-sm">
              <span className="font-semibold">Correction Requested:</span> Your submitted corrections are currently under review by admissions staff. They will become final once approved.
            </div>
          </div>
        )}

        {isSessionCompleted && !hasCorrectionsPending && !isSubmittedSuccess && (
          <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-800 dark:text-emerald-300 flex items-start gap-3">
            <CheckCircle2 className="w-5 h-5 flex-shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400" />
            <div className="text-sm flex-1">
              <span className="font-semibold">Verification Completed:</span> Your document extraction data has been submitted and saved directly as your final verified records.
            </div>
            <Button
              id="completed-close-tab-btn"
              size="sm"
              variant="outline"
              onClick={handleCloseTab}
              className="cursor-pointer gap-1.5 shrink-0"
            >
              <XCircle className="w-4 h-4" /> Close Tab
            </Button>
          </div>
        )}

        {verifications.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center text-slate-500">
              <FileCheck2 className="w-12 h-12 mx-auto text-slate-400 mb-3" />
              <p className="font-medium">No extracted fields ready for verification yet.</p>
              <p className="text-xs text-slate-400 mt-1">
                Please ensure your certificates have been extracted by staff.
              </p>
            </CardContent>
          </Card>
        ) : (
          <Card className="border border-slate-200/80 dark:border-slate-800 shadow-xl shadow-slate-200/20 dark:shadow-none backdrop-blur-sm">
            <CardHeader className="border-b border-slate-100 dark:border-slate-800/60 pb-5">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
                    <Edit3 className="w-5 h-5 text-primary" /> Extracted Fields & Values
                  </CardTitle>
                  <CardDescription>
                    Compare AI-extracted values with your uploaded documents.
                  </CardDescription>
                </div>
                {!isSessionCompleted && (
                  <Button variant="outline" size="sm" onClick={loadData} className="gap-1.5 cursor-pointer">
                    <RefreshCw className="w-3.5 h-3.5" /> Refresh
                  </Button>
                )}
              </div>
            </CardHeader>

            <CardContent className="divide-y divide-slate-100 dark:divide-slate-800/60 p-0">
              {verifications.map((field) => {
                const isEdited =
                  String(editedValues[field.id] ?? '').trim() !== String(field.ai_value ?? '').trim()

                return (
                  <div
                    key={field.id}
                    className="p-5 sm:p-6 hover:bg-slate-50/50 dark:hover:bg-slate-900/30 transition-colors space-y-3"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm text-slate-900 dark:text-white">
                          {formatFieldName(field.field_name)}
                        </span>
                        <span className="text-xs text-slate-500 dark:text-slate-400 font-mono">
                          ({field.source_document_name || field.document_type})
                        </span>
                      </div>
                      <div>{getStatusBadge(field.status, field.field_state)}</div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
                      {/* AI Extracted Box */}
                      <div className="p-3.5 rounded-lg bg-slate-100/70 dark:bg-slate-900/60 border border-slate-200/60 dark:border-slate-800">
                        <div className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1 flex items-center justify-between">
                          <span className="flex items-center gap-1.5">
                            <Sparkles className="w-3.5 h-3.5 text-primary" /> AI Extracted Value
                          </span>
                          {field.confidence && (
                            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                              {field.confidence}
                            </span>
                          )}
                        </div>
                        <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                          {field.ai_value && field.ai_value !== 'NOT_AVAILABLE' ? (
                            field.ai_value
                          ) : field.field_state === 'MANUALLY_ENTERED' ? (
                            <span className="inline-flex items-center gap-1 text-xs font-mono font-medium px-2 py-0.5 rounded bg-blue-500/10 text-blue-700 dark:text-blue-400 border border-blue-500/20">
                              MANUALLY ENTERED
                            </span>
                          ) : field.field_state === 'NOT_FOUND' ? (
                            <span className="inline-flex items-center gap-1 text-xs font-mono font-medium px-2 py-0.5 rounded bg-slate-200/60 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-300/60 dark:border-slate-700">
                              NOT FOUND
                            </span>
                          ) : field.field_state === 'DOCUMENT_MISSING' || field.field_state === 'SOURCE_DOCUMENT_MISSING' ? (
                            <span className="inline-flex items-center gap-1 text-xs font-mono font-medium px-2 py-0.5 rounded bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20">
                              DOCUMENT MISSING
                            </span>
                          ) : field.field_state === 'EXTRACTION_FAILED' || field.field_state === 'AI_EXTRACTION_FAILED' || field.field_state === 'OCR_FAILED' ? (
                            <span className="inline-flex items-center gap-1 text-xs font-mono font-medium px-2 py-0.5 rounded bg-rose-500/10 text-rose-700 dark:text-rose-400 border border-rose-500/20">
                              EXTRACTION FAILED
                            </span>
                          ) : (
                            <span className="italic text-slate-400">Not detected</span>
                          )}
                        </div>
                        {field.reason && field.field_state !== 'EXTRACTED' && field.field_state !== 'HIGH_CONFIDENCE' && (
                          <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">
                            {field.reason}
                          </div>
                        )}
                      </div>

                      {/* Student Editable Box */}
                      <div>
                        <label className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1 flex items-center justify-between">
                          <span>Student Value (Editable)</span>
                          {isEdited && !isSessionCompleted && (
                            <span className="text-amber-600 dark:text-amber-400 font-semibold text-[11px]">
                              ● Modified
                            </span>
                          )}
                        </label>
                        <input
                          type="text"
                          disabled={isSessionCompleted || submitting}
                          value={editedValues[field.id] ?? ''}
                          onChange={(e) => handleInputChange(field.id, e.target.value)}
                          placeholder="Confirm or enter corrected value"
                          className={`w-full text-sm font-medium px-3.5 py-2 rounded-lg border transition-all duration-200 bg-white dark:bg-slate-900 ${
                            isEdited && !isSessionCompleted
                              ? 'border-amber-400 focus:border-amber-500 focus:ring-1 focus:ring-amber-500 dark:border-amber-600'
                              : 'border-slate-200 dark:border-slate-700 focus:border-primary focus:ring-1 focus:ring-primary'
                          } ${isSessionCompleted ? 'opacity-70 cursor-not-allowed bg-slate-100 dark:bg-slate-800' : ''}`}
                        />
                      </div>
                    </div>

                    {field.staff_comment && (
                      <div className="text-xs text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-900 p-2.5 rounded-md">
                        <span className="font-semibold">Staff Note:</span> {field.staff_comment}
                      </div>
                    )}
                  </div>
                )
              })}

              <div className="p-6 bg-slate-50/70 dark:bg-slate-900/40 space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                    Optional Note / Reason for Correction:
                  </label>
                  <textarea
                    rows={2}
                    disabled={isSessionCompleted || submitting}
                    value={generalComment}
                    onChange={(e) => setGeneralComment(e.target.value)}
                    placeholder="e.g., Typo in student name on certificate, corrected to match Aadhaar..."
                    className={`w-full text-sm p-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 focus:border-primary focus:ring-1 focus:ring-primary ${
                      isSessionCompleted ? 'opacity-70 cursor-not-allowed bg-slate-100 dark:bg-slate-800' : ''
                    }`}
                  />
                </div>

                <div className="flex flex-col sm:flex-row items-center justify-end gap-3 pt-2">
                  {isSessionCompleted ? (
                    <div className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20 font-bold text-sm">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      Verification Completed & Finalized
                    </div>
                  ) : (
                    <>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={handleConfirmAll}
                        disabled={submitting}
                        className="w-full sm:w-auto gap-2 border-emerald-500/30 hover:bg-emerald-50 text-emerald-700 dark:text-emerald-400 dark:hover:bg-emerald-950/20 cursor-pointer"
                      >
                        <Check className="w-4 h-4 text-emerald-600" />
                        Confirm All Extracted Values
                      </Button>

                      <Button
                        type="button"
                        variant="primary"
                        onClick={handleSubmitCorrection}
                        disabled={submitting}
                        className="w-full sm:w-auto gap-2 bg-primary hover:bg-primary/90 text-white shadow-lg shadow-primary/20 cursor-pointer"
                      >
                        <Edit3 className="w-4 h-4" />
                        Submit Verified Data
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
