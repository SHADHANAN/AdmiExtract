import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/ui/Button'
import { Card, CardContent } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { useBatchStore } from '../store/useBatchStore'
import {
  FileText,
  Plus,
  ArrowRight,
  CheckCircle,
  FolderOpen,
  Layers,
  Settings2,
} from 'lucide-react'

export const DocumentsPage: React.FC = () => {
  const navigate = useNavigate()
  const { batches, fetchBatches } = useBatchStore()
  const [selectedBatchId, setSelectedBatchId] = useState<string>('')

  useEffect(() => {
    fetchBatches()
  }, [fetchBatches])

  useEffect(() => {
    if (batches.length > 0 && !selectedBatchId) {
      setSelectedBatchId(batches[0].id)
    }
  }, [batches, selectedBatchId])

  const currentBatch = batches.find((b) => b.id === selectedBatchId) || batches[0]
  const docRequirements = currentBatch?.docRequirements || []

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <PageHeader
          title="Document Configuration"
          description="Manage required certificates, ID documents, and wanted field extraction mappings for admission cohorts."
        />

        {batches.length > 0 && (
          <div className="flex items-center gap-2.5 bg-card border border-border p-2 rounded-xl shadow-2xs">
            <span className="text-xs font-bold text-muted-foreground uppercase flex items-center gap-1.5 pl-1">
              <FolderOpen className="h-4 w-4 text-primary" /> Batch:
            </span>
            <select
              value={selectedBatchId}
              onChange={(e) => setSelectedBatchId(e.target.value)}
              className="px-3 py-1.5 rounded-lg border border-border bg-background text-xs font-bold text-foreground focus:outline-none focus:ring-2 focus:ring-primary cursor-pointer"
            >
              {batches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.academicYear})
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {batches.length === 0 ? (
        <EmptyState
          title="No Admission Batches Found"
          description="Create your first admission batch to configure required documents and wanted fields."
          icon={<FolderOpen className="h-12 w-12 text-muted-foreground/60" />}
          action={
            <Button variant="primary" onClick={() => navigate('/batches')} className="cursor-pointer">
              Go to Batches
            </Button>
          }
        />
      ) : docRequirements.length === 0 ? (
        <Card className="border border-dashed border-border bg-card/60 p-10 text-center rounded-2xl">
          <CardContent className="flex flex-col items-center justify-center space-y-4 p-0">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <FileText className="h-7 w-7" />
            </div>
            <div className="space-y-1.5 max-w-md">
              <h3 className="text-base font-bold text-foreground">No document types configured yet.</h3>
              <p className="text-xs text-muted-foreground">
                Add your institution's document requirements (e.g., Aadhaar Card, 10th Marksheet, Transfer Certificate) to start collecting candidate files.
              </p>
            </div>
            <Button
              variant="primary"
              onClick={() => navigate(`/batches/${currentBatch.id}`)}
              className="cursor-pointer gap-2 text-xs py-2 px-4 shadow-sm"
            >
              <Plus className="h-4 w-4" /> Add Document Type
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Layers className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-bold text-foreground uppercase tracking-wider">
                Configured Requirements ({docRequirements.length})
              </h3>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate(`/batches/${currentBatch.id}`)}
              className="gap-1.5 text-xs font-semibold"
            >
              <Settings2 className="h-3.5 w-3.5" />
              Manage Configuration
            </Button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {docRequirements.map((doc) => {
              const isMandatory = doc.required !== false
              return (
                <Card key={doc.id || doc.name} className="border border-border bg-card p-5 rounded-xl shadow-2xs hover:shadow-xs transition-shadow">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                      <div className="p-2.5 rounded-lg bg-primary/10 text-primary shrink-0 mt-0.5">
                        <FileText className="h-5 w-5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h4 className="text-sm font-bold text-foreground truncate">{doc.name}</h4>
                        <div className="flex items-center gap-2 mt-1">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-md text-3xs font-extrabold uppercase tracking-wider ${
                              isMandatory
                                ? 'bg-destructive/10 text-destructive border border-destructive/15'
                                : 'bg-primary/10 text-primary border border-primary/15'
                            }`}
                          >
                            {isMandatory ? 'Mandatory' : 'Optional'}
                          </span>
                          <span className="text-3xs font-mono text-muted-foreground">
                            Max {doc.maxSizeMb || 5}MB
                          </span>
                        </div>
                        {doc.description && (
                          <p className="text-xs text-muted-foreground mt-2 line-clamp-2">{doc.description}</p>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="mt-4 pt-3 border-t border-border flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5 text-emerald-600 font-semibold text-3xs">
                      <CheckCircle className="h-3.5 w-3.5" /> Active for Batch
                    </div>
                    <button
                      onClick={() => navigate(`/batches/${currentBatch.id}`)}
                      className="inline-flex items-center gap-1 text-xs font-bold text-primary hover:underline cursor-pointer"
                    >
                      Configure <ArrowRight className="h-3 w-3" />
                    </button>
                  </div>
                </Card>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
