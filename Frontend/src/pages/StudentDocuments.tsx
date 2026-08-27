import React, { useState, useEffect } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useToastStore } from '../store/useToastStore'
import { useAuthStore } from '../store/useAuthStore'
import { Button } from '../components/ui/Button'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card'
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
  Terminal,
  Layers,
  Sparkles,
  Edit2,
  Save,
  ArrowLeft,
  ShieldAlert,
  Printer,
} from 'lucide-react'
import type { DocumentRequirement } from '../types'

/* ─── Local types ─── */
interface DocumentState {
  file: File | null
  status: 'Pending' | 'Uploading' | 'Uploaded' | 'Not Available'
  progress: number
}

interface VerificationLog {
  name: string
  status: 'pending' | 'scanning' | 'complete'
}

interface ExtractedField {
  value: string
  confidence: number
}

/* ─── Fallback requirements if no doc-version configured ─── */
const fallbackRequirements: DocumentRequirement[] = [
  {
    id: 'req_1',
    name: 'Aadhaar Card',
    required: true,
    allowedTypes: ['PDF', 'JPG', 'PNG'],
    maxSizeMb: 5,
    description: 'Upload front and back side of Aadhaar card',
    type: 'MANDATORY',
  },
  {
    id: 'req_5',
    name: 'SSLC Marksheet',
    required: true,
    allowedTypes: ['PDF', 'JPG', 'PNG'],
    maxSizeMb: 5,
    description: '10th grade official marks statement',
    type: 'MANDATORY',
  },
  {
    id: 'req_6',
    name: 'HSC Marksheet',
    required: true,
    allowedTypes: ['PDF', 'JPG', 'PNG'],
    maxSizeMb: 5,
    description: '12th grade / Diploma final marks statement',
    type: 'MANDATORY',
  },
  {
    id: 'req_3',
    name: 'Community Certificate',
    required: true,
    allowedTypes: ['PDF', 'JPG'],
    maxSizeMb: 5,
    description: 'Caste / Community reservation proof',
    type: 'MANDATORY',
  },
]

/* ─── Stepper config ─── */
const STEPS = [
  { number: 1, label: 'Identify' },
  { number: 2, label: 'Upload' },
  { number: 3, label: 'Processing' },
  { number: 4, label: 'Verify' },
  { number: 5, label: 'Success' },
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

   Route: /upload/:batchId/documents[/processing|/verify|/success]

   On mount this component reads the temporary submission session from
   sessionStorage (written by StudentUpload after identity verification).
   If the session is missing the student is redirected back to the
   admissions portal root — no auth, no login required.
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
  const [assignedRequirements, setAssignedRequirements] = useState<DocumentRequirement[]>([])
  const [isLoadingBatch, setIsLoadingBatch] = useState(true)

  /* ── Document upload states ── */
  const [docStates, setDocStates] = useState<Record<string, DocumentState>>({})
  const [draggedOverDoc, setDraggedOverDoc] = useState<string | null>(null)

  /* ── AI extraction ── */
  const [extractedData, setExtractedData] = useState<Record<string, ExtractedField>>({})
  const [editingFields, setEditingFields] = useState<Record<string, boolean>>({})
  const [confirmCheckbox, setConfirmCheckbox] = useState(false)

  /* ── Submission receipt ── */
  const [submissionId, setSubmissionId] = useState('')
  const [submissionTime, setSubmissionTime] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)

  /* ── Processing console logs ── */
  const [verificationLogs, setVerificationLogs] = useState<VerificationLog[]>([
    { name: 'Uploading PDFs to secure admissions server...', status: 'pending' },
    { name: 'Running OCR Document Processing maps...', status: 'pending' },
    { name: 'AI Extracting requested fields & confidence metrics...', status: 'pending' },
    { name: 'Preparing verification payloads...', status: 'pending' },
  ])

  /* ── Derive current step from URL path ── */
  const step = location.pathname.endsWith('/processing')
    ? 3
    : location.pathname.endsWith('/verify')
    ? 4
    : location.pathname.endsWith('/success')
    ? 5
    : 2

  /* ── On mount: read session; redirect if missing ── */
  useEffect(() => {
    const session = readSubmissionSession()
    if (!session || session.batch_id !== batchId) {
      // No valid session — redirect to login root (not /login — just a public page)
      addToast('Your session has expired. Please identify yourself again.', 'error')
      navigate('/', { replace: true })
      return
    }
    setStudentName(session.student_name)
    setRegisterNum(session.register_number)
    setMobileNum(session.mobile_number)
    setBatchName(session.batch_name)
    if (session.class_id) setClassId(session.class_id)
    if (session.class_name) setClassName(session.class_name)

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
  }, [batchId])

  /* ── Load batch doc requirements ── */
  useEffect(() => {
    if (!sessionLoaded || !batchId) return

    const loadRequirements = async () => {
      setIsLoadingBatch(true)
      try {
        const currentV = await api.get(`/public/batches/${batchId}/doc-versions/current`)
        const reqs: DocumentRequirement[] = (currentV.data.documents || []).map((d: any) => ({
          id: d.id,
          name: d.name,
          required: d.required,
          allowedTypes: d.allowed_types || ['PDF', 'JPG', 'PNG'],
          maxSizeMb: d.max_size_mb || 5,
          description: d.description || '',
          type: d.type || 'MANDATORY',
        }))
        setAssignedRequirements(reqs.length > 0 ? reqs : fallbackRequirements)
      } catch {
        setAssignedRequirements(fallbackRequirements)
      } finally {
        setIsLoadingBatch(false)
      }
    }

    loadRequirements()
  }, [sessionLoaded, batchId])

  /* ── Initialise doc states when requirements load ── */
  useEffect(() => {
    if (assignedRequirements.length > 0 && Object.keys(docStates).length === 0) {
      const initial: Record<string, DocumentState> = {}
      assignedRequirements
        .filter((r) => r.type !== 'DISABLED')
        .forEach((r) => {
          initial[r.name] = { file: null, status: 'Pending', progress: 0 }
        })
      setDocStates(initial)
    }
  }, [assignedRequirements])

  /* ── Guard: direct URL access to deep steps without session ── */
  useEffect(() => {
    if (sessionLoaded && step > 2 && !studentName) {
      navigate(`/upload/${batchId}/documents`, { replace: true })
    }
  }, [step, studentName, sessionLoaded])

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

    setDocStates((prev) => ({
      ...prev,
      [req.name]: { ...prev[req.name], status: 'Uploading', progress: 0 },
    }))

    let progress = 0
    const interval = setInterval(() => {
      progress += 10 + Math.floor(Math.random() * 15)
      setDocStates((prev) => {
        if (progress >= 100) {
          clearInterval(interval)
          return { ...prev, [req.name]: { file, status: 'Uploaded', progress: 100 } }
        }
        return { ...prev, [req.name]: { ...prev[req.name], progress } }
      })
    }, 100)
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
    setDocStates((prev) => ({ ...prev, [docName]: { file: null, status: 'Pending', progress: 0 } }))
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

  const canSubmit = missingRequired.length === 0 && missingOptional.length === 0

  /* ─────────────────────────────────────────────
     Step 2 → 3: Trigger AI extraction
  ───────────────────────────────────────────── */
  const handleUploadSubmit = async () => {
    if (!canSubmit) {
      addToast('Please upload all required files or mark optional documents as waived.', 'error')
      return
    }

    navigate(`/upload/${batchId}/documents/processing`)
    setVerificationLogs((prev) => prev.map((l) => ({ ...l, status: 'pending' })))
    setIsProcessing(true)

    const formData = new FormData()
    formData.append('batch_id', batchId!)
    formData.append('register_number', registerNum)
    formData.append('student_name', studentName)
    if (mobileNum) formData.append('mobile_number', mobileNum)

    Object.values(docStates).forEach((ds) => {
      if (ds.file) formData.append('files', ds.file)
    })

    let logIdx = 0
    const logInterval = setInterval(() => {
      setVerificationLogs((prev) =>
        prev.map((l, i) => {
          if (i === logIdx) return { ...l, status: 'scanning' }
          if (i < logIdx) return { ...l, status: 'complete' }
          return l
        })
      )
      logIdx++
    }, 800)

    try {
      const response = await api.post('/student-submissions/extract', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const rawExtracted = response.data.verification_fields || response.data.extracted_data || {}
      setExtractedData(rawExtracted)

      setTimeout(() => {
        clearInterval(logInterval)
        setVerificationLogs((prev) => prev.map((l) => ({ ...l, status: 'complete' })))
        setIsProcessing(false)
        addToast('Documents processed! Please verify details.', 'success')
        navigate(`/upload/${batchId}/documents/verify`)
      }, 3200)
    } catch (err: any) {
      clearInterval(logInterval)
      setIsProcessing(false)
      addToast(err.response?.data?.detail || 'Document extraction failed. Try again.', 'error')
      navigate(`/upload/${batchId}/documents`)
    }
  }

  /* ─────────────────────────────────────────────
     Step 4 → 5: Confirm and save submission
  ───────────────────────────────────────────── */
  const handleConfirmSubmit = async () => {
    if (!confirmCheckbox) {
      addToast('Please review details and check the confirmation box.', 'error')
      return
    }

    setIsProcessing(true)

    const formattedDocs = enabledDocs.map((req) => {
      const s = docStates[req.name]
      return {
        document_name: req.name,
        status:
          s?.status === 'Uploaded'
            ? 'Uploaded'
            : s?.status === 'Not Available'
            ? 'Not Available'
            : 'Pending',
        file_path: s?.file
          ? `uploads/${batchId}/${registerNum}/${s.file.name}`
          : undefined,
        file_size_mb: s?.file ? Number((s.file.size / (1024 * 1024)).toFixed(1)) : undefined,
        file_type: s?.file ? s.file.name.split('.').pop()?.toUpperCase() : undefined,
        uploaded_at: new Date().toISOString(),
      }
    })

    const verifiedDict: Record<string, string | null> = {}
    Object.keys(extractedData).forEach((k) => {
      verifiedDict[k] = extractedData[k].value
    })

    const payload = {
      batch_id: batchId,
      batch_name: batchName,
      class_id: classId,
      class_name: className,
      student_name: studentName,
      register_number: registerNum,
      mobile_number: mobileNum,
      email: email || undefined,
      submission_status: 'Verified',
      documents: formattedDocs,
      extracted_data: verifiedDict,
    }

    try {
      const response = await api.post('/student-submissions/confirm', payload)
      const data = response.data
      setSubmissionId(data.id)
      setSubmissionTime(new Date(data.submitted_at).toLocaleString())
      setIsProcessing(false)
      clearSubmissionSession()
      addToast('Application submitted & Excel updated!', 'success')
      navigate(`/upload/${batchId}/documents/success`)
    } catch (err: any) {
      setIsProcessing(false)
      addToast(err.response?.data?.detail || 'Finalization failed. Try again.', 'error')
    }
  }

  const handleFieldChange = (fieldName: string, val: string) =>
    setExtractedData((prev) => ({
      ...prev,
      [fieldName]: { ...prev[fieldName], value: val },
    }))

  const toggleEditField = (fieldName: string) =>
    setEditingFields((prev) => ({ ...prev, [fieldName]: !prev[fieldName] }))

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
    <div className="flex min-h-screen flex-col bg-[#f9fafb] dark:bg-[#080d16] transition-colors duration-300">

      {/* ── Header ── */}
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
              Dynamic Portal
            </span>
          </div>
        </div>
        <div className="hidden sm:flex items-center gap-2 text-xs font-semibold text-muted-foreground">
          <span className="px-2 py-0.5 bg-secondary rounded-md border border-border">
            {studentName}
          </span>
          <span className="text-border">·</span>
          <span className="font-mono">{registerNum}</span>
        </div>
        <div className="flex items-center gap-2 text-xs font-bold text-muted-foreground bg-secondary/80 px-3 py-1.5 rounded-xl border border-border/80">
          <Lock className="h-3.5 w-3.5 text-primary shrink-0" />
          <span>AES-256 Secured</span>
        </div>
      </header>

      {/* ── Stepper ── */}
      <div className="w-full max-w-4xl mx-auto px-4 pt-8 pb-4">
        <div className="relative flex items-center justify-between">
          <div className="absolute left-0 top-1/2 h-0.5 w-full -translate-y-1/2 bg-border dark:bg-border/40" />
          <div
            className="absolute left-0 top-1/2 h-0.5 -translate-y-1/2 bg-primary transition-all duration-500"
            style={{ width: `${((step - 1) / 4) * 100}%` }}
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
                        key={req.name}
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
                                  {isMandatory ? 'Required' : 'Optional'}
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
                                {isUploaded && state.file ? (
                                  <div className="flex items-center gap-2 text-green-600 font-semibold truncate max-w-[280px]">
                                    <Check className="h-4 w-4 shrink-0 stroke-[2.5]" />
                                    <span className="truncate">{state.file.name}</span>
                                    <span className="text-3xs text-muted-foreground font-normal shrink-0">
                                      ({(state.file.size / 1024 / 1024).toFixed(2)} MB)
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
                              <div className="inline-flex gap-2">
                                <label className="relative flex items-center justify-center p-2 rounded-lg border border-border bg-card hover:bg-secondary text-muted-foreground hover:text-foreground cursor-pointer transition-colors shadow-2xs">
                                  <input
                                    type="file"
                                    onChange={(e) => handleFileChange(req, e)}
                                    className="hidden"
                                    accept={allowedTypes.map((t) => `.${t.toLowerCase()}`).join(',')}
                                  />
                                  <RefreshCw className="h-4 w-4" />
                                </label>
                                <button
                                  onClick={() => handleRemoveFile(req.name)}
                                  className="p-2 rounded-lg border border-destructive/20 bg-destructive/5 hover:bg-destructive/10 text-destructive transition-colors cursor-pointer shadow-2xs"
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
              </div>

              {/* Right: Checklist sidebar */}
              <div className="space-y-6">
                <Card className="sticky top-24 border border-border bg-card rounded-2xl shadow-md overflow-hidden">
                  <div className="h-1 bg-gradient-to-r from-primary to-indigo-500" />
                  <div className="px-6 py-4 border-b border-border bg-secondary/20 flex items-center gap-2">
                    <FileCheck className="h-4 w-4 text-primary" />
                    <CardTitle className="text-sm font-bold text-foreground">Verification Checklist</CardTitle>
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
                            <div key={req.name} className="flex items-center justify-between text-xs py-1.5 border-b border-border/50">
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
                        <ShieldCheck className="h-5 w-5 shrink-0 mt-0.5 animate-pulse" />
                        <div className="text-xs font-semibold leading-relaxed">
                          All documents ready! Proceed to AI validation.
                        </div>
                      </div>
                    )}

                    <div className="space-y-3 pt-4 border-t border-border">
                      <Button
                        variant="primary"
                        className="w-full py-5 rounded-xl font-bold shadow-md shadow-primary/10 text-sm flex items-center justify-center gap-2 cursor-pointer transition-all"
                        onClick={handleUploadSubmit}
                        disabled={!canSubmit}
                      >
                        Submit Documents <ArrowRight className="h-4.5 w-4.5" />
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          )}

          {/* ══ STEP 3: Processing ══ */}
          {step === 3 && (
            <Card className="border border-border bg-card shadow-xl max-w-xl mx-auto overflow-hidden rounded-2xl">
              <div className="h-2 bg-gradient-to-r from-primary to-indigo-500" />
              <CardContent className="p-8 text-center space-y-6">
                <div className="relative mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-primary/5 text-primary border border-primary/20">
                  <Loader2 className="h-10 w-10 animate-spin" />
                </div>
                <div className="space-y-2">
                  <h3 className="text-xl font-black text-foreground">Processing Your Documents</h3>
                  <p className="text-sm text-muted-foreground max-w-sm mx-auto">
                    Analyzing visual document boundaries, executing OCR character extraction, and saving verified directory data.
                  </p>
                </div>

                <div className="bg-[#0f172a] text-green-400 font-mono text-left text-xs p-4 rounded-xl border border-slate-800 shadow-inner max-w-md mx-auto space-y-2.5">
                  <div className="flex items-center gap-2 text-slate-400 border-b border-slate-800 pb-2 mb-2">
                    <Terminal className="h-4 w-4" />
                    <span className="font-bold text-3xs uppercase tracking-wider">OCR Processing Console</span>
                  </div>
                  {verificationLogs.map((log, i) => {
                    const done = log.status === 'complete'
                    const scanning = log.status === 'scanning'
                    return (
                      <div
                        key={i}
                        className={`flex items-center gap-2.5 transition-opacity duration-300 ${!done && !scanning ? 'opacity-30' : 'opacity-100'}`}
                      >
                        {done ? (
                          <Check className="h-3.5 w-3.5 text-green-400 shrink-0 stroke-[2.5]" />
                        ) : scanning ? (
                          <Loader2 className="h-3.5 w-3.5 text-primary animate-spin shrink-0" />
                        ) : (
                          <div className="h-3.5 w-3.5 rounded-full border border-slate-600 shrink-0" />
                        )}
                        <span className={scanning ? 'text-white font-bold animate-pulse' : ''}>{log.name}</span>
                      </div>
                    )
                  })}
                </div>
              </CardContent>
            </Card>
          )}

          {/* ══ STEP 4: Verify AI Fields ══ */}
          {step === 4 && (() => {
            const getFieldIcon = (name: string) => {
              const lower = name.toLowerCase()
              if (lower.includes('aadhaar') || lower.includes('aadhar')) return <CreditCard className="h-4 w-4 text-blue-500" />
              if (lower.includes('community') || lower.includes('caste')) return <Award className="h-4 w-4 text-amber-500" />
              if (lower.includes('category')) return <Users className="h-4 w-4 text-purple-500" />
              if (lower.includes('birth') || lower.includes('dob')) return <Baby className="h-4 w-4 text-pink-500" />
              if (lower.includes('income') || lower.includes('bank') || lower.includes('ifsc') || lower.includes('account')) return <CircleDollarSign className="h-4 w-4 text-emerald-500" />
              if (lower.includes('mark') || lower.includes('sslc') || lower.includes('hsc')) return <Award className="h-4 w-4 text-purple-500" />
              return <FileText className="h-4 w-4 text-primary" />
            }

            const PROFILE_FIELDS = ['student name', 'register number', 'mobile number', 'email', 'name', 'register no', 'mobile']
            const isProfileField = (fieldName: string) => {
              const lower = fieldName.toLowerCase().trim()
              return PROFILE_FIELDS.some(p => lower === p || lower.includes('student name') || lower.includes('register number') || lower.includes('mobile number'))
            }

            const isYesNoQuestionField = (name: string): boolean => {
              if (!name) return false
              const lower = name.trim().toLowerCase()
              if (lower.includes('yes/no') || lower.includes('yes / no') || lower.endsWith('?')) return true
              if (['is ', 'did ', 'does ', 'whether ', 'has '].some((p) => lower.startsWith(p))) return true
              if (['same as', 'first graduate', 'special admission', 'differently abled', 'orphan'].some((p) => lower.includes(p))) return true
              return false
            }

            const documentFields = Object.keys(extractedData).filter(f => !isProfileField(f))

            return (
              <Card className="border border-border bg-card shadow-xl max-w-3xl mx-auto overflow-hidden rounded-2xl">
                <div className="h-2 bg-gradient-to-r from-primary to-indigo-500" />
                <CardHeader className="text-center pt-8 pb-6 border-b border-border">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-500/10 text-indigo-600 mb-4 border border-indigo-500/10">
                    <Sparkles className="h-6 w-6" />
                  </div>
                  <CardTitle className="text-2xl font-black text-foreground">Verify Extracted Information</CardTitle>
                  <CardDescription className="mt-1">
                    Review your account profile details and verified document fields before final submission.
                  </CardDescription>
                </CardHeader>
                <CardContent className="p-6 md:p-8 space-y-6">

                  {/* Section 1: Account Profile (Read Only) */}
                  <div className="p-5 rounded-2xl border border-primary/20 bg-primary/5 space-y-3">
                    <div className="flex items-center gap-2 text-xs font-extrabold uppercase tracking-wider text-primary">
                      <Lock className="h-3.5 w-3.5" />
                      <span>Section 1: Account Profile (Read Only)</span>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                      <div>
                        <span className="text-muted-foreground block font-semibold">Student Name</span>
                        <span className="font-bold text-foreground text-sm">{studentName}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground block font-semibold">Register Number</span>
                        <span className="font-bold text-foreground text-sm">{registerNum}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground block font-semibold">Mobile Number</span>
                        <span className="font-bold text-foreground text-sm">{mobileNum}</span>
                      </div>
                      {email && (
                        <div>
                          <span className="text-muted-foreground block font-semibold">Email</span>
                          <span className="font-bold text-foreground text-sm">{email}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Section 2: Document Extraction Results */}
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <h4 className="text-xs font-extrabold uppercase tracking-wider text-foreground flex items-center gap-2">
                        <FileText className="h-4 w-4 text-primary" />
                        <span>Section 2: Document Extraction Results</span>
                      </h4>
                      <span className="text-2xs font-semibold text-muted-foreground bg-secondary px-2.5 py-1 rounded-full border border-border">
                        {documentFields.length} Document Field{documentFields.length !== 1 ? 's' : ''}
                      </span>
                    </div>

                    {documentFields.length === 0 ? (
                      <div className="p-6 rounded-2xl border border-dashed border-border text-center space-y-2 bg-secondary/10">
                        <CheckCircle className="h-8 w-8 text-green-500 mx-auto" />
                        <p className="text-sm font-bold text-foreground">All Profile Details Verified</p>
                        <p className="text-xs text-muted-foreground">
                          Account profile details verified from student identification. No additional document fields required.
                        </p>
                      </div>
                    ) : (
                      <div className="grid grid-cols-1 gap-4">
                        {documentFields.map((fieldName) => {
                          const item = extractedData[fieldName]
                          const value = typeof item === 'object' && item !== null ? item.value : item
                          const rawConf = typeof item === 'object' && item !== null ? item.confidence : undefined
                          const isYesNoQuestion = isYesNoQuestionField(fieldName)
                          const isMissingValue =
                            value === null ||
                            value === undefined ||
                            String(value).trim() === '' ||
                            String(value).trim().toLowerCase() === 'not detected' ||
                            String(value).trim().toUpperCase() === 'NULL' ||
                            (!isYesNoQuestion && (value === 'NO' || value === 'No' || rawConf === 0))
                          const isOptionalUnuploaded = (value === 'No' || value === 'NO') && rawConf === 0
                          const confidence = isMissingValue ? 0 : (rawConf !== undefined && rawConf !== null ? rawConf : 80)
                          const isLow = !isMissingValue && !isOptionalUnuploaded && confidence > 0 && confidence < 90
                          const isEditing = editingFields[fieldName]

                          return (
                            <div
                              key={fieldName}
                              className={`p-5 rounded-2xl border transition-all duration-300 ${
                                isLow
                                  ? 'border-amber-500/40 bg-amber-500/5 dark:bg-amber-950/10 shadow-sm ring-1 ring-amber-500/20'
                                  : 'border-border bg-card hover:bg-secondary/10'
                              }`}
                            >
                              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                                <div className="flex-1 space-y-1.5 min-w-0">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    {getFieldIcon(fieldName)}
                                    <span className="text-xs font-bold text-foreground uppercase tracking-wider">
                                      {fieldName}
                                    </span>
                                    <span
                                      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-3xs font-extrabold uppercase border ${
                                        isMissingValue
                                          ? 'bg-secondary/80 text-muted-foreground border-border'
                                          : confidence >= 95
                                          ? 'bg-green-500/10 text-green-600 border-green-500/15'
                                          : confidence >= 90
                                          ? 'bg-blue-500/10 text-blue-600 border-blue-500/15'
                                          : 'bg-amber-500/10 text-amber-600 border-amber-500/15'
                                      }`}
                                    >
                                      {isLow && <ShieldAlert className="h-3 w-3 stroke-[2.5]" />}
                                      {confidence}% confidence
                                    </span>
                                    {isLow && (
                                      <span className="text-3xs font-bold text-amber-600 animate-pulse bg-amber-100 dark:bg-amber-900/40 px-2 py-0.5 rounded border border-amber-200 dark:border-amber-900/60">
                                        Review Flagged
                                      </span>
                                    )}
                                  </div>

                                  {isEditing ? (
                                    <input
                                      type="text"
                                      value={value === 'NO' || value === 'NULL' ? '' : value || ''}
                                      onChange={(e) => handleFieldChange(fieldName, e.target.value)}
                                      className="flex h-10 w-full rounded-lg border border-primary bg-card px-3 py-2 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                      autoFocus
                                    />
                                  ) : (
                                    <div className="text-base font-bold text-foreground truncate">
                                      {!isMissingValue && value !== null && value !== undefined && String(value).trim() !== '' ? (
                                        String(value)
                                      ) : (
                                        <span className="text-muted-foreground italic font-normal">Not detected</span>
                                      )}
                                    </div>
                                  )}
                                </div>

                                <div className="shrink-0">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="font-bold flex items-center gap-1.5 cursor-pointer hover:bg-secondary"
                                    onClick={() => toggleEditField(fieldName)}
                                  >
                                    {isEditing ? (
                                      <><Save className="h-3.5 w-3.5 text-primary" /> <span>Done</span></>
                                    ) : (
                                      <><Edit2 className="h-3.5 w-3.5 text-muted-foreground" /> <span>Edit</span></>
                                    )}
                                  </Button>
                                </div>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>

                  <div className="flex items-start gap-3 bg-secondary/30 border border-border p-4 rounded-xl select-none mt-6">
                    <input
                      type="checkbox"
                      id="confirm-cb"
                      checked={confirmCheckbox}
                      onChange={(e) => setConfirmCheckbox(e.target.checked)}
                      className="h-5 w-5 accent-primary cursor-pointer mt-0.5"
                    />
                    <label htmlFor="confirm-cb" className="text-xs font-semibold text-muted-foreground leading-relaxed cursor-pointer">
                      I confirm that the above information is correct. I have reviewed and corrected any OCR extraction mistakes.
                    </label>
                  </div>

                  <div className="flex gap-4 pt-4 border-t border-border mt-6">
                    <Button
                      variant="outline"
                      className="w-full py-5 rounded-xl font-bold text-sm flex items-center justify-center gap-2 cursor-pointer transition-all"
                      onClick={() => navigate(`/upload/${batchId}/documents`)}
                    >
                      <ArrowLeft className="h-4 w-4" /> Back to Uploads
                    </Button>
                    <Button
                      variant="primary"
                      className="w-full py-5 rounded-xl font-bold shadow-md shadow-primary/10 text-sm flex items-center justify-center gap-2 cursor-pointer transition-all"
                      onClick={handleConfirmSubmit}
                      disabled={!confirmCheckbox || isProcessing}
                    >
                      {isProcessing ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <><span>Confirm &amp; Submit</span> <ArrowRight className="h-4 w-4" /></>
                      )}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )
          })()}


          {/* ══ STEP 5: Success ══ */}
          {step === 5 && (
            <Card className="border border-border bg-card shadow-2xl max-w-xl mx-auto overflow-hidden rounded-2xl">
              <div className="h-2 bg-gradient-to-r from-emerald-500 to-green-500" />
              <CardContent className="p-8 space-y-8 text-center">
                <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-green-500/10 text-green-600 border border-green-500/20 shadow-md">
                  <CheckCircle className="h-10 w-10 animate-[bounce_1s_ease-in-out_1]" />
                </div>
                <div className="space-y-2">
                  <h3 className="text-2xl font-black text-foreground">Submission Successful</h3>
                  <p className="text-sm text-muted-foreground">
                    Your documents have been successfully verified and cataloged under your admissions cohort file profile.
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
                        {submissionId || 'sub_pending'}
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
                    <div>
                      <span className="text-muted-foreground block text-2xs uppercase font-semibold">Submission Time</span>
                      <span className="font-bold text-foreground font-mono">
                        {submissionTime || new Date().toLocaleString()}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block text-2xs uppercase font-semibold">Status</span>
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-3xs font-extrabold uppercase bg-green-100 text-green-800 border border-green-200">
                        Verified
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex flex-col sm:flex-row gap-3 pt-2">
                  <Button
                    variant="outline"
                    className="w-full py-4 rounded-xl cursor-pointer flex items-center justify-center gap-2"
                    onClick={() => window.print()}
                  >
                    <Printer className="h-4 w-4" /> Print Receipt
                  </Button>
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
