import React, { useState, useEffect } from 'react'
import { AlertTriangle, Trash2, Loader2, X, FileText, User, Hash, Layers } from 'lucide-react'
import { Button } from './Button'

export interface DeleteStudentTarget {
  id: string
  name: string
  registerNum: string
  className?: string
  documentsCount: number
}

interface DeleteStudentModalProps {
  target: DeleteStudentTarget | null
  isOpen: boolean
  onClose: () => void
  onConfirm: (target: DeleteStudentTarget) => Promise<void>
}

export const DeleteStudentModal: React.FC<DeleteStudentModalProps> = ({
  target,
  isOpen,
  onClose,
  onConfirm,
}) => {
  const [confirmText, setConfirmText] = useState('')
  const [isDeleting, setIsDeleting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Reset state when opening/closing
  useEffect(() => {
    if (isOpen) {
      setConfirmText('')
      setIsDeleting(false)
      setErrorMessage(null)
    }
  }, [isOpen])

  // Keyboard shortcut: Escape to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen && !isDeleting) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, isDeleting, onClose])

  if (!isOpen || !target) return null

  const isConfirmed = confirmText.trim() === 'DELETE'

  const handleDelete = async () => {
    if (!isConfirmed || isDeleting) return
    setIsDeleting(true)
    setErrorMessage(null)
    try {
      await onConfirm(target)
      onClose()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Unable to delete this student. No data was removed.'
      setErrorMessage(msg)
      setIsDeleting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center p-4 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-student-modal-title"
    >
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/75 backdrop-blur-xs transition-opacity"
        onClick={!isDeleting ? onClose : undefined}
      />

      {/* Modal Dialog */}
      <div className="relative z-10 w-full max-w-md rounded-2xl bg-card border border-border shadow-2xl p-6 text-card-foreground transition-all duration-200 animate-in fade-in zoom-in-95">
        {/* Close Button */}
        {!isDeleting && (
          <button
            onClick={onClose}
            className="absolute top-4 right-4 p-1 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors cursor-pointer"
            title="Cancel"
          >
            <X className="h-4 w-4" />
          </button>
        )}

        {/* Header with Warning Icon */}
        <div className="flex items-start gap-3.5 mb-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-rose-500/10 text-rose-500 border border-rose-500/20">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div>
            <h3 id="delete-student-modal-title" className="text-lg font-bold text-foreground">
              Delete Student?
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
              This will permanently remove this student's admission submission and related data. This action cannot be undone.
            </p>
          </div>
        </div>

        {/* Student Metadata Preview Card */}
        <div className="my-4 rounded-xl border border-rose-500/20 bg-rose-500/5 dark:bg-rose-950/20 p-3.5 space-y-2 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground flex items-center gap-1.5 font-medium">
              <User className="h-3.5 w-3.5 text-foreground/70" /> Student Name
            </span>
            <span className="font-bold text-foreground">{target.name}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground flex items-center gap-1.5 font-medium">
              <Hash className="h-3.5 w-3.5 text-foreground/70" /> Register Number
            </span>
            <span className="font-mono font-bold text-foreground px-1.5 py-0.5 rounded bg-card border border-border">
              {target.registerNum}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground flex items-center gap-1.5 font-medium">
              <Layers className="h-3.5 w-3.5 text-foreground/70" /> Section Allocation
            </span>
            <span className="font-semibold text-foreground">
              {target.className ? `Section ${target.className}` : 'General'}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground flex items-center gap-1.5 font-medium">
              <FileText className="h-3.5 w-3.5 text-foreground/70" /> Uploaded Documents
            </span>
            <span className="font-bold text-rose-600 dark:text-rose-400">
              {target.documentsCount} documents
            </span>
          </div>
        </div>

        {/* Error message banner if API failed */}
        {errorMessage && (
          <div className="mb-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-600 dark:text-rose-400 text-xs flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{errorMessage}</span>
          </div>
        )}

        {/* Confirmation Input Guard */}
        <div className="mb-5 space-y-1.5">
          <label htmlFor="confirm-delete-input" className="block text-xs font-semibold text-foreground">
            Type <span className="font-mono font-bold text-rose-600 dark:text-rose-400 bg-rose-500/10 px-1.5 py-0.5 rounded border border-rose-500/20">DELETE</span> to confirm:
          </label>
          <input
            id="confirm-delete-input"
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            disabled={isDeleting}
            placeholder="DELETE"
            autoFocus
            autoComplete="off"
            className="w-full h-9 rounded-lg border border-input bg-card px-3 text-sm font-mono font-bold text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-rose-500/20 focus:border-rose-500"
          />
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-border">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onClose}
            disabled={isDeleting}
            className="text-xs"
          >
            Cancel
          </Button>
          <button
            type="button"
            onClick={handleDelete}
            disabled={!isConfirmed || isDeleting}
            className="inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 active:bg-rose-800 disabled:opacity-40 disabled:pointer-events-none transition-colors shadow-xs cursor-pointer"
          >
            {isDeleting ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Deleting...
              </>
            ) : (
              <>
                <Trash2 className="h-3.5 w-3.5" />
                Delete Student
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
