import React from 'react'

interface EmptyStateProps {
  title: string
  description: string
  icon?: React.ReactNode
  action?: React.ReactNode
}

export const EmptyState: React.FC<EmptyStateProps> = ({ title, description, icon, action }) => (
  <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/[0.1] p-12 text-center bg-[#111827]/60 backdrop-blur-xl shadow-inner">
    <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 mb-4 shadow-lg shadow-indigo-500/10">
      {icon ? (
        icon
      ) : (
        <svg className="h-8 w-8 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
        </svg>
      )}
    </div>
    <h3 className="text-base font-bold tracking-tight text-white">{title}</h3>
    <p className="mt-1.5 text-sm text-slate-400 max-w-sm leading-relaxed">{description}</p>
    {action && <div className="mt-6">{action}</div>}
  </div>
)
