import React from 'react'
import { Modal } from './ui/Modal'
import { Button } from './ui/Button'
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  HelpCircle,
  Sparkles,
  FileCheck,
  FileText,
} from 'lucide-react'
import type { BatchDocumentValidationItem, StudentDocument } from '../services/studentDocument'

export interface ClassificationEvidenceModalProps {
  isOpen: boolean
  onClose: () => void
  doc: StudentDocument | BatchDocumentValidationItem | null
  onOpenReclassify?: () => void
}

export const ClassificationEvidenceModal: React.FC<ClassificationEvidenceModalProps> = ({
  isOpen,
  onClose,
  doc,
  onOpenReclassify,
}) => {
  if (!doc) return null

  const expectedType = doc.expected_document_type || doc.document_type || 'N/A'
  const detectedType = doc.detected_document_type || 'UNKNOWN'
  const status = (doc && ('validation_status' in doc ? (doc as any).validation_status : (doc as any).active_version?.validation_status)) || 'PENDING'
  const confidence = typeof doc.classification_confidence === 'number' ? Math.round(doc.classification_confidence * 100) : 0
  const evidence = doc.classification_evidence || []
  const reason = (doc && ('validation_reason' in doc ? (doc as any).validation_reason : (doc as any).active_version?.validation_reason)) || null
  const history = doc.reclassification_history || []

  const getStatusBadge = (st: string) => {
    switch (st) {
      case 'VALID':
        return <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"><CheckCircle2 className="w-3.5 h-3.5" /> VALID</span>
      case 'WRONG_DOCUMENT':
        return <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20"><AlertTriangle className="w-3.5 h-3.5" /> WRONG_DOCUMENT</span>
      case 'NEEDS_REVIEW':
        return <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20"><Clock className="w-3.5 h-3.5" /> NEEDS_REVIEW</span>
      case 'CLASSIFICATION_FAILED':
        return <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-red-500/10 text-red-400 border border-red-500/20"><AlertTriangle className="w-3.5 h-3.5" /> CLASSIFICATION_FAILED</span>
      default:
        return <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/20"><HelpCircle className="w-3.5 h-3.5" /> {st}</span>
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Document Classification Diagnostic & Evidence"
    >
      <div className="space-y-6">
        {/* Header KPI cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800">
            <span className="text-xs text-slate-400 block mb-1">Expected Requirement</span>
            <span className="text-sm font-semibold text-slate-100">{expectedType}</span>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800">
            <span className="text-xs text-slate-400 block mb-1">AI Detected Type</span>
            <span className="text-sm font-semibold text-indigo-300">{detectedType}</span>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800">
            <span className="text-xs text-slate-400 block mb-1">Confidence Score</span>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-sm font-bold text-slate-100">{confidence}%</span>
              <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    confidence >= 90 ? 'bg-emerald-500' : confidence >= 70 ? 'bg-indigo-500' : 'bg-amber-500'
                  }`}
                  style={{ width: `${Math.min(100, confidence)}%` }}
                />
              </div>
            </div>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 flex flex-col justify-between">
            <span className="text-xs text-slate-400 block mb-1">Validation Status</span>
            <div>{getStatusBadge(status)}</div>
          </div>
        </div>

        {/* Warning or Status Info Banner */}
        {status === 'WRONG_DOCUMENT' && (
          <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800/60 flex items-start gap-3 text-xs text-rose-200">
            <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <strong className="text-sm text-rose-300 block">Wrong Document Mismatch Detected</strong>
              <p>
                The student was requested to upload <strong>{expectedType}</strong>, but the AI vision classifier identified this document as a <strong>{detectedType}</strong> with {confidence}% confidence.
              </p>
              <p className="text-rose-400">
                Extraction is automatically blocked to prevent corrupting batch data. If this is a false positive, staff can reclassify it below.
              </p>
            </div>
          </div>
        )}

        {status === 'NEEDS_REVIEW' && (
          <div className="p-4 rounded-xl bg-amber-950/40 border border-amber-800/60 flex items-start gap-3 text-xs text-amber-200">
            <Clock className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <strong className="text-sm text-amber-300 block">Staff Review Required</strong>
              <p>
                The document confidence ({confidence}%) is below the high-accuracy threshold or structural markers were ambiguous.
              </p>
              {reason && <p className="text-amber-400">Diagnostic Note: {reason}</p>}
            </div>
          </div>
        )}

        {/* Evidence Bullets */}
        <div className="space-y-2.5">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
            <Sparkles className="w-4 h-4 text-indigo-400" />
            Classification Evidence & Signals ({evidence.length})
          </div>

          {evidence.length > 0 ? (
            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 space-y-2">
              {evidence.map((ev, idx) => (
                <div key={idx} className="flex items-start gap-2.5 text-xs text-slate-200">
                  <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-1.5 shrink-0" />
                  <span>{ev}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-4 rounded-xl bg-slate-900/40 border border-slate-800/60 text-xs text-slate-400 italic text-center">
              No detailed structural evidence recorded.
            </div>
          )}
        </div>

        {/* Reclassification History */}
        {history.length > 0 && (
          <div className="space-y-2 pt-2 border-t border-slate-800">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-300">
              <FileCheck className="w-4 h-4 text-emerald-400" />
              Reclassification Audit Log ({history.length})
            </div>
            <div className="space-y-2 max-h-32 overflow-y-auto pr-1">
              {history.map((h: any, idx: number) => (
                <div key={idx} className="p-2.5 rounded-lg bg-slate-900/40 border border-slate-800/60 text-xs space-y-1">
                  <div className="flex items-center justify-between text-slate-300">
                    <span className="font-semibold text-indigo-300">{h.previous_type} → {h.new_type}</span>
                    <span className="text-[11px] text-slate-400">{new Date(h.timestamp).toLocaleString()}</span>
                  </div>
                  <div className="text-slate-400 text-[11px] flex justify-between">
                    <span>Reason: {h.reason}</span>
                    <span>Reviewed by: {h.reviewed_by}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-4 border-t border-slate-800">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          {onOpenReclassify && (
            <Button
              variant="primary"
              onClick={() => {
                onClose()
                onOpenReclassify()
              }}
              className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500"
            >
              <FileText className="w-4 h-4" />
              Reclassify Document
            </Button>
          )}
        </div>
      </div>
    </Modal>
  )
}
