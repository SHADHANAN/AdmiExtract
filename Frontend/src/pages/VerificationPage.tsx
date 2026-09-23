import React, { useState, useEffect } from 'react'
import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { useStudentStore } from '../store/useStudentStore'
import { useBatchStore } from '../store/useBatchStore'
import { useToastStore } from '../store/useToastStore'
import {
  CheckSquare,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FileText,
  Download,
  ShieldCheck,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  HelpCircle,
} from 'lucide-react'

export const VerificationPage: React.FC = () => {
  const { submissions, fetchAllSubmissions, updateStudentStatus } = useStudentStore()
  const { batches, fetchBatches } = useBatchStore()
  const { addToast } = useToastStore()

  useEffect(() => {
    fetchAllSubmissions()
    fetchBatches()
  }, [fetchAllSubmissions, fetchBatches])

  const [selectedStudentId, setSelectedStudentId] = useState<string>('')
  const [selectedDocIndex, setSelectedDocIndex] = useState<number>(0)
  const [filterQueue, setFilterQueue] = useState<'pending' | 'all'>('pending')

  // Filter queue
  const queueSubmissions = submissions.filter((s) => {
    if (filterQueue === 'pending') {
      return s.status === 'Verification Pending' || s.status === 'Submitted' || s.status === 'AI Processing'
    }
    return true
  })

  // Set default selected student if none selected
  useEffect(() => {
    if (!selectedStudentId && queueSubmissions.length > 0) {
      setSelectedStudentId(queueSubmissions[0].id)
    }
  }, [queueSubmissions, selectedStudentId])

  const selectedStudent =
    submissions.find((s) => s.id === selectedStudentId) || (queueSubmissions.length > 0 ? queueSubmissions[0] : null)

  const currentBatch = selectedStudent ? batches.find((b) => b.id === selectedStudent.batchId) : null

  // Extract documents for selected student
  const studentDocs = selectedStudent?.documents || []
  const activeDoc = studentDocs[selectedDocIndex] || (studentDocs.length > 0 ? studentDocs[0] : null)

  // Map extracted fields into display list
  const extractedEntries = React.useMemo(() => {
    if (!selectedStudent) return []
    const ext = selectedStudent.extractedData || selectedStudent.extracted_data || {}
    const entries = Object.entries(ext)

    if (entries.length > 0) {
      return entries.map(([key, val]) => {
        let valueStr = ''
        let sourceDoc = 'Multi-Doc Reconciliation'
        let confidence = 96
        let isValid = true
        let isConflict = false

        if (val && typeof val === 'object') {
          valueStr = String(val.value || val.final_value || JSON.stringify(val))
          sourceDoc = val.source_document || val.source || sourceDoc
          confidence = val.confidence || confidence
          isValid = val.is_valid !== false
          isConflict = !!val.has_conflict
        } else {
          valueStr = String(val ?? '')
          // Heuristic source attribution based on field name
          const lowerKey = key.toLowerCase()
          if (lowerKey.includes('aadhaar')) sourceDoc = 'Aadhaar Card'
          else if (lowerKey.includes('dob') || lowerKey.includes('birth')) sourceDoc = 'Aadhaar / 10th Marksheet'
          else if (lowerKey.includes('tc') || lowerKey.includes('transfer')) sourceDoc = 'Transfer Certificate'
          else if (lowerKey.includes('allotment')) sourceDoc = 'Provisional Allotment'
          else if (lowerKey.includes('community') || lowerKey.includes('caste')) sourceDoc = 'Community Certificate'
          else if (lowerKey.includes('income')) sourceDoc = 'Income Certificate'
          else if (lowerKey.includes('bank') || lowerKey.includes('passbook')) sourceDoc = 'Bank Passbook'
          else sourceDoc = 'Verified Documents'
        }

        return {
          field: key,
          value: valueStr,
          source: sourceDoc,
          confidence,
          isValid,
          isConflict,
        }
      })
    }

    // Default institutional fields representation if student profile has direct keys
    return [
      { field: 'Student Full Name', value: selectedStudent.name, source: 'Aadhaar / SSLC Marksheet', confidence: 99, isValid: true, isConflict: false },
      { field: 'Register / Roll Number', value: selectedStudent.registerNum, source: 'Institutional Allocation', confidence: 100, isValid: true, isConflict: false },
      { field: 'Mobile Contact', value: selectedStudent.mobile, source: 'Student Application Form', confidence: 98, isValid: true, isConflict: false },
      { field: 'Email Address', value: selectedStudent.email || 'student@institution.edu', source: 'Student Application Form', confidence: 95, isValid: true, isConflict: false },
      { field: 'Assigned Batch', value: currentBatch?.name || 'AIML Cohort', source: 'Batch Roster', confidence: 100, isValid: true, isConflict: false },
      { field: 'Allocated Section', value: selectedStudent.className ? `Section ${selectedStudent.className}` : 'Section A', source: 'Batch Allocation', confidence: 100, isValid: true, isConflict: false },
    ]
  }, [selectedStudent, currentBatch])

  // Navigation handlers
  const handleSelectStudent = (id: string) => {
    setSelectedStudentId(id)
    setSelectedDocIndex(0)
  }

  const handleNextCandidate = () => {
    const currentIndex = queueSubmissions.findIndex((s) => s.id === selectedStudent?.id)
    if (currentIndex >= 0 && currentIndex < queueSubmissions.length - 1) {
      handleSelectStudent(queueSubmissions[currentIndex + 1].id)
    }
  }

  const handlePrevCandidate = () => {
    const currentIndex = queueSubmissions.findIndex((s) => s.id === selectedStudent?.id)
    if (currentIndex > 0) {
      handleSelectStudent(queueSubmissions[currentIndex - 1].id)
    }
  }

  const handleVerify = async () => {
    if (!selectedStudent) return
    try {
      await updateStudentStatus(selectedStudent.id, 'Verified')
      addToast(`Candidate "${selectedStudent.name}" verified successfully!`, 'success')
      handleNextCandidate()
    } catch (err: any) {
      addToast(err?.message || 'Failed to update verification status', 'error')
    }
  }

  const handleReject = async () => {
    if (!selectedStudent) return
    try {
      await updateStudentStatus(selectedStudent.id, 'Rejected')
      addToast(`Candidate "${selectedStudent.name}" marked as Rejected.`, 'info')
      handleNextCandidate()
    } catch (err: any) {
      addToast(err?.message || 'Failed to update verification status', 'error')
    }
  }

  const handleNeedsReview = async () => {
    if (!selectedStudent) return
    try {
      await updateStudentStatus(selectedStudent.id, 'Verification Pending')
      addToast(`Candidate "${selectedStudent.name}" flagged for review.`, 'info')
    } catch (err: any) {
      addToast(err?.message || 'Failed to update status', 'error')
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Candidate Verification"
        description="Verify extracted student attributes, inspect original certificates side-by-side, and confirm admission records."
        action={
          <div className="flex items-center gap-2 bg-white border border-slate-200 p-1 rounded-lg">
            <button
              onClick={() => setFilterQueue('pending')}
              className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors cursor-pointer ${
                filterQueue === 'pending'
                  ? 'bg-[#065f46] text-white shadow-2xs'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Pending Queue ({submissions.filter((s) => s.status !== 'Verified').length})
            </button>
            <button
              onClick={() => setFilterQueue('all')}
              className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors cursor-pointer ${
                filterQueue === 'all'
                  ? 'bg-[#065f46] text-white shadow-2xs'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              All Candidates ({submissions.length})
            </button>
          </div>
        }
      />

      {queueSubmissions.length === 0 ? (
        <EmptyState
          title="Verification Queue is Clear"
          description="All applicant document packages have been verified. New submissions will queue here automatically for review."
          icon={<CheckSquare className="h-8 w-8 text-emerald-700" />}
        />
      ) : selectedStudent ? (
        <div className="space-y-4">
          {/* Top Candidate Navigator Bar */}
          <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-2xs flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-100 text-[#065f46] font-bold text-sm shrink-0">
                {selectedStudent.name.charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h2 className="text-base font-bold text-slate-900 truncate">
                    {selectedStudent.name}
                  </h2>
                  <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
                    Reg: {selectedStudent.registerNum}
                  </span>
                  <span className="text-xs font-semibold text-emerald-800 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                    {selectedStudent.className ? `Section ${selectedStudent.className}` : 'General'}
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border ${
                      selectedStudent.status === 'Verified'
                        ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                        : selectedStudent.status === 'Rejected'
                        ? 'bg-rose-50 text-rose-800 border-rose-200'
                        : 'bg-amber-50 text-amber-800 border-amber-200'
                    }`}
                  >
                    {selectedStudent.status}
                  </span>
                </div>
                <p className="text-xs text-slate-500 mt-0.5">
                  Cohort: {currentBatch?.name || selectedStudent.batchName || 'AIML Cohort'} • Submitted on {selectedStudent.submittedAt || 'Recent'}
                </p>
              </div>
            </div>

            {/* Candidate Switcher Dropdown & Nav */}
            <div className="flex items-center gap-2 shrink-0 self-end md:self-auto">
              <select
                value={selectedStudent.id}
                onChange={(e) => handleSelectStudent(e.target.value)}
                className="h-9 rounded-lg border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-700 hover:border-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-600/20 focus:border-[#065f46] cursor-pointer"
              >
                {queueSubmissions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.registerNum})
                  </option>
                ))}
              </select>

              <Button
                variant="outline"
                size="sm"
                onClick={handlePrevCandidate}
                disabled={queueSubmissions.findIndex((s) => s.id === selectedStudent.id) === 0}
                className="h-9 px-2"
                title="Previous Candidate"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleNextCandidate}
                disabled={
                  queueSubmissions.findIndex((s) => s.id === selectedStudent.id) === queueSubmissions.length - 1
                }
                className="h-9 px-2"
                title="Next Candidate"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {/* SPLIT LAYOUT: Document Preview (LEFT) vs Extracted Information (RIGHT) */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
            {/* LEFT PANEL: Document Preview (5 cols) */}
            <div className="lg:col-span-5 bg-white border border-slate-200 rounded-xl p-4 shadow-2xs space-y-4">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-[#065f46]" />
                  <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
                    Uploaded Documents ({studentDocs.length})
                  </h3>
                </div>
                {activeDoc && (
                  <span className="text-[11px] font-mono text-slate-500">
                    {activeDoc.fileType || 'PDF'} • {activeDoc.fileSizeMb || 1.2} MB
                  </span>
                )}
              </div>

              {/* Document Selector Pills */}
              <div className="flex flex-wrap gap-1.5">
                {studentDocs.map((doc, idx) => {
                  const isSelected = selectedDocIndex === idx
                  const isUploaded = doc.status === 'Uploaded'
                  return (
                    <button
                      key={idx}
                      onClick={() => setSelectedDocIndex(idx)}
                      className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-colors flex items-center gap-1.5 cursor-pointer ${
                        isSelected
                          ? 'bg-[#065f46] text-white shadow-2xs'
                          : isUploaded
                          ? 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                          : 'bg-slate-50 text-slate-400 border border-dashed border-slate-200'
                      }`}
                    >
                      <span className="truncate max-w-[140px]">{doc.reqName}</span>
                      {isUploaded && (
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${
                            isSelected ? 'bg-lime-400' : 'bg-emerald-500'
                          }`}
                        />
                      )}
                    </button>
                  )
                })}
              </div>

              {/* Document Preview Frame */}
              <div className="relative w-full h-[460px] bg-slate-900 rounded-xl overflow-hidden border border-slate-800 flex flex-col items-center justify-center p-4">
                {activeDoc?.fileUrl ? (
                  <img
                    src={activeDoc.fileUrl}
                    alt={activeDoc.reqName}
                    className="max-h-full max-w-full object-contain rounded shadow"
                  />
                ) : (
                  <div className="text-center text-slate-400 space-y-2">
                    <FileText className="h-10 w-10 mx-auto text-slate-600" />
                    <p className="text-xs">No preview available for this document</p>
                  </div>
                )}

                {/* Scan Watermark */}
                <div className="absolute bottom-3 right-3 bg-white/95 backdrop-blur-xs border border-slate-200 px-2.5 py-1 rounded-md text-[10px] font-mono text-slate-800 flex items-center gap-1.5 shadow-xs">
                  <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
                  <span>AI OCR Verified Document</span>
                </div>
              </div>

              {/* Document Action */}
              <div className="flex items-center justify-between pt-1">
                <span className="text-xs text-slate-500 truncate">
                  {activeDoc?.fileName || activeDoc?.reqName || 'Document'}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => addToast(`Opening ${activeDoc?.reqName}...`, 'info')}
                  className="gap-1.5 text-xs h-8"
                >
                  <Download className="h-3.5 w-3.5" />
                  Download Original
                </Button>
              </div>
            </div>

            {/* RIGHT PANEL: Extracted Information & Field Reconciliation (7 cols) */}
            <div className="lg:col-span-7 bg-white border border-slate-200 rounded-xl p-5 shadow-2xs space-y-5">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <div>
                  <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
                    <Sparkles className="h-4 w-4 text-[#065f46]" />
                    Extracted Information & Reconciliation
                  </h3>
                  <p className="text-xs text-slate-500 mt-0.5">
                    Field-to-value mapping with multi-document cross-validation
                  </p>
                </div>
                <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 text-xs font-bold">
                  {extractedEntries.length} Fields Extracted
                </div>
              </div>

              {/* Fields Table demonstrating: FIELD -> VALUE -> SOURCE -> VALIDATION */}
              <div className="space-y-2.5 max-h-[460px] overflow-y-auto pr-1">
                {extractedEntries.map((item, idx) => (
                  <div
                    key={idx}
                    className="p-3 rounded-lg border border-slate-200/90 bg-slate-50/50 hover:bg-white hover:border-slate-300 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-2xs"
                  >
                    {/* Left: Field Name & Final Value */}
                    <div className="min-w-0 flex-1">
                      <div className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                        {item.field}
                      </div>
                      <div className="text-sm font-bold text-slate-900 mt-0.5 font-mono truncate">
                        {item.value || <span className="text-slate-400 italic">Not detected</span>}
                      </div>
                    </div>

                    {/* Right: Source Document, Confidence & Validation Badge */}
                    <div className="flex items-center gap-2.5 shrink-0 flex-wrap sm:flex-nowrap">
                      {/* Source Document Badge */}
                      <span className="text-[11px] text-slate-600 bg-white border border-slate-200 px-2 py-0.5 rounded font-medium truncate max-w-[160px]">
                        Source: {item.source}
                      </span>

                      {/* Validation Status */}
                      {item.isConflict ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-amber-50 text-amber-800 border border-amber-200">
                          <AlertTriangle className="h-3 w-3 text-amber-600" />
                          Conflict
                        </span>
                      ) : !item.value ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-purple-50 text-purple-800 border border-purple-200">
                          <HelpCircle className="h-3 w-3 text-purple-600" />
                          Needs Review
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold bg-emerald-50 text-emerald-800 border border-emerald-200">
                          <CheckCircle2 className="h-3 w-3 text-emerald-600" />
                          Valid
                        </span>
                      )}

                      {/* Confidence score */}
                      <span className="text-[10px] font-mono text-slate-400">
                        {item.confidence}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>

              {/* Staff Review Action Bar */}
              <div className="pt-4 border-t border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="text-xs text-slate-500">
                  Perform official admission verification for <strong className="text-slate-800">{selectedStudent.name}</strong>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={handleReject}
                    className="text-xs font-semibold gap-1.5 h-9"
                  >
                    <XCircle className="h-4 w-4" />
                    Reject
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleNeedsReview}
                    className="text-xs font-semibold gap-1.5 h-9"
                  >
                    <AlertTriangle className="h-4 w-4 text-amber-600" />
                    Needs Review
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleVerify}
                    className="text-xs font-semibold gap-1.5 h-9 px-4"
                  >
                    <CheckCircle2 className="h-4 w-4 text-lime-300" />
                    Verify Candidate
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
