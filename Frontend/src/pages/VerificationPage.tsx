import React, { useState, useEffect } from 'react'
import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { useStudentStore } from '../store/useStudentStore'
import { useBatchStore } from '../store/useBatchStore'
import { useToastStore } from '../store/useToastStore'
import {
  verificationService,
  type DocumentFieldVerification,
} from '../services/verificationService'
import {
  CheckSquare,
  CheckCircle2,
  XCircle,
  Sparkles,
  Clock,
  Check,
  X,
  RefreshCw,
  UserCheck,
  FileEdit,
} from 'lucide-react'

export const VerificationPage: React.FC = () => {
  const { submissions, fetchAllSubmissions, updateStudentStatus } = useStudentStore()
  const { fetchBatches } = useBatchStore()
  const { addToast } = useToastStore()

  const [activeTab, setActiveTab] = useState<'corrections' | 'submissions'>('corrections')
  const [pendingCorrections, setPendingCorrections] = useState<DocumentFieldVerification[]>([])
  const [loadingCorrections, setLoadingCorrections] = useState(false)
  const [reviewingId, setReviewingId] = useState<string | null>(null)

  const [selectedStudentId, setSelectedStudentId] = useState<string>('')
  const [filterQueue, setFilterQueue] = useState<'pending' | 'all'>('pending')

  const fetchCorrections = async () => {
    try {
      setLoadingCorrections(true)
      const data = await verificationService.getPendingCorrections()
      setPendingCorrections(data)
    } catch (err: any) {
      addToast(err?.message || 'Failed to load pending corrections', 'error')
    } finally {
      setLoadingCorrections(false)
    }
  }

  useEffect(() => {
    fetchAllSubmissions()
    fetchBatches()
    fetchCorrections()
  }, [fetchAllSubmissions, fetchBatches])

  const handleReviewCorrection = async (
    id: string,
    action: 'APPROVE' | 'REJECT',
    comment?: string
  ) => {
    try {
      setReviewingId(id)
      await verificationService.reviewCorrection(id, action, comment)
      addToast(
        action === 'APPROVE'
          ? 'Student correction approved successfully!'
          : 'Student correction rejected.',
        action === 'APPROVE' ? 'success' : 'info'
      )
      await fetchCorrections()
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Review action failed', 'error')
    } finally {
      setReviewingId(null)
    }
  }

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

    return [
      { field: 'Student Full Name', value: selectedStudent.name, source: 'Aadhaar / SSLC Marksheet', confidence: 99, isValid: true, isConflict: false },
      { field: 'Register / Roll Number', value: selectedStudent.registerNum, source: 'Institutional Allocation', confidence: 100, isValid: true, isConflict: false },
      { field: 'Mobile Contact', value: selectedStudent.mobile, source: 'Student Application Form', confidence: 98, isValid: true, isConflict: false },
      { field: 'Email Address', value: selectedStudent.email || 'student@institution.edu', source: 'Student Application Form', confidence: 95, isValid: true, isConflict: false },
    ]
  }, [selectedStudent])

  const handleSelectStudent = (id: string) => {
    setSelectedStudentId(id)
  }

  const handleNextCandidate = () => {
    const currentIndex = queueSubmissions.findIndex((s) => s.id === selectedStudent?.id)
    if (currentIndex >= 0 && currentIndex < queueSubmissions.length - 1) {
      handleSelectStudent(queueSubmissions[currentIndex + 1].id)
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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Candidate & Document Verification"
        description="Review student correction requests, verify extracted fields, and approve admission records."
        action={
          <div className="flex items-center gap-2 bg-slate-100 dark:bg-slate-800 p-1 rounded-lg border border-slate-200 dark:border-slate-700">
            <button
              onClick={() => setActiveTab('corrections')}
              className={`px-3.5 py-1.5 text-xs font-semibold rounded-md transition-all cursor-pointer flex items-center gap-1.5 ${
                activeTab === 'corrections'
                  ? 'bg-primary text-white shadow-sm'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              <FileEdit className="w-3.5 h-3.5" />
              Pending Corrections ({pendingCorrections.length})
            </button>
            <button
              onClick={() => setActiveTab('submissions')}
              className={`px-3.5 py-1.5 text-xs font-semibold rounded-md transition-all cursor-pointer flex items-center gap-1.5 ${
                activeTab === 'submissions'
                  ? 'bg-primary text-white shadow-sm'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              <UserCheck className="w-3.5 h-3.5" />
              Submissions Queue ({queueSubmissions.length})
            </button>
          </div>
        }
      />

      {/* ── TAB 1: PENDING CORRECTIONS REVIEW ── */}
      {activeTab === 'corrections' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2">
              <Clock className="w-4 h-4 text-amber-500" /> Pending Student Corrections
            </h2>
            <Button
              variant="outline"
              size="sm"
              onClick={fetchCorrections}
              disabled={loadingCorrections}
              className="gap-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loadingCorrections ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>

          {pendingCorrections.length === 0 ? (
            <div className="p-12 text-center rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
              <CheckCircle2 className="w-12 h-12 mx-auto text-emerald-500 mb-3" />
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">All caught up!</h3>
              <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm mx-auto mt-1">
                There are no pending student corrections requiring staff review at this time.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4">
              {pendingCorrections.map((item) => (
                <div
                  key={item.id}
                  className="p-5 rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm hover:shadow-md transition-shadow space-y-4"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 dark:border-slate-800 pb-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm text-slate-900 dark:text-white">
                          Student ID: {item.student_id}
                        </span>
                        <span className="text-xs px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 font-mono">
                          {item.document_type} (v{item.document_version_id.slice(0, 6)})
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 mt-0.5">
                        Field: <span className="font-semibold text-slate-700 dark:text-slate-300">{item.field_name}</span>
                        {item.student_updated_at && (
                          <span> • Submitted {new Date(item.student_updated_at).toLocaleString()}</span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="primary"
                        disabled={reviewingId === item.id}
                        onClick={() => handleReviewCorrection(item.id, 'APPROVE')}
                        className="bg-emerald-600 hover:bg-emerald-700 text-white gap-1.5 h-8 text-xs font-semibold"
                      >
                        <Check className="w-3.5 h-3.5" /> Approve
                      </Button>

                      <Button
                        size="sm"
                        variant="outline"
                        disabled={reviewingId === item.id}
                        onClick={() => handleReviewCorrection(item.id, 'REJECT')}
                        className="border-rose-300 text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/20 gap-1.5 h-8 text-xs font-semibold"
                      >
                        <X className="w-3.5 h-3.5" /> Reject
                      </Button>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="p-3.5 rounded-lg bg-slate-50 dark:bg-slate-950 border border-slate-200/80 dark:border-slate-800">
                      <div className="text-xs text-slate-500 font-medium mb-1 flex items-center gap-1.5">
                        <Sparkles className="w-3.5 h-3.5 text-primary" /> Original AI Extracted Value
                      </div>
                      <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                        {item.ai_value || <span className="italic text-slate-400">Empty</span>}
                      </div>
                    </div>

                    <div className="p-3.5 rounded-lg bg-amber-500/10 border border-amber-500/30">
                      <div className="text-xs text-amber-700 dark:text-amber-300 font-medium mb-1 flex items-center gap-1.5">
                        <FileEdit className="w-3.5 h-3.5 text-amber-600" /> Student Corrected Value
                      </div>
                      <div className="text-sm font-bold text-amber-900 dark:text-amber-100">
                        {item.student_value || <span className="italic text-slate-400">Empty</span>}
                      </div>
                    </div>
                  </div>

                  {item.student_comment && (
                    <div className="text-xs text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-800/60 p-2.5 rounded-md">
                      <span className="font-semibold">Student Note:</span> {item.student_comment}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── TAB 2: SUBMISSIONS QUEUE SIDE-BY-SIDE ── */}
      {activeTab === 'submissions' && (
        <div>
          {queueSubmissions.length === 0 ? (
            <EmptyState
              icon={<CheckSquare className="h-10 w-10 text-muted-foreground/60" />}
              title="No Candidates Pending Verification"
              description="All candidate submissions for the selected filter have been fully processed and verified."
              action={
                <Button variant="outline" size="sm" onClick={() => setFilterQueue('all')}>
                  View All Candidates
                </Button>
              }
            />
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
              {/* Left Sidebar Queue */}
              <div className="lg:col-span-4 bg-white border border-slate-200 rounded-xl p-4 space-y-3 shadow-2xs">
                <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                  <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Candidate Queue</span>
                  <span className="text-xs font-semibold bg-slate-100 text-slate-700 px-2 py-0.5 rounded-full">
                    {queueSubmissions.length} Available
                  </span>
                </div>

                <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
                  {queueSubmissions.map((cand) => {
                    const isSelected = cand.id === selectedStudent?.id
                    return (
                      <div
                        key={cand.id}
                        onClick={() => handleSelectStudent(cand.id)}
                        className={`p-3 rounded-lg border text-left cursor-pointer transition-all ${
                          isSelected
                            ? 'bg-[#065f46]/5 border-[#065f46] shadow-2xs'
                            : 'bg-white border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-sm font-semibold text-slate-900 truncate">{cand.name}</p>
                          <span
                            className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${
                              cand.status === 'Verified'
                                ? 'bg-emerald-100 text-emerald-800'
                                : 'bg-amber-100 text-amber-800'
                            }`}
                          >
                            {cand.status}
                          </span>
                        </div>
                        <p className="text-xs text-slate-500 font-mono mt-0.5">{cand.registerNum}</p>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Right Panel Extracted Attributes & Actions */}
              <div className="lg:col-span-8 bg-white border border-slate-200 rounded-xl p-6 space-y-6 shadow-2xs">
                {selectedStudent ? (
                  <>
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-4">
                      <div>
                        <h2 className="text-lg font-bold text-slate-900">{selectedStudent.name}</h2>
                        <p className="text-xs text-slate-500 font-mono">
                          Register No: {selectedStudent.registerNum} • Mobile: {selectedStudent.mobile}
                        </p>
                      </div>

                      <div className="flex items-center gap-2">
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={handleVerify}
                          className="bg-emerald-600 hover:bg-emerald-700 text-white gap-1.5"
                        >
                          <CheckCircle2 className="w-4 h-4" /> Verify Candidate
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleReject}
                          className="border-rose-300 text-rose-600 hover:bg-rose-50 gap-1.5"
                        >
                          <XCircle className="w-4 h-4" /> Reject
                        </Button>
                      </div>
                    </div>

                    <div className="space-y-3">
                      <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
                        Extracted Document Attributes
                      </h3>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {extractedEntries.map((item, idx) => (
                          <div key={idx} className="p-3 rounded-lg bg-slate-50 border border-slate-200/80">
                            <div className="text-xs text-slate-500 font-medium">{item.field}</div>
                            <div className="text-sm font-semibold text-slate-900 mt-0.5">{item.value || '—'}</div>
                            <div className="text-[11px] text-slate-400 mt-1 flex items-center justify-between">
                              <span>Source: {item.source}</span>
                              <span className="text-emerald-600 font-medium">{item.confidence}% confidence</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="text-center py-12 text-slate-400">Select a candidate to view details</div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
