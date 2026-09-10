import React from 'react'
import { PageHeader } from '../components/PageHeader'
import { EmptyState } from '../components/ui/EmptyState'
import { Button } from '../components/ui/Button'
import { FolderOpen, FileSpreadsheet } from 'lucide-react'
import { Link } from 'react-router-dom'

export const ExportPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Excel & Roster Export"
        description="Extract verified admission tables, sync master templates, and download finalized cohort spreadsheets."
      />

      <EmptyState
        title="Batch Excel Templates"
        description="Master Excel spreadsheets are generated and synced per admission batch section. Navigate to your admission batches to download the populated roster workbooks."
        icon={<FileSpreadsheet className="h-8 w-8 text-primary" />}
        action={
          <Link to="/batches">
            <Button variant="primary" size="sm" className="gap-2">
              <FolderOpen className="h-4 w-4" />
              <span>View Admission Batches</span>
            </Button>
          </Link>
        }
      />
    </div>
  )
}
