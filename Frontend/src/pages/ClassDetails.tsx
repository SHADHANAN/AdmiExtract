import React, { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useBatchStore } from '../store/useBatchStore'
import { useToastStore } from '../store/useToastStore'
import { batchClassService } from '../services/batchClass'
import { excelTemplateService } from '../services/excelTemplate'
import { copyToClipboard } from '../utils/clipboard'
import { getStudentUploadUrl } from '../utils/studentPortalUrl'
import type { BatchClass, UploadLink } from '../types'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Modal } from '../components/ui/Modal'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../components/ui/Table'
import { EmptyState } from '../components/ui/EmptyState'
import { DocumentPreviewModal, type DocumentPreviewTarget } from '../components/ui/DocumentPreviewModal'
import { DeleteStudentModal, type DeleteStudentTarget } from '../components/ui/DeleteStudentModal'
import { useAuthStore } from '../store/useAuthStore'
import { studentSubmissionService } from '../services/studentSubmission'
import {
  ArrowLeft,
  Users,
  Link as LinkIcon,
  FileSpreadsheet,
  CheckSquare,
  Download,
  Plus,
  Copy,
  Loader2,
  Eye,
  Settings,
  Maximize2,
  QrCode,
  Trash2,
  ToggleLeft,
  ToggleRight,
  RefreshCw,
  FileText,
  ArrowRight,
} from 'lucide-react'

export const ClassDetails: React.FC = () => {
  const { classId } = useParams<{ classId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { batches, addUploadLink, toggleUploadLink, deleteUploadLink } = useBatchStore()
  const { addToast } = useToastStore()
  const { user } = useAuthStore()

  // Authorized Staff/Admin check - students cannot delete
  const canDeleteStudent = user?.role === 'super_admin' || user?.role === 'department_admin'

  const [classDoc, setClassDoc] = useState<BatchClass | null>(null)
  const [isLoadingClass, setIsLoadingClass] = useState(true)
  const [deleteStudentTarget, setDeleteStudentTarget] = useState<DeleteStudentTarget | null>(null)

  // TanStack queries for server-isolated section students & upload links
  const {
    data: classStudents = [],
    isLoading: isLoadingStudents,
    refetch: refetchStudents,
  } = useQuery({
    queryKey: ['section-students', classId],
    queryFn: () => (classId ? batchClassService.getClassStudents(classId) : Promise.resolve([])),
    enabled: !!classId,
  })

  const {
    data: classLinks = [],
    isLoading: isLoadingLinks,
    refetch: refetchLinks,
  } = useQuery({
    queryKey: ['section-upload-links', classId],
    queryFn: () => (classId ? batchClassService.getClassUploadLinks(classId) : Promise.resolve([])),
    enabled: !!classId,
  })

  // Active Tab state — Class Dashboard Navigation
  const [activeTab, setActiveTab] = useState<'students' | 'links' | 'submissions' | 'exports' | 'settings'>('students')

  // Excel export state
  const [isDownloadingExcel, setIsDownloadingExcel] = useState(false)

  // Class settings edit states
  const [editClassName, setEditClassName] = useState('')
  const [editSection, setEditSection] = useState('')

  // Upload Link Modal states
  const [isLinkModalOpen, setIsLinkModalOpen] = useState(false)
  const [linkTitle, setLinkTitle] = useState('Section Upload Portal')
  const [linkExpiry, setLinkExpiry] = useState('')
  const [isGeneratingLink, setIsGeneratingLink] = useState(false)
  const [qrModalLink, setQrModalLink] = useState<UploadLink | null>(null)
  const [selectedStudent, setSelectedStudent] = useState<any | null>(null)
  const [previewTarget, setPreviewTarget] = useState<DocumentPreviewTarget | null>(null)

  // Handle student deletion
  const handleDeleteStudent = async (target: DeleteStudentTarget) => {
    try {
      await studentSubmissionService.deleteSubmission(target.id, classDoc?.batch_id, classId)
      addToast(`${target.name} has been removed from this section.`, 'success')
      // Refresh section students and counts immediately
      await queryClient.invalidateQueries({ queryKey: ['section-students', classId] })
      await queryClient.invalidateQueries({ queryKey: ['submissions'] })
      if (classDoc?.batch_id) {
        await queryClient.invalidateQueries({ queryKey: ['classes', classDoc.batch_id] })
        await queryClient.invalidateQueries({ queryKey: ['batches'] })
      }
      await refetchStudents()
      setDeleteStudentTarget(null)
    } catch (error: any) {
      const errorMsg =
        error?.response?.data?.detail || error?.message || 'Failed to delete student. No data was removed.'
      addToast(errorMsg, 'error')
      throw error
    }
  }

  // Fetch Class details from backend
  const loadClass = useCallback(async () => {
    if (!classId) return
    setIsLoadingClass(true)
    try {
      const cls = await batchClassService.getClassById(classId)
      setClassDoc(cls)
      setEditClassName(cls.class_name)
      setEditSection(cls.section)
    } catch {
      addToast('Class details could not be loaded.', 'error')
    } finally {
      setIsLoadingClass(false)
    }
  }, [classId, addToast])

  useEffect(() => {
    loadClass()
  }, [loadClass])

  const parentBatch = batches.find((b) => b.id === classDoc?.batch_id)

  const handleDownloadExcel = async () => {
    if (!classDoc || !classId) return
    setIsDownloadingExcel(true)
    try {
      const sectionNameClean = (classDoc.class_name || 'Section').replace(/\s+/g, '_')
      const filename = `${classDoc.batch_id}_${sectionNameClean}_Export.xlsx`
      await excelTemplateService.downloadExcel(classDoc.batch_id, filename, classId)
      addToast(`Downloaded Excel workbook for ${classDoc.class_name}!`, 'success')
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to download Excel workbook', 'error')
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
      queryClient.invalidateQueries({ queryKey: ['section-upload-links', classId] })
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

  const handleCopyLink = async (slug: string) => {
    const fullUrl = getStudentUploadUrl(slug)
    try {
      await copyToClipboard(fullUrl)
      addToast('Section Portal URL copied to clipboard!', 'success')
    } catch (err) {
      console.error('Failed to copy portal URL:', err)
      addToast('Failed to copy link to clipboard.', 'error')
    }
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
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              refetchStudents()
              refetchLinks()
              addToast('Refreshed section data', 'info')
            }}
            className="cursor-pointer gap-1.5 text-xs"
            title="Refresh Section Data"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isLoadingStudents || isLoadingLinks ? 'animate-spin' : ''}`} /> Refresh
          </Button>
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
                      <TableHead>Register Number</TableHead>
                      <TableHead>Student Name</TableHead>
                      <TableHead>Submitted At</TableHead>
                      <TableHead>Documents Uploaded</TableHead>
                      <TableHead>Submission Status</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {classStudents.map((student: any) => {
                      const uploadedDocs = (student.documents || []).filter((d: any) => d.status === 'Uploaded').length
                      const formattedDate = student.submittedAt
                        ? new Date(student.submittedAt).toLocaleString()
                        : 'Pending'
                      return (
                        <TableRow key={student.id} className="hover:bg-secondary/30 transition-colors">
                          <TableCell className="font-mono text-xs font-bold text-foreground">{student.registerNum}</TableCell>
                          <TableCell className="font-semibold text-foreground">{student.studentName || student.name}</TableCell>
                          <TableCell className="text-xs text-muted-foreground">{formattedDate}</TableCell>
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
                              {student.status || 'Pending'}
                            </span>
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-2">
                              <Button variant="outline" size="sm" onClick={() => setSelectedStudent(student)} className="cursor-pointer text-xs">
                                <Eye className="h-3.5 w-3.5 mr-1" /> View Profile
                              </Button>
                              {canDeleteStudent && (
                                <Button
                                  variant="danger"
                                  size="sm"
                                  onClick={() =>
                                    setDeleteStudentTarget({
                                      id: student.id,
                                      name: student.studentName || student.name,
                                      registerNum: student.registerNum,
                                      className: classDoc?.class_name,
                                      documentsCount: (student.documents || []).length,
                                    })
                                  }
                                  className="cursor-pointer text-xs"
                                  title="Delete Student"
                                >
                                  <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete
                                </Button>
                              )}
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
                          <TableCell className="font-mono text-xs text-muted-foreground break-all max-w-[220px] truncate" title={getStudentUploadUrl(slug)}>
                            {getStudentUploadUrl(slug)}
                          </TableCell>
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
                                  queryClient.invalidateQueries({ queryKey: ['section-upload-links', classId] })
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
                                    queryClient.invalidateQueries({ queryKey: ['section-upload-links', classId] })
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
                                    queryClient.invalidateQueries({ queryKey: ['section-upload-links', classId] })
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
                    {classStudents.map((student: any) => {
                      const isSubmitted = (student.documents || []).some((d: any) => d.status === 'Uploaded') || student.status !== 'Pending'
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
                                  const firstUploadedIdx = (student.documents || []).findIndex((d: any) => d.status === 'Uploaded')
                                  if (firstUploadedIdx !== -1) {
                                    const doc = student.documents[firstUploadedIdx]
                                    setPreviewTarget({
                                      submissionId: student.id,
                                      documentIndex: doc.documentIndex !== undefined ? doc.documentIndex : firstUploadedIdx,
                                      documentName: doc.document_name || doc.reqName || 'Document',
                                      fileType: doc.fileType,
                                      fileName: doc.fileName,
                                      studentName: student.name,
                                    })
                                  } else {
                                    addToast('No uploaded documents available for preview.', 'info')
                                  }
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
            <div className="p-6 border border-border rounded-xl bg-card space-y-5 shadow-2xs">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                  <h2 className="text-lg font-bold text-foreground">Export Section Data ({classDoc.class_name})</h2>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Generate and download a dynamic Excel (.xlsx) workbook containing verified student submissions for {classDoc.class_name}.
                  </p>
                </div>
                <Button variant="primary" onClick={handleDownloadExcel} disabled={isDownloadingExcel} className="cursor-pointer gap-2 shrink-0">
                  {isDownloadingExcel ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                  Download Export (.xlsx)
                </Button>
              </div>

              <div className="pt-4 border-t border-border grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs font-semibold">
                <div className="p-3.5 rounded-xl bg-secondary/30 border border-border">
                  <span className="text-muted-foreground block text-[11px]">Enrolled Students</span>
                  <span className="text-foreground font-bold text-base mt-0.5 block">{classStudents.length}</span>
                </div>
                <div className="p-3.5 rounded-xl bg-secondary/30 border border-border">
                  <span className="text-muted-foreground block text-[11px]">Department</span>
                  <span className="text-foreground font-bold text-base mt-0.5 block">{classDoc.department}</span>
                </div>
                <div className="p-3.5 rounded-xl bg-secondary/30 border border-border">
                  <span className="text-muted-foreground block text-[11px]">Export Format</span>
                  <span className="text-foreground font-bold text-base mt-0.5 block">Microsoft Excel (.xlsx)</span>
                </div>
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
                src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(getStudentUploadUrl(qrModalLink.slug || qrModalLink.token))}`}
                alt="QR Code"
                className="w-48 h-48 object-contain"
              />
            </div>
            <p className="font-mono text-xs text-muted-foreground break-all max-w-sm">
              {getStudentUploadUrl(qrModalLink.slug || qrModalLink.token)}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  try {
                    await copyToClipboard(getStudentUploadUrl(qrModalLink.slug || qrModalLink.token))
                    addToast('URL copied to clipboard!', 'success')
                  } catch (err) {
                    console.error('Failed to copy portal URL:', err)
                    addToast('Failed to copy link to clipboard.', 'error')
                  }
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

      {/* MODAL: VIEW STUDENT PROFILE */}
      <Modal isOpen={Boolean(selectedStudent)} onClose={() => setSelectedStudent(null)} title={`Student Profile: ${selectedStudent?.studentName || selectedStudent?.name || ''}`}>
        {selectedStudent && (
          <div className="space-y-4 p-1">
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="p-3 bg-secondary/30 rounded-lg">
                <span className="text-muted-foreground block mb-1">Register Number</span>
                <span className="font-mono font-bold text-foreground text-sm">{selectedStudent.registerNum}</span>
              </div>
              <div className="p-3 bg-secondary/30 rounded-lg">
                <span className="text-muted-foreground block mb-1">Full Name</span>
                <span className="font-semibold text-foreground text-sm">{selectedStudent.studentName || selectedStudent.name}</span>
              </div>
              <div className="p-3 bg-secondary/30 rounded-lg">
                <span className="text-muted-foreground block mb-1">Mobile Number</span>
                <span className="text-foreground">{selectedStudent.mobile || 'N/A'}</span>
              </div>
              <div className="p-3 bg-secondary/30 rounded-lg">
                <span className="text-muted-foreground block mb-1">Email</span>
                <span className="text-foreground">{selectedStudent.email || 'N/A'}</span>
              </div>
              <div className="p-3 bg-secondary/30 rounded-lg">
                <span className="text-muted-foreground block mb-1">Submission Status</span>
                <span className="font-bold text-foreground">{selectedStudent.status || 'Pending'}</span>
              </div>
              <div className="p-3 bg-secondary/30 rounded-lg">
                <span className="text-muted-foreground block mb-1">Submitted At</span>
                <span className="text-foreground">{selectedStudent.submittedAt ? new Date(selectedStudent.submittedAt).toLocaleString() : 'N/A'}</span>
              </div>
            </div>

            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5" />
                Uploaded Documents ({(selectedStudent.documents || []).length})
              </h4>
              <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                {(selectedStudent.documents || []).length > 0 ? (
                  (selectedStudent.documents || []).map((doc: any, i: number) => {
                    const isUploaded = doc.status === 'Uploaded'
                    const docIndex = doc.documentIndex !== undefined ? doc.documentIndex : i
                    const docName = doc.document_name || doc.reqName || 'Document'
                    const canPreview = isUploaded && docIndex !== undefined

                    return (
                      <div
                        key={i}
                        onClick={() => {
                          if (canPreview) {
                            setPreviewTarget({
                              submissionId: selectedStudent.id,
                              documentIndex: docIndex,
                              documentName: docName,
                              fileType: doc.fileType,
                              fileName: doc.fileName,
                              studentName: selectedStudent.studentName || selectedStudent.name,
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
                            <span className="font-bold text-foreground text-xs block truncate">{docName}</span>
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
                                  documentName: docName,
                                  fileType: doc.fileType,
                                  fileName: doc.fileName,
                                  studentName: selectedStudent.studentName || selectedStudent.name,
                                })
                              }}
                              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-slate-950 transition-colors shadow-2xs cursor-pointer"
                              title={`Preview ${docName}`}
                            >
                              <span>Preview</span>
                              <ArrowRight className="h-3 w-3" />
                            </button>
                          )}
                        </div>
                      </div>
                    )
                  })
                ) : (
                  <p className="text-xs text-muted-foreground italic">No documents uploaded.</p>
                )}
              </div>
            </div>

            <div className="flex justify-end pt-3 border-t border-border">
              <Button variant="outline" size="sm" onClick={() => setSelectedStudent(null)}>
                Close
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* MODAL: PREVIEW DOCUMENT */}
      <DocumentPreviewModal
        target={previewTarget}
        onClose={() => setPreviewTarget(null)}
      />

      {/* MODAL: DELETE STUDENT */}
      <DeleteStudentModal
        target={deleteStudentTarget}
        isOpen={!!deleteStudentTarget}
        onClose={() => setDeleteStudentTarget(null)}
        onConfirm={handleDeleteStudent}
      />
    </div>
  )
}
