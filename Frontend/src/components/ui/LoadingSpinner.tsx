import React from 'react'

export const LoadingSpinner: React.FC<{ className?: string }> = ({ className = 'h-8 w-8' }) => (
  <div className="flex items-center justify-center p-4">
    <div className={`animate-spin rounded-full border-4 border-muted border-t-primary ${className}`} />
  </div>
)
