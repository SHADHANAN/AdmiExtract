import React from 'react'
import { PageHeader } from '../components/PageHeader'
import { EmptyState } from '../components/ui/EmptyState'
import { Button } from '../components/ui/Button'
import { CheckSquare, Users } from 'lucide-react'
import { Link } from 'react-router-dom'

export const VerificationPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Admissions Verification Queue"
        description="Review student OCR metadata classifications, verify extracted attributes, and approve candidate dossiers."
      />

      <EmptyState
        title="Verification Queue is Clear"
        description="All applicant document packages have been verified or are up to date. New submissions will queue here automatically for review."
        icon={<CheckSquare className="h-8 w-8 text-primary" />}
        action={
          <Link to="/students">
            <Button variant="outline" size="sm" className="gap-2">
              <Users className="h-4 w-4 text-muted-foreground" />
              <span>Browse All Students</span>
            </Button>
          </Link>
        }
      />
    </div>
  )
}
