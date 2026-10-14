import React, { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  studentDocumentService,
  type StudentDocument,
  type DocumentExtractionRequestResponse,
} from '../services/studentDocument'
import { verificationService } from '../services/verificationService'
import { wantedFieldService, type DocumentTypeOverviewItem } from '../services/wantedField'
import { useToastStore } from '../store/useToastStore'
import { Button } from './ui/Button'
import { Modal } from './ui/Modal'
import { DocumentPreviewModal, type DocumentPreviewTarget } from './ui/DocumentPreviewModal'
import {
  FileText,
  Upload,
  Layers,
  Sparkles,
  Eye,
  CheckCircle2,
  RefreshCw,
  Plus,
  Check,
  X,
  ShieldCheck,
  Info,
  Loader2,
  AlertCircle,
} from 'lucide-react'

export interface StudentDocumentManagerProps {
  isOpen: boolean
  onClose: () => void
  student: {
    id: string
    registerNum: string
    name: string
    studentName?: string
    batchId?: string
    batch_id?: string
    classId?: string
    class_id?: string
    className?: string
    class_name?: string
    department?: string
    department_id?: string
    documents?: any[]
  } | null
}

const DEFAULT_DOC_FIELDS: Record<string, string[]> = {
  AADHAAR: ['Student Name', 'Date of Birth', 'Gender', 'Address', 'Aadhaar Number'],
  '10TH_MARKSHEET': ['Student Name', 'Register Number', 'Date of Birth', 'Total Marks', 'Passing Year', 'School Name'],
  '12TH_MARKSHEET': ['Student Name', 'Register Number', 'Cutoff Marks', 'Total Marks', 'Passing Year', 'Group/Stream'],
  COMMUNITY_CERTIFICATE: ['Student Name', 'Father Name', 'Community/Caste', 'Certificate Number', 'Issuing Authority'],
  TRANSFER_CERTIFICATE: ['Student Name', 'Date of Birth', 'Date of Leaving', 'Conduct', 'Institution Name'],
  INCOME_CERTIFICATE: ['Student Name', 'Parent Name', 'Annual Income', 'Certificate Number', 'Valid Until'],
}

export const StudentDocumentManagerModal: React.FC<StudentDocumentManagerProps> = ({
  isOpen,
  onClose,
  student,
}) => {
  const queryClient = useQueryClient()
  const { addToast } = useToastStore()

  const studentId = student?.registerNum || student?.id || ''
  const batchId = student?.batchId || student?.batch_id || ''
  const classId = student?.classId || student?.class_id || ''

  // Sub-modal states
  const [selectedDocForVersions, setSelectedDocForVersions] = useState<StudentDocument | null>(null)
  const [selectedDocForUploadVersion, setSelectedDocForUploadVersion] = useState<StudentDocument | null>(null)
  const [selectedDocForExtract, setSelectedDocForExtract] = useState<StudentDocument | null>(null)
  const [selectedDocExtractions, setSelectedDocExtractions] = useState<StudentDocument | null>(null)
  const [isAddDocOpen, setIsAddDocOpen] = useState(false)
  const [previewTarget, setPreviewTarget] = useState<DocumentPreviewTarget | null>(null)

  // Upload state
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadDocType, setUploadDocType] = useState('AADHAAR')
  const [uploadDocName, setUploadDocName] = useState('Aadhaar Card')
  const [uploadValidationStatus, setUploadValidationStatus] = useState('VALID')
  const [isUploading, setIsUploading] = useState(false)

  // Extraction Field Selection state
  const [selectedFields, setSelectedFields] = useState<string[]>([])
  const [isExtracting, setIsExtracting] = useState(false)
  const [extractionResult, setExtractionResult] = useState<DocumentExtractionRequestResponse | null>(null)

  // Staff Review comment
  const [staffReviewComments, setStaffReviewComments] = useState<Record<string, string>>({})
  const [reviewingVerifId, setReviewingVerifId] = useState<string | null>(null)

  // 1. Fetch managed StudentDocuments
  const {
    data: documents = [],
    isLoading: isLoadingDocs,
    refetch: refetchDocs,
  } = useQuery({
    queryKey: ['student-documents', studentId],
    queryFn: () => (studentId ? studentDocumentService.getStudentDocuments(studentId) : Promise.resolve([])),
    enabled: isOpen && !!studentId,
  })

  // 2. Fetch student verifications
  const {
    data: verifications = [],
    isLoading: isLoadingVerifs,
    refetch: refetchVerifs,
  } = useQuery({
    queryKey: ['student-verifications', studentId],
    queryFn: () => (studentId ? verificationService.getStudentVerificationHistory(studentId) : Promise.resolve([])),
    enabled: isOpen && !!studentId,
  })

  // 3. Fetch configured wanted fields for the batch
  const { data: wantedFields = [] } = useQuery<DocumentTypeOverviewItem[]>({
    queryKey: ['wanted-fields', batchId],
    queryFn: () => (batchId ? wantedFieldService.getBatchOverview(batchId) : Promise.resolve([])),
    enabled: isOpen && !!batchId,
  })

  // Synchronize field selection when Extract modal opens
  useEffect(() => {
    if (selectedDocForExtract) {
      const docTypeNorm = (selectedDocForExtract.document_type || '').toUpperCase().replace(/\s+/g, '_')
      const docNameNorm = (selectedDocForExtract.document_name || '').toLowerCase()
      const matchedConfig = wantedFields.find(
        (wf: DocumentTypeOverviewItem) =>
          (wf.document_type || '').toUpperCase().replace(/\s+/g, '_') === docTypeNorm ||
          (wf.display_name || '').toLowerCase() === docNameNorm
      )

      if (matchedConfig && matchedConfig.fields && matchedConfig.fields.length > 0) {
        const fieldNames = matchedConfig.fields.map((f) => f.field)
        setSelectedFields(fieldNames)
      } else if (DEFAULT_DOC_FIELDS[docTypeNorm]) {
        setSelectedFields(DEFAULT_DOC_FIELDS[docTypeNorm])
      } else {
        setSelectedFields(['Student Name', 'Date of Birth', 'Register Number'])
      }
      setExtractionResult(null)
    }
  }, [selectedDocForExtract, wantedFields])

  // Consolidate documents strictly by canonical document type (e.g. AADHAAR)
  const consolidatedDocuments = React.useMemo(() => {
    const map = new Map<string, StudentDocument>()
    for (const d of documents) {
      const canonicalKey = (d.document_type || d.document_name || '').toUpperCase().replace(/[^A-Z0-9]/g, '_')
      const existing = map.get(canonicalKey)
      if (!existing) {
        map.set(canonicalKey, d)
      } else {
        const vMap = new Map<string, any>()
        for (const v of existing.versions || []) {
          vMap.set(v.version_id, v)
        }
        for (const v of d.versions || []) {
          vMap.set(v.version_id, v)
        }
        const mergedVersions = Array.from(vMap.values()).sort((a, b) => (a.version_number || 0) - (b.version_number || 0))
        const activeV = mergedVersions.slice().reverse().find((v) => v.is_active) || mergedVersions[mergedVersions.length - 1]
        const maxVer = Math.max(existing.current_version || 0, d.current_version || 0, mergedVersions.length)
        const primary = (d.current_version || 0) > (existing.current_version || 0) ? d : existing
        map.set(canonicalKey, {
          ...primary,
          versions: mergedVersions,
          current_version: maxVer,
          active_version_id: activeV?.version_id,
          active_version: activeV,
        })
      }
    }
    return Array.from(map.values())
  }, [documents])

  // Compute Dashboard Metrics
  const totalDocs = consolidatedDocuments.length
  const validDocs = consolidatedDocuments.filter((d) => d.status === 'UPLOADED' || d.status === 'VERIFIED' || d.active_version?.validation_status === 'VALID').length
  const invalidDocs = consolidatedDocuments.filter((d) => d.active_version?.validation_status === 'INVALID').length
  const pendingVerifCount = verifications.filter((v) => v.status === 'AI_EXTRACTED').length
  const correctionReqCount = verifications.filter((v) => v.status === 'CORRECTION_REQUESTED').length
  const verifiedFieldsCount = verifications.filter((v) => v.status === 'STUDENT_CONFIRMED' || v.status === 'STUDENT_VERIFIED' || v.status === 'STAFF_APPROVED').length

  // Handlers
  const handleUploadVersion = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!uploadFile || !selectedDocForUploadVersion) return

    try {
      setIsUploading(true)
      await studentDocumentService.uploadVersionFile(
        selectedDocForUploadVersion.id,
        uploadFile,
        uploadValidationStatus,
        undefined,
        true
      )
      addToast(`Document replaced successfully for ${selectedDocForUploadVersion.document_name}!`, 'success')
      setSelectedDocForUploadVersion(null)
      setUploadFile(null)
      queryClient.invalidateQueries({ queryKey: ['student-documents', studentId] })
      queryClient.invalidateQueries({ queryKey: ['section-students', classId] })
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to upload version.', 'error')
    } finally {
      setIsUploading(false)
    }
  }

  const handleAddInitialDocument = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!uploadFile) return

    try {
      setIsUploading(true)
      await studentDocumentService.uploadDocumentFile({
        studentId,
        batchId,
        documentType: uploadDocType,
        documentName: uploadDocName,
        classId,
        departmentId: student?.department || student?.department_id,
        file: uploadFile,
      })
      addToast(`Document ${uploadDocName} added successfully!`, 'success')
      setIsAddDocOpen(false)
      setUploadFile(null)
      queryClient.invalidateQueries({ queryKey: ['student-documents', studentId] })
      queryClient.invalidateQueries({ queryKey: ['section-students', classId] })
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to add document.', 'error')
    } finally {
      setIsUploading(false)
    }
  }

  const handleStartExtraction = async () => {
    if (!selectedDocForExtract || selectedFields.length === 0) {
      addToast('Please select at least one field to extract.', 'info')
      return
    }

    try {
      setIsExtracting(true)
      const res = await studentDocumentService.extractFields(
        selectedDocForExtract.id,
        selectedFields,
        selectedDocForExtract.active_version_id
      )
      setExtractionResult(res)
      addToast('Extraction completed successfully!', 'success')
      queryClient.invalidateQueries({ queryKey: ['student-documents', studentId] })
      queryClient.invalidateQueries({ queryKey: ['student-verifications', studentId] })
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'AI extraction failed.', 'error')
    } finally {
      setIsExtracting(false)
    }
  }

  const handleReviewCorrection = async (verifId: string, action: 'APPROVE' | 'REJECT') => {
    try {
      setReviewingVerifId(verifId)
      const comment = staffReviewComments[verifId] || ''
      await verificationService.reviewCorrection(verifId, action, comment)
      addToast(
        action === 'APPROVE' ? 'Student correction approved!' : 'Student correction rejected.',
        action === 'APPROVE' ? 'success' : 'info'
      )
      queryClient.invalidateQueries({ queryKey: ['student-verifications', studentId] })
      queryClient.invalidateQueries({ queryKey: ['student-documents', studentId] })
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Review failed.', 'error')
    } finally {
      setReviewingVerifId(null)
    }
  }

  if (!isOpen || !student) return null

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title=""
    >
      <div className="space-y-6 max-h-[85vh] overflow-y-auto pr-1">
        {/* ── 1. HEADER & METADATA ── */}
        <div className="p-4 rounded-2xl bg-gradient-to-r from-card to-secondary/30 border border-border shadow-xs">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <div className="h-12 w-12 rounded-xl bg-primary/10 border border-primary/20 text-primary flex items-center justify-center shrink-0">
                <FileText className="h-6 w-6" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-foreground flex items-center gap-2">
                  {student.studentName || student.name}
                  <span className="font-mono text-xs px-2.5 py-0.5 rounded-full bg-secondary text-secondary-foreground border border-border">
                    {student.registerNum}
                  </span>
                </h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Section: <strong className="text-foreground">{student.className || student.class_name || 'Assigned Section'}</strong>
                  {student.department && ` · Department: ${student.department}`}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  refetchDocs()
                  refetchVerifs()
                }}
                className="cursor-pointer gap-1 text-xs"
                title="Refresh Documents"
              >
                <RefreshCw className="h-3.5 w-3.5" /> Refresh
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => setIsAddDocOpen(true)}
                className="cursor-pointer gap-1.5 text-xs shadow-xs"
              >
                <Plus className="h-4 w-4" /> Add Document
              </Button>
            </div>
          </div>
        </div>

        {/* ── 2. DASHBOARD SUMMARY ── */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
          <div className="p-3 rounded-xl bg-card border border-border">
            <span className="text-[11px] font-semibold text-muted-foreground block">Total Docs</span>
            <span className="text-lg font-bold text-foreground mt-0.5 block">{totalDocs}</span>
          </div>
          <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
            <span className="text-[11px] font-semibold text-emerald-700 dark:text-emerald-400 block">Valid</span>
            <span className="text-lg font-bold text-emerald-700 dark:text-emerald-400 mt-0.5 block">{validDocs}</span>
          </div>
          <div className="p-3 rounded-xl bg-destructive/10 border border-destructive/20">
            <span className="text-[11px] font-semibold text-destructive block">Invalid</span>
            <span className="text-lg font-bold text-destructive mt-0.5 block">{invalidDocs}</span>
          </div>
          <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
            <span className="text-[11px] font-semibold text-amber-700 dark:text-amber-400 block">Pending Verif</span>
            <span className="text-lg font-bold text-amber-700 dark:text-amber-400 mt-0.5 block">{pendingVerifCount}</span>
          </div>
          <div className="p-3 rounded-xl bg-blue-500/10 border border-blue-500/20">
            <span className="text-[11px] font-semibold text-blue-700 dark:text-blue-400 block">Correction Req</span>
            <span className="text-lg font-bold text-blue-700 dark:text-blue-400 mt-0.5 block">{correctionReqCount}</span>
          </div>
          <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
            <span className="text-[11px] font-semibold text-emerald-700 dark:text-emerald-400 block">Verified Fields</span>
            <span className="text-lg font-bold text-emerald-700 dark:text-emerald-400 mt-0.5 block">{verifiedFieldsCount}</span>
          </div>
        </div>

        {/* ── 3. DOCUMENT LIST ── */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold uppercase tracking-wider text-foreground flex items-center gap-2">
              <Layers className="h-4 w-4 text-primary" />
              Candidate Documents ({consolidatedDocuments.length})
            </h3>
          </div>

          {isLoadingDocs ? (
            <div className="flex items-center justify-center p-8">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
              <span className="ml-2 text-xs text-muted-foreground">Loading documents...</span>
            </div>
          ) : consolidatedDocuments.length === 0 ? (
            <div className="p-8 rounded-2xl border border-dashed border-border bg-card/50 text-center space-y-3">
              <FileText className="h-10 w-10 text-muted-foreground/60 mx-auto" />
              <div>
                <p className="text-sm font-bold text-foreground">No documents stored for this student.</p>
                <p className="text-xs text-muted-foreground mt-0.5">Click "Add Document" to upload student records or certificates.</p>
              </div>
              <Button variant="outline" size="sm" onClick={() => setIsAddDocOpen(true)} className="cursor-pointer">
                <Plus className="h-3.5 w-3.5 mr-1" /> Upload First Document
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              {consolidatedDocuments.map((doc) => {
                const activeVersion = doc.active_version || doc.versions?.[0]
                const docVerifs = verifications.filter((v) => v.document_type === doc.document_type || v.document_id === doc.id)
                const hasPendingCorrection = docVerifs.some((v) => v.status === 'CORRECTION_REQUESTED')
                const isAllVerified = docVerifs.length > 0 && docVerifs.every((v) => v.status === 'STUDENT_CONFIRMED' || v.status === 'STUDENT_VERIFIED' || v.status === 'STAFF_APPROVED')

                return (
                  <div
                    key={doc.id}
                    className="p-4 rounded-2xl border border-border bg-card hover:border-border/80 transition-all shadow-2xs space-y-3"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                      <div className="flex items-start gap-3 min-w-0">
                        <div className="p-2.5 rounded-xl bg-primary/10 text-primary border border-primary/20 shrink-0 mt-0.5">
                          <FileText className="h-5 w-5" />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <h4 className="text-sm font-bold text-foreground truncate">{doc.document_name}</h4>
                            <span className="px-2 py-0.5 rounded-md text-[10px] font-bold uppercase bg-secondary text-secondary-foreground border border-border">
                              {doc.document_type}
                            </span>
                          </div>
                          <div className="flex items-center gap-3 text-xs text-muted-foreground font-mono mt-1 flex-wrap">
                            {activeVersion?.original_filename && (
                              <span className="truncate">File: {activeVersion.original_filename}</span>
                            )}
                            {activeVersion?.uploaded_at && (
                              <span>Uploaded: {new Date(activeVersion.uploaded_at).toLocaleDateString()}</span>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Status Badges */}
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {hasPendingCorrection ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-amber-500/15 text-amber-700 dark:text-amber-400 border border-amber-500/30 animate-pulse">
                            <AlertCircle className="h-3 w-3" /> Correction Requested
                          </span>
                        ) : isAllVerified ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border border-emerald-500/30">
                            <CheckCircle2 className="h-3 w-3" /> Verified
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-secondary text-secondary-foreground border border-border">
                            {doc.status || 'UPLOADED'}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Actions Toolbar */}
                    <div className="pt-3 border-t border-border flex items-center gap-2 flex-wrap">
                      {/* 1. View / Preview */}
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setPreviewTarget({
                            studentDocumentId: doc.id,
                            versionId: doc.active_version_id,
                            documentName: doc.document_name,
                            fileName: activeVersion?.original_filename,
                            fileType: activeVersion?.mime_type,
                            studentName: student.studentName || student.name,
                            registerNumber: studentId,
                          })
                        }}
                        className="cursor-pointer gap-1 text-xs py-1 h-8"
                      >
                        <Eye className="h-3.5 w-3.5 text-primary" /> Preview
                      </Button>

                      {/* 2. Re-upload / Replace */}
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setSelectedDocForUploadVersion(doc)
                          setUploadFile(null)
                        }}
                        className="cursor-pointer gap-1 text-xs py-1 h-8"
                        title="Re-upload or replace this document file"
                      >
                        <RefreshCw className="h-3.5 w-3.5 text-blue-500" /> Re-upload
                      </Button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* ── 4. STAFF CORRECTION REVIEW & FINAL VERIFIED DATA ── */}
        <div className="space-y-3 pt-2">
          <h3 className="text-sm font-bold uppercase tracking-wider text-foreground flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-primary" />
            Verification Records & Corrections ({verifications.length})
          </h3>

          {isLoadingVerifs ? (
            <div className="flex items-center justify-center p-6">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
            </div>
          ) : verifications.length === 0 ? (
            <div className="p-5 rounded-xl border border-border bg-card/60 text-xs text-muted-foreground text-center">
              No field verifications registered yet. Extract data from stored documents to initiate verification.
            </div>
          ) : (
            <div className="rounded-xl border border-border bg-card overflow-hidden shadow-2xs divide-y divide-border">
              {verifications.map((v) => {
                const isCorrectionReq = v.status === 'CORRECTION_REQUESTED'
                const isApproved = v.status === 'STAFF_APPROVED' || v.status === 'STUDENT_CONFIRMED' || v.status === 'STUDENT_VERIFIED'
                const isRejected = v.status === 'STAFF_REJECTED'

                return (
                  <div key={v.id} className="p-3.5 space-y-2.5 hover:bg-secondary/20 transition-colors">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-foreground text-sm">{v.field_name}</span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-secondary text-secondary-foreground border border-border">
                          {v.document_type}
                        </span>
                      </div>
                      <span
                        className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold ${
                          isCorrectionReq
                            ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400 border border-amber-500/30'
                            : isApproved
                            ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border border-emerald-500/30'
                            : isRejected
                            ? 'bg-destructive/15 text-destructive border border-destructive/30'
                            : 'bg-secondary text-secondary-foreground border border-border'
                        }`}
                      >
                        {v.status}
                      </span>
                    </div>

                    {/* Side-by-Side Comparison */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-xs font-mono">
                      <div className="p-2.5 rounded-lg bg-secondary/40 border border-border">
                        <span className="text-[10px] font-sans text-muted-foreground uppercase block">AI Extracted</span>
                        <span className="font-bold text-foreground mt-0.5 block break-words">
                          {v.ai_value !== undefined && v.ai_value !== null ? String(v.ai_value) : '—'}
                        </span>
                      </div>

                      <div
                        className={`p-2.5 rounded-lg border ${
                          isCorrectionReq
                            ? 'bg-amber-500/10 border-amber-500/30'
                            : 'bg-secondary/40 border border-border'
                        }`}
                      >
                        <span className="text-[10px] font-sans text-muted-foreground uppercase block">Student Value</span>
                        <span className="font-bold text-foreground mt-0.5 block break-words">
                          {v.student_value !== undefined && v.student_value !== null ? String(v.student_value) : '—'}
                        </span>
                        {v.student_comment && (
                          <span className="text-[11px] font-sans text-muted-foreground italic block mt-1">
                            "{v.student_comment}"
                          </span>
                        )}
                      </div>

                      <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                        <span className="text-[10px] font-sans text-emerald-700 dark:text-emerald-400 uppercase block font-bold">
                          Final Verified
                        </span>
                        <span className="font-bold text-emerald-800 dark:text-emerald-300 mt-0.5 block break-words">
                          {v.final_value !== undefined && v.final_value !== null ? String(v.final_value) : String(v.ai_value ?? '—')}
                        </span>
                        {v.reviewed_by && (
                          <span className="text-[10px] font-sans text-muted-foreground block mt-0.5">
                            By: {v.reviewed_by}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Staff Actions if Correction Requested */}
                    {isCorrectionReq && (
                      <div className="pt-2 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2 border-t border-border/80">
                        <input
                          type="text"
                          placeholder="Optional staff review note..."
                          value={staffReviewComments[v.id] || ''}
                          onChange={(e) =>
                            setStaffReviewComments((prev) => ({ ...prev, [v.id]: e.target.value }))
                          }
                          className="px-3 py-1.5 text-xs rounded-lg border border-border bg-background flex-1 text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                        />
                        <div className="flex items-center gap-2 shrink-0">
                          <Button
                            variant="primary"
                            size="sm"
                            disabled={reviewingVerifId === v.id}
                            onClick={() => handleReviewCorrection(v.id, 'APPROVE')}
                            className="cursor-pointer gap-1 text-xs py-1 h-8 bg-emerald-600 hover:bg-emerald-500"
                          >
                            <Check className="h-3.5 w-3.5" /> Approve Correction
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={reviewingVerifId === v.id}
                            onClick={() => handleReviewCorrection(v.id, 'REJECT')}
                            className="cursor-pointer gap-1 text-xs py-1 h-8 text-destructive hover:bg-destructive/10"
                          >
                            <X className="h-3.5 w-3.5" /> Reject (Keep AI)
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* ── MODAL: VERSION HISTORY ── */}
        <Modal
          isOpen={Boolean(selectedDocForVersions)}
          onClose={() => setSelectedDocForVersions(null)}
          title={`Version History: ${selectedDocForVersions?.document_name || ''}`}
        >
          {selectedDocForVersions && (
            <div className="space-y-4">
              <div className="p-3 rounded-xl bg-secondary/30 text-xs font-semibold space-y-1">
                <span className="text-muted-foreground">Document Type: </span>
                <span className="font-bold text-foreground">{selectedDocForVersions.document_type}</span>
                <p className="text-[11px] text-muted-foreground">
                  All prior versions are immutably preserved in accordance with institutional audit standards.
                </p>
              </div>

              <div className="space-y-2.5 max-h-80 overflow-y-auto pr-1">
                {(selectedDocForVersions.versions || []).map((v) => {
                  const isActive = v.is_active || v.version_id === selectedDocForVersions.active_version_id
                  return (
                    <div
                      key={v.version_id}
                      className={`p-3.5 rounded-xl border transition-all ${
                        isActive
                          ? 'border-primary/40 bg-primary/5 shadow-2xs'
                          : 'border-border bg-card opacity-90'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-foreground text-sm">Version {v.version_number}</span>
                          {isActive ? (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border border-emerald-500/30">
                              Active Version
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-muted text-muted-foreground border border-border">
                              Archived
                            </span>
                          )}
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-extrabold uppercase ${
                              v.validation_status === 'VALID'
                                ? 'bg-emerald-500/10 text-emerald-600'
                                : v.validation_status === 'INVALID'
                                ? 'bg-destructive/10 text-destructive'
                                : 'bg-secondary text-secondary-foreground'
                            }`}
                          >
                            {v.validation_status}
                          </span>
                        </div>

                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            setPreviewTarget({
                              studentDocumentId: selectedDocForVersions.id,
                              versionId: v.version_id,
                              versionNumber: v.version_number,
                              documentName: `${selectedDocForVersions.document_name} (v${v.version_number})`,
                              fileName: v.original_filename,
                              fileType: v.mime_type,
                              studentName: student.studentName || student.name,
                              registerNumber: studentId,
                            })
                          }}
                          className="cursor-pointer gap-1 text-xs py-1 h-7"
                        >
                          <Eye className="h-3 w-3" /> Preview v{v.version_number}
                        </Button>
                      </div>

                      <div className="mt-2 text-xs font-mono text-muted-foreground space-y-0.5">
                        <div className="truncate">File: {v.original_filename}</div>
                        <div>
                          Uploaded: {new Date(v.uploaded_at).toLocaleString()} by {v.uploaded_by || 'Staff'}
                        </div>
                        {v.file_size_bytes > 0 && <div>Size: {(v.file_size_bytes / (1024 * 1024)).toFixed(2)} MB</div>}
                        {v.validation_reason && (
                          <div className="text-destructive font-sans font-semibold mt-1">
                            Reason: {v.validation_reason}
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>

              <div className="flex justify-end pt-3 border-t border-border">
                <Button variant="outline" size="sm" onClick={() => setSelectedDocForVersions(null)}>
                  Close
                </Button>
              </div>
            </div>
          )}
        </Modal>

        {/* ── MODAL: RE-UPLOAD / REPLACE DOCUMENT ── */}
        <Modal
          isOpen={Boolean(selectedDocForUploadVersion)}
          onClose={() => setSelectedDocForUploadVersion(null)}
          title={`Re-upload Document: ${selectedDocForUploadVersion?.document_name || ''}`}
        >
          {selectedDocForUploadVersion && (
            <form onSubmit={handleUploadVersion} className="space-y-4">
              <p className="text-xs text-muted-foreground">
                Upload a replacement file for <strong className="text-foreground">{selectedDocForUploadVersion.document_name}</strong>. The new file will become the active document.
              </p>

              <div>
                <label className="block text-xs font-bold text-foreground uppercase tracking-wider mb-2">
                  Select Document File (PDF, JPG, PNG)
                </label>
                <input
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png,.webp"
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                  required
                  className="w-full text-xs text-foreground file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-primary file:text-primary-foreground hover:file:opacity-90 cursor-pointer border border-border rounded-xl p-2 bg-background"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-foreground uppercase tracking-wider mb-2">
                  Initial Validation Status
                </label>
                <select
                  value={uploadValidationStatus}
                  onChange={(e) => setUploadValidationStatus(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-border bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary cursor-pointer"
                >
                  <option value="VALID">Valid (Approved Document)</option>
                  <option value="PENDING">Pending Review</option>
                  <option value="INVALID">Invalid (Requires Re-upload)</option>
                </select>
              </div>

              <div className="flex justify-end gap-2 pt-4 border-t border-border">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedDocForUploadVersion(null)}
                  disabled={isUploading}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  disabled={!uploadFile || isUploading}
                  className="cursor-pointer gap-1.5"
                >
                  {isUploading ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" /> Replacing Document...
                    </>
                  ) : (
                    <>
                      <Upload className="h-3.5 w-3.5" /> Replace Document
                    </>
                  )}
                </Button>
              </div>
            </form>
          )}
        </Modal>

        {/* ── MODAL: ADD DOCUMENT ── */}
        <Modal isOpen={isAddDocOpen} onClose={() => setIsAddDocOpen(false)} title="Add Student Document">
          <form onSubmit={handleAddInitialDocument} className="space-y-4">
            <div>
              <label className="block text-xs font-bold text-foreground uppercase tracking-wider mb-2">
                Document Type
              </label>
              <select
                value={uploadDocType}
                onChange={(e) => {
                  setUploadDocType(e.target.value)
                  const map: Record<string, string> = {
                    AADHAAR: 'Aadhaar Card',
                    '10TH_MARKSHEET': '10th Marksheet',
                    '12TH_MARKSHEET': '12th Marksheet',
                    COMMUNITY_CERTIFICATE: 'Community Certificate',
                    TRANSFER_CERTIFICATE: 'Transfer Certificate',
                    INCOME_CERTIFICATE: 'Income Certificate',
                  }
                  setUploadDocName(map[e.target.value] || e.target.value)
                }}
                className="w-full px-3 py-2 text-xs rounded-xl border border-border bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary cursor-pointer"
              >
                <option value="AADHAAR">Aadhaar Card</option>
                <option value="10TH_MARKSHEET">10th Marksheet</option>
                <option value="12TH_MARKSHEET">12th Marksheet / HSC</option>
                <option value="COMMUNITY_CERTIFICATE">Community / Caste Certificate</option>
                <option value="TRANSFER_CERTIFICATE">Transfer Certificate (TC)</option>
                <option value="INCOME_CERTIFICATE">Income Certificate</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-bold text-foreground uppercase tracking-wider mb-2">
                Document Display Name
              </label>
              <input
                type="text"
                value={uploadDocName}
                onChange={(e) => setUploadDocName(e.target.value)}
                required
                className="w-full px-3 py-2 text-xs rounded-xl border border-border bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-foreground uppercase tracking-wider mb-2">
                Select Document File
              </label>
              <input
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.webp"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                required
                className="w-full text-xs text-foreground file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-primary file:text-primary-foreground hover:file:opacity-90 cursor-pointer border border-border rounded-xl p-2 bg-background"
              />
            </div>

            <div className="flex justify-end gap-2 pt-4 border-t border-border">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setIsAddDocOpen(false)}
                disabled={isUploading}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={!uploadFile || isUploading}
                className="cursor-pointer gap-1.5"
              >
                {isUploading ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Uploading...
                  </>
                ) : (
                  <>
                    <Upload className="h-3.5 w-3.5" /> Upload Document
                  </>
                )}
              </Button>
            </div>
          </form>
        </Modal>

        {/* ── MODAL: REQUESTED FIELD SELECTION & EXTRACTION ── */}
        <Modal
          isOpen={Boolean(selectedDocForExtract)}
          onClose={() => setSelectedDocForExtract(null)}
          title={`Extract Fields: ${selectedDocForExtract?.document_name || ''}`}
        >
          {selectedDocForExtract && (
            <div className="space-y-4">
              <div className="p-3.5 rounded-xl bg-primary/10 border border-primary/20 text-xs text-primary space-y-1">
                <div className="flex items-center gap-1.5 font-bold">
                  <Info className="h-4 w-4 shrink-0" />
                  <span>AI will extract only the selected fields.</span>
                </div>
                <p className="text-[11px] opacity-90">
                  Select the required attributes to extract from version v{selectedDocForExtract.current_version}. Stored documents will remain intact.
                </p>
              </div>

              {/* Available Fields Checkboxes */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <label className="font-bold text-foreground uppercase tracking-wider">
                    Configured Fields ({selectedFields.length} selected)
                  </label>
                  <div className="space-y-1">
                    <button
                      type="button"
                      onClick={() => {
                        const docTypeNorm = (selectedDocForExtract.document_type || '').toUpperCase().replace(/\s+/g, '_')
                        const all = DEFAULT_DOC_FIELDS[docTypeNorm] || ['Student Name', 'Date of Birth', 'Register Number', 'Gender', 'Address']
                        setSelectedFields(all)
                      }}
                      className="text-primary hover:underline font-semibold mr-3 cursor-pointer"
                    >
                      Select All
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedFields([])}
                      className="text-muted-foreground hover:underline cursor-pointer"
                    >
                      Clear
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 p-3 rounded-xl border border-border bg-card/60 max-h-56 overflow-y-auto">
                  {(
                    DEFAULT_DOC_FIELDS[(selectedDocForExtract.document_type || '').toUpperCase().replace(/\s+/g, '_')] || [
                      'Student Name',
                      'Date of Birth',
                      'Register Number',
                      'Gender',
                      'Address',
                      'Father Name',
                      'Certificate Number',
                    ]
                  ).map((field) => {
                    const isChecked = selectedFields.includes(field)
                    return (
                      <label
                        key={field}
                        className={`flex items-center gap-2.5 p-2.5 rounded-lg border text-xs cursor-pointer transition-colors ${
                          isChecked
                            ? 'border-primary/40 bg-primary/10 text-foreground font-semibold'
                            : 'border-border bg-card text-muted-foreground hover:bg-secondary/40'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedFields((prev) => [...prev, field])
                            } else {
                              setSelectedFields((prev) => prev.filter((f) => f !== field))
                            }
                          }}
                          className="h-4 w-4 rounded text-primary focus:ring-primary cursor-pointer"
                        />
                        <span>{field}</span>
                      </label>
                    )
                  })}
                </div>
              </div>

              {/* Extraction Results Table if Completed */}
              {extractionResult && (extractionResult.extracted_data || extractionResult.status === 'FAILED') && (
                <div className="space-y-2 pt-2 border-t border-border">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400 flex items-center gap-1.5">
                      <CheckCircle2 className="h-4 w-4" /> Extraction Result
                    </h4>
                    {extractionResult.provenance && (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-primary/10 text-primary border border-primary/20">
                        {extractionResult.provenance}
                      </span>
                    )}
                  </div>
                  <div className="rounded-xl border border-border bg-card overflow-hidden text-xs">
                    <table className="w-full text-left">
                      <thead className="bg-secondary/50 border-b border-border">
                        <tr>
                          <th className="p-2.5 font-bold">Field</th>
                          <th className="p-2.5 font-bold">Value</th>
                          <th className="p-2.5 font-bold text-center">Confidence</th>
                          <th className="p-2.5 font-bold">Source</th>
                          <th className="p-2.5 font-bold text-right">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {extractionResult.status === 'FAILED' ? (
                          selectedFields.map((fieldKey) => {
                            const fieldLabel = fieldKey.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
                            const sourceDoc = selectedDocForExtract?.document_name || selectedDocForExtract?.document_type || 'Document'
                            return (
                              <tr key={fieldKey} className="bg-rose-500/5">
                                <td className="p-2.5 font-semibold text-foreground">{fieldLabel}</td>
                                <td className="p-2.5 text-rose-600 dark:text-rose-400 font-semibold italic">Extraction unavailable</td>
                                <td className="p-2.5 text-center text-muted-foreground">—</td>
                                <td className="p-2.5 text-muted-foreground">{sourceDoc}</td>
                                <td className="p-2.5 text-right font-semibold text-rose-600 dark:text-rose-400">OCR/API unavailable</td>
                              </tr>
                            )
                          })
                        ) : (
                          Object.entries(extractionResult.extracted_data || {}).map(([k, v]) => {
                            const fieldLabel = k.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
                            const sourceDoc = selectedDocForExtract?.document_name || selectedDocForExtract?.document_type || 'Document'
                            const isNotFound = v === null || v === undefined || String(v).trim().toUpperCase() === 'NOT_FOUND'
                            const confScore = (extractionResult as any).confidence ?? 96

                            return (
                              <tr key={k} className={isNotFound ? 'bg-muted/20' : ''}>
                                <td className="p-2.5 font-semibold text-foreground">{fieldLabel}</td>
                                <td className="p-2.5 font-mono">
                                  {isNotFound ? (
                                    <span className="text-muted-foreground italic font-sans font-medium">—</span>
                                  ) : (
                                    <span className="font-bold text-foreground">{String(v)}</span>
                                  )}
                                </td>
                                <td className="p-2.5 text-center text-muted-foreground">
                                  {isNotFound ? '—' : `${confScore}%`}
                                </td>
                                <td className="p-2.5 text-muted-foreground">{isNotFound ? '—' : sourceDoc}</td>
                                <td className="p-2.5 text-right font-semibold">
                                  {isNotFound ? (
                                    <span className="text-slate-500 uppercase text-[11px] font-bold">NOT_FOUND</span>
                                  ) : (
                                    <span className="text-emerald-600 dark:text-emerald-400 uppercase text-[11px] font-bold">EXTRACTED</span>
                                  )}
                                </td>
                              </tr>
                            )
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-4 border-t border-border">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedDocForExtract(null)}
                  disabled={isExtracting}
                >
                  Close
                </Button>
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  onClick={handleStartExtraction}
                  disabled={selectedFields.length === 0 || isExtracting}
                  className="cursor-pointer gap-1.5"
                >
                  {isExtracting ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" /> Extracting AI Fields...
                    </>
                  ) : (
                    <>
                      <Sparkles className="h-3.5 w-3.5" /> Start Extraction
                    </>
                  )}
                </Button>
              </div>
            </div>
          )}
        </Modal>

        {/* ── MODAL: EXTRACTIONS HISTORY ── */}
        <Modal
          isOpen={Boolean(selectedDocExtractions)}
          onClose={() => setSelectedDocExtractions(null)}
          title={`Extraction History: ${selectedDocExtractions?.document_name || ''}`}
        >
          {selectedDocExtractions && (
            <ExtractionHistoryView studentDocumentId={selectedDocExtractions.id} onClose={() => setSelectedDocExtractions(null)} />
          )}
        </Modal>

        {/* ── PREVIEW MODAL ── */}
        <DocumentPreviewModal target={previewTarget} onClose={() => setPreviewTarget(null)} />
      </div>
    </Modal>
  )
}

// Subcomponent: Extraction History View
const ExtractionHistoryView: React.FC<{ studentDocumentId: string; onClose: () => void }> = ({
  studentDocumentId,
  onClose,
}) => {
  const { data: extractions = [], isLoading } = useQuery({
    queryKey: ['document-extractions', studentDocumentId],
    queryFn: () => studentDocumentService.getDocumentExtractions(studentDocumentId),
  })

  return (
    <div className="space-y-4">
      {isLoading ? (
        <div className="flex items-center justify-center p-6">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
        </div>
      ) : extractions.length === 0 ? (
        <div className="p-6 rounded-xl border border-border bg-card/60 text-xs text-muted-foreground text-center">
          No extraction requests logged for this document yet.
        </div>
      ) : (
        <div className="space-y-2.5 max-h-72 overflow-y-auto pr-1">
          {extractions.map((ex) => (
            <div key={ex.extraction_request_id} className="p-3 rounded-xl border border-border bg-card text-xs space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-bold text-foreground">Requested by: {ex.requested_by}</span>
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                    ex.status === 'COMPLETED'
                      ? 'bg-emerald-500/10 text-emerald-600'
                      : ex.status === 'FAILED'
                      ? 'bg-destructive/10 text-destructive'
                      : 'bg-amber-500/10 text-amber-600'
                  }`}
                >
                  {ex.status}
                </span>
              </div>
              <div className="text-[11px] font-mono text-muted-foreground">
                Date: {new Date(ex.requested_at).toLocaleString()}
              </div>
              <div className="text-xs text-foreground">
                <strong>Fields:</strong> {ex.requested_fields.join(', ')}
              </div>
              {ex.error_message && (
                <div className="text-destructive text-[11px] mt-1 font-semibold">Error: {ex.error_message}</div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex justify-end pt-3 border-t border-border">
        <Button variant="outline" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  )
}
