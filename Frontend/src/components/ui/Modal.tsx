import React from 'react'

interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
}

export const Modal: React.FC<ModalProps> = ({ isOpen, onClose, title, children }) => {
  if (!isOpen) return null

  return (
<<<<<<< HEAD
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
      {/* Overlay */}
      <div
        className="fixed inset-0 bg-black/75 backdrop-blur-md transition-opacity duration-200 cursor-pointer"
        onClick={onClose}
      />
      
      {/* Dialog Content */}
      <div className="relative w-full max-w-lg rounded-2xl border border-white/[0.1] bg-[#0F172A]/95 p-6 shadow-2xl backdrop-blur-2xl transition-all z-10">
        <div className="flex items-center justify-between border-b border-white/[0.08] pb-4">
          <h3 className="text-lg font-bold tracking-tight text-white">{title}</h3>
          <button
            onClick={onClose}
            className="rounded-xl p-1.5 text-slate-400 hover:bg-white/[0.08] hover:text-white transition-colors cursor-pointer"
            title="Close"
=======
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Overlay */}
      <div className="fixed inset-0 bg-black/50 backdrop-blur-xs transition-opacity" onClick={onClose} />
      
      {/* Dialog Content */}
      <div className="relative w-full max-w-lg rounded-xl border border-border bg-card p-6 shadow-lg transition-all z-10">
        <div className="flex items-center justify-between border-b border-border pb-3">
          <h3 className="text-lg font-semibold text-foreground">{title}</h3>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  )
}
