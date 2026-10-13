import React, { useState } from 'react'
import { Modal } from './ui/Modal'
import { Button } from './ui/Button'
import { useToastStore } from '../store/useToastStore'
import {
  studentDocumentService,
  type StudentDocument,
  type BatchDocumentValidationItem,
} from '../services/studentDocument'
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  HelpCircle,
  FileText,
  UserCheck,
  History,
  Loader2,
} from 'lucide-react'

export interface ReclassifyModalProps {
  isOpen: boolean
  onClose: () => void
  doc: StudentDocument | BatchDocumentValidationItem | null
  onSuccess?: () => void
}

const SUPPORTED_DOC_TYPES = [
  { value: 'AADHAAR', label: 'Aadhaar Card' },
  { value: 'COMMUNITY_CERTIFICATE', label: 'Community / Caste Certificate' },
  { value: 'INCOME_CERTIFICATE', label: 'Income Certificate' },
  { value: 'NATIVITY_CERTIFICATE', label: 'Nativity / Residence Certificate' },
  { value: 'SSLC', label: 'SSLC / 10th Marksheet' },
  { value: 'HSC', label: 'HSC / 12th Marksheet' },
  { value: 'TRANSFER_CERTIFICATE', label: 'Transfer Certificate (TC)' },
  { value: 'BANK_PASSBOOK', label: 'Bank Passbook' },
  { value: 'BIRTH_CERTIFICATE', label: 'Birth Certificate' },
  { value: 'BONAFIDE', label: 'Bonafide Certificate' },
  { value: 'ALLOTMENT_ORDER', label: 'Allotment Order' },
  { value: 'UNKNOWN', label: 'Other / Unrecognized' },
]

export const ReclassifyModal: React.FC<ReclassifyModalProps> = ({
  isOpen,
  onClose,
  doc,
  onSuccess,
}) => {
  const { addToast } = useToastStore()
  const [selectedType, setSelectedType] = useState<string>('')
  const [reason, setReason] = useState<string>('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const activeDocId = doc ? ('id' in doc ? doc.id : doc.document_id) : ''
  const currentExpected = doc?.expected_document_type || doc?.document_type || 'N/A'
  const currentDetected = doc?.detected_document_type || 'UNKNOWN'
  const currentStatus = (doc && ('validation_status' in doc ? (doc as any).validation_status : doc.active_version?.validation_status)) || 'PENDING'
  const confidence = doc ? (typeof doc.classification_confidence === 'number' ? Math.round(doc.classification_confidence * 100) : 0) : 0
  const history = doc?.reclassification_history || []

  React.useEffect(() => {
    if (doc) {
      setSelectedType(doc.detected_document_type || doc.document_type || 'AADHAAR')
      setReason('')
    }
  }, [doc])

  const handleReclassify = async () => {
    if (!activeDocId) return
    if (!selectedType) {
      addToast('Please select a document type', 'error')
      return
    }

    setIsSubmitting(true)
    try {
      await studentDocumentService.reclassifyDocument(
        activeDocId,
        selectedType,
        reason.trim() || 'Manual staff reclassification & verification'
      )
      addToast(`Document successfully reclassified to '${selectedType}'`, 'success')
      if (onSuccess) onSuccess()
      onClose()
    } catch (err: any) {
      console.error('Reclassification failed:', err)
      addToast(err.response?.data?.detail || err.message || 'Failed to reclassify document.', 'error')
    } finally {
      setIsSubmitting(false)
    }
  }

  const getStatusBadge = (st: string) => {
    switch (st) {
      case 'VALID':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"><CheckCircle2 className="w-3.5 h-3.5" /> VALID</span>
      case 'WRONG_DOCUMENT':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20"><AlertTriangle className="w-3.5 h-3.5" /> WRONG_DOCUMENT</span>
      case 'NEEDS_REVIEW':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20"><Clock className="w-3.5 h-3.5" /> NEEDS_REVIEW</span>
      case 'CLASSIFICATION_FAILED':
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-red-500/10 text-red-400 border border-red-500/20"><AlertTriangle className="w-3.5 h-3.5" /> CLASSIFICATION_FAILED</span>
      default:
        return <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/20"><HelpCircle className="w-3.5 h-3.5" /> {st}</span>
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Staff Document Reclassification"
    >
      <div className="space-y-6">
        {/* Document Diagnostic Summary */}
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-sky-400" />
              <span className="text-sm font-semibold text-slate-200">
                {doc?.document_name || 'Document'}
              </span>
              {'original_filename' in (doc || {}) && (doc as any).original_filename && (
                <span className="text-xs text-slate-400 font-mono">
                  ({(doc as any).original_filename})
                </span>
              )}
            </div>
            {getStatusBadge(currentStatus)}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 pt-2 text-xs border-t border-slate-800">
            <div>
              <span className="text-slate-400 block mb-0.5">Expected Document</span>
              <span className="font-semibold text-slate-200">{currentExpected}</span>
            </div>
            <div>
              <span className="text-slate-400 block mb-0.5">AI Detected Type</span>
              <span className="font-semibold text-indigo-300">{currentDetected}</span>
            </div>
            <div>
              <span className="text-slate-400 block mb-0.5">Classification Confidence</span>
              <span className="font-semibold text-slate-200">{confidence}%</span>
            </div>
          </div>

          {currentStatus === 'WRONG_DOCUMENT' && (
            <div className="p-2.5 rounded-lg bg-rose-950/40 border border-rose-800/50 flex items-start gap-2 text-xs text-rose-300">
              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
              <div>
                <strong>Warning:</strong> The student uploaded a <strong>{currentDetected}</strong> instead of the required <strong>{currentExpected}</strong>. Extraction rules for {currentExpected} are currently blocked to prevent bad data.
              </div>
            </div>
          )}
        </div>

        {/* Reclassification Selection Form */}
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              Select Correct Document Type <span className="text-rose-400">*</span>
            </label>
            <select
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-900/80 border border-slate-700 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-colors"
            >
              {SUPPORTED_DOC_TYPES.map((dt) => (
                <option key={dt.value} value={dt.value}>
                  {dt.label} ({dt.value})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              Staff Review Reason & Justification
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Verified by admissions officer after inspecting Tamil revenue seal."
              rows={2}
              className="w-full px-3.5 py-2 rounded-xl bg-slate-900/80 border border-slate-700 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-colors"
            />
          </div>
        </div>

        {/* Reclassification Audit History */}
        {history.length > 0 && (
          <div className="space-y-2 pt-2 border-t border-slate-800">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-300">
              <History className="w-3.5 h-3.5 text-amber-400" />
              Reclassification Audit Trail ({history.length})
            </div>
            <div className="max-h-36 overflow-y-auto space-y-2 pr-1">
              {history.map((h: any, idx: number) => (
                <div
                  key={idx}
                  className="p-2.5 rounded-lg bg-slate-900/40 border border-slate-800/60 text-xs space-y-1"
                >
                  <div className="flex items-center justify-between text-slate-300">
                    <span className="font-semibold text-indigo-300">
                      {h.previous_type} → {h.new_type}
                    </span>
                    <span className="text-[11px] text-slate-400">
                      {new Date(h.timestamp).toLocaleString()}
                    </span>
                  </div>
                  <div className="text-slate-400 flex items-center justify-between text-[11px]">
                    <span>Reason: {h.reason}</span>
                    <span className="text-slate-400">By: {h.reviewed_by}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer Actions */}
        <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-800">
          <Button variant="ghost" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleReclassify}
            disabled={isSubmitting || !selectedType}
            className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <UserCheck className="w-4 h-4" />
                Confirm Reclassification
              </>
            )}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
