import React from 'react'
import { PageHeader } from '../components/PageHeader'
import { EmptyState } from '../components/ui/EmptyState'
import { CheckSquare } from 'lucide-react'

export const VerificationPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Admissions Verification Queue"
        description="Verify student OCR classifications, check confidence ratings, and approve applications."
      />

      <EmptyState
        title="Queue is Empty"
        description="There are currently no document verification tasks pending counselor review."
        icon={<CheckSquare className="h-12 w-12 text-muted-foreground/60" />}
      />
    </div>
  )
}
