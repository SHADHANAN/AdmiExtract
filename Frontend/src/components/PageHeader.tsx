import React from 'react'

interface PageHeaderProps {
  title: string
  description?: string
  action?: React.ReactNode
}

export const PageHeader: React.FC<PageHeaderProps> = ({ title, description, action }) => (
  <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-border pb-5 mb-8">
    <div className="flex-1">
      <h1 className="text-2xl font-bold tracking-tight text-foreground m-0">{title}</h1>
      {description && <p className="text-muted-foreground mt-1 text-sm">{description}</p>}
    </div>
    {action && <div className="flex items-center gap-3">{action}</div>}
  </div>
)
