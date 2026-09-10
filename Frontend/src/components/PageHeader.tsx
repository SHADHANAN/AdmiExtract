import React from 'react'

interface PageHeaderProps {
  title: string
  description?: string
  action?: React.ReactNode
}

export const PageHeader: React.FC<PageHeaderProps> = ({ title, description, action }) => (
<<<<<<< HEAD
  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-white/[0.08] pb-6 mb-8">
    <div className="flex-1 min-w-0">
      <h1 className="text-2xl font-bold tracking-tight text-white m-0 leading-tight">{title}</h1>
      {description && <p className="text-sm text-slate-400 mt-1.5 leading-relaxed">{description}</p>}
    </div>
    {action && <div className="flex items-center gap-3 shrink-0">{action}</div>}
=======
  <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-border pb-5 mb-8">
    <div className="flex-1">
      <h1 className="text-2xl font-bold tracking-tight text-foreground m-0">{title}</h1>
      {description && <p className="text-muted-foreground mt-1 text-sm">{description}</p>}
    </div>
    {action && <div className="flex items-center gap-3">{action}</div>}
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
  </div>
)
