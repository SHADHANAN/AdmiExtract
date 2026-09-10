import React, { useState } from 'react'
import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/ui/Button'
<<<<<<< HEAD
=======
import { Input } from '../components/ui/Input'
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
import { Modal } from '../components/ui/Modal'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../components/ui/Table'
import { EmptyState } from '../components/ui/EmptyState'
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
  Download,
  ShieldCheck,
  Maximize2,
  Filter,
  Sparkles,
  Loader2
} from 'lucide-react'
import type { StudentSubmission } from '../types'

export const Students: React.FC = () => {
  const { submissions, updateStudentStatus, startAiProcessing, fetchAllSubmissions } = useStudentStore()
  const { batches, fetchBatches, classesByBatch, fetchClassesForBatch } = useBatchStore()
  const { addToast } = useToastStore()

  // Fetch all student submissions and batches from FastAPI backend when component mounts
  React.useEffect(() => {
    fetchAllSubmissions()
    fetchBatches()
  }, [fetchAllSubmissions, fetchBatches])

  const [searchQuery, setSearchQuery] = useState('')
  const [selectedBatchId, setSelectedBatchId] = useState<string>('ALL')
  const [selectedClassId, setSelectedClassId] = useState<string>('ALL')
  const [selectedStudent, setSelectedStudent] = useState<StudentSubmission | null>(null)
  const [previewDoc, setPreviewDoc] = useState<{ title: string; url?: string; type?: string; studentName?: string } | null>(null)

  // Fetch classes when batch selection changes
  React.useEffect(() => {
    if (selectedBatchId !== 'ALL') {
      fetchClassesForBatch(selectedBatchId)
    }
    setSelectedClassId('ALL')
  }, [selectedBatchId, fetchClassesForBatch])

  // Available classes for current batch filter
  const currentBatchClasses = selectedBatchId !== 'ALL' ? (classesByBatch[selectedBatchId] || []) : []

  // Filter submissions
  const filteredSubmissions = submissions.filter((sub) => {
    const matchesSearch =
      sub.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      sub.registerNum.toLowerCase().includes(searchQuery.toLowerCase())
    const matchesBatch = selectedBatchId === 'ALL' || sub.batchId === selectedBatchId
    const matchesClass = selectedClassId === 'ALL' || sub.classId === selectedClassId
    return matchesSearch && matchesBatch && matchesClass
  })

  return (
    <div className="space-y-6">
      <PageHeader
        title="Students & Submissions"
        description="Verify uploaded student transcripts, passports, and review AI OCR metadata classification status."
      />

      {/* Filter and Search Bar */}
<<<<<<< HEAD
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 bg-card border border-border/80 p-4 rounded-2xl shadow-2xs">
        <div className="relative w-full sm:w-80">
          <Search className="h-4 w-4 text-muted-foreground absolute left-3.5 top-3" />
          <input
=======
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 bg-card border border-border p-4 rounded-xl shadow-2xs">
        <div className="relative w-full sm:w-80">
          <Input
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
            type="text"
            placeholder="Search candidate name or reg no..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
<<<<<<< HEAD
            className="w-full pl-10 pr-4 py-2 border border-border rounded-xl bg-card text-sm text-foreground placeholder:text-muted-foreground/60 transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary hover:border-slate-300"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2.5 w-full sm:w-auto justify-end">
          <Filter className="h-4 w-4 text-muted-foreground shrink-0" />
          <select
            value={selectedBatchId}
            onChange={(e) => {
              setSelectedBatchId(e.target.value)
              setSelectedClassId('ALL')
            }}
            className="h-10 rounded-xl border border-white/[0.08] bg-[#111827]/80 px-3.5 text-xs font-semibold text-white transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 hover:border-white/[0.18] cursor-pointer"
          >
            <option value="ALL" className="bg-[#111827] text-white">All Admission Batches</option>
            {batches.map((b) => (
              <option key={b.id} value={b.id} className="bg-[#111827] text-white">
=======
            className="pl-9"
          />
          <Search className="h-4 w-4 text-muted-foreground absolute left-3 top-3" />
        </div>

        <div className="flex flex-wrap items-center gap-3 w-full sm:w-auto justify-end">
          <Filter className="h-4 w-4 text-muted-foreground shrink-0" />
          <select
            value={selectedBatchId}
            onChange={(e) => setSelectedBatchId(e.target.value)}
            className="h-10 rounded-md border border-border bg-card px-3 text-xs font-semibold text-foreground focus:outline-none focus:ring-2 focus:ring-ring cursor-pointer"
          >
            <option value="ALL">All Admission Batches</option>
            {batches.map((b) => (
              <option key={b.id} value={b.id}>
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
                {b.name}
              </option>
            ))}
          </select>

          {selectedBatchId !== 'ALL' && currentBatchClasses.length > 0 && (
            <select
              value={selectedClassId}
              onChange={(e) => setSelectedClassId(e.target.value)}
<<<<<<< HEAD
              className="h-10 rounded-xl border border-white/[0.08] bg-[#111827]/80 px-3.5 text-xs font-semibold text-white transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 hover:border-white/[0.18] cursor-pointer"
            >
              <option value="ALL" className="bg-[#111827] text-white">All Classes</option>
              {currentBatchClasses.map((cls) => (
                <option key={cls.id} value={cls.id} className="bg-[#111827] text-white">
=======
              className="h-10 rounded-md border border-border bg-card px-3 text-xs font-semibold text-foreground focus:outline-none focus:ring-2 focus:ring-ring cursor-pointer"
            >
              <option value="ALL">All Classes</option>
              {currentBatchClasses.map((cls) => (
                <option key={cls.id} value={cls.id}>
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
                  {cls.class_name} (Sec {cls.section})
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* Submissions Table */}
      {filteredSubmissions.length > 0 ? (
<<<<<<< HEAD
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Register ID</TableHead>
              <TableHead>Student Name</TableHead>
              <TableHead>Admission Batch</TableHead>
              <TableHead>Section</TableHead>
              <TableHead>Mobile</TableHead>
              <TableHead>Uploaded Docs</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Submitted On</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredSubmissions.map((student) => {
              const batch = batches.find((b) => b.id === student.batchId)
              const uploadedDocs = student.documents.filter((d) => d.status === 'Uploaded').length

              const statusStyles: Record<string, string> = {
                Verified: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
                Rejected: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
                'AI Processing': 'bg-blue-500/10 text-blue-400 border-blue-500/20',
                Submitted: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
                'Verification Pending': 'bg-amber-500/10 text-amber-400 border-amber-500/20',
              }
              const badgeClass = statusStyles[student.status] || 'bg-slate-800 text-slate-300 border-slate-700'

              return (
                <TableRow key={student.id}>
                  <TableCell>
                    <span className="font-mono text-xs font-semibold text-white px-2 py-0.5 rounded-md bg-[#0F172A] border border-white/[0.08]">
                      {student.registerNum}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2.5">
                      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-500/15 text-indigo-400 font-bold text-xs shrink-0 border border-indigo-500/20">
                        {student.name ? student.name.charAt(0).toUpperCase() : 'S'}
                      </div>
                      <span className="font-semibold text-white">{student.name}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-xs font-medium text-slate-400">{batch ? batch.name : 'N/A'}</TableCell>
                  <TableCell className="text-xs font-semibold text-indigo-400">{student.className || 'Default'}</TableCell>
                  <TableCell className="text-xs text-slate-400 font-mono">{student.mobile}</TableCell>
                  <TableCell>
                    <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-[#0F172A] border border-white/[0.08] text-slate-300 text-xs font-semibold">
                      {uploadedDocs} Files
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${badgeClass}`}>
                      {student.status === 'Verified' ? (
                        <CheckCircle className="h-3 w-3" />
                      ) : student.status === 'Rejected' ? (
                        <XCircle className="h-3 w-3" />
                      ) : student.status === 'AI Processing' ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Clock className="h-3 w-3" />
                      )}
                      <span>{student.status}</span>
                    </span>
                  </TableCell>
                  <TableCell className="text-xs text-slate-400">{student.submittedAt}</TableCell>
                  <TableCell className="text-right">
                    <div className="inline-flex items-center gap-1.5 justify-end">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setSelectedStudent(student)}
                        className="cursor-pointer gap-1 text-xs py-1 px-2.5"
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
                        className="cursor-pointer gap-1 text-xs py-1 px-2.5"
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
                        }}
                        className="cursor-pointer gap-1 text-xs py-1 px-2.5 shadow-2xs"
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
=======
        <div className="rounded-xl border border-border bg-card overflow-hidden shadow-2xs">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Register ID</TableHead>
                <TableHead>Student Name</TableHead>
                <TableHead>Admission Batch</TableHead>
                <TableHead>Class</TableHead>
                <TableHead>Contact Mobile</TableHead>
                <TableHead>Uploaded Documents</TableHead>
                <TableHead>Verification Status</TableHead>
                <TableHead>Submitted On</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredSubmissions.map((student) => {
                const batch = batches.find((b) => b.id === student.batchId)
                const uploadedDocs = student.documents.filter((d) => d.status === 'Uploaded').length

                return (
                  <TableRow key={student.id} className="hover:bg-secondary/30 transition-colors">
                    <TableCell className="font-mono text-xs font-bold text-foreground">{student.registerNum}</TableCell>
                    <TableCell className="font-semibold text-foreground">{student.name}</TableCell>
                    <TableCell className="text-xs font-medium text-muted-foreground">{batch ? batch.name : 'N/A'}</TableCell>
                    <TableCell className="text-xs font-semibold text-primary">{student.className || 'Default Class'}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{student.mobile}</TableCell>
                    <TableCell className="text-xs font-bold text-foreground">{uploadedDocs} Files</TableCell>
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
                    <TableCell className="text-xs text-muted-foreground">{student.submittedAt}</TableCell>
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
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
      ) : (
        <EmptyState
          title="No Student Records Found"
          description="No candidate submissions match your current search and filter criteria."
<<<<<<< HEAD
          icon={<Users className="h-10 w-10 text-primary" />}
=======
          icon={<Users className="h-12 w-12 text-muted-foreground/60" />}
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
        />
      )}

      {/* STUDENT DETAILS INSPECTION MODAL */}
      {selectedStudent && (
        <Modal
          isOpen={!!selectedStudent}
          onClose={() => setSelectedStudent(null)}
          title={`Candidate Details: ${selectedStudent.name}`}
        >
          <div className="space-y-6">
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
                <span className="text-muted-foreground block">Submitted On</span>
                <span className="font-bold text-foreground">{selectedStudent.submittedAt}</span>
              </div>
              <div>
                <span className="text-muted-foreground block">Verification Status</span>
                <span className="font-bold text-primary">{selectedStudent.status}</span>
              </div>
            </div>

            <div className="space-y-3">
              <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Uploaded Files</h4>
              <div className="space-y-2.5 max-h-[280px] overflow-y-auto pr-1">
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
                  <CheckCircle className="h-3.5 w-3.5" /> Verify Student
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

      {/* DOCUMENT PREVIEW MODAL */}
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
                onClick={() => addToast(`Downloading ${previewDoc.title}...`, 'info')}
                className="cursor-pointer gap-1.5"
              >
                <Download className="h-3.5 w-3.5" /> Download File
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
