import React from 'react'
import { PageHeader } from '../components/PageHeader'
import { EmptyState } from '../components/ui/EmptyState'
import { FileText } from 'lucide-react'

export const DocumentsPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Documents Database"
        description="Query classified transcripts, certificates, and ID documents across all intakes."
      />

      <EmptyState
        title="No Documents Cataloged"
        description="Once uploads are received and parsed by the AI processor, the database of attachments will occupy this view."
        icon={<FileText className="h-12 w-12 text-muted-foreground/60" />}
      />
    </div>
  )
}
