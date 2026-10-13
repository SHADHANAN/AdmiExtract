import React, { useState, useEffect } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useToastStore } from '../store/useToastStore'
import { useAuthStore } from '../store/useAuthStore'
import { Button } from '../components/ui/Button'
import { Card, CardTitle, CardContent } from '../components/ui/Card'
import { ThemeToggle } from '../components/ui/ThemeToggle'
import { api } from '../services/api'
import { readSubmissionSession, clearSubmissionSession, getStudentMe } from '../services/studentIdentity'
import {
  GraduationCap,
  Folder,
  FileText,
  X,
  ShieldCheck,
  CheckCircle,
  Loader2,
  Lock,
  Upload,
  Check,
  Trash2,
  AlertTriangle,
  FolderOpen,
  ArrowRight,
  RefreshCw,
  FileCheck,
  CreditCard,
  Baby,
  Users,
  CircleDollarSign,
  Award,
  Milestone,
  AlertCircle,
  Layers,
} from 'lucide-react'
import type { DocumentRequirement } from '../types'

/* ─── Local types ─── */
interface DocumentState {
  file: File | null
  status: 'Pending' | 'Uploading' | 'Uploaded' | 'Not Available'
  progress: number
  existingFileName?: string
  existingDocumentId?: string
  fileSizeMb?: number
  version?: number
  isReplacement?: boolean
}

/* ─── Stepper config (Store Once Flow) ─── */
const STEPS = [
  { number: 1, label: 'Student Details' },
  { number: 2, label: 'Documents' },
  { number: 3, label: 'Complete' },
]

/* ─── Icon helper ─── */
const getDocIcon = (name: string) => {
  const n = name.toLowerCase()
  if (n.includes('aadhaar') || n.includes('id') || n.includes('card')) return CreditCard
  if (n.includes('birth')) return Baby
  if (n.includes('community') || n.includes('caste') || n.includes('social')) return Users
  if (n.includes('income') || n.includes('salary') || n.includes('tax')) return CircleDollarSign
  if (n.includes('marksheet') || n.includes('sslc') || n.includes('hsc') || n.includes('grade'))
    return Award
  if (n.includes('transfer') || n.includes('migration') || n.includes('leaving')) return Milestone
  return FileText
}

/* ═══════════════════════════════════════════════════════════════════
   StudentDocuments — Document upload workspace for verified students.

   PRODUCT RULE:
   When a student uploads an admission document, the system ONLY receives
   and persists the document. No AI processing, OCR, or verification at upload.

   Route: /student/:batchId/documents[/success]
          /upload/:batchId/documents[/success]
═══════════════════════════════════════════════════════════════════ */
export const StudentDocuments: React.FC = () => {
  const { batchId } = useParams<{ batchId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { addToast } = useToastStore()

  /* ── Session & batch metadata ── */
  const [sessionLoaded, setSessionLoaded] = useState(false)
  const [studentName, setStudentName] = useState('')
  const [registerNum, setRegisterNum] = useState('')
  const [mobileNum, setMobileNum] = useState('')
  const [email, setEmail] = useState('')
  const [batchName, setBatchName] = useState('')
  const [classId, setClassId] = useState<string | undefined>()
  const [className, setClassName] = useState<string | undefined>()
  const [uploadLinkId, setUploadLinkId] = useState<string | undefined>()
  const [token, setToken] = useState<string | undefined>()
  const [assignedRequirements, setAssignedRequirements] = useState<DocumentRequirement[]>([])
  const [isLoadingBatch, setIsLoadingBatch] = useState(true)

  /* ── Document upload states ── */
  const [docStates, setDocStates] = useState<Record<string, DocumentState>>({})
  const [draggedOverDoc, setDraggedOverDoc] = useState<string | null>(null)

  /* ── Submission receipt ── */
  const [submissionId, setSubmissionId] = useState('')
  const [submissionTime, setSubmissionTime] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [savedDocuments, setSavedDocuments] = useState<
    Array<{
      document_name: string
      document_type?: string
      status: string
      file_size_mb?: number
      file_type?: string
      version?: number
      file_path?: string
      filename?: string
    }>
  >([])

  /* ── Derive current step from URL path ── */
  const step = location.pathname.endsWith('/success') ? 3 : 2

  const basePath = location.pathname.startsWith('/student')
    ? `/student/${batchId}/documents`
    : `/upload/${batchId}/documents`

  /* ── On mount: read session; redirect if missing ── */
  useEffect(() => {
    const session = readSubmissionSession()
    if (!session || session.batch_id !== batchId) {
      addToast('Your session has expired. Please identify yourself again.', 'error')
      navigate('/', { replace: true })
      return
    }
    setStudentName(session.student_name)
    setRegisterNum(session.register_number)
    setMobileNum(session.mobile_number)
    setBatchName(session.batch_name)
    if (session.email) setEmail(session.email)
    if (session.class_id) setClassId(session.class_id)
    if (session.class_name) setClassName(session.class_name)
    if (session.upload_link_id) setUploadLinkId(session.upload_link_id)
    if (session.token) setToken(session.token)
    if (session.submission_id) setSubmissionId(session.submission_id)

    if (session.uploaded_documents && session.uploaded_documents.length > 0) {
      setSavedDocuments(session.uploaded_documents as any)
    }

    if (session.submission_id) {
      const tokenParam = session.token ? `?token=${encodeURIComponent(session.token)}` : ''
      const headers = session.token ? { 'X-Verification-Token': session.token } : undefined
      api.get(`/student-submissions/public/${session.submission_id}${tokenParam}`, { headers })
        .then((res) => {
          if (res.data?.documents && Array.isArray(res.data.documents)) {
            setSavedDocuments(res.data.documents)
          }
        })
        .catch(() => {})
    }

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
          }
        } catch {
          // fallback to session
        }
      }
    }
    fetchStudentProfile()
    setSessionLoaded(true)
  }, [batchId, navigate, addToast])

  /* ── Load document requirements for this batch/class ── */
  useEffect(() => {
    if (!sessionLoaded || !batchId) return

    const loadRequirements = async () => {
      setIsLoadingBatch(true)
      try {
        const cleanClassId = classId && classId !== 'undefined' && classId !== 'null' ? classId.trim() : undefined
        const url = cleanClassId
          ? `/public/batches/${batchId}/doc-versions/current?classId=${encodeURIComponent(cleanClassId)}&class_id=${encodeURIComponent(cleanClassId)}`
          : `/public/batches/${batchId}/doc-versions/current`
        const currentV = await api.get(url)
        const rawDocs = currentV.data?.documents || currentV.data || []
        const isHexId = (val: string) => /^[0-9a-fA-F]{24}$/.test((val || '').trim())
        const dedupedMap = new Map<string, DocumentRequirement>()
        for (const d of rawDocs) {
          const reqStatus = (d.requirement_status || d.type || (d.required ? 'REQUIRED' : 'OPTIONAL')).toUpperCase()
          if (reqStatus === 'DISABLED') continue

          const isMandatory = d.required !== undefined ? Boolean(d.required) : (reqStatus === 'REQUIRED' || reqStatus === 'MANDATORY')
          const docDisplayName = (d.name || d.display_name || d.document_name || d.code || 'Document').trim()
          const rawTypeCandidate = d.document_type || d.document_code || d.code || ''
          const docTypeCode = (rawTypeCandidate && !isHexId(rawTypeCandidate) ? rawTypeCandidate : docDisplayName).trim()
          const stableKey = (d.code && !isHexId(d.code) ? d.code : (docTypeCode || docDisplayName)).toUpperCase()

          if (!dedupedMap.has(stableKey)) {
            dedupedMap.set(stableKey, {
              id: d.id || d.code || docTypeCode || docDisplayName,
              name: docDisplayName,
              required: isMandatory,
              allowedTypes: d.allowed_types || d.allowedTypes || ['PDF', 'JPG', 'PNG'],
              maxSizeMb: d.max_size_mb || d.maxSizeMb || 5,
              description: d.description || '',
              type: isMandatory ? 'MANDATORY' : 'OPTIONAL',
              documentType: docTypeCode,
              documentCode: docTypeCode,
              code: docTypeCode,
            })
          }
        }
        const reqs: DocumentRequirement[] = Array.from(dedupedMap.values())
        setAssignedRequirements(reqs)
      } catch (err) {
        console.error('Failed to load batch document requirements:', err)
        setAssignedRequirements([])
      } finally {
        setIsLoadingBatch(false)
      }
    }

    loadRequirements()
  }, [sessionLoaded, batchId, classId])

  /* ── Initialise doc states when requirements or saved documents load ── */
  useEffect(() => {
    if (assignedRequirements.length > 0) {
      setDocStates((prev) => {
        const next: Record<string, DocumentState> = { ...prev }
        assignedRequirements
          .filter((r) => r.type !== 'DISABLED')
          .forEach((r) => {
            const existingSaved = savedDocuments.find(
              (d) =>
                d.document_name?.trim().toLowerCase() === r.name?.trim().toLowerCase() ||
                (d as any).name?.trim().toLowerCase() === r.name?.trim().toLowerCase()
            )

            if (!next[r.name] || (next[r.name].status === 'Pending' && existingSaved)) {
              if (
                existingSaved &&
                (existingSaved.status === 'Uploaded' ||
                  existingSaved.status === 'Submitted' ||
                  existingSaved.status === 'Verified')
              ) {
                const rawPath = (existingSaved as any).file_path || ''
                const fname =
                  (existingSaved as any).filename ||
                  (rawPath ? rawPath.replace(/\\/g, '/').split('/').pop() : `${r.name}.pdf`)
                const existingDocId = (existingSaved as any).id || (existingSaved as any).student_document_id
                next[r.name] = {
                  file: null,
                  status: 'Uploaded',
                  progress: 100,
                  existingFileName: fname,
                  existingDocumentId: existingDocId,
                  fileSizeMb: existingSaved.file_size_mb,
                  version: existingSaved.version || 1,
                  isReplacement: false,
                }
              } else if (existingSaved && existingSaved.status === 'Not Available') {
                next[r.name] = {
                  file: null,
                  status: 'Not Available',
                  progress: 0,
                  version: 1,
                }
              } else if (!next[r.name]) {
                next[r.name] = { file: null, status: 'Pending', progress: 0, version: 1 }
              }
            }
          })
        return next
      })
    }
  }, [assignedRequirements, savedDocuments])


  /* ── Guard: direct URL access to deep steps without session ── */
  useEffect(() => {
    if (sessionLoaded && step > 2 && !studentName) {
      navigate(basePath, { replace: true })
    }
  }, [step, studentName, sessionLoaded, basePath, navigate])

  /* ─────────────────────────────────────────────
     Upload helpers
  ───────────────────────────────────────────── */
  const enabledDocs = assignedRequirements.filter((r) => r.type !== 'DISABLED')

  const startSimulatedUpload = (req: DocumentRequirement, file: File) => {
    const allowedTypes = req.allowedTypes || ['PDF', 'JPG', 'PNG']
    const maxSizeMb = req.maxSizeMb || 5

    const fileExt = file.name.split('.').pop()?.toUpperCase()
    if (!fileExt || !allowedTypes.map((t) => t.toUpperCase()).includes(fileExt)) {
      addToast(
        `Invalid file format for "${req.name}". Allowed: ${allowedTypes.join(', ')}`,
        'error'
      )
      return
    }

    const fileSizeMb = file.size / (1024 * 1024)
    if (fileSizeMb > maxSizeMb) {
      addToast(
        `File size (${fileSizeMb.toFixed(1)} MB) exceeds ${maxSizeMb} MB limit for "${req.name}".`,
        'error'
      )
      return
    }

    const prevDocState = docStates[req.name]
    const isReplacing = prevDocState?.status === 'Uploaded'

    setDocStates((prev) => ({
      ...prev,
      [req.name]: {
        ...prev[req.name],
        status: 'Uploading',
        progress: 0,
        isReplacement: isReplacing,
      },
    }))

    let progress = 0
    const interval = setInterval(() => {
      progress += 20 + Math.floor(Math.random() * 25)
      setDocStates((prev) => {
        if (progress >= 100) {
          clearInterval(interval)
          if (isReplacing) {
            addToast(`Replaced "${req.name}" with ${file.name}`, 'success')
          } else {
            addToast(`Selected "${req.name}" (${file.name})`, 'success')
          }
          return {
            ...prev,
            [req.name]: {
              file,
              status: 'Uploaded',
              progress: 100,
              existingFileName: file.name,
              fileSizeMb: Number((file.size / (1024 * 1024)).toFixed(2)),
              version: 1,
              isReplacement: isReplacing,
            },
          }
        }
        return { ...prev, [req.name]: { ...prev[req.name], progress } }
      })
    }, 80)
  }


  const handleFileChange = (req: DocumentRequirement, e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) startSimulatedUpload(req, e.target.files[0])
  }

  const handleDrop = (e: React.DragEvent, req: DocumentRequirement) => {
    e.preventDefault()
    setDraggedOverDoc(null)
    if (e.dataTransfer.files?.[0]) startSimulatedUpload(req, e.dataTransfer.files[0])
  }

  const handleRemoveFile = (docName: string) => {
    setDocStates((prev) => ({
      ...prev,
      [docName]: { file: null, status: 'Pending', progress: 0, existingFileName: undefined, fileSizeMb: undefined },
    }))
    setSavedDocuments((prev) => prev.filter((d) => d.document_name !== docName && (d as any).name !== docName))
    addToast(`Cleared upload for ${docName}.`, 'info')
  }

  const handleToggleNotAvailable = (docName: string) => {
    setDocStates((prev) => {
      const isNA = prev[docName]?.status === 'Not Available'
      return {
        ...prev,
        [docName]: { file: null, status: isNA ? 'Pending' : 'Not Available', progress: 0 },
      }
    })
  }

  /* ─────────────────────────────────────────────
     Submission counters / eligibility
  ───────────────────────────────────────────── */
  const uploadedCount = Object.values(docStates).filter((s) => s.status === 'Uploaded').length
  const notAvailableCount = Object.values(docStates).filter(
    (s) => s.status === 'Not Available'
  ).length

  const missingRequired = enabledDocs.filter((req) => {
    const isMandatory = req.required !== undefined ? req.required : req.type === 'MANDATORY'
    return isMandatory && docStates[req.name]?.status !== 'Uploaded'
  })

  const missingOptional = enabledDocs.filter((req) => {
    const isMandatory = req.required !== undefined ? req.required : req.type === 'MANDATORY'
    if (isMandatory) return false
    const s = docStates[req.name]
    return s?.status !== 'Uploaded' && s?.status !== 'Not Available'
  })

  const canSubmit = enabledDocs.length > 0 && missingRequired.length === 0 && missingOptional.length === 0

  /* ─────────────────────────────────────────────
     Step 2 → 3: Save Documents (Store Once, No AI at upload)
  ───────────────────────────────────────────── */
  const handleUploadSubmit = async () => {
    if (!canSubmit) {
      addToast('Please upload all required files or mark optional documents as waived.', 'error')
      return
    }

    setIsSubmitting(true)

    const formData = new FormData()
    formData.append('batch_id', batchId!)
    formData.append('register_number', registerNum)
    formData.append('student_name', studentName)
    if (mobileNum) formData.append('mobile_number', mobileNum)
    if (email) formData.append('email', email)
    if (classId) formData.append('class_id', classId)
    if (className) formData.append('class_name', className)
    if (uploadLinkId) formData.append('upload_link_id', uploadLinkId)
    if (token) formData.append('token', token)

    const metadata: Array<{
      document_id?: string
      document_name: string
      document_type?: string
      filename?: string
      file_size_mb?: number
      file_index?: number
      is_new_file: boolean
      status: string
    }> = []

    let uploadFileIdx = 0

    enabledDocs.forEach((req) => {
      const s = docStates[req.name]
      const actualDocType = req.documentType || req.code || req.id || req.name
      if (s?.status === 'Uploaded') {
        if (s.file) {
          metadata.push({
            document_id: s.existingDocumentId,
            document_name: req.name,
            document_type: actualDocType,
            filename: s.file.name,
            file_index: uploadFileIdx,
            is_new_file: true,
            status: 'Uploaded',
          })
          formData.append('files', s.file)
          uploadFileIdx++
        } else {
          // Preserved previously uploaded document
          metadata.push({
            document_id: s.existingDocumentId,
            document_name: req.name,
            document_type: actualDocType,
            filename: s.existingFileName || `${req.name}.pdf`,
            file_size_mb: s.fileSizeMb,
            is_new_file: false,
            status: 'Uploaded',
          })
        }
      } else if (s?.status === 'Not Available') {
        metadata.push({
          document_id: s.existingDocumentId,
          document_name: req.name,
          document_type: actualDocType,
          is_new_file: false,
          status: 'Not Available',
        })
      }
    })

    formData.append('documents_metadata', JSON.stringify(metadata))

    try {
      const response = await api.post('/student-submissions/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const data = response.data
      setSubmissionId(data.id)
      setSubmissionTime(new Date(data.submitted_at || Date.now()).toLocaleString())
      setSavedDocuments(data.documents || [])
      clearSubmissionSession()
      addToast('Documents uploaded successfully and securely saved!', 'success')
      navigate(`${basePath}/success`)
    } catch (err: any) {
      const errMsg = err.response?.data?.detail || 'Document upload failed. Please try again.'
      addToast(errMsg, 'error')
    } finally {
      setIsSubmitting(false)
    }
  }

  /* ─────────────────────────────────────────────
     Loading & session guard states
  ───────────────────────────────────────────── */
  if (!sessionLoaded || isLoadingBatch) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f9fafb] dark:bg-[#0b0f19]">
        <Loader2 className="h-10 w-10 text-primary animate-spin" />
        <p className="text-sm text-muted-foreground mt-4 ml-4 font-medium">
          Preparing upload workspace...
        </p>
      </div>
    )
  }

  const batchFolder = batchName.replace(/\s+/g, '_')
  const studentFolder = `${registerNum}_${studentName.replace(/\s+/g, '_')}`

  /* ═══════════════════════════════════════════
     RENDER
  ═══════════════════════════════════════════ */
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground transition-colors duration-300">

      {/* ── Header ── */}
      <header className="sticky top-0 z-50 flex h-16 w-full items-center justify-between border-b border-border bg-card/80 backdrop-blur-md px-6 md:px-8 shadow-2xs">
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
        <div className="hidden sm:flex items-center gap-2 text-xs font-semibold text-muted-foreground">
          <span className="px-2 py-0.5 bg-secondary rounded-md border border-border">
            {studentName}
          </span>
          <span className="text-border">·</span>
          <span className="font-mono">{registerNum}</span>
          {email && (
            <>
              <span className="text-border">·</span>
              <span className="font-mono text-muted-foreground">{email}</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <div className="flex items-center gap-2 text-xs font-bold text-muted-foreground bg-secondary/80 px-3 py-1.5 rounded-xl border border-border/80">
            <Lock className="h-3.5 w-3.5 text-primary shrink-0" />
            <span>AES-256 Secured</span>
          </div>
        </div>
      </header>

      {/* ── 3-Step Progress Stepper ── */}
      <div className="w-full max-w-2xl mx-auto px-4 pt-8 pb-4">
        <div className="relative flex items-center justify-between">
          <div className="absolute left-0 top-1/2 h-0.5 w-full -translate-y-1/2 bg-border dark:bg-border/40" />
          <div
            className="absolute left-0 top-1/2 h-0.5 -translate-y-1/2 bg-primary transition-all duration-500"
            style={{ width: `${((step - 1) / (STEPS.length - 1)) * 100}%` }}
          />
          {STEPS.map((s) => {
            const done = step > s.number
            const active = step === s.number
            return (
              <div key={s.number} className="relative z-10 flex flex-col items-center">
                <div
                  className={`flex h-10 w-10 items-center justify-center rounded-full border-2 font-bold text-sm transition-all duration-300 ${
                    done
                      ? 'bg-primary border-primary text-primary-foreground'
                      : active
                      ? 'bg-card border-primary text-primary ring-4 ring-primary/10'
                      : 'bg-card border-border text-muted-foreground'
                  }`}
                >
                  {done ? <Check className="h-5 w-5 stroke-[2.5]" /> : s.number}
                </div>
                <span
                  className={`hidden sm:block text-xs font-bold mt-2 transition-colors duration-300 ${
                    active ? 'text-primary' : 'text-muted-foreground'
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
            <span>Step {step} of 3:</span>
            <span className="font-bold">{STEPS[step - 1]?.label}</span>
          </span>
        </div>
      </div>

      {/* ── Main ── */}
      <main className="flex-1 flex items-start justify-center px-4 py-8 md:py-12 sm:px-6 lg:px-8">
        <div className="w-full max-w-6xl">

          {/* ══ STEP 2: Document Upload ══ */}
          {step === 2 && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
              {/* Left: Document cards */}
              <div className="lg:col-span-2 space-y-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-card border border-border p-6 rounded-2xl shadow-xs">
                  <div>
                    <h1 className="text-2xl font-black tracking-tight text-foreground">
                      Admission Documents Portal
                    </h1>
                    <p className="text-sm text-muted-foreground mt-0.5">
                      Batch:{' '}
                      <span className="font-semibold text-foreground">{batchName}</span> • Candidate:{' '}
                      <span className="font-semibold text-foreground">
                        {studentName} ({registerNum})
                      </span>
                      {email && (
                        <>
                          {' '}• <span className="font-medium text-muted-foreground">{email}</span>
                        </>
                      )}
                    </p>
                  </div>
                  <div className="flex flex-col bg-secondary/50 border border-border/80 px-4 py-3 rounded-xl text-xs font-mono select-none shrink-0">
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <FolderOpen className="h-4 w-4 text-indigo-500" />
                      <span>{batchFolder}</span>
                    </div>
                    <div className="flex items-center gap-2 text-foreground font-semibold mt-1 pl-4 border-l border-primary/30 ml-2">
                      <Folder className="h-4 w-4 text-primary fill-primary/10" />
                      <span>{studentFolder}</span>
                    </div>
                  </div>
                </div>

                {enabledDocs.length === 0 ? (
                  <div className="text-center py-16 px-6 bg-card rounded-2xl border border-dashed border-border space-y-3">
                    <AlertCircle className="h-12 w-12 text-muted-foreground mx-auto" />
                    <h3 className="text-lg font-bold text-foreground">No admission documents configured</h3>
                    <p className="text-sm text-muted-foreground max-w-md mx-auto">
                      No admission documents have been configured for this batch/class. Please contact your admissions administrator.
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-5">
                    {enabledDocs.map((req) => {
                      const isMandatory = req.required !== undefined ? req.required : req.type === 'MANDATORY'
                      const allowedTypes = req.allowedTypes || ['PDF', 'JPG', 'PNG']
                      const maxSizeMb = req.maxSizeMb || 5
                      const state = docStates[req.name] || { file: null, status: 'Pending', progress: 0 }
                      const isUploading = state.status === 'Uploading'
                      const isUploaded = state.status === 'Uploaded'
                      const isNA = state.status === 'Not Available'
                      const isHovered = draggedOverDoc === req.name
                      const DocIcon = getDocIcon(req.name)

                      return (
                        <Card
                          key={req.id || req.name}
                          className={`transition-all duration-300 border-2 overflow-hidden ${
                            isUploaded
                              ? 'border-green-500/20 bg-green-500/2 dark:bg-green-950/5 shadow-2xs'
                              : isNA
                              ? 'border-border/50 bg-secondary/20 opacity-80'
                              : isUploading
                              ? 'border-primary/20 bg-primary/2'
                              : isHovered
                              ? 'border-primary ring-4 ring-primary/10'
                              : 'border-border bg-card hover:-translate-y-0.5 hover:shadow-xs'
                          }`}
                          onDragOver={(e) => { e.preventDefault(); setDraggedOverDoc(req.name) }}
                          onDragLeave={(e) => { e.preventDefault(); setDraggedOverDoc(null) }}
                          onDrop={(e) => handleDrop(e, req)}
                        >
                          <div className="p-5 flex flex-col md:flex-row md:items-center justify-between gap-5">
                            <div className="flex items-start gap-4 min-w-0 flex-1">
                              <div
                                className={`p-3 rounded-xl border shrink-0 mt-0.5 transition-colors ${
                                  isUploaded
                                    ? 'bg-green-500/10 text-green-600 border-green-500/25'
                                    : isNA
                                    ? 'bg-secondary text-muted-foreground border-border'
                                    : isUploading
                                    ? 'bg-primary/10 text-primary border-primary/20'
                                    : 'bg-primary/5 text-primary border-primary/10'
                                }`}
                              >
                                <DocIcon className="h-6 w-6" />
                              </div>
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <h3 className="font-bold text-foreground text-base leading-none">{req.name}</h3>
                                  <span
                                    className={`inline-flex items-center px-2 py-0.5 rounded-full text-3xs font-extrabold uppercase tracking-wider ${
                                      isMandatory
                                        ? 'bg-destructive/10 text-destructive border border-destructive/15'
                                        : 'bg-primary/10 text-primary border border-primary/15'
                                    }`}
                                  >
                                    {isMandatory ? 'REQUIRED' : 'OPTIONAL'}
                                  </span>
                                </div>

                                {req.description && (
                                  <p className="text-xs text-muted-foreground font-medium mt-1">{req.description}</p>
                                )}

                                <div className="flex items-center gap-3 text-3xs font-mono text-muted-foreground/80 mt-1.5 flex-wrap">
                                  <span>Accepted: <strong className="text-foreground">{allowedTypes.join(', ')}</strong></span>
                                  <span>Max: <strong className="text-foreground">{maxSizeMb} MB</strong></span>
                                </div>

                                <div className="mt-2 text-xs">
                                  {isUploaded && (state.file || state.existingFileName) ? (
                                    <div className="flex items-center gap-2 text-green-600 font-semibold truncate max-w-[280px]">
                                      <Check className="h-4 w-4 shrink-0 stroke-[2.5]" />
                                      <span className="truncate">{state.file ? state.file.name : (state.existingFileName || 'Document uploaded')}</span>
                                      <span className="text-3xs text-muted-foreground font-normal shrink-0">
                                        ({state.file ? (state.file.size / 1024 / 1024).toFixed(2) : (state.fileSizeMb ? Number(state.fileSizeMb).toFixed(2) : '0.50')} MB)
                                      </span>
                                    </div>
                                  ) : isNA ? (
                                    <span className="text-muted-foreground italic font-medium">
                                      Waived: Marked as Not Available
                                    </span>
                                  ) : isUploading ? (
                                    <div className="w-[180px] sm:w-[240px]">
                                      <div className="flex items-center justify-between text-3xs text-primary font-bold mb-1">
                                        <span className="animate-pulse">Uploading...</span>
                                        <span>{state.progress}%</span>
                                      </div>
                                      <div className="w-full bg-secondary h-1.5 rounded-full overflow-hidden border border-border/20">
                                        <div
                                          className="bg-primary h-full rounded-full transition-all duration-150"
                                          style={{ width: `${state.progress}%` }}
                                        />
                                      </div>
                                    </div>
                                  ) : null}
                                </div>
                              </div>
                            </div>

                            <div className="flex items-center justify-end gap-3 shrink-0 flex-wrap sm:flex-nowrap">
                              {!isMandatory && (
                                <div className="flex items-center gap-2 bg-secondary/50 hover:bg-secondary border border-border/60 py-1.5 px-3 rounded-lg transition-colors select-none">
                                  <input
                                    type="checkbox"
                                    id={`na-${req.name}`}
                                    checked={isNA}
                                    onChange={() => handleToggleNotAvailable(req.name)}
                                    className="h-4 w-4 accent-primary cursor-pointer"
                                  />
                                  <label htmlFor={`na-${req.name}`} className="text-xs font-bold text-muted-foreground cursor-pointer">
                                    I don't have this
                                  </label>
                                </div>
                              )}

                              {isUploaded ? (
                                <div className="inline-flex items-center gap-2">
                                  <label
                                    htmlFor={`reupload-${req.id || req.name}`}
                                    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-primary/30 bg-primary/5 hover:bg-primary/10 text-primary text-xs font-bold transition-all cursor-pointer shadow-2xs select-none"
                                    title="Replace this document with a new file"
                                  >
                                    <RefreshCw className="h-3.5 w-3.5" />
                                    <span>Re-upload</span>
                                    <input
                                      id={`reupload-${req.id || req.name}`}
                                      type="file"
                                      onChange={(e) => handleFileChange(req, e)}
                                      className="hidden"
                                      accept={allowedTypes.map((t) => `.${t.toLowerCase()}`).join(',')}
                                    />
                                  </label>
                                  <button
                                    onClick={() => handleRemoveFile(req.name)}
                                    className="p-2 rounded-lg border border-destructive/20 bg-destructive/5 hover:bg-destructive/10 text-destructive transition-colors cursor-pointer shadow-2xs"
                                    title="Clear upload"
                                  >
                                    <Trash2 className="h-4 w-4" />
                                  </button>
                                </div>
                              ) : isNA ? (
                                <span className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border/80 bg-secondary/40 text-xs font-bold text-muted-foreground select-none">
                                  <AlertTriangle className="h-3.5 w-3.5" /> Waived
                                </span>
                              ) : isUploading ? (
                                <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-primary/20 bg-primary/5 text-xs font-bold text-primary select-none">
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> uploading
                                </span>
                              ) : (
                                <label className="relative flex items-center justify-center gap-2 px-4 py-2 border border-dashed border-primary/50 bg-primary/2 hover:bg-primary/5 text-primary text-xs font-bold rounded-lg cursor-pointer transition-all duration-200 hover:border-primary">
                                  <input
                                    type="file"
                                    onChange={(e) => handleFileChange(req, e)}
                                    className="hidden"
                                    accept={allowedTypes.map((t) => `.${t.toLowerCase()}`).join(',')}
                                  />
                                  <Upload className="h-3.5 w-3.5" />
                                  <span>Upload File</span>
                                </label>
                              )}
                            </div>
                          </div>
                        </Card>
                      )
                    })}
                  </div>
                )}
              </div>

              {/* Right: Checklist sidebar */}
              <div className="space-y-6">
                <Card className="sticky top-24 border border-border bg-card rounded-2xl shadow-md overflow-hidden">
                  <div className="h-1 bg-gradient-to-r from-primary to-indigo-500" />
                  <div className="px-6 py-4 border-b border-border bg-secondary/20 flex items-center gap-2">
                    <FileCheck className="h-4 w-4 text-primary" />
                    <CardTitle className="text-sm font-bold text-foreground">Upload Checklist</CardTitle>
                  </div>
                  <CardContent className="p-6 space-y-6">
                    <div className="grid grid-cols-3 gap-3 text-center">
                      <div className="p-3 bg-green-500/5 border border-green-500/10 rounded-xl">
                        <div className="text-2xl font-black text-green-600">{uploadedCount}</div>
                        <div className="text-3xs text-muted-foreground font-extrabold uppercase mt-0.5">Uploaded</div>
                      </div>
                      <div className="p-3 bg-destructive/5 border border-destructive/10 rounded-xl">
                        <div className="text-2xl font-black text-destructive">{missingRequired.length}</div>
                        <div className="text-3xs text-muted-foreground font-extrabold uppercase mt-0.5">Missing</div>
                      </div>
                      <div className="p-3 bg-amber-500/5 border border-amber-500/10 rounded-xl">
                        <div className="text-2xl font-black text-amber-600">{notAvailableCount}</div>
                        <div className="text-3xs text-muted-foreground font-extrabold uppercase mt-0.5">Waived</div>
                      </div>
                    </div>

                    <div className="space-y-3">
                      <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Status Review</h4>
                      <div className="space-y-2">
                        {enabledDocs.map((req) => {
                          const s = docStates[req.name]
                          const uploaded = s?.status === 'Uploaded'
                          const na = s?.status === 'Not Available'
                          return (
                            <div key={req.id || req.name} className="flex items-center justify-between text-xs py-1.5 border-b border-border/50">
                              <span className="font-semibold text-muted-foreground truncate max-w-[160px]">{req.name}</span>
                              {uploaded ? (
                                <span className="inline-flex items-center gap-0.5 text-green-600 font-extrabold">
                                  <Check className="h-3.5 w-3.5 stroke-[2.5]" /> Ready
                                </span>
                              ) : na ? (
                                <span className="inline-flex items-center gap-0.5 text-amber-600 font-bold">
                                  <AlertCircle className="h-3.5 w-3.5" /> Waived
                                </span>
                              ) : (
                                <span className="text-destructive font-bold inline-flex items-center gap-0.5">
                                  <X className="h-3.5 w-3.5 stroke-[2.5]" /> Pending
                                </span>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>

                    {!canSubmit ? (
                      <div className="p-4 bg-destructive/5 border border-destructive/10 rounded-xl flex gap-3 text-destructive">
                        <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
                        <div className="text-xs font-semibold leading-relaxed">
                          Upload all mandatory files and handle optional documents.
                        </div>
                      </div>
                    ) : (
                      <div className="p-4 bg-green-500/5 border border-green-500/10 rounded-xl flex gap-3 text-green-600">
                        <ShieldCheck className="h-5 w-5 shrink-0 mt-0.5" />
                        <div className="text-xs font-semibold leading-relaxed">
                          All documents ready for secure persistent storage.
                        </div>
                      </div>
                    )}

                    <div className="space-y-3 pt-4 border-t border-border">
                      <Button
                        variant="primary"
                        className="w-full py-5 rounded-xl font-bold shadow-md shadow-primary/10 text-sm flex items-center justify-center gap-2 cursor-pointer transition-all"
                        onClick={handleUploadSubmit}
                        disabled={!canSubmit || isSubmitting}
                      >
                        {isSubmitting ? (
                          <>
                            <Loader2 className="h-4.5 w-4.5 animate-spin" />
                            <span>Saving Documents...</span>
                          </>
                        ) : (
                          <>
                            <span>Submit Documents</span>
                            <ArrowRight className="h-4.5 w-4.5" />
                          </>
                        )}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          )}

          {/* ══ STEP 3: Complete / Saved ══ */}
          {step === 3 && (
            <Card className="border border-border bg-card shadow-2xl max-w-xl mx-auto overflow-hidden rounded-2xl">
              <div className="h-2 bg-gradient-to-r from-emerald-500 to-green-500" />
              <CardContent className="p-8 space-y-8 text-center">
                <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-green-500/10 text-green-600 border border-green-500/20 shadow-md">
                  <CheckCircle className="h-10 w-10 animate-[bounce_1s_ease-in-out_1]" />
                </div>
                <div className="space-y-2">
                  <h3 className="text-2xl font-black text-foreground">Document Upload Completed</h3>
                  <p className="text-base font-semibold text-green-600 dark:text-green-400">
                    Document uploaded successfully
                  </p>
                  <p className="text-sm text-muted-foreground">
                    Your documents have been securely saved and are available for admissions staff processing.
                  </p>
                </div>

                <div className="border border-border rounded-xl bg-secondary/20 p-5 space-y-3.5 text-left shadow-inner">
                  <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                    <Layers className="h-4 w-4 text-primary" /> Enrollment Submission Slip
                  </h4>
                  <div className="grid grid-cols-2 gap-y-3.5 gap-x-4 text-xs pt-2">
                    <div>
                      <span className="text-muted-foreground block text-2xs uppercase font-semibold">Submission ID</span>
                      <span className="font-bold text-foreground font-mono truncate block max-w-[200px]">
                        {submissionId || 'sub_stored'}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block text-2xs uppercase font-semibold">Cohort Batch</span>
                      <span className="font-bold text-foreground">{batchName}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block text-2xs uppercase font-semibold">Student Name</span>
                      <span className="font-bold text-foreground">{studentName}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block text-2xs uppercase font-semibold">Register Number</span>
                      <span className="font-bold text-foreground font-mono">{registerNum}</span>
                    </div>
                    {mobileNum && (
                      <div>
                        <span className="text-muted-foreground block text-2xs uppercase font-semibold">Mobile</span>
                        <span className="font-bold text-foreground">{mobileNum}</span>
                      </div>
                    )}
                    {email && (
                      <div>
                        <span className="text-muted-foreground block text-2xs uppercase font-semibold">Email</span>
                        <span className="font-bold text-foreground truncate block">{email}</span>
                      </div>
                    )}
                    <div>
                      <span className="text-muted-foreground block text-2xs uppercase font-semibold">Saved Time</span>
                      <span className="font-bold text-foreground font-mono">
                        {submissionTime || new Date().toLocaleString()}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block text-2xs uppercase font-semibold">Status</span>
                      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-3xs font-extrabold uppercase bg-green-100 text-green-800 border border-green-200 dark:bg-green-950/40 dark:text-green-300 dark:border-green-800">
                        <ShieldCheck className="h-3 w-3" /> Successfully Saved
                      </span>
                    </div>
                  </div>
                </div>

                {savedDocuments.length > 0 && (
                  <div className="border border-border rounded-xl bg-secondary/10 p-4 text-left space-y-2.5">
                    <h5 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
                      Stored Documents ({savedDocuments.filter((d) => d.status === 'Uploaded').length})
                    </h5>
                    <div className="space-y-1.5 max-h-48 overflow-y-auto">
                      {savedDocuments.map((d, i) => (
                        <div
                          key={i}
                          className="flex items-center justify-between text-xs py-1.5 px-2 rounded-lg bg-card border border-border/60"
                        >
                          <div className="flex items-center gap-2 truncate">
                            <FileText className="h-3.5 w-3.5 text-primary shrink-0" />
                            <span className="font-semibold text-foreground truncate">{d.document_name}</span>
                            {d.status === 'Uploaded' && d.version && (
                              <span className="inline-flex items-center px-1.5 py-0.2 rounded text-3xs font-extrabold bg-primary/10 text-primary border border-primary/20">
                                v{d.version}
                              </span>
                            )}
                          </div>
                          <div className="shrink-0">
                            {d.status === 'Uploaded' ? (
                              <span className="text-3xs font-bold text-green-600 bg-green-500/10 px-2 py-0.5 rounded border border-green-500/20">
                                Saved {d.file_size_mb ? `(${d.file_size_mb} MB)` : ''}
                              </span>
                            ) : (
                              <span className="text-3xs font-medium text-muted-foreground italic">
                                Waived
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="pt-2">
                  <Button
                    variant="primary"
                    className="w-full py-4 rounded-xl cursor-pointer shadow-md shadow-primary/10 hover:shadow-lg transition-all"
                    onClick={() => window.close()}
                  >
                    Close Portal
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </main>
    </div>
  )
}
