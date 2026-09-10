import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card'
import { Modal } from '../components/ui/Modal'
import { useBatchStore } from '../store/useBatchStore'
import { useToastStore } from '../store/useToastStore'
import { FolderOpen, Plus, Search, Calendar, Share2, Layers, Edit3, Trash2 } from 'lucide-react'

import { api } from '../services/api'
import { copyToClipboard } from '../utils/clipboard'
import type { BatchClass, Batch } from '../types'

export const Batches: React.FC = () => {
  const navigate = useNavigate()
  const { batches, addBatch, updateBatch, deleteBatch, fetchBatches, uploadLinks, fetchUploadLinks, createClass } = useBatchStore()
  const { addToast } = useToastStore()

  // Filter and Search states
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedDept, setSelectedDept] = useState('')
  const [selectedYear, setSelectedYear] = useState('')
  const [selectedStatus, setSelectedStatus] = useState('')

  // Create Batch Modal Dialog states
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [newBatchName, setNewBatchName] = useState('')
  const [newBatchDept, setNewBatchDept] = useState('AIML')
  const [newBatchYear, setNewBatchYear] = useState('2025-2029')
  const [newBatchDesc, setNewBatchDesc] = useState('')
  const [newBatchStart, setNewBatchStart] = useState('')
  const [newBatchEnd, setNewBatchEnd] = useState('')
  const [newBatchStatus, setNewBatchStatus] = useState<'active' | 'closed'>('active')

  // Create Class Modal Dialog states
  const [isClassModalOpen, setIsClassModalOpen] = useState(false)
  const [activeBatchForClass] = useState<string | null>(null)
  const [newClassName, setNewClassName] = useState('')
  const [newClassDept, setNewClassDept] = useState('')
  const [newClassSection, setNewClassSection] = useState('A')
  const [newClassYear, setNewClassYear] = useState('')

  // Edit Batch Modal Dialog states
  const [isEditModalOpen, setIsEditModalOpen] = useState(false)
  const [editingBatchId, setEditingBatchId] = useState<string | null>(null)
  const [editBatchName, setEditBatchName] = useState('')
  const [editBatchDept, setEditBatchDept] = useState('AIML')
  const [editBatchYear, setEditBatchYear] = useState('2025-2029')
  const [editBatchDesc, setEditBatchDesc] = useState('')
  const [editBatchStart, setEditBatchStart] = useState('')
  const [editBatchEnd, setEditBatchEnd] = useState('')
  const [editBatchStatus, setEditBatchStatus] = useState<'active' | 'closed' | 'archived'>('active')

  const [availableDepts, setAvailableDepts] = useState<any[]>([])

  React.useEffect(() => {
    fetchBatches()
    fetchUploadLinks()
  }, [fetchBatches, fetchUploadLinks])

  React.useEffect(() => {
    const loadDepts = async () => {
      try {
        const res = await api.get('/departments')
        setAvailableDepts(res.data)
        if (res.data.length > 0) {
          setNewBatchDept(res.data[0].code)
        }
      } catch (err) {
        setAvailableDepts([
          { id: '1', name: 'Artificial Intelligence & Machine Learning', code: 'AIML' },
          { id: '2', name: 'Computer Science & Engineering', code: 'CSE' },
          { id: '3', name: 'Electronics & Communication Engineering', code: 'ECE' }
        ])
        setNewBatchDept('AIML')
      }
    }
    loadDepts()
  }, [])

  const handleCreateBatch = (e: React.FormEvent) => {
    e.preventDefault()
    if (!newBatchName.trim()) {
      addToast('Batch name cannot be empty', 'error')
      return
    }

    addBatch({
      name: newBatchName,
      department: newBatchDept,
      academicYear: newBatchYear,
      description: newBatchDesc,
      startDate: newBatchStart || undefined,
      endDate: newBatchEnd || undefined,
      status: newBatchStatus,
    })

    addToast(`Batch "${newBatchName}" created successfully!`, 'success')
    setIsModalOpen(false)

    // Clear fields
    setNewBatchName('')
    setNewBatchDesc('')
    setNewBatchStart('')
    setNewBatchEnd('')
  }

  const openEditModal = (batch: Batch) => {
    setEditingBatchId(batch.id)
    setEditBatchName(batch.name)
    setEditBatchDept(batch.department)
    setEditBatchYear(batch.academicYear)
    setEditBatchDesc(batch.description || '')
    setEditBatchStart(batch.startDate || '')
    setEditBatchEnd(batch.endDate || '')
    setEditBatchStatus(batch.status)
    setIsEditModalOpen(true)
  }

  const handleUpdateBatch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingBatchId || !editBatchName.trim()) {
      addToast('Batch name cannot be empty', 'error')
      return
    }

    try {
      await updateBatch(editingBatchId, {
        name: editBatchName,
        department: editBatchDept,
        academicYear: editBatchYear,
        description: editBatchDesc,
        startDate: editBatchStart || undefined,
        endDate: editBatchEnd || undefined,
        status: editBatchStatus,
      })
      addToast(`Batch "${editBatchName}" updated successfully!`, 'success')
      setIsEditModalOpen(false)
    } catch (err: any) {
      addToast(err?.response?.data?.detail || 'Failed to update batch', 'error')
    }
  }

  const handleCreateClass = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!activeBatchForClass) return

    const sectionStr = newClassSection.trim() || 'A'
    let classNameToSubmit = newClassName.trim()
    if (!classNameToSubmit) {
      classNameToSubmit = sectionStr.toLowerCase().startsWith('section') ? sectionStr : `Section ${sectionStr}`
    }

    try {
      await createClass(activeBatchForClass, {
        class_name: classNameToSubmit,
        department: newClassDept.trim() || 'General',
        section: sectionStr,
        academic_year: newClassYear.trim() || '2025-2026',
      })
      addToast(`Class "${classNameToSubmit}" created successfully!`, 'success')
      setIsClassModalOpen(false)
      setNewClassName('')
    } catch (err: any) {
      const errMsg = err?.response?.data?.detail || 'Failed to create class.'
      addToast(errMsg, 'error')
    }
  }

  // Filter batches
  const filteredBatches = batches.filter((batch) => {
    const matchesSearch = batch.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                          batch.department.toLowerCase().includes(searchTerm.toLowerCase())
    const matchesDept = selectedDept ? batch.department === selectedDept : true
    const matchesYear = selectedYear ? batch.academicYear === selectedYear : true
    const matchesStatus = selectedStatus ? batch.status === selectedStatus : true

    return matchesSearch && matchesDept && matchesYear && matchesStatus
  })

  // Extract unique departments and academic years for filter dropdowns
  const uniqueDepts = Array.from(new Set(batches.map((b) => b.department)))
  const uniqueYears = Array.from(new Set(batches.map((b) => b.academicYear)))

  return (
    <div className="space-y-6">
      <PageHeader
        title="Admission Batches"
        description="Monitor student cohorts, manage multiple classes within batches, and configure link options."
        action={
          <Button variant="primary" onClick={() => setIsModalOpen(true)} className="cursor-pointer">
            <Plus className="mr-2 h-4 w-4" /> New Batch
          </Button>
        }
      />

      {/* Search & Filter Controls */}
      <div className="flex flex-col md:flex-row gap-3.5 bg-[#0F172A]/70 p-4 rounded-2xl border border-white/[0.08] shadow-lg shadow-black/20">
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search admission cohorts by name..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-white/[0.08] rounded-xl bg-[#111827]/80 text-sm text-white placeholder:text-slate-500 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 hover:border-white/[0.18]"
          />
        </div>

        <div className="flex flex-wrap gap-2.5">
          <select
            value={selectedDept}
            onChange={(e) => setSelectedDept(e.target.value)}
            className="px-3.5 py-2 border border-white/[0.08] rounded-xl bg-[#111827]/80 text-xs font-semibold text-white transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 hover:border-white/[0.18] cursor-pointer"
          >
            <option value="" className="bg-[#111827] text-white">All Departments</option>
            {uniqueDepts.map((d) => (
              <option key={d} value={d} className="bg-[#111827] text-white">{d}</option>
            ))}
          </select>

          <select
            value={selectedYear}
            onChange={(e) => setSelectedYear(e.target.value)}
            className="px-3.5 py-2 border border-white/[0.08] rounded-xl bg-[#111827]/80 text-xs font-semibold text-white transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 hover:border-white/[0.18] cursor-pointer"
          >
            <option value="" className="bg-[#111827] text-white">All Academic Years</option>
            {uniqueYears.map((y) => (
              <option key={y} value={y} className="bg-[#111827] text-white">{y}</option>
            ))}
          </select>

          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value)}
            className="px-3.5 py-2 border border-white/[0.08] rounded-xl bg-[#111827]/80 text-xs font-semibold text-white transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 hover:border-white/[0.18] cursor-pointer"
          >
            <option value="" className="bg-[#111827] text-white">All Statuses</option>
            <option value="active" className="bg-[#111827] text-white">Active</option>
            <option value="closed" className="bg-[#111827] text-white">Closed</option>
            <option value="archived" className="bg-[#111827] text-white">Archived</option>
          </select>
        </div>
      </div>

      {/* Batch Cards Grid */}
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {filteredBatches.map((batch) => {
          const statusColors = {
            active: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
            closed: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
            archived: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
          }

          const classesList: BatchClass[] = batch.classes || []

          return (
            <Card
              key={batch.id}
              onClick={() => navigate(`/batches/${batch.id}`)}
              className="group relative flex flex-col justify-between hover:shadow-2xl hover:shadow-indigo-500/10 transition-all duration-300 hover:-translate-y-1 cursor-pointer rounded-2xl border border-white/[0.08] overflow-hidden bg-[#111827]"
            >
              <div className="h-1.5 w-full bg-gradient-to-r from-indigo-500 via-indigo-600 to-purple-600" />
              
              <CardHeader className="pb-3">
                <div className="flex justify-between items-start">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-400 border border-indigo-500/25 shadow-xs">
                    <FolderOpen className="h-5 w-5" />
                  </div>
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${statusColors[batch.status]}`}>
                    {batch.status}
                  </span>
                </div>
                <div className="mt-3">
                  <CardTitle className="text-lg font-bold text-white group-hover:text-indigo-400 transition-colors truncate">
                    {batch.name}
                  </CardTitle>
                  <CardDescription className="text-xs font-semibold uppercase tracking-wider text-slate-400 mt-1">
                    {batch.department}
                  </CardDescription>
                </div>
              </CardHeader>

              <CardContent className="space-y-4 pt-0">
                <p className="text-xs text-slate-400 line-clamp-2 leading-relaxed min-h-[2rem]">
                  {batch.description || 'Institutional admission batch cohort.'}
                </p>

                {/* Batch Section Summary Indicator */}
                <div className="bg-[#0F172A]/80 p-2.5 rounded-xl border border-white/[0.08] flex items-center justify-between text-xs font-semibold text-white">
                  <div className="flex items-center gap-2">
                    <Layers className="h-3.5 w-3.5 text-indigo-400" />
                    <span>Dept: <strong className="text-indigo-400">{batch.department}</strong></span>
                  </div>
                  <span className="px-2 py-0.5 rounded-md bg-indigo-500/15 text-indigo-300 border border-indigo-500/20 text-[11px] font-bold">
                    {classesList.length} {classesList.length === 1 ? 'Section' : 'Sections'}
                  </span>
                </div>

                {/* Real Stats Section (No Fake Analytics) */}
                <div className="grid grid-cols-4 gap-1.5 bg-[#0F172A]/50 p-2.5 rounded-xl border border-white/[0.06] text-center">
                  <div>
                    <div className="text-[10px] uppercase font-semibold text-slate-500">Students</div>
                    <div className="text-sm font-bold text-white mt-0.5">{batch.stats.students}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase font-semibold text-slate-500">Pending</div>
                    <div className="text-sm font-bold text-amber-400 mt-0.5">{batch.stats.pending}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase font-semibold text-slate-500">Verified</div>
                    <div className="text-sm font-bold text-emerald-400 mt-0.5">{batch.stats.verified}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase font-semibold text-slate-500">Rejected</div>
                    <div className="text-sm font-bold text-rose-400 mt-0.5">{batch.stats.rejected}</div>
                  </div>
                </div>

                <div className="flex justify-between items-center text-xs text-slate-400 pt-3 border-t border-white/[0.08]">
                  <div className="flex items-center gap-1.5 font-medium">
                    <Calendar className="h-3.5 w-3.5 text-indigo-400" />
                    <span>{batch.academicYear}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        e.stopPropagation()
                        navigate(`/batches/${batch.id}`)
                      }}
                      className="cursor-pointer text-xs"
                    >
                      Open
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async (e) => {
                        e.stopPropagation()
                        const uploadLink = uploadLinks.find((l) => l.batchId === batch.id && l.isActive) || uploadLinks.find((l) => l.batchId === batch.id)
                        const slug = uploadLink?.slug || uploadLink?.token
                        if (!slug || slug === 'undefined' || slug === 'null' || !slug.trim()) {
                          addToast('Upload link could not be generated.', 'error')
                          return
                        }
                        const url = `${window.location.origin}/upload/${slug}`
                        try {
                          await copyToClipboard(url)
                          addToast('Upload portal URL copied to clipboard!', 'success')
                        } catch (err) {
                          console.error('Failed to copy portal URL:', err)
                          addToast('Failed to copy link to clipboard.', 'error')
                        }
                      }}
                      className="cursor-pointer p-1.5"
                      title="Share Portal Link"
                    >
                      <Share2 className="h-4 w-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={(e) => {
                        e.stopPropagation()
                        openEditModal(batch)
                      }}
                      className="cursor-pointer p-1.5 text-muted-foreground hover:text-foreground"
                      title="Edit Batch"
                    >
                      <Edit3 className="h-4 w-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async (e) => {
                        e.stopPropagation()
                        if (window.confirm(`Are you sure you want to delete batch "${batch.name}"?`)) {
                          try {
                            await deleteBatch(batch.id)
                            addToast(`Batch "${batch.name}" deleted successfully!`, 'success')
                          } catch (err: any) {
                            addToast(err?.response?.data?.detail || 'Failed to delete batch', 'error')
                          }
                        }
                      }}
                      className="cursor-pointer p-1.5 text-muted-foreground hover:text-destructive"
                      title="Delete Batch"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {filteredBatches.length === 0 && (
        <div className="flex flex-col items-center justify-center p-12 text-center bg-card rounded-2xl border border-dashed border-border/80">
          <FolderOpen className="h-12 w-12 text-muted-foreground/60 mb-3" />
          <h3 className="text-base font-bold text-foreground tracking-tight">No cohorts found</h3>
          <p className="text-sm text-muted-foreground mt-1 max-w-sm">Try updating your search query or criteria filters to locate admission batches.</p>
        </div>
      )}

      {/* Create Batch Modal Dialog */}
      <Modal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} title="Create New Admission Batch">
        <form onSubmit={handleCreateBatch} className="space-y-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Department
            </label>
            <select
              value={newBatchDept}
              onChange={(e) => setNewBatchDept(e.target.value)}
              className="flex h-10 w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {availableDepts.map((d) => (
                <option key={d.code} value={d.code}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>

          <Input
            label="Batch Name"
            type="text"
            placeholder="CSE 2025-2029"
            value={newBatchName}
            onChange={(e) => setNewBatchName(e.target.value)}
            required
          />

          <Input
            label="Academic Year"
            type="text"
            placeholder="2025-2029"
            value={newBatchYear}
            onChange={(e) => setNewBatchYear(e.target.value)}
            required
          />

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Description
            </label>
            <textarea
              placeholder="Provide a brief description of the batch intakes..."
              value={newBatchDesc}
              onChange={(e) => setNewBatchDesc(e.target.value)}
              className="flex min-h-[80px] w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Admission Start Date"
              type="date"
              value={newBatchStart}
              onChange={(e) => setNewBatchStart(e.target.value)}
            />
            <Input
              label="Admission End Date"
              type="date"
              value={newBatchEnd}
              onChange={(e) => setNewBatchEnd(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Status
            </label>
            <select
              value={newBatchStatus}
              onChange={(e) => setNewBatchStatus(e.target.value as 'active' | 'closed')}
              className="flex h-10 w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="active">Active</option>
              <option value="closed">Closed</option>
            </select>
          </div>

          <div className="flex justify-end gap-3 pt-4 border-t border-border">
            <Button type="button" variant="outline" onClick={() => setIsModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary">
              Create Cohort
            </Button>
          </div>
        </form>
      </Modal>

      {/* Create Class Modal Dialog */}
      <Modal isOpen={isClassModalOpen} onClose={() => setIsClassModalOpen(false)} title="Create Class in Batch">
        <form onSubmit={handleCreateClass} className="space-y-4">
          <Input
            label="Class / Section Name (Optional)"
            type="text"
            placeholder="e.g. Section A (leave blank to auto-generate from section)"
            value={newClassName}
            onChange={(e) => setNewClassName(e.target.value)}
          />

          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Department"
              type="text"
              placeholder="e.g. Computer Science"
              value={newClassDept}
              onChange={(e) => setNewClassDept(e.target.value)}
              required
            />
            <Input
              label="Section"
              type="text"
              placeholder="e.g. A"
              value={newClassSection}
              onChange={(e) => setNewClassSection(e.target.value)}
              required
            />
          </div>

          <Input
            label="Academic Year"
            type="text"
            placeholder="e.g. 2025-2026"
            value={newClassYear}
            onChange={(e) => setNewClassYear(e.target.value)}
            required
          />

          <div className="flex justify-end gap-3 pt-4 border-t border-border">
            <Button type="button" variant="outline" onClick={() => setIsClassModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary">
              Create Class
            </Button>
          </div>
        </form>
      </Modal>

      {/* Edit Batch Modal Dialog */}
      <Modal isOpen={isEditModalOpen} onClose={() => setIsEditModalOpen(false)} title="Edit Admission Batch">
        <form onSubmit={handleUpdateBatch} className="space-y-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Department
            </label>
            <select
              value={editBatchDept}
              onChange={(e) => setEditBatchDept(e.target.value)}
              className="flex h-10 w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {availableDepts.map((d) => (
                <option key={d.code} value={d.code}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>

          <Input
            label="Batch Name"
            type="text"
            placeholder="CSE 2025-2029"
            value={editBatchName}
            onChange={(e) => setEditBatchName(e.target.value)}
            required
          />

          <Input
            label="Academic Year"
            type="text"
            placeholder="2025-2029"
            value={editBatchYear}
            onChange={(e) => setEditBatchYear(e.target.value)}
            required
          />

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Description
            </label>
            <textarea
              placeholder="Brief description of the admissions batch..."
              value={editBatchDesc}
              onChange={(e) => setEditBatchDesc(e.target.value)}
              className="flex min-h-[80px] w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Admission Start Date"
              type="date"
              value={editBatchStart}
              onChange={(e) => setEditBatchStart(e.target.value)}
            />
            <Input
              label="Admission End Date"
              type="date"
              value={editBatchEnd}
              onChange={(e) => setEditBatchEnd(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Status
            </label>
            <select
              value={editBatchStatus}
              onChange={(e) => setEditBatchStatus(e.target.value as 'active' | 'closed' | 'archived')}
              className="flex h-10 w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="active">Active</option>
              <option value="closed">Closed</option>
              <option value="archived">Archived</option>
            </select>
          </div>

          <div className="flex justify-end gap-3 pt-4 border-t border-border">
            <Button type="button" variant="outline" onClick={() => setIsEditModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary">
              Save Changes
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
