import React, { useState } from 'react'
import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/ui/Button'
import { Modal } from '../components/ui/Modal'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../components/ui/Table'
import { EmptyState } from '../components/ui/EmptyState'
import { DocumentPreviewModal, type DocumentPreviewTarget } from '../components/ui/DocumentPreviewModal'
import { DeleteStudentModal, type DeleteStudentTarget } from '../components/ui/DeleteStudentModal'
import { useStudentStore } from '../store/useStudentStore'
import { useBatchStore } from '../store/useBatchStore'
import { useToastStore } from '../store/useToastStore'
import {
  Users,
  Eye,
  CheckCircle,
  XCircle,
  Clock,
  Search,
  ShieldCheck,
  Loader2,
  RotateCcw,
  AlertTriangle,
  FileText,
  ArrowRight,
  Trash2,
} from 'lucide-react'
import type { StudentSubmission } from '../types'

export const Students: React.FC = () => {
  const { submissions, updateStudentStatus, fetchAllSubmissions, deleteSubmission } = useStudentStore()
  const { batches, fetchBatches, fetchClassesForBatch } = useBatchStore()
  const { addToast } = useToastStore()

  // Fetch all student submissions and batches from FastAPI backend when component mounts
  React.useEffect(() => {
    fetchAllSubmissions()
    fetchBatches()
  }, [fetchAllSubmissions, fetchBatches])

  const [searchQuery, setSearchQuery] = useState('')
  const [selectedBatchId, setSelectedBatchId] = useState<string>('ALL')
  const [selectedSection, setSelectedSection] = useState<string>('ALL')
  const [selectedStatus, setSelectedStatus] = useState<string>('ALL')
  const [selectedStudent, setSelectedStudent] = useState<StudentSubmission | null>(null)

  // DocumentPreviewModal state — lazy loaded per-click
  const [previewTarget, setPreviewTarget] = useState<DocumentPreviewTarget | null>(null)

  // DeleteStudentModal state for safe permanent deletion
  const [deleteTarget, setDeleteTarget] = useState<DeleteStudentTarget | null>(null)

  const handleDeleteConfirm = async (target: DeleteStudentTarget) => {
    await deleteSubmission(target.id)
    if (selectedStudent?.id === target.id) {
      setSelectedStudent(null)
    }
    await Promise.all([
      fetchAllSubmissions(),
      fetchBatches(),
    ])
    addToast('Student deleted successfully.', 'success')
  }

  // Fetch classes when batch selection changes
  React.useEffect(() => {
    if (selectedBatchId !== 'ALL') {
      fetchClassesForBatch(selectedBatchId)
    }
    setSelectedSection('ALL')
  }, [selectedBatchId, fetchClassesForBatch])

  // Extract all available sections across batches
  const availableSections = React.useMemo(() => {
    const sections = new Set<string>()
    submissions.forEach((s) => {
      if (s.className) sections.add(s.className)
    })
    return Array.from(sections)
  }, [submissions])

  // Filter submissions
  const filteredSubmissions = submissions.filter((sub) => {
    const matchesSearch =
      sub.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      sub.registerNum.toLowerCase().includes(searchQuery.toLowerCase())

    const matchesBatch = selectedBatchId === 'ALL' || sub.batchId === selectedBatchId

    const matchesSection =
      selectedSection === 'ALL' ||
      sub.className === selectedSection ||
      (selectedSection === 'Unassigned' && !sub.className)

    let matchesStatus = true
    if (selectedStatus !== 'ALL') {
      if (selectedStatus === 'Verified') matchesStatus = sub.status === 'Verified'
      else if (selectedStatus === 'Rejected') matchesStatus = sub.status === 'Rejected'
      else if (selectedStatus === 'Pending')
        matchesStatus = sub.status === 'Pending' || sub.status === 'Submitted' || sub.status === 'Verification Pending'
      else if (selectedStatus === 'Processing')
        matchesStatus = sub.status === 'AI Processing'
      else if (selectedStatus === 'Completed')
        matchesStatus = sub.status === 'Verified'
      else if (selectedStatus === 'Needs Review')
        matchesStatus = sub.status === 'Verification Pending'
    }

    return matchesSearch && matchesBatch && matchesSection && matchesStatus
  })

  const hasActiveFilters =
    searchQuery.trim() !== '' ||
    selectedBatchId !== 'ALL' ||
    selectedSection !== 'ALL' ||
    selectedStatus !== 'ALL'

  const clearFilters = () => {
    setSearchQuery('')
    setSelectedBatchId('ALL')
    setSelectedSection('ALL')
    setSelectedStatus('ALL')
  }

  const renderStatusBadge = (status: string) => {
    const s = status.toLowerCase()
    if (s === 'verified' || s === 'completed') {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20">
          <CheckCircle className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />
          Verified
        </span>
      )
    }
    if (s === 'rejected') {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-700 dark:text-rose-400 border border-rose-500/20">
          <XCircle className="h-3 w-3 text-rose-600 dark:text-rose-400" />
          Rejected
        </span>
      )
    }
    if (s.includes('processing')) {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-500/10 text-sky-700 dark:text-sky-400 border border-sky-500/20">
          <Loader2 className="h-3 w-3 text-sky-600 dark:text-sky-400 animate-spin" />
          Processing
        </span>
      )
    }
    if (s.includes('review')) {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-500/10 text-purple-700 dark:text-purple-400 border border-purple-500/20">
          <AlertTriangle className="h-3 w-3 text-purple-600 dark:text-purple-400" />
          Needs Review
        </span>
      )
    }
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20">
        <Clock className="h-3 w-3 text-amber-600 dark:text-amber-400" />
        Pending
      </span>
    )
  }

  const renderDocStatusBadge = (status: string) => {
    if (status === 'Uploaded') {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-green-100 text-green-800 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border dark:border-emerald-800/40">
          Uploaded
        </span>
      )
    }
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-muted text-muted-foreground border border-border">
        Document unavailable
      </span>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Student Management"
        description="Review student submissions, track multi-document extraction status, and verify candidate admission credentials."
      />

      {/* Filter and Search Bar */}
      <div className="bg-card border border-border p-4 rounded-xl shadow-2xs space-y-3">
        <div className="flex flex-col md:flex-row items-center justify-between gap-3">
          {/* Search Input */}
          <div className="relative w-full md:w-80">
            <Search className="h-4 w-4 text-muted-foreground absolute left-3.5 top-3" />
            <input
              type="text"
              placeholder="Search by student name or register no..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-input rounded-lg bg-card text-sm text-foreground placeholder:text-muted-foreground transition-colors focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
            />
          </div>

          {/* Filters Row */}
          <div className="flex flex-wrap items-center gap-2.5 w-full md:w-auto justify-end">
            {/* Section Filter */}
            <select
              value={selectedSection}
              onChange={(e) => setSelectedSection(e.target.value)}
              className="h-9 rounded-lg border border-input bg-card px-3 text-xs font-semibold text-foreground hover:border-border focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary cursor-pointer"
            >
              <option value="ALL">All Sections</option>
              {availableSections.map((sec) => (
                <option key={sec} value={sec}>
                  Section {sec}
                </option>
              ))}
            </select>

            {/* Status Filter */}
            <select
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value)}
              className="h-9 rounded-lg border border-input bg-card px-3 text-xs font-semibold text-foreground hover:border-border focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary cursor-pointer"
            >
              <option value="ALL">All Statuses</option>
              <option value="Pending">Pending</option>
              <option value="Processing">Processing</option>
              <option value="Completed">Completed</option>
              <option value="Verified">Verified</option>
              <option value="Needs Review">Needs Review</option>
              <option value="Rejected">Rejected</option>
            </select>

            {/* Batch Filter */}
            <select
              value={selectedBatchId}
              onChange={(e) => setSelectedBatchId(e.target.value)}
              className="h-9 rounded-lg border border-input bg-card px-3 text-xs font-semibold text-foreground hover:border-border focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary cursor-pointer"
            >
              <option value="ALL">All Batches</option>
              {batches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>

            {/* Clear Filters Button */}
            {hasActiveFilters && (
              <Button
                variant="ghost"
                size="sm"
                onClick={clearFilters}
                className="text-xs gap-1 h-9 px-2.5"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Clear Filters
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Submissions Table */}
      {filteredSubmissions.length > 0 ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Student Name</TableHead>
              <TableHead>Register Number</TableHead>
              <TableHead>Section</TableHead>
              <TableHead>Documents</TableHead>
              <TableHead>Processing</TableHead>
              <TableHead>Verification</TableHead>
              <TableHead>Last Updated</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredSubmissions.map((student) => {
              const uploadedDocs = student.documents.filter((d) => d.status === 'Uploaded').length
              const totalDocs = student.documents.length

              return (
                <TableRow key={student.id}>
                  {/* Student Name */}
                  <TableCell>
                    <div className="flex items-center gap-2.5">
                      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary font-bold text-xs shrink-0">
                        {student.name ? student.name.charAt(0).toUpperCase() : 'S'}
                      </div>
                      <span className="font-bold text-foreground">{student.name}</span>
                    </div>
                  </TableCell>

                  {/* Register Number */}
                  <TableCell>
                    <span className="font-mono text-xs font-bold text-foreground px-2 py-0.5 rounded bg-secondary border border-border">
                      {student.registerNum || 'N/A'}
                    </span>
                  </TableCell>

                  {/* Section */}
                  <TableCell>
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-secondary text-foreground border border-border">
                      {student.className ? `Section ${student.className}` : 'General'}
                    </span>
                  </TableCell>

                  {/* Documents */}
                  <TableCell>
                    <span className="inline-flex items-center gap-1 text-xs font-semibold text-muted-foreground">
                      <FileText className="h-3.5 w-3.5" />
                      {uploadedDocs}/{totalDocs || uploadedDocs} Uploaded
                    </span>
                  </TableCell>

                  {/* Processing Status */}
                  <TableCell>
                    {student.status === 'AI Processing' ? (
                      <span className="inline-flex items-center gap-1 text-xs font-semibold text-sky-600 dark:text-sky-400">
                        <Loader2 className="h-3 w-3 animate-spin" /> In Progress
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">Completed</span>
                    )}
                  </TableCell>

                  {/* Verification Status */}
                  <TableCell>{renderStatusBadge(student.status)}</TableCell>

                  {/* Last Updated */}
                  <TableCell className="text-xs text-muted-foreground">
                    {student.updatedAt
                      ? new Date(student.updatedAt).toLocaleDateString()
                      : student.submittedAt || 'Recent'}
                  </TableCell>

                  {/* Actions */}
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setSelectedStudent(student)}
                        className="gap-1 text-xs py-1 px-2.5"
                        title="View Student Profile"
                      >
                        <Eye className="h-3.5 w-3.5" /> View
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setDeleteTarget({
                            id: student.id,
                            name: student.name,
                            registerNum: student.registerNum,
                            className: student.className,
                            documentsCount: student.documents.length,
                          })
                        }
                        className="gap-1 text-xs py-1 px-2 text-muted-foreground hover:text-rose-600 hover:bg-rose-500/10 dark:hover:text-rose-400 border border-transparent hover:border-rose-500/20 transition-colors"
                        title="Delete Student"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        <span className="hidden sm:inline">Delete</span>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      ) : (
        <EmptyState
          title="No Students Found"
          description="No student records match your current search and filter criteria."
          icon={<Users className="h-8 w-8 text-primary" />}
          action={
            hasActiveFilters ? (
              <Button variant="outline" size="sm" onClick={clearFilters}>
                <RotateCcw className="h-3.5 w-3.5 mr-1" />
                Clear Filters
              </Button>
            ) : undefined
          }
        />
      )}

      {/* ── STUDENT PROFILE MODAL ── */}
      {selectedStudent && (
        <Modal
          isOpen={!!selectedStudent}
          onClose={() => setSelectedStudent(null)}
          title={`Student Profile: ${selectedStudent.name}`}
        >
          <div className="space-y-5">
            {/* Info Grid */}
            <div className="p-4 bg-secondary/50 border border-border rounded-xl grid grid-cols-2 gap-3 text-xs">
              <div>
                <span className="text-muted-foreground block">Registration Number</span>
                <span className="font-bold text-foreground font-mono">{selectedStudent.registerNum}</span>
              </div>
              <div>
                <span className="text-muted-foreground block">Mobile Contact</span>
                <span className="font-bold text-foreground">{selectedStudent.mobile || 'N/A'}</span>
              </div>
              <div>
                <span className="text-muted-foreground block">Section Allocation</span>
                <span className="font-bold text-foreground">
                  {selectedStudent.className ? `Section ${selectedStudent.className}` : 'General'}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground block">Verification Status</span>
                <div className="mt-0.5">{renderStatusBadge(selectedStudent.status)}</div>
              </div>
              {selectedStudent.email && (
                <div className="col-span-2">
                  <span className="text-muted-foreground block">Email</span>
                  <span className="font-bold text-foreground">{selectedStudent.email}</span>
                </div>
              )}
              <div className="col-span-2">
                <span className="text-muted-foreground block">Submitted At</span>
                <span className="font-bold text-foreground">{selectedStudent.submittedAt || 'N/A'}</span>
              </div>
            </div>

            {/* Document List */}
            <div className="space-y-2">
              <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5" />
                Uploaded Documents ({selectedStudent.documents.length})
              </h4>
              <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
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
                      {/* Document icon + info */}
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

                      {/* Status & Preview Action */}
                      <div className="flex items-center gap-2 shrink-0">
                        {renderDocStatusBadge(doc.status)}

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

            {/* Action Row */}
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 pt-4 border-t border-border">
              {/* Separate Destructive Action */}
              <div>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() =>
                    setDeleteTarget({
                      id: selectedStudent.id,
                      name: selectedStudent.name,
                      registerNum: selectedStudent.registerNum,
                      className: selectedStudent.className,
                      documentsCount: selectedStudent.documents.length,
                    })
                  }
                  className="gap-1.5 w-full sm:w-auto bg-rose-600 hover:bg-rose-700 text-white dark:bg-rose-600 dark:hover:bg-rose-700 shadow-2xs"
                  title="Permanently Delete Student"
                >
                  <Trash2 className="h-3.5 w-3.5" /> Delete Student
                </Button>
              </div>

              {/* Normal Workflow Actions */}
              <div className="flex items-center justify-end gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => {
                    updateStudentStatus(selectedStudent.id, 'Verified')
                    setSelectedStudent((prev) => (prev ? { ...prev, status: 'Verified' } : null))
                    addToast(`Marked ${selectedStudent.name} as Verified!`, 'success')
                  }}
                  className="gap-1"
                >
                  <CheckCircle className="h-3.5 w-3.5" /> Verify Student
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    updateStudentStatus(selectedStudent.id, 'Rejected')
                    setSelectedStudent((prev) => (prev ? { ...prev, status: 'Rejected' } : null))
                    addToast(`Marked ${selectedStudent.name} as Rejected.`, 'info')
                  }}
                  className="gap-1 text-rose-600 dark:text-rose-400 hover:bg-rose-500/10 border border-border"
                >
                  <XCircle className="h-3.5 w-3.5" /> Reject
                </Button>
                <Button variant="outline" size="sm" onClick={() => setSelectedStudent(null)}>
                  Close
                </Button>
              </div>
            </div>
          </div>
        </Modal>
      )}

      {/* ── DELETE STUDENT CONFIRMATION MODAL ── */}
      <DeleteStudentModal
        target={deleteTarget}
        isOpen={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDeleteConfirm}
      />

      {/* ── DOCUMENT PREVIEW MODAL ── */}
      <DocumentPreviewModal
        target={previewTarget}
        onClose={() => setPreviewTarget(null)}
      />

      {/* AI Verification badge (kept from original) */}
      {previewTarget && (
        <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-[60] pointer-events-none">
          <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card/90 backdrop-blur-sm border border-border shadow-lg text-xs font-semibold text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5 text-success" />
            Staff-authenticated document access
          </div>
        </div>
      )}
    </div>
  )
}
