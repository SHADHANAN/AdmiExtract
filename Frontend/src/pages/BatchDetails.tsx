import React, { useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Modal } from '../components/ui/Modal'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../components/ui/Table'
import { EmptyState } from '../components/ui/EmptyState'
import { useBatchStore } from '../store/useBatchStore'
import { useStudentStore } from '../store/useStudentStore'
import { useToastStore } from '../store/useToastStore'
import {
  ArrowLeft,
  Users,
  Link as LinkIcon,
  FileText,
  Download,
  Copy,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Share2,
  Calendar,
  MessageSquare,
  Mail,
  Plus,
  Eye,
  CheckCircle,
  XCircle,
  Clock,
  Maximize2,
  Loader2,
  Layers,
  FolderOpen,
  AlertTriangle,
  RefreshCw,
  ArrowRight,
  Sparkles,
  ShieldCheck,
  FileCheck,
  HelpCircle,
} from 'lucide-react'
import { DocumentPreviewModal, type DocumentPreviewTarget } from '../components/ui/DocumentPreviewModal'
import { ReclassifyModal } from '../components/ReclassifyModal'
import { ClassificationEvidenceModal } from '../components/ClassificationEvidenceModal'
import type { DocumentRequirement, StudentSubmission } from '../types'
import { studentSubmissionService } from '../services/studentSubmission'
import { wantedFieldService, type DocumentTypeOverviewItem } from '../services/wantedField'
import {
  studentDocumentService,
  type BatchDocumentValidationResponse,
  type BatchDocumentValidationItem,
} from '../services/studentDocument'
import { copyToClipboard } from '../utils/clipboard'
import { getStudentUploadUrl } from '../utils/studentPortalUrl'

export const BatchDetails: React.FC = () => {
  const { batchId } = useParams<{ batchId: string }>()
  const navigate = useNavigate()
  const {
    batches,
    uploadLinks,
    addUploadLink,
    toggleUploadLink,
    updateUploadLinkExpiry,
    deleteUploadLink,
    fetchBatches,
    fetchUploadLinks,
    classesByBatch,
    fetchClassesForBatch,
    createClass,
    deleteClass,
  } = useBatchStore()
  const { submissions, updateStudentStatus, fetchSubmissionsByBatch } = useStudentStore()
  const { addToast } = useToastStore()

  const [selectedClassId, setSelectedClassId] = useState<string>('all')

  // Explicit State Handling: loading, error, notFound, success
  const [isLoading, setIsLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)

  // Fetch student submissions, batches, and upload links from FastAPI backend with error handling
  const loadBatchData = React.useCallback(async () => {
    if (!batchId) return
    setIsLoading(true)
    setFetchError(null)
    try {
      await Promise.all([
        fetchSubmissionsByBatch(batchId),
        fetchBatches(),
        fetchUploadLinks(),
        fetchClassesForBatch(batchId),
      ])
    } catch (err: any) {
      console.error('Failed to load batch data:', err)
      setFetchError(err.message || 'Failed to fetch batch data from server.')
    } finally {
      setIsLoading(false)
    }
  }, [batchId, fetchSubmissionsByBatch, fetchBatches, fetchUploadLinks, fetchClassesForBatch])

  React.useEffect(() => {
    loadBatchData()
  }, [loadBatchData])

  const [searchParams] = useSearchParams()
  const initialTab = searchParams.get('tab')

  // Active Tab state — Default to 'sections' or URL parameter
  const [activeTab, setActiveTab] = useState<'sections' | 'students' | 'validation' | 'documents' | 'links'>(
    (initialTab as any) || 'sections'
  )

  // Document Validation state
  const [validationData, setValidationData] = useState<BatchDocumentValidationResponse | null>(null)
  const [isLoadingValidation, setIsLoadingValidation] = useState(false)
  const [validationStatusFilter, setValidationStatusFilter] = useState<string>('ALL')
  const [validationSearchQuery, setValidationSearchQuery] = useState<string>('')
  const [selectedDocForReclassify, setSelectedDocForReclassify] = useState<BatchDocumentValidationItem | null>(null)
  const [selectedDocForEvidence, setSelectedDocForEvidence] = useState<BatchDocumentValidationItem | null>(null)

  // Create Section Modal states
  const [isSectionModalOpen, setIsSectionModalOpen] = useState(false)
  const [newSecName, setNewSecName] = useState('')
  const [newSecCode, setNewSecCode] = useState('A')

  // Share menu open state (indexed by linkId)
  const [openShareMenu, setOpenShareMenu] = useState<string | null>(null)

  // Link Dialog states
  const [isLinkModalOpen, setIsLinkModalOpen] = useState(false)
  const [linkTitle, setLinkTitle] = useState('')
  const [linkExpiry, setLinkExpiry] = useState('')

  // Edit Expiry Modal states
  const [isExpiryModalOpen, setIsExpiryModalOpen] = useState(false)
  const [selectedLinkForExpiry, setSelectedLinkForExpiry] = useState<any | null>(null)
  const [editLinkExpiry, setEditLinkExpiry] = useState('')

  // Student Details Modal states
  const [selectedStudent, setSelectedStudent] = useState<StudentSubmission | null>(null)

  // Preview Modal state
  const [previewTarget, setPreviewTarget] = useState<DocumentPreviewTarget | null>(null)

  // Find batch
  const batch = batches.find((b) => b.id === batchId)

  // Local state for tracking document requirement updates
  const [tempRequirements, setTempRequirements] = useState<DocumentRequirement[]>(batch?.docRequirements || [
    { id: 'req_1', name: 'Aadhaar Card', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, description: 'Upload front and back side of Aadhaar card', type: 'MANDATORY' },
    { id: 'req_2', name: 'SSLC Marksheet', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, description: '10th grade official marks statement', type: 'MANDATORY' },
    { id: 'req_3', name: 'HSC Marksheet', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, description: '12th grade / Diploma final marks statement', type: 'MANDATORY' },
    { id: 'req_4', name: 'Community Certificate', required: true, allowedTypes: ['PDF', 'JPG'], maxSizeMb: 5, description: 'Caste / Community reservation proof', type: 'MANDATORY' },
  ])

  // Sync temp requirements when batch changes
  React.useEffect(() => {
    if (batch?.docRequirements && batch.docRequirements.length > 0) {
      setTempRequirements(batch.docRequirements)
    }
  }, [batch?.docRequirements])

  const [isDownloadingAllDocs, setIsDownloadingAllDocs] = useState(false)

  // Document Requirements State
  const [wantedOverview, setWantedOverview] = useState<DocumentTypeOverviewItem[]>([])
  const [isLoadingWanted, setIsLoadingWanted] = useState(false)

  // Add Document Requirement Modal States
  const [isAddDocModalOpen, setIsAddDocModalOpen] = useState(false)
  const [newDocName, setNewDocName] = useState('')
  const [newDocCode, setNewDocCode] = useState('')
  const [newDocDescription, setNewDocDescription] = useState('')
  const [newDocRequirementStatus, setNewDocRequirementStatus] = useState<'REQUIRED' | 'OPTIONAL' | 'DISABLED'>('REQUIRED')
  const [isCreatingDoc, setIsCreatingDoc] = useState(false)
  const [isDeletingDoc, setIsDeletingDoc] = useState(false)

  // Load Document Requirements Overview
  const loadWantedOverview = React.useCallback(async () => {
    if (!batchId) return
    setIsLoadingWanted(true)
    try {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      const overview = await wantedFieldService.getBatchOverview(batchId, classIdParam)

      // Defensively deduplicate by document_type
      const deduped: DocumentTypeOverviewItem[] = []
      const seen = new Set<string>()
      for (const item of overview) {
        const code = (item.document_type || '').toUpperCase().trim()
        if (!seen.has(code)) {
          seen.add(code)
          deduped.push(item)
        }
      }
      setWantedOverview(deduped)
    } catch (err) {
      console.error('Failed to load document requirements overview:', err)
    } finally {
      setIsLoadingWanted(false)
    }
  }, [batchId, selectedClassId])

  React.useEffect(() => {
    loadWantedOverview()
  }, [loadWantedOverview])

  // Load Batch Document Validation Diagnostics & Statuses
  const loadValidationData = React.useCallback(async () => {
    if (!batchId) return
    setIsLoadingValidation(true)
    try {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      const data = await studentDocumentService.getBatchDocumentValidation(batchId, classIdParam)
      setValidationData(data)
    } catch (err) {
      console.error('Failed to load document validation data:', err)
    } finally {
      setIsLoadingValidation(false)
    }
  }, [batchId, selectedClassId])

  React.useEffect(() => {
    if (activeTab === 'validation' || activeTab === 'documents') {
      loadValidationData()
    }
  }, [activeTab, loadValidationData])

  // Filtered validation documents
  const filteredValidationDocs = React.useMemo(() => {
    if (!validationData?.documents) return []
    return validationData.documents.filter((doc) => {
      // Status filter
      if (validationStatusFilter !== 'ALL') {
        if (validationStatusFilter === 'WRONG_DOCUMENT' && doc.validation_status !== 'WRONG_DOCUMENT') return false
        if (validationStatusFilter === 'VALID' && doc.validation_status !== 'VALID') return false
        if (validationStatusFilter === 'NEEDS_REVIEW' && !['NEEDS_REVIEW', 'PENDING', 'UNKNOWN'].includes(doc.validation_status)) return false
        if (validationStatusFilter === 'CLASSIFICATION_FAILED' && doc.validation_status !== 'CLASSIFICATION_FAILED') return false
      }

      // Search query filter
      if (validationSearchQuery.trim()) {
        const q = validationSearchQuery.toLowerCase().trim()
        const stuName = (doc.student_name || '').toLowerCase()
        const regNum = (doc.register_number || doc.student_id || '').toLowerCase()
        const fn = (doc.original_filename || '').toLowerCase()
        const expType = (doc.expected_document_type || doc.document_name || '').toLowerCase()
        const detType = (doc.detected_document_type || '').toLowerCase()

        return stuName.includes(q) || regNum.includes(q) || fn.includes(q) || expType.includes(q) || detType.includes(q)
      }

      return true
    })
  }, [validationData?.documents, validationStatusFilter, validationSearchQuery])

  const handleDocNameChange = (name: string) => {
    setNewDocName(name)
    const autoCode = name
      .toUpperCase()
      .replace(/[^A-Z0-9\s_-]/g, '')
      .trim()
      .replace(/[\s-]+/g, '_')
    setNewDocCode(autoCode)
  }

  const handleOpenAddDocModal = () => {
    setNewDocName('')
    setNewDocCode('')
    setNewDocDescription('')
    setNewDocRequirementStatus('REQUIRED')
    setIsAddDocModalOpen(true)
  }

  const handleCreateDocumentType = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!batchId) return
    const trimmedName = newDocName.trim()
    const trimmedCode = newDocCode.trim()

    if (!trimmedName) {
      addToast('Document Name is required.', 'error')
      return
    }
    if (!trimmedCode) {
      addToast('Document Code is required.', 'error')
      return
    }

    const normCode = trimmedCode.toUpperCase().replace(/[\s-]+/g, '_').replace(/[^A-Z0-9_]/g, '')

    const existingDoc = wantedOverview.find(
      (d) =>
        d.document_type.toUpperCase().trim() === normCode ||
        d.display_name.trim().toLowerCase() === trimmedName.toLowerCase()
    )

    setIsCreatingDoc(true)
    try {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      if (existingDoc) {
        const res = await wantedFieldService.saveDocumentConfig(
          batchId,
          existingDoc.document_type,
          existingDoc.fields,
          classIdParam,
          {
            display_name: trimmedName,
            description: newDocDescription.trim() || undefined,
            requirement_status: newDocRequirementStatus,
          }
        )
        addToast(`Document "${res.display_name}" updated (${newDocRequirementStatus}).`, 'success')
        setIsAddDocModalOpen(false)
        setNewDocName('')
        setNewDocCode('')
        setNewDocDescription('')
        setNewDocRequirementStatus('REQUIRED')
        await loadWantedOverview()
        return
      }

      const res = await wantedFieldService.createDocumentType(
        batchId,
        {
          name: trimmedName,
          code: normCode,
          description: newDocDescription.trim() || undefined,
          requirement_status: newDocRequirementStatus,
        },
        classIdParam
      )
      addToast(`Document requirement "${res.display_name}" added (${newDocRequirementStatus}).`, 'success')
      setIsAddDocModalOpen(false)
      setNewDocName('')
      setNewDocCode('')
      setNewDocDescription('')
      setNewDocRequirementStatus('REQUIRED')
      await loadWantedOverview()
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to configure document requirement.', 'error')
    } finally {
      setIsCreatingDoc(false)
    }
  }

  const handleUpdateRequirementStatus = async (
    docType: string,
    newStatus: 'REQUIRED' | 'OPTIONAL' | 'DISABLED'
  ) => {
    if (!batchId) return
    try {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      await wantedFieldService.updateDocumentRequirement(
        batchId,
        docType,
        { requirement_status: newStatus },
        classIdParam
      )
      addToast(`Updated ${docType} requirement to ${newStatus}`, 'success')
      await loadWantedOverview()
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to update requirement status.', 'error')
    }
  }

  const handleAddPresetDoc = async (preset: { name: string; code: string; desc: string; status: 'REQUIRED' | 'OPTIONAL' }) => {
    if (!batchId) return
    try {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      await wantedFieldService.createDocumentType(
        batchId,
        {
          name: preset.name,
          code: preset.code,
          description: preset.desc,
          requirement_status: preset.status,
        },
        classIdParam
      )
      addToast(`Added document requirement "${preset.name}"`, 'success')
      await loadWantedOverview()
    } catch (err: any) {
      addToast(err?.response?.data?.detail || `Document requirement "${preset.name}" is already configured.`, 'info')
    }
  }

  const handleDeleteDocumentType = async (docType: string, docName: string) => {
    if (!batchId) return
    const confirmMsg = `Are you sure you want to remove "${docName}" (${docType})? If student files reference this document, it will be safely archived to protect uploaded records.`
    if (!window.confirm(confirmMsg)) return

    setIsDeletingDoc(true)
    try {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      const res = await wantedFieldService.deleteDocumentType(batchId, docType, classIdParam)
      addToast(res.message, res.archived ? 'info' : 'success')
      await loadWantedOverview()
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to delete document type.', 'error')
    } finally {
      setIsDeletingDoc(false)
    }
  }

  // Filter student submissions for this batch & class
  const batchClasses = (batchId ? classesByBatch[batchId] : []) || batch?.classes || []
  const allBatchStudents = submissions.filter((s) => s.batchId === batchId || (batch && s.batchId === batch.id))
  const batchStudents = allBatchStudents.filter((s) => {
    if (selectedClassId === 'all') return true
    return s.classId === selectedClassId
  })
  const batchLinks = uploadLinks.filter((l) => l.batchId === batchId || (batch && l.batchId === batch.id))

  const activeBatch = batch || {
    id: batchId || 'batch_1',
    name: batchId ? `Batch ${batchId}` : 'Admission Batch',
    department: 'AIML',
    academicYear: '2025-2029',
    description: 'Admission batch section workspace.',
    startDate: '2025-06-01',
    endDate: '2025-08-30',
    status: 'active' as const,
    stats: { students: allBatchStudents.length, pending: 0, verified: 0, rejected: 0 },
    classes: batchClasses,
    currentDocVersion: 1,
    docRequirements: tempRequirements,
  }

  const handleDownloadAllDocuments = async () => {
    if (!selectedStudent || isDownloadingAllDocs) return
    const uploadedDocs = (selectedStudent.documents || []).filter(
      (d: any) => d.status === 'Uploaded'
    )
    if (uploadedDocs.length === 0) {
      addToast('No documents available for download.', 'info')
      return
    }

    setIsDownloadingAllDocs(true)
    try {
      await studentSubmissionService.downloadAllDocuments(
        selectedStudent.id,
        selectedStudent.name,
        selectedStudent.registerNum
      )
      addToast(`Downloaded all documents for ${selectedStudent.name}!`, 'success')
    } catch (err: any) {
      const msg = err?.message || ''
      if (msg.includes('No documents available')) {
        addToast('No documents available for download.', 'info')
      } else {
        addToast('Unable to download all documents. Please try again.', 'error')
      }
    } finally {
      setIsDownloadingAllDocs(false)
    }
  }

  const handleGenerateLink = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!activeBatch) return
    if (!linkTitle.trim()) {
      addToast('Link title is required', 'error')
      return
    }

    try {
      await addUploadLink({
        batchId: activeBatch.id,
        class_id: selectedClassId === 'all' ? undefined : selectedClassId,
        token: Math.random().toString(36).substring(2, 9),
        title: linkTitle,
        expiresAt: linkExpiry || '',
        isActive: true,
      })
      await fetchUploadLinks()
      addToast(`Link "${linkTitle}" generated!`, 'success')
      setIsLinkModalOpen(false)
      setLinkTitle('')
      setLinkExpiry('')
    } catch (err: any) {
      addToast(err?.message || 'Failed to generate link', 'error')
    }
  }

  const handleCopyLink = async (slug: string) => {
    if (!slug || slug === 'undefined' || slug === 'null' || !slug.trim()) {
      addToast('Upload link could not be generated.', 'error')
      return
    }
    const fullPortalUrl = getStudentUploadUrl(slug)
    try {
      await copyToClipboard(fullPortalUrl)
      addToast('URL copied to clipboard!', 'success')
      setOpenShareMenu(null)
    } catch (err) {
      console.error('Failed to copy portal URL to clipboard:', err)
      addToast('Failed to copy link to clipboard.', 'error')
    }
  }

  const handleSaveExpiry = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedLinkForExpiry) return

    try {
      await updateUploadLinkExpiry(selectedLinkForExpiry.id, editLinkExpiry || null)
      addToast('Expiry date updated successfully!', 'success')
      setIsExpiryModalOpen(false)
      setSelectedLinkForExpiry(null)
      setEditLinkExpiry('')
    } catch (err: any) {
      addToast(err.message || 'Failed to update expiry date', 'error')
    }
  }

  const handleRemoveExpiry = async () => {
    if (!selectedLinkForExpiry) return

    try {
      await updateUploadLinkExpiry(selectedLinkForExpiry.id, null)
      addToast('Expiry date removed successfully!', 'success')
      setIsExpiryModalOpen(false)
      setSelectedLinkForExpiry(null)
      setEditLinkExpiry('')
    } catch (err: any) {
      addToast(err.message || 'Failed to remove expiry date', 'error')
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 text-primary animate-spin" />
        <span className="ml-3 text-sm text-muted-foreground font-semibold">Loading Batch Workspace...</span>
      </div>
    )
  }

  if (fetchError) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" onClick={() => navigate('/batches')} className="cursor-pointer">
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Batches
        </Button>
        <div className="p-6 rounded-xl border border-destructive/20 bg-destructive/5 text-destructive space-y-3">
          <div className="flex items-center gap-2 font-bold text-base">
            <AlertTriangle className="h-5 w-5" /> Failed to Load Batch Workspace
          </div>
          <p className="text-xs text-muted-foreground font-mono">{fetchError}</p>
          <Button variant="outline" size="sm" onClick={loadBatchData} className="cursor-pointer gap-2 border-destructive/30">
            <RefreshCw className="h-3.5 w-3.5" /> Retry Loading
          </Button>
        </div>
      </div>
    )
  }

  if (!activeBatch) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" onClick={() => navigate('/batches')} className="cursor-pointer">
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Batches
        </Button>
        <EmptyState
          title="Cohort Not Found"
          description="The admission batch you are looking for does not exist or has been archived."
          icon={<ArrowLeft className="h-12 w-12 text-muted-foreground/60" />}
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Button variant="ghost" onClick={() => navigate('/batches')} className="cursor-pointer">
        <ArrowLeft className="mr-2 h-4 w-4" /> Back to Batches
      </Button>

      {/* Header Info */}
      <div className="flex flex-col md:flex-row md:items-center justify-between border-b border-border pb-6 gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-extrabold tracking-tight text-foreground m-0">{activeBatch.name}</h1>
            <span
              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider border ${
                activeBatch.status === 'active' ? 'bg-green-100 text-green-800 border-green-200' : 'bg-red-100 text-red-800 border-red-200'
              }`}
            >
              {activeBatch.status}
            </span>
          </div>
          <p className="text-sm text-muted-foreground mt-1.5 font-medium">
            {activeBatch.department} • <span className="font-semibold text-foreground">Intake Year:</span> {activeBatch.academicYear}
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <Button variant="outline" onClick={() => setIsSectionModalOpen(true)} className="cursor-pointer gap-1.5">
            <Plus className="h-4 w-4" /> Create Section
          </Button>
          <Button
            variant="outline"
            onClick={() => setActiveTab('documents')}
            className={`cursor-pointer gap-1.5 ${
              activeTab === 'documents'
                ? 'bg-secondary text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <FileText className="h-4 w-4 text-emerald-500" /> Document Requirements
          </Button>
          <Button
            variant="outline"
            onClick={() => navigate(`/data-extraction/${batchId}`)}
            className="cursor-pointer gap-1.5 border-emerald-500/30 text-emerald-500 hover:bg-emerald-500/10"
          >
            <Sparkles className="h-4 w-4" /> Data Extraction
          </Button>
          <button
            type="button"
            onClick={() => setIsLinkModalOpen(true)}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs shadow-xs transition-colors cursor-pointer"
          >
            <Plus className="h-4 w-4 text-slate-950 font-bold" /> Generate Portal Link
          </button>
        </div>
      </div>

      {/* Tabs list */}
      <div className="flex border-b border-border gap-1 overflow-x-auto">
        {(
          [
            { id: 'sections', label: `Sections (${batchClasses.length})`, icon: Layers },
            { id: 'students', label: `Students (${batchStudents.length})`, icon: Users },
            {
              id: 'validation',
              label: `Document Validation ${validationData ? `(${validationData.summary.total_documents})` : ''}`,
              icon: ShieldCheck,
              hasWarning: (validationData?.summary.wrong_documents || 0) > 0,
            },
            { id: 'documents', label: 'Document Requirements', icon: FileText },
            { id: 'links', label: `Upload Links (${batchLinks.length})`, icon: LinkIcon },
          ] as const
        ).map((tab) => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap ${
                isActive
                  ? 'border-primary text-primary font-bold'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
              }`}
            >
              <Icon className={`h-4 w-4 ${isActive ? 'text-primary' : ''}`} />
              <span>{tab.label}</span>
              {(tab as any).hasWarning && (
                <span className="inline-flex items-center px-1.5 py-0.2 rounded-full text-[10px] font-extrabold bg-rose-500 text-white animate-pulse">
                  {validationData?.summary.wrong_documents} MISMATCH
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Tab content renderer */}
      <div className="py-4">
        {/* 0. SECTIONS CARD GRID TAB */}
        {activeTab === 'sections' && (
          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-foreground flex items-center gap-2">
                  <Layers className="h-5 w-5 text-primary" /> Classes / Sections in {activeBatch.name}
                </h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Each section is an independent workspace with its own submissions, upload link, and document collection.
                </p>
              </div>
              <Button variant="primary" onClick={() => setIsSectionModalOpen(true)} className="cursor-pointer gap-1.5">
                <Plus className="h-4 w-4" /> Create Section
              </Button>
            </div>

            {batchClasses.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                {batchClasses.map((cls) => {
                  const studentCount = cls.stats?.students ?? allBatchStudents.filter((s) => s.classId === cls.id).length
                  const secStr = cls.section ? cls.section.trim() : 'A'
                  const sectionLabel = secStr.toLowerCase().startsWith('section')
                    ? secStr
                    : cls.class_name && !cls.class_name.toLowerCase().startsWith((activeBatch.department || '').toLowerCase())
                    ? cls.class_name
                    : `Section ${secStr}`

                  return (
                    <div
                      key={cls.id}
                      className="p-5 rounded-xl border border-border bg-card shadow-2xs hover:shadow-md transition-all flex flex-col justify-between space-y-4"
                    >
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-foreground text-base flex items-center gap-2">
                            <FolderOpen className="h-5 w-5 text-primary" />
                            {cls.department} - {sectionLabel}
                          </span>
                        </div>
                        <span className="text-xs text-muted-foreground font-semibold block">
                          Department: <strong className="text-foreground">{cls.department}</strong>
                        </span>
                      </div>

                      <div className="flex items-center justify-between px-3 py-2 rounded-lg bg-secondary/40 border border-border/60 text-xs">
                        <span className="font-semibold text-muted-foreground">Students</span>
                        <span className="font-extrabold text-foreground font-mono text-sm">{studentCount}</span>
                      </div>

                      <div className="flex items-center justify-between gap-2 pt-2 border-t border-border/40">
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={() => navigate(`/classes/${cls.id}`)}
                          className="w-full cursor-pointer text-xs font-bold gap-1"
                        >
                          Open Section
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={async () => {
                            if (window.confirm(`Are you sure you want to delete section "${cls.class_name}"?`)) {
                              try {
                                await deleteClass(cls.id)
                                addToast(`Section "${cls.class_name}" deleted.`, 'success')
                              } catch (err: any) {
                                addToast(err?.response?.data?.detail || 'Failed to delete section', 'error')
                              }
                            }
                          }}
                          className="text-destructive hover:bg-destructive/10 cursor-pointer p-2 shrink-0"
                          title="Delete Section"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <EmptyState
                title="No classes created yet."
                description={`No sections or classes have been created for ${activeBatch.name} yet. Click "+ Create Section" to add one.`}
                icon={<Layers className="h-12 w-12 text-muted-foreground/60" />}
                action={
                  <Button variant="primary" onClick={() => setIsSectionModalOpen(true)} className="cursor-pointer">
                    <Plus className="mr-2 h-4 w-4" /> Create Section
                  </Button>
                }
              />
            )}
          </div>
        )}

        {/* 1. STUDENTS TAB */}
        {activeTab === 'students' && (
          <div className="space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-foreground">Enrolled Candidate Submissions</h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Review student upload status, verify submitted documents, and inspect preview files.
                </p>
              </div>

              {/* Class Filter Selector */}
              {batchClasses.length > 0 && (
                <div className="flex items-center gap-2 bg-card px-3 py-1.5 rounded-xl border border-border">
                  <span className="text-xs font-bold text-muted-foreground uppercase flex items-center gap-1.5">
                    <Layers className="h-4 w-4 text-primary" /> Class:
                  </span>
                  <select
                    value={selectedClassId}
                    onChange={(e) => setSelectedClassId(e.target.value)}
                    className="px-3 py-1 rounded-lg border border-border bg-background text-xs font-bold text-foreground focus:outline-none focus:ring-2 focus:ring-primary cursor-pointer"
                  >
                    <option value="all">All Classes ({allBatchStudents.length})</option>
                    {batchClasses.map((cls) => (
                      <option key={cls.id} value={cls.id}>
                        {cls.class_name} (Sec {cls.section})
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            {batchStudents.length > 0 ? (
              <div className="rounded-xl border border-border bg-card overflow-hidden shadow-2xs">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Register Number</TableHead>
                      <TableHead>Student Name</TableHead>
                      <TableHead>Submitted At</TableHead>
                      <TableHead>Documents Uploaded</TableHead>
                      <TableHead>Submission Status</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {batchStudents.map((student) => {
                      const uploadedDocs = student.documents.filter((d) => d.status === 'Uploaded').length
                      const totalDocs = tempRequirements.length || student.documents.length

                      return (
                        <TableRow key={student.id} className="hover:bg-secondary/30 transition-colors">
                          <TableCell className="font-mono text-xs font-bold text-foreground">{student.registerNum}</TableCell>
                          <TableCell className="font-semibold text-foreground">{student.name}</TableCell>
                          <TableCell className="text-xs text-muted-foreground">{student.submittedAt}</TableCell>
                          <TableCell>
                            <span className="text-xs font-bold text-foreground">
                              {uploadedDocs} / {totalDocs} Files
                            </span>
                          </TableCell>
                          <TableCell>
                            <span
                              className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold ${
                                student.status === 'Verified'
                                  ? 'bg-green-100 text-green-800 border border-green-200'
                                  : student.status === 'Rejected'
                                  ? 'bg-red-100 text-red-800 border border-red-200'
                                  : student.status === 'AI Processing'
                                  ? 'bg-purple-100 text-purple-800 border border-purple-200 animate-pulse'
                                  : student.status === 'Submitted'
                                  ? 'bg-blue-100 text-blue-800 border border-blue-200'
                                  : 'bg-amber-100 text-amber-800 border border-amber-200'
                              }`}
                            >
                              {student.status === 'Verified' ? (
                                <CheckCircle className="h-3.5 w-3.5" />
                              ) : student.status === 'Rejected' ? (
                                <XCircle className="h-3.5 w-3.5" />
                              ) : student.status === 'AI Processing' ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Clock className="h-3.5 w-3.5" />
                              )}
                              {student.status}
                            </span>
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="inline-flex items-center gap-1.5 justify-end">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setSelectedStudent(student)}
                                className="cursor-pointer gap-1 text-xs py-1"
                                title="View Student Profile"
                              >
                                <Eye className="h-3.5 w-3.5" /> View
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => {
                                  const firstUploadedIdx = student.documents.findIndex((d) => d.status === 'Uploaded')
                                  if (firstUploadedIdx !== -1) {
                                    const doc = student.documents[firstUploadedIdx]
                                    setPreviewTarget({
                                      submissionId: student.id,
                                      documentIndex: doc.documentIndex !== undefined ? doc.documentIndex : firstUploadedIdx,
                                      documentName: doc.reqName,
                                      fileType: doc.fileType,
                                      fileName: doc.fileName,
                                      studentName: student.name,
                                    })
                                  } else {
                                    addToast('No uploaded documents available for preview.', 'info')
                                  }
                                }}
                                className="cursor-pointer gap-1 text-xs py-1"
                                title="Preview Documents"
                              >
                                <Maximize2 className="h-3.5 w-3.5" /> Preview
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <EmptyState
                title="No Student Submissions"
                description="No students have submitted documents for this batch yet. Share the generated portal link to receive applications."
                icon={<Users className="h-12 w-12 text-muted-foreground/60" />}
                action={
                  <Button
                    variant="outline"
                    onClick={async () => {
                      const activePortal = batchLinks.find((l) => l.isActive) || batchLinks[0]
                      const slug = activePortal?.slug || activePortal?.token
                      if (!slug || slug === 'undefined' || slug === 'null' || !slug.trim()) {
                        addToast('Upload link could not be generated.', 'error')
                        return
                      }
                      const fullPortalUrl = getStudentUploadUrl(slug)
                      try {
                        await copyToClipboard(fullPortalUrl)
                        addToast('Upload portal URL copied to clipboard!', 'success')
                      } catch (err) {
                        console.error('Failed to copy upload portal URL:', err)
                        addToast('Failed to copy link to clipboard.', 'error')
                      }
                    }}
                    className="cursor-pointer"
                  >
                    <Share2 className="mr-2 h-4 w-4" /> Share Upload Link
                  </Button>
                }
              />
            )}
          </div>
        )}

        {/* 1.5 DOCUMENT VALIDATION TAB */}
        {activeTab === 'validation' && (
          <div className="space-y-6">
            {/* KPI Summary Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
              <div className="p-4 rounded-xl border border-border bg-card shadow-2xs">
                <span className="text-xs font-semibold text-muted-foreground block mb-1">Total Documents</span>
                <div className="flex items-baseline justify-between">
                  <span className="text-2xl font-extrabold text-foreground font-mono">
                    {validationData?.summary.total_documents || 0}
                  </span>
                  <FileText className="h-4 w-4 text-muted-foreground" />
                </div>
              </div>

              <div className="p-4 rounded-xl border border-emerald-500/30 bg-emerald-950/20 shadow-2xs">
                <span className="text-xs font-semibold text-emerald-400 block mb-1">Valid & Verified</span>
                <div className="flex items-baseline justify-between">
                  <span className="text-2xl font-extrabold text-emerald-300 font-mono">
                    {validationData?.summary.valid || 0}
                  </span>
                  <CheckCircle className="h-4 w-4 text-emerald-400" />
                </div>
              </div>

              <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-950/20 shadow-2xs">
                <span className="text-xs font-semibold text-rose-400 block mb-1">Wrong Documents</span>
                <div className="flex items-baseline justify-between">
                  <span className="text-2xl font-extrabold text-rose-300 font-mono">
                    {validationData?.summary.wrong_documents || 0}
                  </span>
                  <AlertTriangle className="h-4 w-4 text-rose-400" />
                </div>
              </div>

              <div className="p-4 rounded-xl border border-amber-500/30 bg-amber-950/20 shadow-2xs">
                <span className="text-xs font-semibold text-amber-400 block mb-1">Needs Review</span>
                <div className="flex items-baseline justify-between">
                  <span className="text-2xl font-extrabold text-amber-300 font-mono">
                    {validationData?.summary.needs_review || 0}
                  </span>
                  <Clock className="h-4 w-4 text-amber-400" />
                </div>
              </div>

              <div className="p-4 rounded-xl border border-red-500/30 bg-red-950/20 shadow-2xs">
                <span className="text-xs font-semibold text-red-400 block mb-1">Classification Failed</span>
                <div className="flex items-baseline justify-between">
                  <span className="text-2xl font-extrabold text-red-300 font-mono">
                    {validationData?.summary.classification_failed || 0}
                  </span>
                  <XCircle className="h-4 w-4 text-red-400" />
                </div>
              </div>
            </div>

            {/* Filter & Search Bar */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl border border-border bg-card">
              <div className="flex items-center gap-3 flex-1 flex-wrap">
                <Input
                  placeholder="Search student name, register no, or filename..."
                  value={validationSearchQuery}
                  onChange={(e) => setValidationSearchQuery(e.target.value)}
                  className="max-w-xs text-xs"
                />

                <select
                  value={validationStatusFilter}
                  onChange={(e) => setValidationStatusFilter(e.target.value)}
                  className="px-3 py-1.5 rounded-lg border border-border bg-background text-xs font-bold text-foreground focus:outline-none focus:ring-2 focus:ring-primary cursor-pointer"
                >
                  <option value="ALL">All Statuses</option>
                  <option value="VALID">Valid Only</option>
                  <option value="WRONG_DOCUMENT">Wrong Document Mismatches</option>
                  <option value="NEEDS_REVIEW">Needs Review / Low Confidence</option>
                  <option value="CLASSIFICATION_FAILED">Classification Failed</option>
                </select>

                {batchClasses.length > 0 && (
                  <select
                    value={selectedClassId}
                    onChange={(e) => setSelectedClassId(e.target.value)}
                    className="px-3 py-1.5 rounded-lg border border-border bg-background text-xs font-bold text-foreground focus:outline-none focus:ring-2 focus:ring-primary cursor-pointer"
                  >
                    <option value="all">All Sections</option>
                    {batchClasses.map((cls) => (
                      <option key={cls.id} value={cls.id}>
                        {cls.class_name} (Sec {cls.section})
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={loadValidationData}
                disabled={isLoadingValidation}
                className="cursor-pointer gap-1.5 text-xs shrink-0"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${isLoadingValidation ? 'animate-spin' : ''}`} />
                <span>Refresh Validation</span>
              </Button>
            </div>

            {/* Document Validation Table */}
            {isLoadingValidation ? (
              <div className="py-12 flex flex-col items-center justify-center gap-3 text-muted-foreground">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
                <span className="text-xs font-medium">Validating document classifications...</span>
              </div>
            ) : filteredValidationDocs.length > 0 ? (
              <div className="rounded-xl border border-border bg-card overflow-hidden shadow-2xs">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Student</TableHead>
                      <TableHead>Expected Document</TableHead>
                      <TableHead>Uploaded File</TableHead>
                      <TableHead>Detected Type</TableHead>
                      <TableHead>Confidence</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Evidence</TableHead>
                      <TableHead>Version</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredValidationDocs.map((docItem) => {
                      const confPercent = Math.round(docItem.classification_confidence * 100)
                      return (
                        <TableRow key={docItem.document_id} className="hover:bg-secondary/30 transition-colors">
                          <TableCell>
                            <div>
                              <span className="font-semibold text-foreground text-sm block">
                                {docItem.student_name || docItem.register_number}
                              </span>
                              <span className="font-mono text-xs text-muted-foreground">
                                {docItem.register_number}
                              </span>
                            </div>
                          </TableCell>
                          <TableCell className="font-semibold text-xs text-foreground">
                            {docItem.expected_document_type || docItem.document_name}
                          </TableCell>
                          <TableCell className="font-mono text-xs text-muted-foreground max-w-[180px] truncate" title={docItem.original_filename || ''}>
                            {docItem.original_filename || 'N/A'}
                          </TableCell>
                          <TableCell>
                            <span className="font-mono text-xs font-bold text-indigo-400">
                              {docItem.detected_document_type || 'UNKNOWN'}
                            </span>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-1.5">
                              <span className="font-mono text-xs font-bold">{confPercent}%</span>
                              <div className="w-12 h-1.5 rounded-full bg-slate-800 overflow-hidden hidden sm:block">
                                <div
                                  className={`h-full rounded-full ${
                                    confPercent >= 90 ? 'bg-emerald-500' : confPercent >= 70 ? 'bg-indigo-500' : 'bg-amber-500'
                                  }`}
                                  style={{ width: `${Math.min(100, confPercent)}%` }}
                                />
                              </div>
                            </div>
                          </TableCell>
                          <TableCell>
                            {docItem.validation_status === 'VALID' && (
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                <CheckCircle className="w-3 h-3" /> VALID
                              </span>
                            )}
                            {docItem.validation_status === 'WRONG_DOCUMENT' && (
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                                <AlertTriangle className="w-3 h-3" /> WRONG_DOCUMENT
                              </span>
                            )}
                            {docItem.validation_status === 'NEEDS_REVIEW' && (
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                                <Clock className="w-3 h-3" /> NEEDS_REVIEW
                              </span>
                            )}
                            {docItem.validation_status === 'CLASSIFICATION_FAILED' && (
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-500/10 text-red-400 border border-red-500/20">
                                <AlertTriangle className="w-3 h-3" /> FAILED
                              </span>
                            )}
                            {docItem.validation_status === 'UNKNOWN' && (
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/20">
                                <HelpCircle className="w-3 h-3" /> UNKNOWN
                              </span>
                            )}
                          </TableCell>
                          <TableCell>
                            <button
                              type="button"
                              onClick={() => setSelectedDocForEvidence(docItem)}
                              className="text-xs text-indigo-400 hover:text-indigo-300 font-medium underline underline-offset-2 cursor-pointer flex items-center gap-1"
                            >
                              <Sparkles className="w-3 h-3" />
                              <span>{docItem.classification_evidence?.length || 0} signals</span>
                            </button>
                          </TableCell>
                          <TableCell className="font-mono text-xs text-muted-foreground">
                            v{docItem.version_number}
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="inline-flex items-center gap-1.5">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => {
                                  setPreviewTarget({
                                    studentDocumentId: docItem.document_id,
                                    versionId: docItem.active_version_id,
                                    documentName: `${docItem.student_name || docItem.register_number} - ${docItem.document_name}`,
                                  })
                                }}
                                className="cursor-pointer text-xs h-7 px-2"
                                title="Preview Document"
                              >
                                <Eye className="h-3.5 w-3.5 mr-1" /> Preview
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setSelectedDocForReclassify(docItem)}
                                className="cursor-pointer text-xs h-7 px-2 border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/10"
                                title="Reclassify Document"
                              >
                                <FileText className="h-3.5 w-3.5 mr-1" /> Reclassify
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <EmptyState
                title="No documents matching filter"
                description="No uploaded student documents match the current search or status filter."
                icon={<ShieldCheck className="h-12 w-12 text-muted-foreground/60" />}
              />
            )}
          </div>
        )}

        {/* 2. UPLOAD LINKS TAB */}
        {activeTab === 'links' && (
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <h2 className="text-lg font-bold text-foreground">Batch Portals</h2>
              <Button variant="primary" onClick={() => setIsLinkModalOpen(true)} className="cursor-pointer">
                <Plus className="mr-2 h-4 w-4" /> Generate Link
              </Button>
            </div>

            {batchLinks.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Portal Name</TableHead>
                    <TableHead>Tokenized Link</TableHead>
                    <TableHead>Submissions</TableHead>
                    <TableHead>Expiry Date</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {batchLinks.map((link) => {
                    const effectiveSlug = link.slug || link.token
                    return (
                      <TableRow key={link.id} className="relative">
                        <TableCell className="font-semibold text-foreground">{link.title}</TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground break-all max-w-[220px] truncate" title={getStudentUploadUrl(effectiveSlug)}>
                          {getStudentUploadUrl(effectiveSlug)}
                        </TableCell>
                        <TableCell>{link.submissionCount} uploads</TableCell>
                        <TableCell className="text-muted-foreground">{link.expiresAt || 'Always Active'}</TableCell>
                        <TableCell>
                          <span
                            className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                              link.isActive ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
                            }`}
                          >
                            {link.isActive ? 'Active' : 'Disabled'}
                          </span>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="inline-flex items-center gap-1">
                            <button
                              onClick={() => handleCopyLink(effectiveSlug)}
                              className="p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground rounded-lg transition-colors cursor-pointer"
                              title="Copy link"
                            >
                              <Copy className="h-4 w-4" />
                            </button>

                            <div className="relative">
                              <button
                                onClick={() => setOpenShareMenu(openShareMenu === link.id ? null : link.id)}
                                className="p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground rounded-lg transition-colors cursor-pointer"
                                title="Share options"
                              >
                                <Share2 className="h-4 w-4" />
                              </button>
                              {openShareMenu === link.id && (
                                <div className="absolute right-0 mt-1 w-44 rounded-lg border border-border bg-card shadow-lg z-20 py-1.5 text-left">
                                  <button
                                    onClick={() => handleCopyLink(effectiveSlug)}
                                    className="flex w-full items-center gap-2.5 px-3 py-1.5 text-xs font-medium text-foreground hover:bg-secondary transition-colors cursor-pointer"
                                  >
                                    <Copy className="h-4.5 w-4.5 text-muted-foreground" /> Copy URL
                                  </button>
                                  <button
                                    onClick={() => {
                                      addToast(`Sharing link ${getStudentUploadUrl(effectiveSlug)} via WhatsApp...`, 'info')
                                      setOpenShareMenu(null)
                                    }}
                                    className="flex w-full items-center gap-2.5 px-3 py-1.5 text-xs font-medium text-foreground hover:bg-secondary transition-colors cursor-pointer"
                                  >
                                    <MessageSquare className="h-4.5 w-4.5 text-green-600" /> Share WhatsApp
                                  </button>
                                  <button
                                    onClick={() => {
                                      addToast(`Sharing link ${getStudentUploadUrl(effectiveSlug)} via Email...`, 'info')
                                      setOpenShareMenu(null)
                                    }}
                                    className="flex w-full items-center gap-2.5 px-3 py-1.5 text-xs font-medium text-foreground hover:bg-secondary transition-colors cursor-pointer"
                                  >
                                    <Mail className="h-4.5 w-4.5 text-blue-600" /> Share Email
                                  </button>
                                </div>
                              )}
                            </div>

                          <button
                            onClick={() => toggleUploadLink(link.id)}
                            className="p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground rounded-lg transition-colors cursor-pointer"
                            title={link.isActive ? 'Disable link' : 'Enable link'}
                          >
                            {link.isActive ? <ToggleRight className="h-5 w-5 text-primary" /> : <ToggleLeft className="h-5 w-5" />}
                          </button>

                          <button
                            onClick={() => {
                              setSelectedLinkForExpiry(link)
                              setEditLinkExpiry(link.expiresAt || '')
                              setIsExpiryModalOpen(true)
                            }}
                            className="p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground rounded-lg transition-colors cursor-pointer"
                            title="Manage expiry date"
                          >
                            <Calendar className="h-4 w-4" />
                          </button>

                          <button
                            onClick={() => {
                              deleteUploadLink(link.id)
                              addToast('Link deleted successfully', 'success')
                            }}
                            className="p-1.5 text-destructive hover:bg-destructive/10 rounded-lg transition-colors cursor-pointer"
                            title="Delete Link"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
            ) : (
              <EmptyState
                title="No Portals Yet"
                description="There are no upload links created for this batch. Generate a tokenized portal URL to start receiving file uploads."
                icon={<LinkIcon className="h-12 w-12 text-muted-foreground/60" />}
              />
            )}
          </div>
        )}

        {/* 3. DOCUMENT REQUIREMENTS TAB (DOCUMENT COLLECTION ONLY) */}
        {activeTab === 'documents' && (
          <div className="space-y-6">
            {/* Notice Banner: Clear separation between Document Collection & Data Extraction */}
            <div className="p-4 rounded-xl border border-emerald-500/20 bg-emerald-950/20 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div className="flex items-start gap-3">
                <div className="h-9 w-9 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center shrink-0 mt-0.5">
                  <ShieldCheck className="h-5 w-5" />
                </div>
                <div className="space-y-0.5">
                  <h4 className="text-sm font-bold text-foreground">Document Collection Requirements</h4>
                  <p className="text-xs text-muted-foreground">
                    Configure which documents students must upload during admission. To select extraction fields, Excel headers, and OCR mappings, use the{' '}
                    <strong className="text-emerald-400 font-semibold">Data Extraction Workspace</strong>.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => navigate(`/data-extraction/${batchId}`)}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs shrink-0 cursor-pointer transition-colors"
              >
                <Sparkles className="h-3.5 w-3.5" />
                <span>Go to Data Extraction</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>

            {/* Document Collection Requirements Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-border">
              <div>
                <div className="flex items-center gap-2">
                  <FileText className="h-5 w-5 text-primary" />
                  <h2 className="text-xl font-extrabold text-foreground tracking-tight">Required Documents for Applicants</h2>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Which documents should students upload through the admission portal?
                </p>
              </div>

              <div className="flex items-center gap-3 flex-wrap">
                <div className="flex items-center gap-2 bg-card px-3 py-1.5 rounded-xl border border-border">
                  <span className="text-[11px] font-bold text-muted-foreground uppercase flex items-center gap-1.5">
                    <Layers className="h-3.5 w-3.5 text-primary" /> SCOPE:
                  </span>
                  <select
                    value={selectedClassId}
                    onChange={(e) => setSelectedClassId(e.target.value)}
                    className="px-2.5 py-1 rounded-lg border border-border bg-background text-xs font-bold text-foreground focus:outline-none focus:ring-1 focus:ring-primary cursor-pointer"
                  >
                    <option value="all">Batch Level (All Sections)</option>
                    {batchClasses.map((cls) => (
                      <option key={cls.id} value={cls.id}>
                        {cls.class_name} (Sec {cls.section})
                      </option>
                    ))}
                  </select>
                </div>

                <button
                  type="button"
                  onClick={handleOpenAddDocModal}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground font-bold text-xs shadow-xs transition-colors cursor-pointer"
                >
                  <Plus className="h-3.5 w-3.5 stroke-[3]" /> Add Document Requirement
                </button>

                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => loadWantedOverview()}
                  disabled={isLoadingWanted}
                  className="cursor-pointer gap-1.5 text-xs h-9 px-3"
                  title="Refresh Requirements"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${isLoadingWanted ? 'animate-spin' : ''}`} />
                  Refresh
                </Button>
              </div>
            </div>

            {/* Quick Presets Bar */}
            <div className="p-4 rounded-xl bg-card border border-border space-y-2">
              <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider block">
                Quick Add Standard Admission Documents:
              </span>
              <div className="flex flex-wrap gap-2">
                {[
                  { name: 'Aadhaar Card', code: 'AADHAAR', desc: 'Front and back side of Aadhaar Card', status: 'REQUIRED' as const },
                  { name: '10th SSLC Marksheet', code: 'SSLC', desc: '10th Standard Marksheet / Passing Certificate', status: 'REQUIRED' as const },
                  { name: '12th HSC Marksheet', code: 'HSC', desc: '12th Standard Marksheet / Higher Secondary', status: 'REQUIRED' as const },
                  { name: 'Community Certificate', code: 'COMMUNITY', desc: 'Permanent Community Certificate from Revenue Authority', status: 'REQUIRED' as const },
                  { name: 'Transfer Certificate', code: 'TRANSFER_CERTIFICATE', desc: 'School / College Leaving Transfer Certificate', status: 'REQUIRED' as const },
                  { name: 'Bank Passbook', code: 'BANK_PASSBOOK', desc: 'Bank Account Passbook / Statement copy', status: 'REQUIRED' as const },
                  { name: 'Income Certificate', code: 'INCOME', desc: 'Annual Family Income Certificate', status: 'OPTIONAL' as const },
                  { name: 'Passport', code: 'PASSPORT', desc: 'Valid Passport Document', status: 'OPTIONAL' as const },
                ].map((preset) => {
                  const alreadyAdded = wantedOverview.some(
                    (d) => d.document_type.toUpperCase().trim() === preset.code
                  )
                  return (
                    <button
                      key={preset.code}
                      type="button"
                      disabled={alreadyAdded}
                      onClick={() => handleAddPresetDoc(preset)}
                      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                        alreadyAdded
                          ? 'bg-secondary/40 text-muted-foreground/60 border border-border/40 cursor-not-allowed'
                          : 'bg-secondary hover:bg-secondary/80 text-foreground border border-border hover:border-primary/40'
                      }`}
                    >
                      {alreadyAdded ? <FileCheck className="h-3.5 w-3.5 text-emerald-500" /> : <Plus className="h-3.5 w-3.5 text-primary" />}
                      <span>{preset.name}</span>
                      {alreadyAdded && <span className="text-[10px] text-muted-foreground">(Added)</span>}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Document Collection Requirements List */}
            {wantedOverview.length === 0 ? (
              <div className="p-12 text-center border-2 border-dashed border-border rounded-2xl bg-card/50 flex flex-col items-center justify-center space-y-4">
                <div className="h-14 w-14 rounded-2xl bg-primary/10 text-primary flex items-center justify-center">
                  <FileText className="h-7 w-7" />
                </div>
                <div className="max-w-md space-y-1">
                  <h3 className="text-base font-bold text-foreground">No Document Requirements Configured</h3>
                  <p className="text-xs text-muted-foreground">
                    Define which documents students must upload during admission (e.g. Aadhaar, 10th Marksheet, Community Certificate).
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleOpenAddDocModal}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-primary text-primary-foreground font-bold text-xs shadow-sm cursor-pointer"
                >
                  <Plus className="h-4 w-4 stroke-[3]" /> Add First Document Requirement
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {wantedOverview.map((item) => {
                  const reqStatus = item.requirement_status || 'REQUIRED'
                  return (
                    <div
                      key={item.document_type}
                      className="p-5 rounded-2xl border border-border bg-card shadow-sm hover:border-border/80 transition-all flex flex-col justify-between space-y-4"
                    >
                      <div className="space-y-3">
                        {/* Top Row: Name, Code, and Delete */}
                        <div className="flex items-start justify-between gap-2">
                          <div className="space-y-0.5 min-w-0">
                            <span className="font-bold text-sm text-foreground block truncate uppercase tracking-tight">
                              {item.display_name}
                            </span>
                            <span className="text-3xs font-mono font-bold text-muted-foreground block">
                              CODE: {item.document_type}
                            </span>
                          </div>

                          <button
                            type="button"
                            disabled={isDeletingDoc}
                            onClick={() => handleDeleteDocumentType(item.document_type, item.display_name)}
                            className="p-1.5 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-colors cursor-pointer disabled:opacity-50"
                            title="Remove Document Requirement"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>

                        {/* Description */}
                        {item.description && (
                          <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                            {item.description}
                          </p>
                        )}

                        {/* File Constraints Info */}
                        <div className="grid grid-cols-2 gap-2 p-2.5 rounded-xl bg-secondary/40 border border-border/60 text-xs">
                          <div>
                            <span className="text-[10px] font-bold text-muted-foreground block uppercase">Formats</span>
                            <span className="font-semibold text-foreground text-xs">PDF, JPG, PNG</span>
                          </div>
                          <div className="border-l border-border/60 pl-2">
                            <span className="text-[10px] font-bold text-muted-foreground block uppercase">Max Size</span>
                            <span className="font-semibold text-foreground text-xs">5 MB</span>
                          </div>
                        </div>
                      </div>

                      {/* Bottom Row: Portal Requirement Status Dropdown */}
                      <div className="pt-3 border-t border-border/60 flex items-center justify-between gap-2">
                        <span className="text-xs font-bold text-muted-foreground uppercase">
                          Portal Requirement:
                        </span>
                        <select
                          value={reqStatus}
                          onChange={(e) => {
                            const val = e.target.value as 'REQUIRED' | 'OPTIONAL' | 'DISABLED'
                            handleUpdateRequirementStatus(item.document_type, val)
                          }}
                          className={`text-xs font-bold px-2.5 py-1 rounded-lg border focus:outline-none focus:ring-1 focus:ring-primary cursor-pointer uppercase ${
                            reqStatus === 'REQUIRED'
                              ? 'bg-blue-950/80 text-blue-400 border-blue-800/40'
                              : reqStatus === 'OPTIONAL'
                              ? 'bg-purple-950/80 text-purple-400 border-purple-800/40'
                              : 'bg-zinc-900 text-zinc-400 border-zinc-700'
                          }`}
                        >
                          <option value="REQUIRED">REQUIRED</option>
                          <option value="OPTIONAL">OPTIONAL</option>
                          <option value="DISABLED">DISABLED (Hidden)</option>
                        </select>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {/* MODAL: GENERATE UPLOAD LINK */}
      <Modal isOpen={isLinkModalOpen} onClose={() => setIsLinkModalOpen(false)} title="Generate Tokenized Upload Link">
        <form onSubmit={handleGenerateLink} className="space-y-4">
          <Input
            label="Portal Link Name"
            type="text"
            placeholder="e.g. Passport & Transcript Upload Portal"
            value={linkTitle}
            onChange={(e) => setLinkTitle(e.target.value)}
            required
          />

          <Input
            label="Link Expiry Date"
            type="date"
            value={linkExpiry}
            onChange={(e) => setLinkExpiry(e.target.value)}
          />

          <div className="rounded-lg bg-secondary/50 border border-border p-3 flex gap-2.5">
            <Calendar className="h-5 w-5 text-indigo-500 shrink-0 mt-0.5" />
            <div className="text-xs text-muted-foreground leading-relaxed">
              Upon generation, the system creates a public URL token. Accessing the URL requires no credentials, allowing prospective applicants to direct-upload verification documents securely.
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-4 border-t border-border">
            <Button type="button" variant="outline" onClick={() => setIsLinkModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary">
              Generate Portal
            </Button>
          </div>
        </form>
      </Modal>

      {/* MODAL: MANAGE UPLOAD LINK EXPIRY */}
      <Modal isOpen={isExpiryModalOpen} onClose={() => setIsExpiryModalOpen(false)} title="Manage Link Expiry">
        <form onSubmit={handleSaveExpiry} className="space-y-4">
          <Input
            label="Link Expiry Date"
            type="date"
            value={editLinkExpiry}
            onChange={(e) => setEditLinkExpiry(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Leave empty to remove the expiry date. If no expiry date is set, the link remains active indefinitely.
          </p>

          <div className="flex justify-between items-center pt-4 border-t border-border">
            {selectedLinkForExpiry?.expiresAt && (
              <Button
                type="button"
                variant="outline"
                className="text-destructive border-destructive hover:bg-destructive/10 cursor-pointer"
                onClick={handleRemoveExpiry}
              >
                Remove Expiry Date
              </Button>
            )}
            <div className="flex gap-3 ml-auto">
              <Button type="button" variant="outline" onClick={() => setIsExpiryModalOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" variant="primary">
                Save Changes
              </Button>
            </div>
          </div>
        </form>
      </Modal>

      {/* MODAL: STUDENT DETAILS INSPECTION & DOCUMENT PREVIEW */}
      {selectedStudent && (
        <Modal
          isOpen={!!selectedStudent}
          onClose={() => setSelectedStudent(null)}
          title={`Candidate Details: ${selectedStudent.name}`}
        >
          <div className="space-y-6">
            {/* Student Header */}
            <div className="p-4 bg-secondary/40 border border-border rounded-xl grid grid-cols-2 gap-3 text-xs">
              <div>
                <span className="text-muted-foreground block">Registration No.</span>
                <span className="font-bold text-foreground font-mono">{selectedStudent.registerNum}</span>
              </div>
              <div>
                <span className="text-muted-foreground block">Mobile Contact</span>
                <span className="font-bold text-foreground">{selectedStudent.mobile}</span>
              </div>
              <div>
                <span className="text-muted-foreground block">Submission Timestamp</span>
                <span className="font-bold text-foreground">{selectedStudent.submittedAt}</span>
              </div>
              <div>
                <span className="text-muted-foreground block">Verification Status</span>
                <span className="font-bold text-primary">{selectedStudent.status}</span>
              </div>
            </div>

            {/* Document list with Preview Action */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5" />
                  Uploaded Documents ({selectedStudent.documents.length})
                </h4>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleDownloadAllDocuments}
                  disabled={
                    isDownloadingAllDocs ||
                    (selectedStudent.documents || []).filter((d: any) => d.status === 'Uploaded').length === 0
                  }
                  className="cursor-pointer gap-1.5 text-xs h-8 px-2.5"
                  title={
                    (selectedStudent.documents || []).filter((d: any) => d.status === 'Uploaded').length === 0
                      ? 'No documents available for download.'
                      : 'Download all uploaded documents as a single combined PDF'
                  }
                >
                  {isDownloadingAllDocs ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                      <span>Preparing documents...</span>
                    </>
                  ) : (
                    <>
                      <Download className="h-3.5 w-3.5" />
                      <span>Download All</span>
                    </>
                  )}
                </Button>
              </div>
              <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
                {selectedStudent.documents.length === 0 && (
                  <p className="text-xs text-muted-foreground italic py-2">No documents submitted.</p>
                )}
                {selectedStudent.documents.map((doc, idx) => {
                  const isUploaded = doc.status === 'Uploaded'
                  const docIndex = doc.documentIndex !== undefined ? doc.documentIndex : idx
                  const canPreview = isUploaded && docIndex !== undefined

                  return (
                    <div
                      key={idx}
                      onClick={() => {
                        if (canPreview) {
                          setPreviewTarget({
                            submissionId: selectedStudent.id,
                            documentIndex: docIndex,
                            documentName: doc.reqName,
                            fileType: doc.fileType,
                            fileName: doc.fileName,
                            studentName: selectedStudent.name,
                          })
                        }
                      }}
                      className={`p-3 rounded-xl border transition-all flex items-center justify-between gap-3 shadow-2xs ${
                        canPreview
                          ? 'border-border bg-card hover:bg-secondary/40 hover:border-emerald-500/40 cursor-pointer'
                          : 'border-border/60 bg-card/60 opacity-80 cursor-default'
                      }`}
                    >
                      <div className="flex items-start gap-2.5 min-w-0">
                        <div
                          className={`flex h-8 w-8 items-center justify-center rounded-lg shrink-0 mt-0.5 ${
                            isUploaded
                              ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20'
                              : 'bg-muted text-muted-foreground border border-border'
                          }`}
                        >
                          <FileText className="h-4 w-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="font-bold text-foreground text-xs block truncate">{doc.reqName}</span>
                          {doc.fileName ? (
                            <span className="text-[11px] text-muted-foreground font-mono block mt-0.5 truncate">
                              {doc.fileName}
                              {doc.fileSizeMb ? ` · ${doc.fileSizeMb} MB` : ''}
                            </span>
                          ) : !isUploaded ? (
                            <span className="text-[11px] text-muted-foreground/60 italic block mt-0.5">
                              Document unavailable
                            </span>
                          ) : null}
                        </div>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        {isUploaded ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-green-100 text-green-800 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border dark:border-emerald-800/40">
                            Uploaded
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-muted text-muted-foreground border border-border">
                            Document unavailable
                          </span>
                        )}

                        {canPreview && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              setPreviewTarget({
                                submissionId: selectedStudent.id,
                                documentIndex: docIndex,
                                documentName: doc.reqName,
                                fileType: doc.fileType,
                                fileName: doc.fileName,
                                studentName: selectedStudent.name,
                              })
                            }}
                            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-slate-950 transition-colors shadow-2xs cursor-pointer"
                            title={`Preview ${doc.reqName}`}
                          >
                            <span>Preview</span>
                            <ArrowRight className="h-3 w-3" />
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Status change buttons */}
            <div className="flex items-center justify-between pt-4 border-t border-border">
              <div className="flex gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => {
                    updateStudentStatus(selectedStudent.id, 'Verified')
                    setSelectedStudent((prev) => prev ? { ...prev, status: 'Verified' } : null)
                    addToast(`Marked ${selectedStudent.name} as Verified!`, 'success')
                  }}
                  className="cursor-pointer gap-1"
                >
                  <CheckCircle className="h-3.5 w-3.5" /> Mark Verified
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => {
                    updateStudentStatus(selectedStudent.id, 'Rejected')
                    setSelectedStudent((prev) => prev ? { ...prev, status: 'Rejected' } : null)
                    addToast(`Marked ${selectedStudent.name} as Rejected.`, 'info')
                  }}
                  className="cursor-pointer gap-1"
                >
                  <XCircle className="h-3.5 w-3.5" /> Reject
                </Button>
              </div>
              <Button variant="outline" size="sm" onClick={() => setSelectedStudent(null)}>
                Close
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* MODAL: DOCUMENT PREVIEW MODAL */}
      <DocumentPreviewModal
        target={previewTarget}
        onClose={() => setPreviewTarget(null)}
      />

      {/* MODAL: CREATE SECTION MODAL */}
      <Modal isOpen={isSectionModalOpen} onClose={() => setIsSectionModalOpen(false)} title={`Create Section in ${activeBatch.name}`}>
        <form
          onSubmit={async (e) => {
            e.preventDefault()
            const secCode = newSecCode.trim() || 'A'
            let secName = newSecName.trim()
            if (!secName) {
              secName = secCode.toLowerCase().startsWith('section') ? secCode : `Section ${secCode}`
            }
            try {
              await createClass(activeBatch.id, {
                class_name: secName,
                department: activeBatch.department,
                section: secCode,
                academic_year: activeBatch.academicYear,
              })
              addToast(`Section "${secName}" created successfully!`, 'success')
              setIsSectionModalOpen(false)
              setNewSecName('')
            } catch (err: any) {
              addToast(err?.response?.data?.detail || 'Failed to create section', 'error')
            }
          }}
          className="space-y-4"
        >
          <Input
            label="Section Code"
            type="text"
            placeholder="e.g. A, B, or C"
            value={newSecCode}
            onChange={(e) => setNewSecCode(e.target.value)}
            required
          />
          <Input
            label="Section Name (Optional)"
            type="text"
            placeholder="e.g. Section A (defaults to Section {code})"
            value={newSecName}
            onChange={(e) => setNewSecName(e.target.value)}
          />
          <div className="flex justify-end gap-3 pt-4 border-t border-border">
            <Button type="button" variant="outline" onClick={() => setIsSectionModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary">
              Create Section
            </Button>
          </div>
        </form>
      </Modal>

      {/* ADD DOCUMENT REQUIREMENT MODAL */}
      <Modal
        isOpen={isAddDocModalOpen}
        onClose={() => setIsAddDocModalOpen(false)}
        title="Add Document Collection Requirement"
      >
        <form onSubmit={handleCreateDocumentType} className="space-y-4">
          <p className="text-xs text-muted-foreground">
            Configure which document type students are required to upload for this admission batch.
          </p>

          <div>
            <label className="text-xs font-bold text-foreground block mb-1">Common Document Presets</label>
            <div className="flex flex-wrap gap-1.5">
              {[
                { name: 'Aadhaar Card', code: 'AADHAAR', desc: 'Front and back copy of Aadhaar Card' },
                { name: '10th SSLC Marksheet', code: 'SSLC', desc: '10th Marksheet / Passing Certificate' },
                { name: '12th HSC Marksheet', code: 'HSC', desc: '12th Marksheet / Higher Secondary' },
                { name: 'Community Certificate', code: 'COMMUNITY', desc: 'Permanent Community Certificate from Revenue Authority' },
                { name: 'Transfer Certificate', code: 'TRANSFER_CERTIFICATE', desc: 'Transfer Certificate from previous institution' },
                { name: 'Income Certificate', code: 'INCOME', desc: 'Annual Family Income Certificate' },
                { name: 'Birth Certificate', code: 'BIRTH_CERTIFICATE', desc: 'Official Birth Certificate' },
                { name: 'Passport', code: 'PASSPORT', desc: 'Valid Passport document' },
                { name: 'Bank Passbook', code: 'BANK_PASSBOOK', desc: 'Bank Account Passbook / Statement' },
                { name: 'Nativity Certificate', code: 'NATIVITY', desc: 'Proof of Nativity / Residence' },
                { name: 'Bonafide Certificate', code: 'BONAFIDE', desc: 'Bonafide / Study Certificate' },
                { name: 'Migration Certificate', code: 'MIGRATION', desc: 'Migration Certificate' },
              ].map((preset) => (
                <button
                  type="button"
                  key={preset.code}
                  onClick={() => {
                    setNewDocName(preset.name)
                    setNewDocCode(preset.code)
                    setNewDocDescription(preset.desc)
                  }}
                  className={`text-3xs px-2.5 py-1 rounded-lg border font-medium transition-colors cursor-pointer ${
                    newDocCode === preset.code
                      ? 'bg-primary text-primary-foreground border-primary'
                      : 'bg-secondary/60 hover:bg-secondary border-border text-foreground'
                  }`}
                >
                  {preset.name}
                </button>
              ))}
            </div>
          </div>

          <Input
            label="Document Name"
            type="text"
            placeholder="e.g. Aadhaar Card, Community Certificate"
            value={newDocName}
            onChange={(e) => handleDocNameChange(e.target.value)}
            required
          />

          <Input
            label="Document Code"
            type="text"
            placeholder="e.g. AADHAAR, COMMUNITY"
            value={newDocCode}
            onChange={(e) => setNewDocCode(e.target.value.toUpperCase())}
            required
          />
          <span className="text-3xs text-muted-foreground block -mt-2">
            Unique identifier normalized to uppercase alphanumeric and underscores.
          </span>

          <Input
            label="Instructions for Student (Optional)"
            type="text"
            placeholder="e.g. Clear color scan or PDF of front and back side"
            value={newDocDescription}
            onChange={(e) => setNewDocDescription(e.target.value)}
          />

          <div>
            <label className="text-xs font-bold text-foreground block mb-1.5">Upload Requirement Status</label>
            <div className="grid grid-cols-3 gap-2">
              {[
                { value: 'REQUIRED', label: 'REQUIRED', desc: 'Mandatory before submission' },
                { value: 'OPTIONAL', label: 'OPTIONAL', desc: 'Optional / Can be submitted later' },
                { value: 'DISABLED', label: 'DISABLED', desc: 'Hidden from Student Portal' },
              ].map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setNewDocRequirementStatus(opt.value as any)}
                  className={`p-2.5 rounded-xl border text-left cursor-pointer transition-all ${
                    newDocRequirementStatus === opt.value
                      ? 'border-primary bg-primary/10 text-foreground ring-2 ring-primary/20'
                      : 'border-border bg-card text-muted-foreground hover:bg-secondary/40'
                  }`}
                >
                  <span className="font-bold text-xs block text-foreground">{opt.label}</span>
                  <span className="text-3xs block text-muted-foreground mt-0.5">{opt.desc}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-4 border-t border-border">
            <Button
              type="button"
              variant="outline"
              onClick={() => setIsAddDocModalOpen(false)}
              disabled={isCreatingDoc}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={isCreatingDoc || !newDocName.trim() || !newDocCode.trim()}
              className="gap-1.5"
            >
              {isCreatingDoc && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Save Requirement
            </Button>
          </div>
        </form>
      </Modal>

      {/* RECLASSIFY DOCUMENT MODAL */}
      <ReclassifyModal
        isOpen={Boolean(selectedDocForReclassify)}
        onClose={() => setSelectedDocForReclassify(null)}
        doc={selectedDocForReclassify}
        onSuccess={() => {
          loadValidationData()
        }}
      />

      {/* CLASSIFICATION EVIDENCE MODAL */}
      <ClassificationEvidenceModal
        isOpen={Boolean(selectedDocForEvidence)}
        onClose={() => setSelectedDocForEvidence(null)}
        doc={selectedDocForEvidence}
        onOpenReclassify={() => {
          if (selectedDocForEvidence) {
            setSelectedDocForReclassify(selectedDocForEvidence)
          }
        }}
      />
    </div>
  )
}
