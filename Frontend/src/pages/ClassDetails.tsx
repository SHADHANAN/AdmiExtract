import React, { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useBatchStore } from '../store/useBatchStore'
import { useStudentStore } from '../store/useStudentStore'
import { useToastStore } from '../store/useToastStore'
import { batchClassService } from '../services/batchClass'
import { excelTemplateService, type ExcelTemplateResponse } from '../services/excelTemplate'
<<<<<<< HEAD
import type { BatchClass, StudentSubmission, UploadLink } from '../types'
=======
import type { BatchClass, DocumentRequirement, StudentSubmission, UploadLink } from '../types'
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Modal } from '../components/ui/Modal'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../components/ui/Table'
import { EmptyState } from '../components/ui/EmptyState'
import {
  ArrowLeft,
  Users,
  Link as LinkIcon,
<<<<<<< HEAD
=======
  FileText,
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
  FileSpreadsheet,
  CheckSquare,
  Download,
  Plus,
  Copy,
  Loader2,
  Eye,
  Upload,
  Settings,
  Maximize2,
  QrCode,
  Trash2,
  ToggleLeft,
  ToggleRight,
  RefreshCw,
<<<<<<< HEAD
=======
  Layers,
  Info,
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
} from 'lucide-react'

export const ClassDetails: React.FC = () => {
  const { classId } = useParams<{ classId: string }>()
  const navigate = useNavigate()
  const { batches, uploadLinks, addUploadLink, fetchUploadLinks, toggleUploadLink, deleteUploadLink } = useBatchStore()
  const { submissions, fetchSubmissionsByBatch } = useStudentStore()
  const { addToast } = useToastStore()

  const [classDoc, setClassDoc] = useState<BatchClass | null>(null)
  const [isLoadingClass, setIsLoadingClass] = useState(true)

  // Active Tab state — Class Dashboard Navigation
  const [activeTab, setActiveTab] = useState<'students' | 'links' | 'submissions' | 'exports' | 'settings'>('students')

  // Excel template states
  const [excelTemplate, setExcelTemplate] = useState<ExcelTemplateResponse | null>(null)
  const [isUploadingExcel, setIsUploadingExcel] = useState(false)
  const [, setExcelMappings] = useState<Record<string, string>>({})
  const [, setLookupColumn] = useState<string>('Reg No')
  const [isDownloadingExcel, setIsDownloadingExcel] = useState(false)

<<<<<<< HEAD
=======
  // Document requirement states for this class
  const [requirements] = useState<DocumentRequirement[]>([
    { id: 'req_1', name: 'Aadhaar Card', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, type: 'MANDATORY' },
    { id: 'req_2', name: 'SSLC Marksheet', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, type: 'MANDATORY' },
    { id: 'req_3', name: 'HSC Marksheet', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, type: 'MANDATORY' },
    { id: 'req_4', name: 'Community Certificate', required: false, allowedTypes: ['PDF', 'JPG'], maxSizeMb: 5, type: 'OPTIONAL' },
  ])

>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
  // Class settings edit states
  const [editClassName, setEditClassName] = useState('')
  const [editSection, setEditSection] = useState('')

  // Upload Link Modal states
  const [isLinkModalOpen, setIsLinkModalOpen] = useState(false)
  const [linkTitle, setLinkTitle] = useState('Section Upload Portal')
  const [linkExpiry, setLinkExpiry] = useState('')
  const [isGeneratingLink, setIsGeneratingLink] = useState(false)
  const [qrModalLink, setQrModalLink] = useState<UploadLink | null>(null)
  const [, setSelectedStudent] = useState<StudentSubmission | null>(null)
  const [, setPreviewDoc] = useState<{ title: string; url?: string; type?: string; studentName?: string } | null>(null)

  // Fetch Class details from backend
  const loadClass = useCallback(async () => {
    if (!classId) return
    setIsLoadingClass(true)
    try {
      const cls = await batchClassService.getClassById(classId)
      setClassDoc(cls)
      setEditClassName(cls.class_name)
      setEditSection(cls.section)
      if (cls.batch_id) {
        fetchSubmissionsByBatch(cls.batch_id)
      }
    } catch {
      addToast('Class details could not be loaded.', 'error')
    } finally {
      setIsLoadingClass(false)
    }
  }, [classId, fetchSubmissionsByBatch, addToast])

  // Fetch Excel template for class
  const loadExcelTemplateInfo = useCallback(async () => {
    if (classDoc?.batch_id && classId) {
      const data = await excelTemplateService.getTemplate(classDoc.batch_id, classId)
      if (data) {
        setExcelTemplate(data)
        setExcelMappings(data.field_mappings || {})
        setLookupColumn(data.lookup_column || (data.headers[0] || 'Reg No'))
      }
    }
  }, [classDoc?.batch_id, classId])

  useEffect(() => {
    loadClass()
  }, [loadClass])

  useEffect(() => {
    if (classDoc) {
      loadExcelTemplateInfo()
    }
  }, [classDoc, loadExcelTemplateInfo])

  // Filter items STRICTLY for this class (Section A)
  const parentBatch = batches.find((b) => b.id === classDoc?.batch_id)
  const classStudents = submissions.filter((s) => {
    if (s.classId) return s.classId === classId
    if (classDoc && s.batchId === classDoc.batch_id && s.className === classDoc.class_name) return true
    return false
  })
  const classLinks = uploadLinks.filter((l) => l.class_id === classId || (classDoc && l.batchId === classDoc.batch_id))

  // Handlers
  const handleExcelUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!classDoc || !e.target.files || e.target.files.length === 0) return
    const file = e.target.files[0]
    if (!file.name.toLowerCase().endsWith('.xlsx')) {
      addToast('Only .xlsx format Excel files are allowed.', 'error')
      return
    }
    setIsUploadingExcel(true)
    try {
      const res = await excelTemplateService.uploadTemplate(classDoc.batch_id, file, classId)
      setExcelTemplate(res)
      setExcelMappings(res.field_mappings || {})
      setLookupColumn(res.lookup_column || (res.headers[0] || 'Reg No'))
      addToast(`Excel template "${file.name}" uploaded for ${classDoc.class_name}!`, 'success')
    } catch (err: any) {
      addToast(err.message || 'Failed to upload Excel template', 'error')
    } finally {
      setIsUploadingExcel(false)
    }
  }

  const handleDownloadExcel = async () => {
    if (!classDoc || !classId) return
    setIsDownloadingExcel(true)
    try {
      await excelTemplateService.downloadExcel(classDoc.batch_id, excelTemplate?.template_filename, classId)
      addToast(`Downloaded Excel workbook for ${classDoc.class_name}!`, 'success')
    } catch (err: any) {
      addToast(err.message || 'Failed to download Excel workbook', 'error')
    } finally {
      setIsDownloadingExcel(false)
    }
  }

  const handleGenerateLink = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!classDoc) return
    if (!linkTitle.trim()) {
      addToast('Link title is required', 'error')
      return
    }
    setIsGeneratingLink(true)
    try {
      await addUploadLink({
        batchId: classDoc.batch_id,
        class_id: classId,
        token: Math.random().toString(36).substring(2, 9),
        title: linkTitle,
        expiresAt: linkExpiry || '',
        isActive: true,
      })
      await fetchUploadLinks()
      addToast(`Upload link generated specifically for ${classDoc.class_name}!`, 'success')
      setIsLinkModalOpen(false)
      setLinkTitle('')
      setLinkExpiry('')
    } catch (err: any) {
      addToast(err?.message || 'Failed to generate upload link', 'error')
    } finally {
      setIsGeneratingLink(false)
    }
  }

  const handleCopyLink = (slug: string) => {
    const fullUrl = `${window.location.origin}/upload/${slug}`
    navigator.clipboard.writeText(fullUrl)
    addToast('Section Portal URL copied to clipboard!', 'success')
  }

  if (isLoadingClass) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 text-primary animate-spin" />
        <span className="ml-3 text-sm text-muted-foreground font-semibold">Loading Section Workspace...</span>
      </div>
    )
  }

  if (!classDoc) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" onClick={() => navigate('/batches')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Batches
        </Button>
        <EmptyState
          title="Section Not Found"
          description="The class or section specified does not exist or has been removed."
          icon={<ArrowLeft className="h-12 w-12 text-muted-foreground/60" />}
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Hierarchy Navigation Breadcrumb: Dashboard -> Batch -> Department -> Section */}
      <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground">
        <button onClick={() => navigate('/dashboard')} className="hover:text-foreground cursor-pointer">Dashboard</button>
        <span>→</span>
        <button onClick={() => navigate('/batches')} className="hover:text-foreground cursor-pointer">Batch</button>
        <span>→</span>
        <button onClick={() => navigate(`/batches/${classDoc.batch_id}`)} className="hover:text-foreground cursor-pointer">
          {parentBatch ? parentBatch.name : 'Batch'}
        </button>
        <span>→</span>
        <span className="text-foreground font-bold">{classDoc.department}</span>
        <span>→</span>
        <span className="text-primary font-bold">{classDoc.class_name}</span>
      </div>

      {/* Class Workspace Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between border-b border-border pb-6 gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-extrabold tracking-tight text-foreground m-0">{classDoc.class_name}</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-primary/10 text-primary border border-primary/20">
              Section {classDoc.section}
            </span>
          </div>
          <p className="text-sm text-muted-foreground mt-1.5 font-medium">
            Batch: <strong className="text-foreground">{parentBatch?.name || 'Batch'}</strong> • Department: <strong className="text-foreground">{classDoc.department}</strong> • Class: <strong className="text-foreground">{classDoc.class_name}</strong>
          </p>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          <Button variant="outline" size="sm" onClick={() => setIsLinkModalOpen(true)} className="cursor-pointer gap-1.5 text-xs">
            <Plus className="h-4 w-4" /> Generate Section Link
          </Button>
          <Button variant="outline" size="sm" onClick={() => setActiveTab('exports')} className="cursor-pointer gap-1.5 text-xs">
            <FileSpreadsheet className="h-4 w-4 text-emerald-600" /> Export Data
          </Button>
        </div>
      </div>

      {/* Class Dashboard Navigation Tabs */}
      <div className="flex border-b border-border gap-1 overflow-x-auto">
        {(
          [
            { id: 'students', label: `Students (${classStudents.length})`, icon: Users },
            { id: 'links', label: `Upload Link (${classLinks.length})`, icon: LinkIcon },
            { id: 'submissions', label: `Enrolled Candidate Submissions (${classStudents.length})`, icon: CheckSquare },
            { id: 'exports', label: 'Export', icon: Download },
            { id: 'settings', label: 'Settings', icon: Settings },
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

      {/* Tab Content Renderer */}
      <div className="py-2">
        {/* 1. STUDENTS TAB */}
        {activeTab === 'students' && (
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <div>
                <h2 className="text-lg font-bold text-foreground">Students in {classDoc.class_name}</h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Student roster isolated strictly to {classDoc.class_name} ({classDoc.department}).
                </p>
              </div>
            </div>

            {classStudents.length > 0 ? (
              <div className="rounded-xl border border-border bg-card overflow-hidden shadow-2xs">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Register No</TableHead>
                      <TableHead>Student Name</TableHead>
                      <TableHead>Contact Mobile</TableHead>
                      <TableHead>Uploaded Documents</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {classStudents.map((student) => {
                      const uploadedDocs = student.documents.filter((d) => d.status === 'Uploaded').length
                      return (
                        <TableRow key={student.id} className="hover:bg-secondary/30 transition-colors">
                          <TableCell className="font-mono text-xs font-bold text-foreground">{student.registerNum}</TableCell>
                          <TableCell className="font-semibold text-foreground">{student.name}</TableCell>
                          <TableCell className="text-xs text-muted-foreground">{student.mobile}</TableCell>
                          <TableCell className="text-xs font-bold text-foreground">{uploadedDocs} Files</TableCell>
                          <TableCell>
                            <span
                              className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold ${
                                student.status === 'Verified'
                                  ? 'bg-green-100 text-green-800 border border-green-200'
                                  : student.status === 'Rejected'
                                  ? 'bg-red-100 text-red-800 border border-red-200'
                                  : 'bg-blue-100 text-blue-800 border border-blue-200'
                              }`}
                            >
                              {student.status}
                            </span>
                          </TableCell>
                          <TableCell className="text-right">
                            <Button variant="outline" size="sm" onClick={() => setSelectedStudent(student)} className="cursor-pointer text-xs">
                              <Eye className="h-3.5 w-3.5 mr-1" /> View Profile
                            </Button>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <EmptyState
                title="No Students Enrolled"
                description={`No students have submitted documents for ${classDoc.class_name} yet.`}
                icon={<Users className="h-12 w-12 text-muted-foreground/60" />}
              />
            )}
          </div>
        )}

        {/* 2. UPLOAD LINK TAB */}
        {activeTab === 'links' && (
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <div>
                <h2 className="text-lg font-bold text-foreground">Upload Link ({classDoc.class_name})</h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Students opening this link will automatically submit documents ONLY to {classDoc.class_name}.
                </p>
              </div>
              <Button variant="primary" onClick={() => setIsLinkModalOpen(true)} className="cursor-pointer">
                <Plus className="mr-2 h-4 w-4" /> Generate Section Link
              </Button>
            </div>

            {classLinks.length > 0 ? (
              <div className="rounded-xl border border-border bg-card overflow-hidden shadow-2xs">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Portal Name</TableHead>
                      <TableHead>Target Class</TableHead>
                      <TableHead>Tokenized Link</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {classLinks.map((link) => {
                      const slug = link.slug || link.token
                      return (
                        <TableRow key={link.id}>
                          <TableCell className="font-semibold text-foreground">{link.title}</TableCell>
                          <TableCell className="text-xs font-bold text-primary">{classDoc.class_name}</TableCell>
                          <TableCell className="font-mono text-xs text-muted-foreground">/upload/{slug}</TableCell>
                          <TableCell>
                            <span
                              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold ${
                                link.isActive ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
                              }`}
                            >
                              {link.isActive ? 'Active' : 'Disabled'}
                            </span>
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="inline-flex items-center gap-2">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => handleCopyLink(slug)}
                                className="cursor-pointer gap-1 text-xs"
                                title="Copy Portal URL"
                              >
                                <Copy className="h-3.5 w-3.5" /> Copy URL
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setQrModalLink(link)}
                                className="cursor-pointer gap-1 text-xs"
                                title="Show QR Code"
                              >
                                <QrCode className="h-3.5 w-3.5" /> QR Code
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={async () => {
                                  await toggleUploadLink(link.id)
                                  await fetchUploadLinks()
                                  addToast(`Link ${link.isActive ? 'disabled' : 'activated'}`, 'info')
                                }}
                                title={link.isActive ? 'Disable Link' : 'Enable Link'}
                                className="cursor-pointer p-1.5"
                              >
                                {link.isActive ? <ToggleRight className="h-5 w-5 text-primary" /> : <ToggleLeft className="h-5 w-5" />}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={async () => {
                                  if (window.confirm('Regenerate upload link? Existing tokens will be replaced.')) {
                                    await addUploadLink({
                                      batchId: classDoc.batch_id,
                                      class_id: classId,
                                      token: Math.random().toString(36).substring(2, 9),
                                      title: link.title,
                                      expiresAt: link.expiresAt || '',
                                      isActive: true,
                                    })
                                    await fetchUploadLinks()
                                    addToast('Upload link regenerated successfully!', 'success')
                                  }
                                }}
                                title="Regenerate Link"
                                className="cursor-pointer p-1.5 text-muted-foreground hover:text-foreground"
                              >
                                <RefreshCw className="h-4 w-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={async () => {
                                  if (window.confirm(`Delete upload link "${link.title}"?`)) {
                                    await deleteUploadLink(link.id)
                                    await fetchUploadLinks()
                                    addToast('Upload link deleted successfully!', 'success')
                                  }
                                }}
                                title="Delete Link"
                                className="cursor-pointer p-1.5 text-destructive hover:bg-destructive/10"
                              >
                                <Trash2 className="h-4 w-4" />
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
                title="No Upload Link Generated"
                description={`Generate an upload link allowing student submissions specifically for ${classDoc.class_name}.`}
                icon={<LinkIcon className="h-12 w-12 text-muted-foreground/60" />}
              />
            )}
          </div>
        )}



        {/* 4. ENROLLED CANDIDATE SUBMISSIONS TAB */}
        {activeTab === 'submissions' && (
          <div className="space-y-4">
            {/* Metadata Section Header */}
            <div className="p-4 rounded-xl border border-border bg-card space-y-1">
              <div className="grid grid-cols-3 gap-4 text-xs font-semibold">
                <div>
                  <span className="text-muted-foreground block">Batch:</span>
                  <span className="text-foreground font-bold text-sm">{parentBatch?.name || 'Batch'}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block">Department:</span>
                  <span className="text-foreground font-bold text-sm">{classDoc.department}</span>
                </div>
                <div>
                  <span className="text-muted-foreground block">Class / Section:</span>
                  <span className="text-primary font-bold text-sm">{classDoc.class_name}</span>
                </div>
              </div>
            </div>

            <div className="flex justify-between items-center">
              <div>
                <h2 className="text-lg font-bold text-foreground">Enrolled Candidate Submissions</h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Displaying ONLY students belonging to {classDoc.class_name}.
                </p>
              </div>
            </div>

            {classStudents.length > 0 ? (
              <div className="rounded-xl border border-border bg-card overflow-hidden shadow-2xs">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Register No</TableHead>
                      <TableHead>Student Name</TableHead>
                      <TableHead className="text-center">Submitted</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {classStudents.map((student) => {
                      const isSubmitted = student.documents.some((d) => d.status === 'Uploaded') || student.status !== 'Pending'
                      return (
                        <TableRow key={student.id} className="hover:bg-secondary/30 transition-colors">
                          <TableCell className="font-mono text-xs font-bold text-foreground">{student.registerNum}</TableCell>
                          <TableCell className="font-semibold text-foreground">{student.name}</TableCell>
                          <TableCell className="text-center">
                            {isSubmitted ? (
                              <span className="inline-flex items-center text-green-600 font-bold text-sm">✓</span>
                            ) : (
                              <span className="text-xs text-muted-foreground">-</span>
                            )}
                          </TableCell>
                          <TableCell>
                            <span
                              className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold ${
                                student.status === 'Verified'
                                  ? 'bg-green-100 text-green-800 border border-green-200'
                                  : student.status === 'Rejected'
                                  ? 'bg-red-100 text-red-800 border border-red-200'
                                  : 'bg-amber-100 text-amber-800 border border-amber-200'
                              }`}
                            >
                              {student.status}
                            </span>
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="inline-flex items-center gap-1.5 justify-end">
                              <Button variant="outline" size="sm" onClick={() => setSelectedStudent(student)} className="cursor-pointer text-xs py-1">
                                <Eye className="h-3.5 w-3.5 mr-1" /> View
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
                                className="cursor-pointer text-xs py-1"
                              >
                                <Maximize2 className="h-3.5 w-3.5 mr-1" /> Preview
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
                title="No Submissions Found"
                description={`No candidate submissions received for ${classDoc.class_name} yet.`}
                icon={<CheckSquare className="h-12 w-12 text-muted-foreground/60" />}
              />
            )}
          </div>
        )}

        {/* 5. EXPORT TAB */}
        {activeTab === 'exports' && (
          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-foreground">Export Class Data ({classDoc.class_name})</h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Export verified student submissions and mapped Excel workbooks strictly for {classDoc.class_name}.
                </p>
              </div>
              <Button variant="primary" onClick={handleDownloadExcel} disabled={isDownloadingExcel} className="cursor-pointer gap-2">
                {isDownloadingExcel ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                Download Export (.xlsx)
              </Button>
            </div>

            {/* Template Status */}
            <div className="p-6 border border-border rounded-xl bg-card space-y-4 shadow-2xs">
              <div className="flex items-center gap-2 text-foreground font-bold text-sm">
                <Upload className="h-4 w-4 text-primary" /> Upload Excel Template for {classDoc.class_name}
              </div>
              <div className="border-2 border-dashed border-border hover:border-primary/50 rounded-xl p-6 text-center transition-colors bg-secondary/20">
                <input type="file" id="class-excel-upload" accept=".xlsx" onChange={handleExcelUpload} className="hidden" />
                <label htmlFor="class-excel-upload" className="cursor-pointer flex flex-col items-center gap-2">
                  {isUploadingExcel ? <Loader2 className="h-8 w-8 text-primary animate-spin" /> : <FileSpreadsheet className="h-8 w-8 text-primary" />}
                  <div>
                    <span className="font-bold text-sm text-foreground block">
                      {excelTemplate ? `Replace "${excelTemplate.template_filename}"` : 'Click to Upload admission.xlsx'}
                    </span>
                    <span className="text-xs text-muted-foreground mt-0.5 block">
                      Excel template will be bound to class ID {classId}.
                    </span>
                  </div>
                </label>
              </div>
            </div>
          </div>
        )}

        {/* 6. SETTINGS TAB */}
        {activeTab === 'settings' && (
          <div className="space-y-4">
            <h2 className="text-lg font-bold text-foreground">Class & Section Settings</h2>
            <div className="p-6 border border-border rounded-xl bg-card space-y-4 max-w-xl">
              <Input
                label="Class / Section Name"
                type="text"
                value={editClassName}
                onChange={(e) => setEditClassName(e.target.value)}
              />
              <Input
                label="Section Code"
                type="text"
                value={editSection}
                onChange={(e) => setEditSection(e.target.value)}
              />
              <Button
                variant="primary"
                onClick={async () => {
                  try {
                    await batchClassService.updateClass(classId!, {
                      class_name: editClassName,
                      section: editSection,
                    })
                    addToast('Class settings updated successfully!', 'success')
                    loadClass()
                  } catch (err: any) {
                    addToast(err.message || 'Failed to update settings', 'error')
                  }
                }}
                className="cursor-pointer"
              >
                Save Settings
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* MODAL: GENERATE PORTAL LINK */}
      <Modal isOpen={isLinkModalOpen} onClose={() => setIsLinkModalOpen(false)} title={`Generate Portal Link for ${classDoc.class_name}`}>
        <form onSubmit={handleGenerateLink} className="space-y-4">
          <Input
            label="Portal Name"
            type="text"
            placeholder={`e.g. ${classDoc.class_name} Document Portal`}
            value={linkTitle}
            onChange={(e) => setLinkTitle(e.target.value)}
            required
          />
          <Input label="Link Expiry Date" type="date" value={linkExpiry} onChange={(e) => setLinkExpiry(e.target.value)} />
          <div className="flex justify-end gap-3 pt-4 border-t border-border">
            <Button type="button" variant="outline" onClick={() => setIsLinkModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={isGeneratingLink}>
              {isGeneratingLink ? 'Generating...' : 'Generate Link'}
            </Button>
          </div>
        </form>
      </Modal>

      {/* MODAL: QR CODE */}
      <Modal isOpen={Boolean(qrModalLink)} onClose={() => setQrModalLink(null)} title={`QR Code: ${qrModalLink?.title || 'Upload Link'}`}>
        {qrModalLink && (
          <div className="flex flex-col items-center justify-center p-4 space-y-4 text-center">
            <div className="p-3 bg-white border border-border rounded-xl shadow-md">
              <img
                src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(`${window.location.origin}/upload/${qrModalLink.slug || qrModalLink.token}`)}`}
                alt="QR Code"
                className="w-48 h-48 object-contain"
              />
            </div>
            <p className="font-mono text-xs text-muted-foreground break-all max-w-sm">
              {`${window.location.origin}/upload/${qrModalLink.slug || qrModalLink.token}`}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  navigator.clipboard.writeText(`${window.location.origin}/upload/${qrModalLink.slug || qrModalLink.token}`)
                  addToast('URL copied to clipboard!', 'success')
                }}
              >
                <Copy className="h-4 w-4 mr-1" /> Copy URL
              </Button>
              <Button variant="primary" size="sm" onClick={() => setQrModalLink(null)}>
                Close
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
