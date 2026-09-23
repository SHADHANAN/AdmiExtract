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
  Upload,
  FileSpreadsheet,
  Settings2,
  Save,
  Check,
  Layers,
  FolderOpen,
  AlertTriangle,
  AlertCircle,
  RefreshCw,
  ArrowRight,
} from 'lucide-react'
import { DocumentPreviewModal, type DocumentPreviewTarget } from '../components/ui/DocumentPreviewModal'

import type { DocumentRequirement, StudentSubmission } from '../types'
import { excelTemplateService, type ExcelTemplateResponse } from '../services/excelTemplate'
import { wantedFieldService, type DocumentTypeOverviewItem, type WantedFieldItem } from '../services/wantedField'
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
  const [activeTab, setActiveTab] = useState<'sections' | 'students' | 'links' | 'documents' | 'exports'>(
    (initialTab as any) || 'sections'
  )

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

  const classifyFieldDomain = (name: string): string | null => {
    if (!name) return null
    const norm = name.toLowerCase().replace(/[^a-z0-9]/g, '')
    const rawLower = name.toLowerCase().trim()

    // Identification
    if (norm.includes('aadhaar') || norm.includes('aadhar') || norm.includes('uidai')) return 'IDENTIFICATION_AADHAAR'
    if (norm.includes('emis')) return 'IDENTIFICATION_EMIS'
    if (
      (rawLower.includes('transfer') || rawLower.includes('tc') || rawLower.startsWith('tc ')) &&
      (rawLower.includes('no') || rawLower.includes('num') || rawLower.includes('number') || rawLower.includes('cert'))
    ) return 'IDENTIFICATION_TC'
    if (rawLower.includes('admission') && (rawLower.includes('no') || rawLower.includes('num') || rawLower.includes('number') || rawLower.includes('id'))) return 'IDENTIFICATION_ADMISSION'
    if (norm.includes('registernumber') || norm.includes('registerno') || norm.includes('regno') || norm.includes('rollnumber') || norm.includes('rollno')) return 'IDENTIFICATION_REGISTER'

    // Academic
    if (rawLower.includes('sslc') || rawLower.includes('10th')) {
      if (rawLower.includes('year') || rawLower.includes('passing')) return 'ACADEMIC_PASSING_YEAR'
      return 'ACADEMIC_10TH'
    }
    if (rawLower.includes('hsc') || rawLower.includes('12th') || rawLower.includes('+2')) {
      if (rawLower.includes('year') || rawLower.includes('passing')) return 'ACADEMIC_PASSING_YEAR'
      return 'ACADEMIC_12TH'
    }
    if ((rawLower.includes('school') || rawLower.includes('institution') || rawLower.includes('college')) && (rawLower.includes('name') || rawLower.includes('studied'))) return 'ACADEMIC_INSTITUTION'

    // Dates
    if (rawLower.includes('issue date') || rawLower.includes('date of issue') || rawLower.includes('tc issue date') || rawLower.includes('tc date')) return 'DATE_ISSUE'
    if (rawLower.includes('leaving date') || rawLower.includes('date of leaving') || rawLower.includes('tc leaving date')) return 'DATE_LEAVING'
    if (rawLower.includes('admission date') || rawLower.includes('date of admission')) return 'DATE_ADMISSION'
    if (rawLower.includes('dob') || rawLower.includes('birth') || rawLower.includes('date of birth')) return 'DATE_DOB'

    // Identity
    if (rawLower.includes('father')) return 'IDENTITY_FATHER_NAME'
    if (rawLower.includes('mother')) return 'IDENTITY_MOTHER_NAME'
    if (rawLower.includes('guardian')) return 'IDENTITY_GUARDIAN_NAME'
    if ((rawLower.includes('student') || rawLower.includes('candidate') || rawLower.includes('applicant')) && rawLower.includes('name')) return 'IDENTITY_STUDENT_NAME'
    if (norm === 'name' || rawLower === "student's name") return 'IDENTITY_STUDENT_NAME'

    // Contact
    if (rawLower.includes('mobile') || rawLower.includes('phone') || rawLower.includes('cell') || rawLower.includes('contact no')) return 'CONTACT_MOBILE'
    if (rawLower.includes('email') || rawLower.includes('e-mail')) return 'CONTACT_EMAIL'

    // Financial
    if (rawLower.includes('income')) return 'FINANCIAL_INCOME'

    // Community
    if (rawLower.includes('caste') || rawLower.includes('community name') || norm.includes('subcaste')) return 'COMMUNITY_CASTE'
    if (rawLower.includes('community') || rawLower.includes('category')) return 'COMMUNITY_CATEGORY'

    // Address
    if (rawLower.includes('taluk') || rawLower.includes('tehsil') || rawLower.includes('mandal') || norm === 'tk') return 'ADDRESS_TALUK'
    if (rawLower.includes('district') || norm === 'dist' || norm === 'dt') return 'ADDRESS_DISTRICT'
    if (rawLower.includes('state') || rawLower.includes('province')) return 'ADDRESS_STATE'
    if (rawLower.includes('village') || rawLower.includes('town') || norm === 'vtc') return 'ADDRESS_VILLAGE'
    if (rawLower.includes('pincode') || rawLower.includes('pin code') || rawLower.includes('postal code') || norm === 'pin') return 'ADDRESS_PINCODE'
    if (rawLower.includes('address') || rawLower.includes('residential') || rawLower.includes('permanent') || rawLower.includes('communication')) return 'ADDRESS_FULL'

    return null
  }

  const checkFieldCompatibility = (aiFieldLabel: string, excelHeader: string): { isCompatible: boolean; message: string } => {
    if (!aiFieldLabel || !excelHeader) return { isCompatible: false, message: 'Header is required' }
    const d1 = classifyFieldDomain(aiFieldLabel)
    const d2 = classifyFieldDomain(excelHeader)

    if (d1 && d2) {
      if (d1 === d2) return { isCompatible: true, message: 'Mapped' }
      return { isCompatible: false, message: `Invalid mapping: ${aiFieldLabel} cannot be mapped to ${excelHeader}.` }
    }
    if (d1 && !d2) {
      return { isCompatible: false, message: `Invalid mapping: ${aiFieldLabel} cannot be mapped to ${excelHeader}.` }
    }
    if (!d1 && d2) {
      return { isCompatible: false, message: `Invalid mapping: ${aiFieldLabel} cannot be mapped to ${excelHeader}.` }
    }

    const norm1 = aiFieldLabel.toLowerCase().replace(/[^a-z0-9]/g, '')
    const norm2 = excelHeader.toLowerCase().replace(/[^a-z0-9]/g, '')
    if (norm1 === norm2 || norm1.includes(norm2) || norm2.includes(norm1)) {
      return { isCompatible: true, message: 'Mapped' }
    }
    return { isCompatible: false, message: `Invalid mapping: ${aiFieldLabel} cannot be mapped to ${excelHeader}.` }
  }

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

  // Excel Template states
  const [excelTemplate, setExcelTemplate] = useState<ExcelTemplateResponse | null>(null)
  const [isUploadingExcel, setIsUploadingExcel] = useState(false)
  const [excelMappings, setExcelMappings] = useState<Record<string, string>>({})
  const [lookupColumn, setLookupColumn] = useState<string>('Reg No')
  const [isSavingMappings, setIsSavingMappings] = useState(false)
  const [isDownloadingExcel, setIsDownloadingExcel] = useState(false)

  // Fetch Excel template metadata (per class if selected)
  const loadExcelTemplateInfo = React.useCallback(async () => {
    if (batchId) {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      const data = await excelTemplateService.getTemplate(batchId, classIdParam)
      if (data) {
        setExcelTemplate(data)
        setExcelMappings(data.field_mappings || {})
        setLookupColumn(data.lookup_column || (data.headers[0] || 'Reg No'))
      } else {
        setExcelTemplate(null)
        setExcelMappings({})
      }
    }
  }, [batchId, selectedClassId])

  React.useEffect(() => {
    loadExcelTemplateInfo()
  }, [loadExcelTemplateInfo])

  // Document-Specific Wanted Field Selection States
  const [wantedOverview, setWantedOverview] = useState<DocumentTypeOverviewItem[]>([])
  const [selectedDocType, setSelectedDocType] = useState<string>('')
  const [activeDocFields, setActiveDocFields] = useState<WantedFieldItem[]>([])
  const [isLoadingWanted, setIsLoadingWanted] = useState(false)
  const [isSavingWanted, setIsSavingWanted] = useState(false)

  // Add Document Type Modal States
  const [isAddDocModalOpen, setIsAddDocModalOpen] = useState(false)
  const [newDocName, setNewDocName] = useState('')
  const [newDocCode, setNewDocCode] = useState('')
  const [newDocDescription, setNewDocDescription] = useState('')
  const [newDocRequirementStatus, setNewDocRequirementStatus] = useState<'REQUIRED' | 'OPTIONAL' | 'DISABLED'>('REQUIRED')
  const [activeDocRequirementStatus, setActiveDocRequirementStatus] = useState<'REQUIRED' | 'OPTIONAL' | 'DISABLED'>('REQUIRED')
  const [isCreatingDoc, setIsCreatingDoc] = useState(false)

  // Add Custom Field Modal States
  const [isAddFieldModalOpen, setIsAddFieldModalOpen] = useState(false)
  const [newFieldName, setNewFieldName] = useState('')
  const [isAddingField, setIsAddingField] = useState(false)

  // Delete Document State
  const [isDeletingDoc, setIsDeletingDoc] = useState(false)

  // Load Wanted Fields Overview
  const loadWantedOverview = React.useCallback(async (targetDocToSelect?: string) => {
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
      
      const docToFind = targetDocToSelect || selectedDocType
      const current = deduped.find((o) => o.document_type === docToFind)
      if (current) {
        setSelectedDocType(current.document_type)
        setActiveDocFields(current.fields)
        setActiveDocRequirementStatus(current.requirement_status || 'REQUIRED')
      } else if (deduped.length > 0) {
        setSelectedDocType(deduped[0].document_type)
        setActiveDocFields(deduped[0].fields)
        setActiveDocRequirementStatus(deduped[0].requirement_status || 'REQUIRED')
      } else {
        setSelectedDocType('')
        setActiveDocFields([])
        setActiveDocRequirementStatus('REQUIRED')
      }
    } catch (err) {
      console.error('Failed to load wanted fields overview:', err)
    } finally {
      setIsLoadingWanted(false)
    }
  }, [batchId, selectedClassId, selectedDocType])

  React.useEffect(() => {
    loadWantedOverview()
  }, [loadWantedOverview])

  const availableHeaders = React.useMemo(() => {
    if (excelTemplate && excelTemplate.headers && excelTemplate.headers.length > 0) {
      return excelTemplate.headers
    }
    const fromOverview = wantedOverview.find((o) => o.template_headers && o.template_headers.length > 0)
    if (fromOverview && fromOverview.template_headers.length > 0) {
      return fromOverview.template_headers
    }
    return []
  }, [excelTemplate, wantedOverview])

  const handleSelectDocType = (docType: string) => {
    setSelectedDocType(docType)
    const docItem = wantedOverview.find((o) => o.document_type === docType)
    if (docItem) {
      setActiveDocFields(docItem.fields)
      setActiveDocRequirementStatus(docItem.requirement_status || 'REQUIRED')
    }
  }

  const handleDocNameChange = (name: string) => {
    setNewDocName(name)
    // Auto-suggest normalized code if code wasn't manually customized
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

    // Check if document already exists in current overview
    const existingDoc = wantedOverview.find(
      (d) =>
        d.document_type.toUpperCase().trim() === normCode ||
        d.display_name.trim().toLowerCase() === trimmedName.toLowerCase()
    )

    setIsCreatingDoc(true)
    try {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      if (existingDoc) {
        // Document already exists in current configuration -> update it instead of appending another record
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
        await loadWantedOverview(res.document_type)
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
      addToast(`Document "${res.display_name}" configured (${newDocRequirementStatus}) with 0 wanted fields.`, 'success')
      setIsAddDocModalOpen(false)
      setNewDocName('')
      setNewDocCode('')
      setNewDocDescription('')
      setNewDocRequirementStatus('REQUIRED')
      await loadWantedOverview(res.document_type)
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to configure document type.', 'error')
    } finally {
      setIsCreatingDoc(false)
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
      await loadExcelTemplateInfo()
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to delete document type.', 'error')
    } finally {
      setIsDeletingDoc(false)
    }
  }

  const handleAddCustomField = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!batchId || !selectedDocType) return
    const trimmed = newFieldName.trim()
    if (!trimmed) {
      addToast('Field name cannot be empty.', 'error')
      return
    }

    setIsAddingField(true)
    try {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      const res = await wantedFieldService.addCustomField(batchId, selectedDocType, trimmed, classIdParam)
      setActiveDocFields(res.fields)
      addToast(`Added field "${trimmed}". It is currently disabled (unselected).`, 'success')
      setNewFieldName('')
      setIsAddFieldModalOpen(false)
      await loadWantedOverview(selectedDocType)
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to add custom field.', 'error')
    } finally {
      setIsAddingField(false)
    }
  }

  const handleToggleWantedField = (fieldName: string) => {
    setActiveDocFields((prev) =>
      prev.map((f) => {
        if (f.field === fieldName) {
          const nextEnabled = !f.enabled
          let nextHeader = f.excel_header
          if (nextEnabled && (!nextHeader || !nextHeader.trim())) {
            const compatible = availableHeaders.find((h) => checkFieldCompatibility(f.field, h).isCompatible)
            if (compatible) nextHeader = compatible
          }
          return { ...f, enabled: nextEnabled, excel_header: nextHeader }
        }
        return f
      })
    )
  }

  const handleSetWantedFieldHeader = (fieldName: string, targetHeader: string) => {
    setActiveDocFields((prev) =>
      prev.map((f) => (f.field === fieldName ? { ...f, excel_header: targetHeader || null } : f))
    )
  }

  const handleSelectAllWantedFields = () => {
    setActiveDocFields((prev) =>
      prev.map((f) => {
        let nextHeader = f.excel_header
        if (!nextHeader || !nextHeader.trim()) {
          const compatible = availableHeaders.find((h) => checkFieldCompatibility(f.field, h).isCompatible)
          if (compatible) nextHeader = compatible
        }
        return { ...f, enabled: true, excel_header: nextHeader }
      })
    )
  }

  const handleDeselectAllWantedFields = () => {
    setActiveDocFields((prev) => prev.map((f) => ({ ...f, enabled: false })))
  }

  const handleSaveDocWantedFields = async () => {
    if (!batchId) return
    setIsSavingWanted(true)
    try {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      const activeDocOverview = wantedOverview.find((o) => o.document_type === selectedDocType)
      await wantedFieldService.saveDocumentConfig(
        batchId,
        selectedDocType,
        activeDocFields,
        classIdParam,
        {
          requirement_status: activeDocRequirementStatus,
          display_name: activeDocOverview?.display_name,
          description: activeDocOverview?.description || undefined,
        }
      )
      addToast(`Saved wanted fields for ${selectedDocType} successfully!`, 'success')
      await loadWantedOverview()
      await loadExcelTemplateInfo()
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to save document configuration.', 'error')
    } finally {
      setIsSavingWanted(false)
    }
  }

  const handleExcelUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!batchId || !e.target.files || e.target.files.length === 0) return
    const file = e.target.files[0]
    if (!file.name.toLowerCase().endsWith('.xlsx')) {
      addToast('Only .xlsx format Excel files are allowed.', 'error')
      return
    }
    setIsUploadingExcel(true)
    try {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      const res = await excelTemplateService.uploadTemplate(batchId, file, classIdParam)
      setExcelTemplate(res)
      setExcelMappings(res.field_mappings || {})
      setLookupColumn(res.lookup_column || (res.headers[0] || 'Reg No'))
      addToast(`Excel template "${file.name}" uploaded! Extracted ${res.headers.length} columns.`, 'success')
    } catch (err: any) {
      addToast(err.message || 'Failed to upload Excel template', 'error')
    } finally {
      setIsUploadingExcel(false)
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



  const handleSaveExcelMappings = async () => {
    if (!batchId) return
    setIsSavingMappings(true)
    try {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      const res = await excelTemplateService.saveMappings(batchId, excelMappings, lookupColumn, classIdParam)
      setExcelTemplate(res)
      addToast('Field mappings saved successfully!', 'success')
    } catch (err: any) {
      addToast(err.message || 'Failed to save mappings', 'error')
    } finally {
      setIsSavingMappings(false)
    }
  }

  const handleDownloadExcel = async () => {
    if (!batchId) return
    setIsDownloadingExcel(true)
    try {
      const classIdParam = selectedClassId === 'all' ? undefined : selectedClassId
      await excelTemplateService.downloadExcel(batchId, excelTemplate?.template_filename, classIdParam)
      addToast('Downloaded updated Excel workbook!', 'success')
    } catch (err: any) {
      addToast(err.message || 'Failed to download Excel workbook', 'error')
    } finally {
      setIsDownloadingExcel(false)
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

        <div className="flex items-center gap-3">
          <Button variant="outline" onClick={() => setIsSectionModalOpen(true)} className="cursor-pointer gap-1.5">
            <Plus className="h-4 w-4" /> Create Section
          </Button>
          <Button variant="outline" onClick={() => setActiveTab('documents')} className="cursor-pointer">
            <FileText className="mr-2 h-4 w-4" /> Configure Documents
          </Button>
          <Button variant="primary" onClick={() => setIsLinkModalOpen(true)} className="cursor-pointer shadow-xs">
            <Plus className="mr-2 h-4 w-4" /> Generate Portal Link
          </Button>
        </div>
      </div>

      {/* Tabs list */}
      <div className="flex border-b border-border gap-1 overflow-x-auto">
        {(
          [
            { id: 'sections', label: `Sections (${batchClasses.length})`, icon: Layers },
            { id: 'students', label: `Students (${batchStudents.length})`, icon: Users },
            { id: 'links', label: `Upload Links (${batchLinks.length})`, icon: LinkIcon },
            { id: 'documents', label: 'Document Configuration', icon: FileText },
            { id: 'exports', label: 'Exports', icon: Download },
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
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
              }`}
            >
              <Icon className="h-4 w-4" />
              {tab.label}
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
                  Each section is an independent workspace with its own student list, upload link, document rules, and export data.
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

        {/* STUDENTS TAB */}
        {activeTab === 'students' && (
          <div className="space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-foreground">Enrolled Candidate Submissions</h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Review student upload status, verify OCR extraction fields, and inspect preview documents.
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
                              {uploadedDocs} / {totalDocs} Files (PDF)
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

        {/* UPLOAD LINKS TAB */}
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

        {/* DOCUMENT CONFIGURATION TAB - EXCLUSIVELY: DOCUMENT TYPE -> WANTED FIELDS -> FIELD -> EXCEL TARGET COLUMN */}
        {activeTab === 'documents' && (
          <div className="space-y-6">
            {/* Page Header */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border">
              <div>
                <div className="flex items-center gap-2">
                  <FileText className="h-5 w-5 text-primary" />
                  <h2 className="text-lg font-bold text-foreground">Document Configuration</h2>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Configure document types, select wanted fields for extraction, and map them to Excel headers.
                </p>
              </div>

              <div className="flex items-center gap-3 flex-wrap">
                {batchClasses.length > 0 && (
                  <div className="flex items-center gap-2 bg-card px-3 py-1.5 rounded-xl border border-border">
                    <span className="text-xs font-bold text-muted-foreground uppercase flex items-center gap-1.5">
                      <Layers className="h-4 w-4 text-primary" /> Class Scope:
                    </span>
                    <select
                      value={selectedClassId}
                      onChange={(e) => setSelectedClassId(e.target.value)}
                      className="px-3 py-1 rounded-lg border border-border bg-background text-xs font-bold text-foreground focus:outline-none focus:ring-2 focus:ring-primary cursor-pointer"
                    >
                      <option value="all">Batch Level (Default)</option>
                      {batchClasses.map((cls) => (
                        <option key={cls.id} value={cls.id}>
                          {cls.class_name} (Sec {cls.section})
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleOpenAddDocModal}
                  className="cursor-pointer gap-1.5 text-xs shadow-xs"
                >
                  <Plus className="h-3.5 w-3.5" />
                  Add Document Type
                </Button>

                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => loadWantedOverview()}
                  disabled={isLoadingWanted}
                  className="cursor-pointer gap-1.5 text-xs"
                  title="Refresh Configurations"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${isLoadingWanted ? 'animate-spin' : ''}`} />
                  Refresh
                </Button>
              </div>
            </div>

            {/* Empty State: ZERO configured document types */}
            {wantedOverview.length === 0 ? (
              <div className="p-12 text-center border-2 border-dashed border-border rounded-2xl bg-card/50 flex flex-col items-center justify-center space-y-4">
                <div className="h-14 w-14 rounded-2xl bg-primary/10 text-primary flex items-center justify-center">
                  <FileText className="h-7 w-7" />
                </div>
                <div className="max-w-md space-y-1">
                  <h3 className="text-base font-bold text-foreground">No document types configured yet.</h3>
                  <p className="text-xs text-muted-foreground">
                    This batch has no configured documents. Staff/Admin must create document types manually to configure wanted extraction fields.
                  </p>
                </div>
                <Button
                  variant="primary"
                  onClick={handleOpenAddDocModal}
                  className="cursor-pointer gap-2 text-xs py-2 px-4 shadow-sm"
                >
                  <Plus className="h-4 w-4" />
                  Add Document Type
                </Button>
              </div>
            ) : (
              <>
                {/* Section 1: Document Type Cards */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                      <Layers className="h-3.5 w-3.5 text-primary" /> DOCUMENT TYPES ({wantedOverview.length})
                    </span>
                    <span className="text-3xs text-muted-foreground">
                      Click Configure on any card below to select its wanted fields
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {wantedOverview.map((item) => {
                      const isSelected = selectedDocType === item.document_type
                      let statusBadge = (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-3xs font-extrabold bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">
                          <CheckCircle className="h-3 w-3" /> Configured
                        </span>
                      )
                      if (item.status === 'NO_WANTED_FIELDS' || item.wanted_count === 0) {
                        statusBadge = (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-3xs font-extrabold bg-zinc-500/10 text-zinc-500 border border-zinc-500/20">
                            <XCircle className="h-3 w-3" /> Not Configured
                          </span>
                        )
                      } else if (item.status === 'INCOMPLETE' || item.unmapped_count > 0) {
                        statusBadge = (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-3xs font-extrabold bg-amber-500/10 text-amber-600 border border-amber-500/20">
                            <Clock className="h-3 w-3" /> Incomplete
                          </span>
                        )
                      }

                      return (
                        <div
                          key={item.document_type}
                          onClick={() => handleSelectDocType(item.document_type)}
                          className={`p-4 rounded-xl border transition-all cursor-pointer select-none flex flex-col justify-between ${
                            isSelected
                              ? 'border-primary bg-primary/5 ring-2 ring-primary/20 shadow-xs'
                              : 'border-border bg-card hover:bg-secondary/30 hover:border-border/80'
                          }`}
                        >
                          <div>
                            <div className="flex items-start justify-between gap-2">
                              <div>
                                <span className="font-bold text-sm text-foreground block">{item.display_name}</span>
                                <span className="text-3xs font-mono text-muted-foreground mt-0.5 block">
                                  {item.document_type}
                                </span>
                              </div>
                              <div className="flex items-center gap-1.5 flex-wrap justify-end">
                                <span
                                  className={`inline-flex items-center px-2 py-0.5 rounded text-3xs font-extrabold uppercase ${
                                    item.requirement_status === 'OPTIONAL'
                                      ? 'bg-purple-500/10 text-purple-600 border border-purple-500/20'
                                      : item.requirement_status === 'DISABLED'
                                      ? 'bg-zinc-500/10 text-zinc-500 border border-zinc-500/20'
                                      : 'bg-blue-500/10 text-blue-600 border border-blue-500/20'
                                  }`}
                                >
                                  {item.requirement_status || 'REQUIRED'}
                                </span>
                                {statusBadge}
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    handleDeleteDocumentType(item.document_type, item.display_name)
                                  }}
                                  className="p-1 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded transition-colors cursor-pointer"
                                  title="Delete or Archive Document Type"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            </div>

                            {item.description && (
                              <p className="text-3xs text-muted-foreground mt-1 line-clamp-1">{item.description}</p>
                            )}

                            <div className="mt-4 pt-3 border-t border-border/50 grid grid-cols-3 gap-2 text-center">
                              <div className="bg-secondary/40 rounded-lg p-1.5">
                                <span className="text-3xs text-muted-foreground block">Wanted</span>
                                <span className="text-xs font-bold text-foreground">
                                  {item.wanted_count}
                                </span>
                              </div>
                              <div className="bg-emerald-500/5 rounded-lg p-1.5 border border-emerald-500/10">
                                <span className="text-3xs text-emerald-600 font-semibold block">Mapped</span>
                                <span className="text-xs font-bold text-emerald-600">{item.mapped_count}</span>
                              </div>
                              <div className="bg-secondary/40 rounded-lg p-1.5">
                                <span className="text-3xs text-muted-foreground block">Unmapped</span>
                                <span
                                  className={`text-xs font-bold ${
                                    item.unmapped_count > 0 ? 'text-amber-600' : 'text-muted-foreground'
                                  }`}
                                >
                                  {item.unmapped_count}
                                </span>
                              </div>
                            </div>
                          </div>

                          <div className="mt-3 pt-2 border-t border-border/40 flex items-center justify-between text-3xs font-semibold">
                            <span className={isSelected ? 'text-primary font-bold' : 'text-muted-foreground'}>
                              {isSelected ? '● Currently Configuring' : 'Status: ' + (item.wanted_count === 0 ? 'Not Configured' : 'Configured')}
                            </span>
                            <Button
                              variant={isSelected ? 'primary' : 'outline'}
                              size="sm"
                              className="h-6 px-2.5 text-3xs"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleSelectDocType(item.document_type)
                              }}
                            >
                              Configure
                            </Button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>

                {/* Section 2: Active Document Wanted Fields & Excel Target Column */}
                {(() => {
                  const activeDocOverview = wantedOverview.find((o) => o.document_type === selectedDocType)
                  if (!activeDocOverview) return null

                  const enabledFields = activeDocFields.filter((f) => f.enabled)
                  const hasUnmappedEnabled = enabledFields.some((f) => !f.excel_header || !f.excel_header.trim())

                  // Calculate duplicate target conflicts within enabled fields of this document
                  const headerOwners: Record<string, string> = {}
                  let hasDuplicateConflict = false
                  for (const f of enabledFields) {
                    if (f.excel_header && f.excel_header.trim()) {
                      const h = f.excel_header.trim()
                      if (headerOwners[h] && headerOwners[h] !== f.field) {
                        hasDuplicateConflict = true
                      } else {
                        headerOwners[h] = f.field
                      }
                    }
                  }

                  const hasCompatibilityErrors = enabledFields.some(
                    (f) => f.excel_header && !checkFieldCompatibility(f.field, f.excel_header).isCompatible
                  )

                  const canSave = !hasUnmappedEnabled && !hasDuplicateConflict && !hasCompatibilityErrors

                  return (
                    <div className="p-6 border border-border rounded-xl bg-card space-y-5 shadow-2xs">
                      {/* Active Document Header */}
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-border">
                        <div>
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-extrabold text-base text-foreground uppercase tracking-wide">
                              {activeDocOverview.display_name || selectedDocType}
                            </span>
                            <span className="text-3xs px-2 py-0.5 rounded bg-secondary border border-border font-mono font-bold text-muted-foreground">
                              {selectedDocType}
                            </span>
                            <span className="text-3xs px-2 py-0.5 rounded bg-primary/10 text-primary font-bold">
                              v{activeDocOverview.version || 1}
                            </span>
                            <div className="flex items-center gap-1.5 ml-2">
                              <span className="text-3xs uppercase font-bold text-muted-foreground">Portal Status:</span>
                              <select
                                value={activeDocRequirementStatus}
                                onChange={(e) => setActiveDocRequirementStatus(e.target.value as any)}
                                className={`text-3xs font-extrabold px-2 py-0.5 rounded border focus:outline-none focus:ring-1 cursor-pointer uppercase ${
                                  activeDocRequirementStatus === 'REQUIRED'
                                    ? 'bg-blue-500/10 text-blue-700 dark:text-blue-400 border-blue-500/30 focus:ring-blue-500'
                                    : activeDocRequirementStatus === 'OPTIONAL'
                                    ? 'bg-purple-500/10 text-purple-700 dark:text-purple-400 border-purple-500/30 focus:ring-purple-500'
                                    : 'bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border-zinc-500/30 focus:ring-zinc-500'
                                }`}
                              >
                                <option value="REQUIRED">REQUIRED</option>
                                <option value="OPTIONAL">OPTIONAL</option>
                                <option value="DISABLED">DISABLED (Hidden)</option>
                              </select>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground flex-wrap">
                            <span className="font-bold text-foreground">Wanted Fields:</span>
                            <span>
                              {enabledFields.length} of {activeDocFields.length} selected for extraction
                            </span>
                            <span>•</span>
                            <span>Saving updates this document&apos;s wanted fields and requirement status</span>
                          </div>
                        </div>

                        {/* Action Buttons */}
                        <div className="flex items-center gap-2 flex-wrap">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setNewFieldName('')
                              setIsAddFieldModalOpen(true)
                            }}
                            className="cursor-pointer text-xs py-1 gap-1"
                            title="Add Custom Field to this document"
                          >
                            <Plus className="h-3 w-3" /> Add Field
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleSelectAllWantedFields}
                            className="cursor-pointer text-xs py-1"
                          >
                            Select All
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleDeselectAllWantedFields}
                            className="cursor-pointer text-xs py-1"
                          >
                            Deselect All
                          </Button>
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={handleSaveDocWantedFields}
                            disabled={isSavingWanted || !canSave}
                            className="cursor-pointer text-xs py-1 gap-1.5"
                          >
                            {isSavingWanted ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Save className="h-3.5 w-3.5" />
                            )}
                            Save {activeDocOverview.display_name ? activeDocOverview.display_name.split(' ')[0] : 'Doc'} Configuration
                          </Button>
                          <Button
                            variant="danger"
                            size="sm"
                            onClick={() => handleDeleteDocumentType(selectedDocType, activeDocOverview.display_name)}
                            disabled={isDeletingDoc}
                            className="cursor-pointer text-xs py-1 gap-1"
                            title="Delete or Archive Document Type"
                          >
                            <Trash2 className="h-3 w-3" /> Delete Doc
                          </Button>
                        </div>
                      </div>

                      {/* Guidance Alerts */}
                      {enabledFields.length === 0 && (
                        <div className="p-3.5 rounded-lg border border-zinc-300 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50 flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                          <AlertCircle className="h-4 w-4 shrink-0 text-zinc-500" />
                          <span>
                            <strong>Zero fields selected:</strong> AI multimodal extraction for this document will be
                            skipped during batch processing with status <code>NO_WANTED_FIELDS_CONFIGURED</code> without faking data.
                          </span>
                        </div>
                      )}

                      {hasUnmappedEnabled && (
                        <div className="p-3.5 rounded-lg border border-amber-300 dark:border-amber-800/60 bg-amber-50 dark:bg-amber-950/30 flex items-center gap-2 text-xs text-amber-800 dark:text-amber-300">
                          <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />
                          <span>
                            Every enabled wanted field must have a target Excel column assigned before saving.
                          </span>
                        </div>
                      )}

                      {hasDuplicateConflict && (
                        <div className="p-3.5 rounded-lg border border-destructive/30 bg-destructive/5 flex items-center gap-2 text-xs text-destructive">
                          <AlertCircle className="h-4 w-4 shrink-0" />
                          <span>
                            Multiple wanted fields are assigned to the same Excel column. Each Excel column must be unique per document.
                          </span>
                        </div>
                      )}

                      {/* Empty fields prompt if custom document has no fields */}
                      {activeDocFields.length === 0 ? (
                        <div className="p-8 text-center border border-dashed border-border rounded-lg bg-secondary/10 space-y-2">
                          <p className="text-xs font-semibold text-foreground">No available fields defined for this document yet.</p>
                          <p className="text-3xs text-muted-foreground">Click &quot;+ Add Field&quot; above to add fields you want to extract.</p>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setNewFieldName('')
                              setIsAddFieldModalOpen(true)
                            }}
                            className="cursor-pointer text-xs gap-1 mt-2"
                          >
                            <Plus className="h-3 w-3" /> Add Field
                          </Button>
                        </div>
                      ) : (
                        /* Wanted Fields Table: FIELD -> EXCEL TARGET COLUMN */
                        <div className="rounded-xl border border-border overflow-hidden bg-card">
                          <Table>
                            <TableHeader>
                              <TableRow className="bg-secondary/40">
                                <TableHead className="w-16 text-center">Wanted</TableHead>
                                <TableHead>Field Name</TableHead>
                                <TableHead>Target Excel Header Column</TableHead>
                                <TableHead className="w-28 text-center">Status</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {activeDocFields.map((field) => {
                                const isEnabled = field.enabled
                                const selectedHeader = field.excel_header || ''
                                const isMapped = isEnabled && Boolean(selectedHeader)
                                const compatResult = isMapped ? checkFieldCompatibility(field.field, selectedHeader) : null
                                const isInvalid = isMapped && compatResult ? !compatResult.isCompatible : false
                                const conflictingOwner =
                                  isMapped && headerOwners[selectedHeader] && headerOwners[selectedHeader] !== field.field
                                    ? headerOwners[selectedHeader]
                                    : null

                                return (
                                  <TableRow
                                    key={field.field}
                                    className={`transition-colors ${
                                      isEnabled ? 'bg-card hover:bg-secondary/20' : 'bg-secondary/10 opacity-60'
                                    }`}
                                  >
                                    {/* Checkbox Column */}
                                    <TableCell className="text-center">
                                      <input
                                        type="checkbox"
                                        checked={isEnabled}
                                        onChange={() => handleToggleWantedField(field.field)}
                                        className="h-4 w-4 rounded border-border text-primary focus:ring-primary cursor-pointer"
                                        title={isEnabled ? 'Disable field extraction' : 'Enable field extraction'}
                                      />
                                    </TableCell>

                                    {/* Field Name */}
                                    <TableCell className="font-semibold text-xs text-foreground">
                                      <div>
                                        <span
                                          className={`block font-bold ${
                                            isEnabled ? 'text-foreground' : 'text-muted-foreground line-through'
                                          }`}
                                        >
                                          {field.field}
                                        </span>
                                        <span className="text-3xs text-muted-foreground font-normal block mt-0.5">
                                          Source: {activeDocOverview.display_name || selectedDocType}
                                        </span>
                                      </div>
                                    </TableCell>

                                    {/* Target Excel Column Dropdown */}
                                    <TableCell>
                                      <div className="space-y-1">
                                        <select
                                          disabled={!isEnabled}
                                          value={selectedHeader}
                                          onChange={(e) => handleSetWantedFieldHeader(field.field, e.target.value)}
                                          className={`w-full max-w-sm px-3 py-1.5 text-xs rounded border bg-background font-medium focus:outline-none focus:ring-2 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-secondary/40 ${
                                            !isEnabled
                                              ? 'border-border text-muted-foreground'
                                              : isInvalid
                                              ? 'border-destructive focus:ring-destructive text-destructive'
                                              : conflictingOwner
                                              ? 'border-amber-500 focus:ring-amber-500 text-amber-600'
                                              : !selectedHeader
                                              ? 'border-amber-400 focus:ring-amber-400 text-amber-700'
                                              : 'border-border focus:ring-primary text-foreground'
                                          }`}
                                        >
                                          <option value="">
                                            {isEnabled
                                              ? availableHeaders.length > 0
                                                ? '-- Select Target Excel Column --'
                                                : '-- No Excel Template Uploaded --'
                                              : '-- Extraction Disabled --'}
                                          </option>
                                          {selectedHeader && !availableHeaders.includes(selectedHeader) && (
                                            <option value={selectedHeader}>{selectedHeader}</option>
                                          )}
                                          {availableHeaders.map((h) => {
                                            const isCompat = checkFieldCompatibility(field.field, h).isCompatible
                                            const owner = headerOwners[h]
                                            const isOwnedByOther = Boolean(owner && owner !== field.field)
                                            const isDisabled = !isCompat || isOwnedByOther

                                            let optionLabel = h
                                            if (!isCompat) {
                                              optionLabel = `${h} (Incompatible)`
                                            } else if (isOwnedByOther) {
                                              optionLabel = `${h} (Already mapped to ${owner})`
                                            }

                                            return (
                                              <option key={h} value={h} disabled={isDisabled}>
                                                {optionLabel}
                                              </option>
                                            )
                                          })}
                                        </select>

                                        {isEnabled && isInvalid && (
                                          <p className="text-destructive text-3xs font-semibold flex items-center gap-1">
                                            <AlertCircle className="h-3 w-3 inline shrink-0" />
                                            Invalid mapping: {field.field} cannot be mapped to {selectedHeader}.
                                          </p>
                                        )}

                                        {isEnabled && conflictingOwner && !isInvalid && (
                                          <p className="text-amber-600 text-3xs font-semibold flex items-center gap-1">
                                            <AlertTriangle className="h-3 w-3 inline shrink-0" />
                                            Conflict: Column &quot;{selectedHeader}&quot; is already mapped to{' '}
                                            {conflictingOwner}.
                                          </p>
                                        )}
                                      </div>
                                    </TableCell>

                                    {/* Status Column */}
                                    <TableCell className="text-center">
                                      {!isEnabled ? (
                                        <span className="inline-flex items-center px-2 py-0.5 rounded text-3xs font-medium bg-secondary text-muted-foreground border border-border">
                                          Disabled
                                        </span>
                                      ) : isInvalid ? (
                                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-3xs font-extrabold bg-red-100 text-red-800">
                                          <AlertCircle className="h-3 w-3" /> Invalid
                                        </span>
                                      ) : conflictingOwner ? (
                                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-3xs font-extrabold bg-amber-100 text-amber-800">
                                          <AlertTriangle className="h-3 w-3" /> Conflict
                                        </span>
                                      ) : isMapped ? (
                                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-3xs font-extrabold bg-emerald-100 text-emerald-800">
                                          <Check className="h-3 w-3" /> Mapped
                                        </span>
                                      ) : (
                                        <span className="inline-flex items-center px-2 py-0.5 rounded text-3xs font-bold bg-amber-100 text-amber-800">
                                          Unmapped
                                        </span>
                                      )}
                                    </TableCell>
                                  </TableRow>
                                )
                              })}
                            </TableBody>
                          </Table>
                        </div>
                      )}

                      {/* Footer Save Button */}
                      <div className="flex justify-end pt-2">
                        <Button
                          variant="primary"
                          onClick={handleSaveDocWantedFields}
                          disabled={isSavingWanted || !canSave}
                          className="cursor-pointer gap-2"
                        >
                          {isSavingWanted ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Save className="h-4 w-4" />
                          )}
                          Save {activeDocOverview.display_name || selectedDocType} Configuration
                        </Button>
                      </div>
                    </div>
                  )
                })()}
              </>
            )}
          </div>
        )}

        {/* EXPORTS & EXCEL TEMPLATE TAB */}
        {activeTab === 'exports' && (
          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-foreground">Excel Template & Auto Row Update</h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Upload an Excel template (.xlsx), configure AI field mappings, and auto-update candidate rows on verification per Class.
                </p>
              </div>

              <div className="flex items-center gap-3">
                {batchClasses.length > 0 && (
                  <div className="flex items-center gap-2 bg-card px-3 py-1.5 rounded-xl border border-border">
                    <span className="text-xs font-bold text-muted-foreground uppercase flex items-center gap-1.5">
                      <Layers className="h-4 w-4 text-primary" /> Class Scope:
                    </span>
                    <select
                      value={selectedClassId}
                      onChange={(e) => setSelectedClassId(e.target.value)}
                      className="px-3 py-1 rounded-lg border border-border bg-background text-xs font-bold text-foreground focus:outline-none focus:ring-2 focus:ring-primary cursor-pointer"
                    >
                      <option value="all">Batch Level (Default)</option>
                      {batchClasses.map((cls) => (
                        <option key={cls.id} value={cls.id}>
                          {cls.class_name} (Sec {cls.section})
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {excelTemplate && (
                  <Button
                    variant="primary"
                    onClick={handleDownloadExcel}
                    disabled={isDownloadingExcel}
                    className="cursor-pointer gap-2"
                  >
                    {isDownloadingExcel ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                    Download Updated Excel
                  </Button>
                )}
              </div>
            </div>

            {/* Metric Cards Bar */}
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-4 rounded-xl border border-border bg-card shadow-2xs">
                <span className="text-xs text-muted-foreground font-medium block">Template Status</span>
                <span className="text-sm font-bold text-foreground mt-1 flex items-center gap-1.5 truncate">
                  <FileSpreadsheet className="h-4 w-4 text-emerald-600 shrink-0" />
                  {excelTemplate ? excelTemplate.template_filename : 'No Template Uploaded'}
                </span>
              </div>
              <div className="p-4 rounded-xl border border-border bg-card shadow-2xs">
                <span className="text-xs text-muted-foreground font-medium block">Total Excel Rows</span>
                <span className="text-2xl font-black text-foreground mt-1">
                  {excelTemplate ? excelTemplate.total_rows : 0}
                </span>
              </div>
              <div className="p-4 rounded-xl border border-border bg-card shadow-2xs">
                <span className="text-xs text-muted-foreground font-medium block">Students Updated</span>
                <span className="text-2xl font-black text-emerald-600 mt-1">
                  {excelTemplate ? excelTemplate.updated_count : 0}
                </span>
              </div>
              <div className="p-4 rounded-xl border border-border bg-card shadow-2xs">
                <span className="text-xs text-muted-foreground font-medium block">Remaining Students</span>
                <span className="text-2xl font-black text-amber-600 mt-1">
                  {excelTemplate ? excelTemplate.remaining_students : 0}
                </span>
              </div>
            </div>

            {/* 1. Upload Excel Template Area */}
            <div className="p-6 border border-border rounded-xl bg-card space-y-4 shadow-2xs">
              <div className="flex items-center gap-2 text-foreground font-bold text-sm">
                <Upload className="h-4 w-4 text-primary" /> 1. Upload Excel Template (.xlsx only)
              </div>
              <div className="border-2 border-dashed border-border hover:border-primary/50 rounded-xl p-6 text-center transition-colors bg-secondary/20">
                <input
                  type="file"
                  id="excel-template-upload"
                  accept=".xlsx"
                  onChange={handleExcelUpload}
                  className="hidden"
                />
                <label htmlFor="excel-template-upload" className="cursor-pointer flex flex-col items-center gap-2">
                  {isUploadingExcel ? (
                    <Loader2 className="h-8 w-8 text-primary animate-spin" />
                  ) : (
                    <FileSpreadsheet className="h-8 w-8 text-primary" />
                  )}
                  <div>
                    <span className="font-bold text-sm text-foreground block">
                      {excelTemplate ? `Replace "${excelTemplate.template_filename}"` : 'Click to Upload Excel Template (.xlsx)'}
                    </span>
                    <span className="text-xs text-muted-foreground mt-0.5 block">
                      Only .xlsx files are accepted. Formula formatting and existing rows will be preserved.
                    </span>
                  </div>
                </label>
              </div>
            </div>

            {/* 2. Document-Specific Wanted Field & Excel Column Mapping Matrix */}
            {excelTemplate && excelTemplate.headers.length > 0 && (
              <div className="p-6 border border-border rounded-xl bg-card space-y-6 shadow-2xs">
                {/* Section Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-border">
                  <div>
                    <div className="flex items-center gap-2 text-foreground font-bold text-base">
                      <Settings2 className="h-5 w-5 text-primary" /> 2. Document-Specific Wanted Field Selection & Mapping
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Configure exactly which fields are extracted from each document type and which Excel column each field populates.
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => loadWantedOverview()}
                      disabled={isLoadingWanted}
                      className="cursor-pointer gap-1.5 text-xs"
                      title="Refresh Configurations"
                    >
                      <RefreshCw className={`h-3.5 w-3.5 ${isLoadingWanted ? 'animate-spin' : ''}`} />
                      Refresh
                    </Button>
                  </div>
                </div>

                {/* Primary Lookup Key Selector */}
                <div className="p-4 rounded-lg bg-secondary/40 border border-border flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <span className="text-xs font-bold text-foreground block">Primary Row Lookup Key Column</span>
                    <span className="text-3xs text-muted-foreground block">
                      The system uses candidate Register Number to find the matching row in this column.
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <select
                      value={lookupColumn}
                      onChange={(e) => setLookupColumn(e.target.value)}
                      className="px-3 py-1.5 rounded-lg border border-border bg-background text-xs font-bold text-foreground focus:outline-none focus:ring-2 focus:ring-primary cursor-pointer"
                    >
                      {excelTemplate.headers.map((h) => (
                        <option key={h} value={h}>
                          {h}
                        </option>
                      ))}
                    </select>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleSaveExcelMappings}
                      disabled={isSavingMappings}
                      className="cursor-pointer gap-1.5 text-xs"
                    >
                      {isSavingMappings ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                      Save Lookup Key
                    </Button>
                  </div>
                </div>

            {/* 3. Document Configuration Link Banner */}
            <div className="p-6 border border-border rounded-xl bg-card flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-2xs">
              <div>
                <span className="font-bold text-base text-foreground block flex items-center gap-2">
                  <FileText className="h-5 w-5 text-primary" /> Document-Specific Wanted Fields Configuration
                </span>
                <p className="text-xs text-muted-foreground mt-1">
                  Configure which fields should be extracted from each document and where those selected fields should go in Excel.
                </p>
              </div>
              <Button
                variant="primary"
                size="sm"
                onClick={() => setActiveTab('documents')}
                className="cursor-pointer gap-2 shrink-0"
              >
                <FileText className="h-4 w-4" /> Go to Document Configuration
              </Button>
            </div>
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
              <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5" />
                Uploaded Documents ({selectedStudent.documents.length})
              </h4>
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

      {/* ADD DOCUMENT TYPE MODAL */}
      <Modal
        isOpen={isAddDocModalOpen}
        onClose={() => setIsAddDocModalOpen(false)}
        title="Add Document Type"
      >
        <form onSubmit={handleCreateDocumentType} className="space-y-4">
          <p className="text-xs text-muted-foreground">
            Configure a new document type for this batch. All document types start with zero wanted fields until explicitly selected.
          </p>

          <div>
            <label className="text-xs font-bold text-foreground block mb-1">Quick Presets (Optional)</label>
            <div className="flex flex-wrap gap-1.5">
              {[
                { name: 'Aadhaar Card', code: 'AADHAAR' },
                { name: 'Transfer Certificate', code: 'TC' },
                { name: 'Community Certificate', code: 'COMMUNITY' },
                { name: 'Income Certificate', code: 'INCOME' },
                { name: 'SSLC Marksheet', code: 'SSLC' },
                { name: 'HSC Marksheet', code: 'HSC' },
                { name: 'Birth Certificate', code: 'BIRTH_CERTIFICATE' },
                { name: 'Passport', code: 'PASSPORT' },
                { name: 'Bank Passbook', code: 'BANK_PASSBOOK' },
                { name: 'Nativity Certificate', code: 'NATIVITY' },
                { name: 'Bonafide Certificate', code: 'BONAFIDE' },
                { name: 'Migration Certificate', code: 'MIGRATION' },
              ].map((preset) => (
                <button
                  type="button"
                  key={preset.code}
                  onClick={() => {
                    setNewDocName(preset.name)
                    setNewDocCode(preset.code)
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
            placeholder="e.g. Aadhaar Card, Residence Certificate"
            value={newDocName}
            onChange={(e) => handleDocNameChange(e.target.value)}
            required
          />

          <Input
            label="Document Code"
            type="text"
            placeholder="e.g. AADHAAR, RESIDENCE_CERTIFICATE"
            value={newDocCode}
            onChange={(e) => setNewDocCode(e.target.value.toUpperCase())}
            required
          />
          <span className="text-3xs text-muted-foreground block -mt-2">
            Unique identifier normalized to uppercase alphanumeric and underscores.
          </span>

          <Input
            label="Description (Optional)"
            type="text"
            placeholder="e.g. Government issued proof of residence"
            value={newDocDescription}
            onChange={(e) => setNewDocDescription(e.target.value)}
          />

          <div>
            <label className="text-xs font-bold text-foreground block mb-1.5">Student Upload Requirement</label>
            <div className="grid grid-cols-3 gap-2">
              {[
                { value: 'REQUIRED', label: 'REQUIRED', desc: 'Must upload before submission' },
                { value: 'OPTIONAL', label: 'OPTIONAL', desc: 'Optional / Waivable by student' },
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
              Add Document
            </Button>
          </div>
        </form>
      </Modal>

      {/* ADD CUSTOM FIELD MODAL */}
      <Modal
        isOpen={isAddFieldModalOpen}
        onClose={() => setIsAddFieldModalOpen(false)}
        title={`Add Field to ${selectedDocType}`}
      >
        <form onSubmit={handleAddCustomField} className="space-y-4">
          <p className="text-xs text-muted-foreground">
            Add a new field to this document configuration. The field will initially be disabled (unselected) until you check it.
          </p>

          <Input
            label="Field Name"
            type="text"
            placeholder="e.g. Passport Expiry Date, Place of Birth"
            value={newFieldName}
            onChange={(e) => setNewFieldName(e.target.value)}
            required
          />

          <div className="flex justify-end gap-3 pt-4 border-t border-border">
            <Button
              type="button"
              variant="outline"
              onClick={() => setIsAddFieldModalOpen(false)}
              disabled={isAddingField}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={isAddingField || !newFieldName.trim()}
              className="gap-1.5"
            >
              {isAddingField && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Add Field
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
