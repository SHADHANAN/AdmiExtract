import React from 'react'

interface EmptyStateProps {
  title: string
  description: string
  icon?: React.ReactNode
  action?: React.ReactNode
}

export const EmptyState: React.FC<EmptyStateProps> = ({ title, description, icon, action }) => (
  <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border p-12 text-center bg-card">
    {icon ? (
      <div className="mb-4 text-muted-foreground">{icon}</div>
    ) : (
      <svg className="mx-auto h-12 w-12 text-muted-foreground/60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
      </svg>
    )}
    <h3 className="mt-2 text-sm font-semibold text-foreground">{title}</h3>
    <p className="mt-1 text-sm text-muted-foreground max-w-sm">{description}</p>
    {action && <div className="mt-6">{action}</div>}
  </div>
)
