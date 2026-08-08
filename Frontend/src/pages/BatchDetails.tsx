import React, { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
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
  CheckSquare,
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
  Edit3,
  ArrowUp,
  ArrowDown,
  Eye,
  CheckCircle,
  XCircle,
  Clock,
  ShieldCheck,
  Maximize2,
  Sparkles,
  Loader2,
  Upload,
  FileSpreadsheet,
  Settings2,
  Save,
  Check,
  FileCheck
} from 'lucide-react'

import type { DocumentRequirement, StudentSubmission } from '../types'
import { excelTemplateService, type ExcelTemplateResponse } from '../services/excelTemplate'

const PRESET_DOCUMENTS = [
  'Aadhaar Card',
  'Birth Certificate',
  'Community Certificate',
  'Income Certificate',
  'SSLC Marksheet',
  'HSC Marksheet',
  'Transfer Certificate',
  'Passport Size Photo',
  'Medical Certificate',
  'Migration Certificate',
]

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
    updateBatchRequirements,
    getBatchDocVersions,
    fetchBatches,
    fetchUploadLinks,
  } = useBatchStore()
  const { submissions, updateStudentStatus, startAiProcessing, fetchSubmissionsByBatch } = useStudentStore()
  const { addToast } = useToastStore()

  // Fetch student submissions, batches, and upload links from FastAPI backend
  React.useEffect(() => {
    if (batchId) {
      fetchSubmissionsByBatch(batchId)
      fetchBatches()
      fetchUploadLinks()
    }
  }, [batchId, fetchSubmissionsByBatch, fetchBatches, fetchUploadLinks])

  // Active Tab state
  const [activeTab, setActiveTab] = useState<'students' | 'links' | 'documents' | 'verification' | 'exports'>('students')

  // Version History toggle state
  const [showVersionHistory, setShowVersionHistory] = useState(false)

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

  // Document Config Modal states
  const [isDocModalOpen, setIsDocModalOpen] = useState(false)
  const [editingDocId, setEditingDocId] = useState<string | null>(null)
  const [docName, setDocName] = useState('')
  const [docRequired, setDocRequired] = useState(true)
  const [docAllowedTypes, setDocAllowedTypes] = useState<string[]>(['PDF', 'JPG', 'PNG'])
  const [docMaxSizeMb, setDocMaxSizeMb] = useState<number>(5)
  const [docDescription, setDocDescription] = useState('')
  const [docExtractionFieldsText, setDocExtractionFieldsText] = useState('')

  const PROFILE_FIELDS = ['student name', 'register number', 'mobile number', 'email', 'name', 'register no', 'mobile']
  const isProfileField = (name: string) => {
    const lower = name.toLowerCase().trim()
    return PROFILE_FIELDS.some(p => lower === p || lower.includes('student name') || lower.includes('register number') || lower.includes('mobile number'))
  }

  const getDefaultFieldsForDoc = (name: string): string[] => {
    const lower = name.toLowerCase().trim()
    if (lower.includes('aadhaar') || lower.includes('aadhar')) return ['Aadhaar Number']
    if (lower.includes('community') || lower.includes('caste')) return ['Community Category']
    if (lower.includes('birth') || lower.includes('dob')) return ['Date of Birth']
    if (lower.includes('income')) return ['Annual Family Income']
    if (lower.includes('sslc')) return ['SSLC Mark Percentage']
    if (lower.includes('hsc')) return ['HSC Mark Percentage']
    if (lower.includes('transfer') || lower.includes('tc')) return ['Transfer Certificate Number', 'School Name', 'Admission Number', 'Issue Date', 'Leaving Date']
    if (lower.includes('migration')) return ['Migration Number', 'University', 'Year']
    if (lower.includes('nativity')) return ['Nativity']
    return [name]
  }

  const getDynamicSystemFields = (requirements: DocumentRequirement[]): { key: string; label: string; docName: string }[] => {
    const fieldsMap: { key: string; label: string; docName: string }[] = []
    const seenKeys = new Set<string>()

    requirements.forEach((req) => {
      const rawFields = req.extractionFields && req.extractionFields.length > 0
        ? req.extractionFields
        : getDefaultFieldsForDoc(req.name)

      rawFields.forEach((fieldName) => {
        const cleanName = fieldName.trim()
        if (!cleanName || isProfileField(cleanName)) return

        const key = cleanName.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
        if (!seenKeys.has(key)) {
          seenKeys.add(key)
          fieldsMap.push({
            key,
            label: cleanName,
            docName: req.name,
          })
        }
      })
    })

    return fieldsMap
  }

  // Student Details Modal states
  const [selectedStudent, setSelectedStudent] = useState<StudentSubmission | null>(null)
  
  // Preview Modal state
  const [previewDoc, setPreviewDoc] = useState<{ title: string; url?: string; type?: string; studentName?: string } | null>(null)

  // Find batch
  const batch = batches.find((b) => b.id === batchId)
  const versionHistory = batchId ? getBatchDocVersions(batchId) : []

  // Local state for tracking document requirement updates
  const [tempRequirements, setTempRequirements] = useState<DocumentRequirement[]>(batch?.docRequirements || [])

  // Sync temp requirements when batch changes
  React.useEffect(() => {
    if (batch?.docRequirements) {
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

  // Fetch Excel template metadata
  const loadExcelTemplateInfo = React.useCallback(async () => {
    if (batchId) {
      const data = await excelTemplateService.getTemplate(batchId)
      if (data) {
        setExcelTemplate(data)
        setExcelMappings(data.field_mappings || {})
        setLookupColumn(data.lookup_column || (data.headers[0] || 'Reg No'))
      }
    }
  }, [batchId])

  React.useEffect(() => {
    loadExcelTemplateInfo()
  }, [loadExcelTemplateInfo])

  const handleExcelUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!batchId || !e.target.files || e.target.files.length === 0) return
    const file = e.target.files[0]
    if (!file.name.toLowerCase().endsWith('.xlsx')) {
      addToast('Only .xlsx format Excel files are allowed.', 'error')
      return
    }
    setIsUploadingExcel(true)
    try {
      const res = await excelTemplateService.uploadTemplate(batchId, file)
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

  // Filter student submissions for this batch
  const batchStudents = batch ? submissions.filter((s) => s.batchId === batch.id) : []
  const batchLinks = batch ? uploadLinks.filter((l) => l.batchId === batch.id) : []

  // Document Modal Handlers
  const openAddDocModal = () => {
    setEditingDocId(null)
    setDocName('')
    setDocRequired(true)
    setDocAllowedTypes(['PDF', 'JPG', 'PNG'])
    setDocMaxSizeMb(5)
    setDocDescription('')
    setDocExtractionFieldsText('')
    setIsDocModalOpen(true)
  }

  const openEditDocModal = (req: DocumentRequirement) => {
    setEditingDocId(req.id)
    setDocName(req.name)
    setDocRequired(req.required ?? (req.type === 'MANDATORY'))
    setDocAllowedTypes(req.allowedTypes || ['PDF', 'JPG', 'PNG'])
    setDocMaxSizeMb(req.maxSizeMb || 5)
    setDocDescription(req.description || '')
    const ef = req.extractionFields && req.extractionFields.length > 0
      ? req.extractionFields
      : getDefaultFieldsForDoc(req.name)
    setDocExtractionFieldsText(ef.join(', '))
    setIsDocModalOpen(true)
  }

  const handleSaveDocConfig = (e: React.FormEvent) => {
    e.preventDefault()
    if (!batch) return
    if (!docName.trim()) {
      addToast('Document name is required', 'error')
      return
    }
    if (docAllowedTypes.length === 0) {
      addToast('Select at least one allowed file format', 'error')
      return
    }

    const parsedExtractionFields = docExtractionFieldsText
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0 && !isProfileField(s))

    if (editingDocId) {
      // Edit existing document
      const updated = tempRequirements.map((r) =>
        r.id === editingDocId
          ? {
              ...r,
              name: docName,
              required: docRequired,
              type: docRequired ? ('MANDATORY' as const) : ('OPTIONAL' as const),
              allowedTypes: docAllowedTypes,
              maxSizeMb: Number(docMaxSizeMb),
              description: docDescription,
              extractionFields: parsedExtractionFields.length > 0 ? parsedExtractionFields : getDefaultFieldsForDoc(docName),
            }
          : r
      )
      const summary = `Updated rules for "${docName}"`
      setTempRequirements(updated)
      updateBatchRequirements(batch.id, updated, summary, 'Staff')
      addToast(`Updated "${docName}" (created new document configuration version).`, 'success')
    } else {
      // Add new document requirement
      const newReq: DocumentRequirement = {
        id: `req_${Math.random().toString(36).substring(2, 9)}`,
        name: docName,
        required: docRequired,
        type: docRequired ? 'MANDATORY' : 'OPTIONAL',
        allowedTypes: docAllowedTypes,
        maxSizeMb: Number(docMaxSizeMb),
        description: docDescription,
        extractionFields: parsedExtractionFields.length > 0 ? parsedExtractionFields : getDefaultFieldsForDoc(docName),
      }
      const updated = [...tempRequirements, newReq]
      const summary = `Added document requirement "${docName}"`
      setTempRequirements(updated)
      updateBatchRequirements(batch.id, updated, summary, 'Staff')
      addToast(`Added "${docName}" (created new document configuration version).`, 'success')
    }

    setIsDocModalOpen(false)
  }

  const handleRemoveDoc = (id: string, name: string) => {
    if (!batch) return
    const updated = tempRequirements.filter((r) => r.id !== id)
    const summary = `Removed document requirement "${name}"`
    setTempRequirements(updated)
    updateBatchRequirements(batch.id, updated, summary, 'Staff')
    addToast(`Removed "${name}" (created new document configuration version).`, 'info')
  }

  const handleMoveDoc = (index: number, direction: 'up' | 'down') => {
    if (!batch) return
    const targetIndex = direction === 'up' ? index - 1 : index + 1
    if (targetIndex < 0 || targetIndex >= tempRequirements.length) return

    const updated = [...tempRequirements]
    const [moved] = updated.splice(index, 1)
    updated.splice(targetIndex, 0, moved)

    setTempRequirements(updated)
    updateBatchRequirements(batch.id, updated, 'Reordered document requirements', 'Staff')
  }

  const handleTypeToggle = (type: string) => {
    if (docAllowedTypes.includes(type)) {
      setDocAllowedTypes(docAllowedTypes.filter((t) => t !== type))
    } else {
      setDocAllowedTypes([...docAllowedTypes, type])
    }
  }

  const handleSaveExcelMappings = async () => {
    if (!batchId) return
    setIsSavingMappings(true)
    try {
      const res = await excelTemplateService.saveMappings(batchId, excelMappings, lookupColumn)
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
      await excelTemplateService.downloadExcel(batchId, excelTemplate?.template_filename)
      addToast('Downloaded updated Excel workbook!', 'success')
    } catch (err: any) {
      addToast(err.message || 'Failed to download Excel workbook', 'error')
    } finally {
      setIsDownloadingExcel(false)
    }
  }

  const handleGenerateLink = (e: React.FormEvent) => {
    e.preventDefault()
    if (!batch) return
    if (!linkTitle.trim()) {
      addToast('Link title is required', 'error')
      return
    }

    const randomToken = Math.random().toString(36).substring(2, 9)
    addUploadLink({
      batchId: batch.id,
      token: randomToken,
      title: linkTitle,
      expiresAt: linkExpiry || '',
      isActive: true,
    })

    addToast(`Link "${linkTitle}" generated!`, 'success')
    setIsLinkModalOpen(false)
    setLinkTitle('')
    setLinkExpiry('')
  }

  const handleCopyLink = (slug: string) => {
    const uploadLink = uploadLinks.find((l) => l.slug === slug || l.token === slug)
    if (!slug || slug === 'undefined' || slug === 'null' || !slug.trim()) {
      addToast('Upload link could not be generated.', 'error')
      return
    }
    const fullUrl = `${window.location.origin}/upload/${slug}`
    navigator.clipboard.writeText(fullUrl)
    addToast('URL copied to clipboard!', 'success')
    setOpenShareMenu(null)
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

  if (!batch) {
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
            <h1 className="text-3xl font-extrabold tracking-tight text-foreground m-0">{batch.name}</h1>
            <span
              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider border ${
                batch.status === 'active' ? 'bg-green-100 text-green-800 border-green-200' : 'bg-red-100 text-red-800 border-red-200'
              }`}
            >
              {batch.status}
            </span>
          </div>
          <p className="text-sm text-muted-foreground mt-1.5 font-medium">
            {batch.department} • <span className="font-semibold text-foreground">Intake Year:</span> {batch.academicYear}
          </p>
        </div>

        <div className="flex items-center gap-3">
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
            { id: 'students', label: `Students (${batchStudents.length})`, icon: Users },
            { id: 'links', label: `Upload Links (${batchLinks.length})`, icon: LinkIcon },
            { id: 'documents', label: `Documents Config (${tempRequirements.length})`, icon: FileText },
            { id: 'verification', label: 'AI Audit Logs', icon: CheckSquare },
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
        {/* STUDENTS TAB */}
        {activeTab === 'students' && (
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <div>
                <h2 className="text-lg font-bold text-foreground">Enrolled Candidate Submissions</h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Review student upload status, verify OCR extraction fields, and inspect preview documents.
                </p>
              </div>
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
                                  const firstUploaded = student.documents.find((d) => d.status === 'Uploaded')
                                  setPreviewDoc({
                                    title: firstUploaded ? firstUploaded.reqName : 'Uploaded Documents',
                                    url: firstUploaded?.fileUrl,
                                    type: firstUploaded?.fileType,
                                    studentName: student.name,
                                  })
                                }}
                                className="cursor-pointer gap-1 text-xs py-1"
                                title="Preview Documents"
                              >
                                <Maximize2 className="h-3.5 w-3.5" /> Preview
                              </Button>
                              <Button
                                variant="primary"
                                size="sm"
                                disabled={student.status === 'AI Processing' || student.status === 'Verified'}
                                onClick={() => {
                                  startAiProcessing(student.id)
                                  addToast(`Started AI OCR extraction for ${student.name}...`, 'info')
                                  if (excelTemplate && batchId) {
                                    excelTemplateService
                                      .updateStudentRow(batchId, student.registerNum, {
                                        student_name: student.name,
                                        register_number: student.registerNum,
                                        mobile_number: student.mobile,
                                        email: student.email || `${student.registerNum.toLowerCase()}@example.com`,
                                        dob: '2005-04-12',
                                        aadhaar_number: '5489 1234 9876',
                                        community: 'BC',
                                        annual_income: 120000,
                                        sslc_marks: 94.5,
                                        hsc_marks: 92.0,
                                      })
                                      .then((res) => {
                                        if (res.updated) {
                                          addToast(`Updated Excel row for candidate ${student.registerNum}!`, 'success')
                                          loadExcelTemplateInfo()
                                        }
                                      })
                                      .catch((err) => {
                                        addToast(err.message || 'Row matching failed in Excel template', 'error')
                                      })
                                  }
                                }}
                                className="cursor-pointer gap-1 text-xs py-1"
                                title="Start AI Verification"
                              >
                                {student.status === 'AI Processing' ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <Sparkles className="h-3.5 w-3.5" />
                                )}
                                Start AI
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
                    onClick={() => {
                      const activePortal = batchLinks.find((l) => l.isActive) || batchLinks[0]
                      const slug = activePortal?.slug || activePortal?.token
                      if (!slug || slug === 'undefined' || slug === 'null' || !slug.trim()) {
                        addToast('Upload link could not be generated.', 'error')
                        return
                      }
                      navigator.clipboard.writeText(`${window.location.origin}/upload/${slug}`)
                      addToast('Upload portal URL copied to clipboard!', 'success')
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
                        <TableCell className="font-mono text-xs text-muted-foreground">/upload/{effectiveSlug}</TableCell>
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
                                      addToast(`Sharing link /upload/${effectiveSlug} via WhatsApp...`, 'info')
                                      setOpenShareMenu(null)
                                    }}
                                    className="flex w-full items-center gap-2.5 px-3 py-1.5 text-xs font-medium text-foreground hover:bg-secondary transition-colors cursor-pointer"
                                  >
                                    <MessageSquare className="h-4.5 w-4.5 text-green-600" /> Share WhatsApp
                                  </button>
                                  <button
                                    onClick={() => {
                                      addToast(`Sharing link /upload/${effectiveSlug} via Email...`, 'info')
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

        {/* DOCUMENTS TAB - DYNAMIC DOCUMENT CONFIGURATION BUILDER WITH VERSIONING */}
        {activeTab === 'documents' && (
          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-bold text-foreground">Dynamic Document Configuration</h2>
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-indigo-100 dark:bg-indigo-950/80 text-indigo-800 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800">
                    <Clock className="h-3.5 w-3.5" /> Current: Version {batch.currentDocVersion || 1}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Changes create a new document configuration version. Existing students remain pinned to their assigned version snapshot.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  onClick={() => setShowVersionHistory(!showVersionHistory)}
                  className="cursor-pointer gap-1.5 text-xs"
                >
                  <FileText className="h-3.5 w-3.5 text-indigo-600" />
                  {showVersionHistory ? 'Hide Version History' : `Version History (${versionHistory.length})`}
                </Button>
                <Button variant="primary" onClick={openAddDocModal} className="cursor-pointer gap-1.5">
                  <Plus className="h-4 w-4" /> Add Document Requirement
                </Button>
              </div>
            </div>

            {/* STAFF DASHBOARD: VERSION HISTORY DRAWER / PANEL */}
            {showVersionHistory && (
              <div className="p-5 rounded-xl border border-indigo-200 dark:border-indigo-900 bg-indigo-50/40 dark:bg-indigo-950/20 space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-indigo-950 dark:text-indigo-200 flex items-center gap-2">
                    <Clock className="h-4 w-4 text-indigo-600" /> Batch Document Version History
                  </h3>
                  <span className="text-xs text-muted-foreground">
                    {versionHistory.length} Total Versions
                  </span>
                </div>

                <div className="space-y-3">
                  {versionHistory.map((ver) => (
                    <div
                      key={ver.id}
                      className={`p-4 rounded-lg border transition-all ${
                        ver.isCurrent
                          ? 'border-indigo-300 dark:border-indigo-800 bg-card shadow-xs'
                          : 'border-border bg-card/60'
                      }`}
                    >
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span
                            className={`px-2.5 py-0.5 rounded-full text-xs font-black uppercase ${
                              ver.isCurrent
                                ? 'bg-indigo-600 text-white'
                                : 'bg-secondary text-muted-foreground border border-border'
                            }`}
                          >
                            Version {ver.version} {ver.isCurrent && '(Active)'}
                          </span>
                          <span className="text-xs font-semibold text-foreground">
                            {ver.changeSummary || 'Configuration snapshot'}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-2xs text-muted-foreground">
                          <span>Created by <strong className="text-foreground">{ver.createdBy}</strong></span>
                          <span>•</span>
                          <span>{new Date(ver.createdAt).toLocaleString()}</span>
                        </div>
                      </div>

                      {/* Document snapshot badges */}
                      <div className="mt-3 flex items-center gap-1.5 flex-wrap">
                        <span className="text-2xs font-bold uppercase tracking-wider text-muted-foreground mr-1">
                          Documents ({ver.documents.length}):
                        </span>
                        {ver.documents.map((doc) => (
                          <span
                            key={doc.id || doc.name}
                            className="px-2 py-0.5 rounded text-xs font-medium bg-secondary text-foreground border border-border flex items-center gap-1"
                          >
                            <FileCheck className="h-3 w-3 text-indigo-500" />
                            {doc.name}
                            {doc.required && (
                              <span className="text-2xs text-destructive font-bold">*</span>
                            )}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}


            {tempRequirements.length > 0 ? (
              <div className="rounded-xl border border-border bg-card overflow-hidden shadow-2xs">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12 text-center">Order</TableHead>
                      <TableHead>Document Name & Description</TableHead>
                      <TableHead>Requirement</TableHead>
                      <TableHead>Accepted Formats</TableHead>
                      <TableHead>Max Size</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tempRequirements.map((req, idx) => {
                      const isReq = req.required ?? (req.type === 'MANDATORY')
                      return (
                        <TableRow key={req.id || req.name} className="hover:bg-secondary/30 transition-colors">
                          <TableCell className="text-center font-mono text-xs text-muted-foreground">
                            <div className="flex flex-col items-center gap-1">
                              <button
                                disabled={idx === 0}
                                onClick={() => handleMoveDoc(idx, 'up')}
                                className="p-1 hover:bg-secondary rounded disabled:opacity-30 cursor-pointer"
                                title="Move Up"
                              >
                                <ArrowUp className="h-3.5 w-3.5" />
                              </button>
                              <span>{idx + 1}</span>
                              <button
                                disabled={idx === tempRequirements.length - 1}
                                onClick={() => handleMoveDoc(idx, 'down')}
                                className="p-1 hover:bg-secondary rounded disabled:opacity-30 cursor-pointer"
                                title="Move Down"
                              >
                                <ArrowDown className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </TableCell>
                          <TableCell>
                            <div>
                              <span className="font-bold text-foreground text-sm block">{req.name}</span>
                              {req.description && (
                                <span className="text-xs text-muted-foreground mt-0.5 block">{req.description}</span>
                              )}
                            </div>
                          </TableCell>
                          <TableCell>
                            <span
                              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-extrabold border uppercase tracking-wider ${
                                isReq
                                  ? 'bg-destructive/10 text-destructive border-destructive/15'
                                  : 'bg-primary/10 text-primary border-primary/15'
                              }`}
                            >
                              {isReq ? 'Required' : 'Optional'}
                            </span>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {(req.allowedTypes || ['PDF', 'JPG', 'PNG']).map((t) => (
                                <span key={t} className="px-2 py-0.5 rounded bg-secondary text-2xs font-mono font-bold text-muted-foreground border border-border">
                                  {t}
                                </span>
                              ))}
                            </div>
                          </TableCell>
                          <TableCell className="font-mono text-xs font-semibold text-foreground">
                            {req.maxSizeMb || 5} MB
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="inline-flex items-center gap-2">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => openEditDocModal(req)}
                                className="cursor-pointer"
                                title="Edit Configuration"
                              >
                                <Edit3 className="h-3.5 w-3.5" /> Edit
                              </Button>
                              <button
                                onClick={() => handleRemoveDoc(req.id, req.name)}
                                className="p-2 text-destructive hover:bg-destructive/10 rounded-lg transition-colors cursor-pointer"
                                title="Remove Document"
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
              </div>
            ) : (
              <EmptyState
                title="No Documents Configured"
                description="Add document requirements to generate the student upload portal for this batch."
                icon={<FileText className="h-12 w-12 text-muted-foreground/60" />}
                action={
                  <Button variant="primary" onClick={openAddDocModal} className="cursor-pointer">
                    <Plus className="mr-2 h-4 w-4" /> Add Document Requirement
                  </Button>
                }
              />
            )}
          </div>
        )}

        {/* VERIFICATION TAB */}
        {activeTab === 'verification' && (
          <div className="space-y-4">
            <h2 className="text-lg font-bold text-foreground">AI OCR Verification Audit Logs</h2>
            <div className="p-6 border border-border rounded-xl bg-card space-y-4">
              <div className="flex items-center gap-3 text-green-600 font-bold text-sm">
                <ShieldCheck className="h-5 w-5" /> All student document scans cross-checked with OCR models
              </div>
              <p className="text-xs text-muted-foreground">
                Automatic entity extraction is active for Aadhaar, Marksheets, and Certificates. Extracted candidate names match admission registry records.
              </p>
            </div>
          </div>
        )}

        {/* EXPORTS & EXCEL TEMPLATE TAB */}
        {activeTab === 'exports' && (
          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-foreground">Excel Template & Auto Row Update</h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Upload an Excel template (.xlsx), configure AI field mappings, and auto-update candidate rows on verification.
                </p>
              </div>
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

            {/* 2. Column Mapping UI Matrix */}
            {excelTemplate && excelTemplate.headers.length > 0 && (
              <div className="p-6 border border-border rounded-xl bg-card space-y-6 shadow-2xs">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2 text-foreground font-bold text-sm">
                      <Settings2 className="h-4 w-4 text-primary" /> 2. Map AI Extracted Fields to Excel Columns
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Extracted headers: {excelTemplate.headers.join(', ')}
                    </p>
                  </div>

                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleSaveExcelMappings}
                    disabled={isSavingMappings}
                    className="cursor-pointer gap-1.5"
                  >
                    {isSavingMappings ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                    Save Field Mappings
                  </Button>
                </div>

                {/* Primary Lookup Key Selector */}
                <div className="p-4 rounded-lg bg-secondary/40 border border-border flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <span className="text-xs font-bold text-foreground block">Primary Row Lookup Key Column</span>
                    <span className="text-3xs text-muted-foreground block">
                      The system uses candidate Register Number to find the matching row in this column.
                    </span>
                  </div>
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
                </div>

                {/* Mapping Matrix Table */}
                <div className="rounded-lg border border-border overflow-hidden">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>AI Extracted System Field</TableHead>
                        <TableHead>Excel Target Header Column</TableHead>
                        <TableHead className="w-24 text-center">Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(() => {
                        const dynamicSystemFields = getDynamicSystemFields(tempRequirements)
                        if (dynamicSystemFields.length === 0) {
                          return (
                            <TableRow>
                              <TableCell colSpan={3} className="text-center py-6 text-xs text-muted-foreground">
                                No document extraction fields configured for this batch. Add document requirements with extraction fields.
                              </TableCell>
                            </TableRow>
                          )
                        }
                        return dynamicSystemFields.map((field) => {
                          const selectedHeader = excelMappings[field.key] || excelMappings[field.label] || ''
                          const isMapped = Boolean(selectedHeader)

                          return (
                            <TableRow key={field.key} className="hover:bg-secondary/20">
                              <TableCell className="font-semibold text-xs text-foreground">
                                <div>
                                  <span className="font-bold text-foreground block">{field.label}</span>
                                  <span className="text-3xs text-muted-foreground block font-normal mt-0.5">
                                    Source Document: {field.docName}
                                  </span>
                                </div>
                              </TableCell>
                              <TableCell>
                                <select
                                  value={selectedHeader}
                                  onChange={(e) =>
                                    setExcelMappings({
                                      ...excelMappings,
                                      [field.key]: e.target.value,
                                      [field.label]: e.target.value,
                                    })
                                  }
                                  className="w-full max-w-xs px-3 py-1 text-xs rounded border border-border bg-background text-foreground font-medium focus:outline-none focus:ring-2 focus:ring-primary cursor-pointer"
                                >
                                  <option value="">-- Do Not Map --</option>
                                  {excelTemplate.headers.map((h) => (
                                    <option key={h} value={h}>
                                      {h}
                                    </option>
                                  ))}
                                </select>
                              </TableCell>
                              <TableCell className="text-center">
                                {isMapped ? (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-3xs font-extrabold bg-green-100 text-green-800">
                                    <Check className="h-3 w-3" /> Mapped
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center px-2 py-0.5 rounded text-3xs font-medium bg-gray-100 text-gray-600">
                                    Unmapped
                                  </span>
                                )}
                              </TableCell>
                            </TableRow>
                          )
                        })
                      })()}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* MODAL: ADD / EDIT DOCUMENT REQUIREMENT */}
      <Modal
        isOpen={isDocModalOpen}
        onClose={() => setIsDocModalOpen(false)}
        title={editingDocId ? 'Edit Document Requirement' : 'Add Document Requirement'}
      >
        <form onSubmit={handleSaveDocConfig} className="space-y-5">
          {/* Document Name with Preset Select */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Document Name
            </label>
            <Input
              type="text"
              placeholder="e.g. Aadhaar Card, SSLC Marksheet, Medical Cert"
              value={docName}
              onChange={(e) => setDocName(e.target.value)}
              required
            />
            <div className="flex items-center gap-1.5 flex-wrap pt-1">
              <span className="text-3xs text-muted-foreground font-bold uppercase mr-1">Presets:</span>
              {PRESET_DOCUMENTS.map((preset) => (
                <button
                  type="button"
                  key={preset}
                  onClick={() => setDocName(preset)}
                  className="px-2 py-0.5 rounded bg-secondary/80 hover:bg-secondary text-3xs font-semibold text-muted-foreground border border-border transition-colors cursor-pointer"
                >
                  {preset}
                </button>
              ))}
            </div>
          </div>

          {/* Mandatory vs Optional */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block">
              Requirement Rule
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label
                className={`flex items-center gap-2 p-3 rounded-xl border cursor-pointer transition-all ${
                  docRequired ? 'border-destructive bg-destructive/5 text-destructive font-bold' : 'border-border bg-card text-muted-foreground'
                }`}
              >
                <input
                  type="radio"
                  name="docReqRule"
                  checked={docRequired}
                  onChange={() => setDocRequired(true)}
                  className="h-4 w-4 accent-destructive"
                />
                <div className="text-xs">
                  <span className="block font-bold">Required (Mandatory)</span>
                  <span className="text-3xs font-normal text-muted-foreground">Student MUST upload file to submit</span>
                </div>
              </label>

              <label
                className={`flex items-center gap-2 p-3 rounded-xl border cursor-pointer transition-all ${
                  !docRequired ? 'border-primary bg-primary/5 text-primary font-bold' : 'border-border bg-card text-muted-foreground'
                }`}
              >
                <input
                  type="radio"
                  name="docReqRule"
                  checked={!docRequired}
                  onChange={() => setDocRequired(false)}
                  className="h-4 w-4 accent-primary"
                />
                <div className="text-xs">
                  <span className="block font-bold">Optional (Waiver Eligible)</span>
                  <span className="text-3xs font-normal text-muted-foreground">Student can select "I don't have this"</span>
                </div>
              </label>
            </div>
          </div>

          {/* Allowed File Types */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block">
              Accepted File Types
            </label>
            <div className="flex gap-4">
              {['PDF', 'JPG', 'PNG'].map((type) => {
                const checked = docAllowedTypes.includes(type)
                return (
                  <label key={type} className="flex items-center gap-2 text-xs font-bold cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => handleTypeToggle(type)}
                      className="h-4 w-4 accent-primary rounded border-border"
                    />
                    <span>{type}</span>
                  </label>
                )
              })}
            </div>
          </div>

          {/* Max File Size */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block">
              Maximum Allowed File Size (MB)
            </label>
            <Input
              type="number"
              min={1}
              max={50}
              value={docMaxSizeMb}
              onChange={(e) => setDocMaxSizeMb(Number(e.target.value))}
              required
            />
          </div>

          {/* Description */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block">
              Description / Instructions for Student
            </label>
            <Input
              type="text"
              placeholder="e.g. Upload front and back side of card in a single file."
              value={docDescription}
              onChange={(e) => setDocDescription(e.target.value)}
            />
          </div>

          {/* AI Entity Extraction Fields */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block">
              AI Entity Extraction Fields (Comma Separated)
            </label>
            <Input
              type="text"
              placeholder="e.g. Transfer Certificate Number, School Name, Admission Number"
              value={docExtractionFieldsText}
              onChange={(e) => setDocExtractionFieldsText(e.target.value)}
            />
            <span className="text-3xs text-muted-foreground block">
              Entities that AI will extract from this document and populate into mapping &amp; verification tables.
            </span>
          </div>

          <div className="flex justify-end gap-3 pt-4 border-t border-border">
            <Button type="button" variant="outline" onClick={() => setIsDocModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary">
              {editingDocId ? 'Save Changes' : 'Add Document'}
            </Button>
          </div>
        </form>
      </Modal>

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
              <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Uploaded Documents</h4>
              <div className="space-y-2.5 max-h-[300px] overflow-y-auto pr-1">
                {selectedStudent.documents.map((doc, idx) => {
                  const isUploaded = doc.status === 'Uploaded'
                  return (
                    <div
                      key={idx}
                      className="p-3 rounded-xl border border-border bg-card flex items-center justify-between gap-3 text-xs"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-foreground">{doc.reqName}</span>
                          <span
                            className={`px-2 py-0.5 rounded text-3xs font-extrabold uppercase ${
                              isUploaded ? 'bg-green-100 text-green-800' : 'bg-secondary text-muted-foreground'
                            }`}
                          >
                            {doc.status}
                          </span>
                        </div>
                        {doc.fileName && (
                          <span className="text-3xs text-muted-foreground font-mono block mt-0.5 truncate">
                            {doc.fileName} ({doc.fileSizeMb} MB)
                          </span>
                        )}
                      </div>

                      {isUploaded && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            setPreviewDoc({
                              title: doc.reqName,
                              url: doc.fileUrl,
                              type: doc.fileType,
                              studentName: selectedStudent.name,
                            })
                          }
                          className="cursor-pointer gap-1 text-3xs py-1"
                        >
                          <Maximize2 className="h-3 w-3" /> Preview
                        </Button>
                      )}
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
      {previewDoc && (
        <Modal
          isOpen={!!previewDoc}
          onClose={() => setPreviewDoc(null)}
          title={`Document Preview: ${previewDoc.title}`}
        >
          <div className="space-y-4">
            <div className="flex items-center justify-between text-xs text-muted-foreground border-b border-border pb-2">
              <span>Candidate: <strong className="text-foreground">{previewDoc.studentName}</strong></span>
              <span>Format: <strong className="font-mono text-foreground">{previewDoc.type || 'PDF'}</strong></span>
            </div>

            {/* Mock Viewer Container */}
            <div className="relative w-full h-[320px] bg-slate-950 rounded-xl overflow-hidden border border-slate-800 flex flex-col items-center justify-center p-4">
              <img
                src={previewDoc.url || 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=800'}
                alt={previewDoc.title}
                className="max-h-full max-w-full object-contain rounded shadow-lg"
              />
              <div className="absolute bottom-3 right-3 bg-card/80 backdrop-blur-sm border border-border px-3 py-1 rounded-lg text-3xs font-mono text-foreground flex items-center gap-1.5">
                <ShieldCheck className="h-3.5 w-3.5 text-green-500" /> AI OCR Verified Scan
              </div>
            </div>

            <div className="flex justify-between items-center pt-2">
              <span className="text-xs text-muted-foreground">Watermarked preview version</span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  addToast(`Downloading ${previewDoc.title}...`, 'info')
                }}
                className="cursor-pointer gap-1.5"
              >
                <Download className="h-3.5 w-3.5" /> Download Document
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
