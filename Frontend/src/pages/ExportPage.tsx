import React, { useState, useEffect } from 'react'
import { PageHeader } from '../components/PageHeader'
import { Card, CardHeader, CardContent } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { useStudentStore } from '../store/useStudentStore'
import { useBatchStore } from '../store/useBatchStore'
import { useToastStore } from '../store/useToastStore'
import { excelTemplateService } from '../services/excelTemplate'
import {
  FileSpreadsheet,
  Download,
  CheckCircle2,
  Users,
  Clock,
  XCircle,
  FolderOpen,
  Check,
} from 'lucide-react'

export const ExportPage: React.FC = () => {
  const { submissions, fetchAllSubmissions } = useStudentStore()
  const { batches, fetchBatches } = useBatchStore()
  const { addToast } = useToastStore()

  useEffect(() => {
    fetchAllSubmissions()
    fetchBatches()
  }, [fetchAllSubmissions, fetchBatches])

  const [selectedBatchId, setSelectedBatchId] = useState<string>('')
  const [isExporting, setIsExporting] = useState(false)
  const [lastExport, setLastExport] = useState<{
    filename: string
    recordCount: number
    timestamp: string
  } | null>(null)

  // Default to first batch
  useEffect(() => {
    if (!selectedBatchId && batches.length > 0) {
      setSelectedBatchId(batches[0].id)
    }
  }, [batches, selectedBatchId])

  const currentBatch = batches.find((b) => b.id === selectedBatchId) || (batches.length > 0 ? batches[0] : null)

  // Filter submissions by current batch or all
  const batchSubmissions = currentBatch
    ? submissions.filter((s) => s.batchId === currentBatch.id || s.batchName === currentBatch.name)
    : submissions

  const totalStudents = batchSubmissions.length
  const verifiedCount = batchSubmissions.filter((s) => s.status === 'Verified').length
  const pendingCount = batchSubmissions.filter(
    (s) => s.status === 'Verification Pending' || s.status === 'Submitted' || s.status === 'AI Processing'
  ).length
  const rejectedCount = batchSubmissions.filter((s) => s.status === 'Rejected').length

  const handleExport = async () => {
    if (!currentBatch) {
      addToast('Please select a valid admission batch first.', 'error')
      return
    }

    setIsExporting(true)
    try {
      const filename = `${currentBatch.name.replace(/\s+/g, '_')}_Student_Roster.xlsx`
      await excelTemplateService.downloadExcel(currentBatch.id, filename)

      setLastExport({
        filename,
        recordCount: verifiedCount > 0 ? verifiedCount : totalStudents,
        timestamp: new Date().toLocaleString(),
      })

      addToast(`Successfully generated ${filename}`, 'success')
    } catch (err: any) {
      addToast(
        err?.response?.data?.detail || 'Failed to generate Excel export. Ensure a template is configured.',
        'error'
      )
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <PageHeader
        title="Excel Export"
        description="Generate and download finalized student admission workbooks pre-populated with verified document extraction fields."
      />

      {/* Cohort Selection Card */}
      <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-2xs flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-50 text-[#065f46] border border-emerald-200 shrink-0">
            <FolderOpen className="h-5 w-5" />
          </div>
          <div>
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider block">
              Admission Cohort
            </span>
            <span className="text-sm font-bold text-slate-900">
              {currentBatch ? currentBatch.name : 'All Batches'}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs font-semibold text-slate-600">Switch Batch:</label>
          <select
            value={selectedBatchId}
            onChange={(e) => {
              setSelectedBatchId(e.target.value)
              setLastExport(null)
            }}
            className="h-9 rounded-lg border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-700 hover:border-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-600/20 focus:border-[#065f46] cursor-pointer"
          >
            {batches.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name} ({b.academicYear || 'Cohort'})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* 4 Summary Statistics Cards: Total Students, Verified, Pending, Rejected */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Total Students */}
        <Card className="border-slate-200">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Total Students
            </span>
            <div className="p-2 rounded-lg bg-slate-100 text-slate-700 border border-slate-200">
              <Users className="h-4 w-4" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-extrabold text-slate-900 font-mono mt-1">
              {totalStudents}
            </div>
            <p className="text-[11px] text-slate-500 mt-0.5">Total registered candidates</p>
          </CardContent>
        </Card>

        {/* Verified */}
        <Card className="border-slate-200">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <span className="text-xs font-bold text-emerald-800 uppercase tracking-wider">
              Verified
            </span>
            <div className="p-2 rounded-lg bg-emerald-50 text-[#065f46] border border-emerald-200">
              <CheckCircle2 className="h-4 w-4" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-extrabold text-[#065f46] font-mono mt-1">
              {verifiedCount}
            </div>
            <p className="text-[11px] text-slate-500 mt-0.5">Approved for final roster</p>
          </CardContent>
        </Card>

        {/* Pending */}
        <Card className="border-slate-200">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <span className="text-xs font-bold text-amber-700 uppercase tracking-wider">
              Pending
            </span>
            <div className="p-2 rounded-lg bg-amber-50 text-amber-700 border border-amber-200">
              <Clock className="h-4 w-4" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-extrabold text-amber-800 font-mono mt-1">
              {pendingCount}
            </div>
            <p className="text-[11px] text-slate-500 mt-0.5">Awaiting staff review</p>
          </CardContent>
        </Card>

        {/* Rejected */}
        <Card className="border-slate-200">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <span className="text-xs font-bold text-rose-700 uppercase tracking-wider">
              Rejected
            </span>
            <div className="p-2 rounded-lg bg-rose-50 text-rose-700 border border-rose-200">
              <XCircle className="h-4 w-4" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-extrabold text-rose-800 font-mono mt-1">
              {rejectedCount}
            </div>
            <p className="text-[11px] text-slate-500 mt-0.5">Flagged for re-upload</p>
          </CardContent>
        </Card>
      </div>

      {/* Export Action Card */}
      <Card className="border-slate-200 p-6 sm:p-8 bg-white shadow-xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-6">
          <div className="space-y-1.5 max-w-xl">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-emerald-50 text-[#065f46] border border-emerald-200 text-xs font-bold">
              <FileSpreadsheet className="h-3.5 w-3.5" />
              <span>Production Roster Sync</span>
            </div>
            <h3 className="text-lg font-bold text-slate-900">
              Export Roster to Master Excel Template
            </h3>
            <p className="text-xs sm:text-sm text-slate-500 leading-relaxed">
              Downloads the official cohort workbook populated with verified admission numbers, candidate names, dates of birth, community reservation categories, and extracted certificate records.
            </p>
          </div>

          <Button
            variant="primary"
            size="lg"
            isLoading={isExporting}
            onClick={handleExport}
            className="gap-2 shrink-0 font-semibold px-6 shadow-xs h-11"
          >
            <Download className="h-4 w-4 text-lime-300" />
            <span>Export Excel</span>
          </Button>
        </div>

        {/* Post-Export Success Confirmation Banner */}
        {lastExport && (
          <div className="mt-6 p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-slate-900 space-y-2 animate-in fade-in duration-200">
            <div className="flex items-center gap-2 text-emerald-800 font-bold text-sm">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-700 text-lime-300">
                <Check className="h-3.5 w-3.5" />
              </div>
              <span>Export completed</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 text-xs border-t border-emerald-200/60 font-medium">
              <div>
                <span className="text-emerald-700 block">Filename</span>
                <strong className="text-slate-900 font-mono">{lastExport.filename}</strong>
              </div>
              <div>
                <span className="text-emerald-700 block">Record count</span>
                <strong className="text-slate-900 font-mono">{lastExport.recordCount} students</strong>
              </div>
              <div>
                <span className="text-emerald-700 block">Timestamp</span>
                <strong className="text-slate-900">{lastExport.timestamp}</strong>
              </div>
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}
