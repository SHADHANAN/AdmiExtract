import React from 'react'

interface PageHeaderProps {
  title: string
  description?: string
  action?: React.ReactNode
  badge?: React.ReactNode
}

export const PageHeader: React.FC<PageHeaderProps> = ({ title, description, action, badge }) => (
  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border pb-5 mb-6">
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2.5 flex-wrap">
        <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-foreground m-0 leading-tight">
          {title}
        </h1>
        {badge}
      </div>
      {description && (
        <p className="text-xs sm:text-sm text-muted-foreground mt-1.5 leading-relaxed max-w-3xl">
          {description}
        </p>
      )}
    </div>
    {action && <div className="flex items-center gap-2.5 shrink-0 self-start sm:self-center">{action}</div>}
  </div>
)
