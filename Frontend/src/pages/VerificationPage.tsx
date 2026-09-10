import React from 'react'
import { PageHeader } from '../components/PageHeader'
import { EmptyState } from '../components/ui/EmptyState'
<<<<<<< HEAD
import { Button } from '../components/ui/Button'
import { CheckSquare, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
=======
import { CheckSquare } from 'lucide-react'
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4

export const VerificationPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Admissions Verification Queue"
<<<<<<< HEAD
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
=======
        description="Verify student OCR classifications, check confidence ratings, and approve applications."
      />

      <EmptyState
        title="Queue is Empty"
        description="There are currently no document verification tasks pending counselor review."
        icon={<CheckSquare className="h-12 w-12 text-muted-foreground/60" />}
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
      />
    </div>
  )
}
