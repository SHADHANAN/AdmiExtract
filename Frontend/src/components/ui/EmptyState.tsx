import React from 'react'

interface EmptyStateProps {
  title: string
  description: string
  icon?: React.ReactNode
  action?: React.ReactNode
}

export const EmptyState: React.FC<EmptyStateProps> = ({ title, description, icon, action }) => (
  <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border p-10 text-center bg-card shadow-2xs">
    <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-primary/10 border border-primary/20 text-primary mb-3.5 shadow-2xs">
      {icon ? (
        icon
      ) : (
        <svg className="h-7 w-7 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
        </svg>
      )}
    </div>
    <h3 className="text-base font-bold tracking-tight text-foreground">{title}</h3>
    <p className="mt-1 text-sm text-muted-foreground max-w-sm leading-relaxed">{description}</p>
    {action && <div className="mt-5">{action}</div>}
  </div>
)
