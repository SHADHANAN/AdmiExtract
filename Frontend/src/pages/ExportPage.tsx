import React from 'react'
import { PageHeader } from '../components/PageHeader'
import { EmptyState } from '../components/ui/EmptyState'
import { Download } from 'lucide-react'

export const ExportPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Exports"
        description="Extract tables, verify status metrics, and download CSV databases."
      />

      <EmptyState
        title="No Export Configurations"
        description="You will be able to download Excel or PDF database models once student cohorts capture active uploads."
        icon={<Download className="h-12 w-12 text-muted-foreground/60" />}
      />
    </div>
  )
}
