import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PageHeader } from '../components/PageHeader'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card'
import { Modal } from '../components/ui/Modal'
import { EmptyState } from '../components/ui/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { useToastStore } from '../store/useToastStore'
import { departmentService } from '../services/department'
import { Building2, Plus, Calendar, ShieldCheck, Search, Edit2, Trash2 } from 'lucide-react'

export const Departments: React.FC = () => {
  const queryClient = useQueryClient()
  const { addToast } = useToastStore()

  // Search & Filter state
  const [searchTerm, setSearchTerm] = useState('')

  // Modal Dialog states
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [selectedDeptId, setSelectedDeptId] = useState<string | null>(null)
  
  // Form input states
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  const [isActive, setIsActive] = useState(true)

  // 1. Fetch departments list
  const { data: departments = [], isLoading, isError, error } = useQuery({
    queryKey: ['departments'],
    queryFn: departmentService.getAll,
  })

  // 2. Create department mutation
  const createMutation = useMutation({
    mutationFn: departmentService.create,
    onSuccess: (newDept) => {
      queryClient.invalidateQueries({ queryKey: ['departments'] })
      addToast(`Department "${newDept.name}" created!`, 'success')
      setIsCreateOpen(false)
      setName('')
      setCode('')
      setDescription('')
    },
    onError: (err: any) => {
      addToast(err?.message || 'Failed to create department.', 'error')
    },
  })

  // 3. Update department mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => departmentService.update(id, data),
    onSuccess: (updatedDept) => {
      queryClient.invalidateQueries({ queryKey: ['departments'] })
      addToast(`Department "${updatedDept.name}" updated successfully!`, 'success')
      setIsEditOpen(false)
      setSelectedDeptId(null)
      setName('')
      setCode('')
      setDescription('')
    },
    onError: (err: any) => {
      addToast(err?.message || 'Failed to update department.', 'error')
    },
  })

  // 4. Delete department mutation
  const deleteMutation = useMutation({
    mutationFn: departmentService.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['departments'] })
      addToast('Department deleted successfully', 'success')
    },
    onError: (err: any) => {
      addToast(err?.message || 'Failed to delete department.', 'error')
    },
  })

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || !code.trim()) return
    createMutation.mutate({ name, code: code.trim().toUpperCase(), description })
  }

  const handleEditClick = (dept: any) => {
    setSelectedDeptId(dept.id)
    setName(dept.name)
    setCode(dept.code || '')
    setDescription(dept.description || '')
    setIsActive(dept.is_active)
    setIsEditOpen(true)
  }

  const handleEditSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedDeptId || !name.trim() || !code.trim()) return
    updateMutation.mutate({
      id: selectedDeptId,
      data: { name, code: code.trim().toUpperCase(), description, is_active: isActive },
    })
  }

  const handleDeleteClick = (id: string) => {
    if (window.confirm('Are you sure you want to delete this department?')) {
      deleteMutation.mutate(id)
    }
  }

  // Filter list locally by search term
  const filteredDepts = departments.filter((d) =>
    d.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (d.description && d.description.toLowerCase().includes(searchTerm.toLowerCase()))
  )

  return (
    <div className="space-y-6">
      <PageHeader
        title="Departments"
        description="Organize courses and intake sessions into departmental subdivisions."
        action={
          <Button variant="primary" onClick={() => setIsCreateOpen(true)} className="cursor-pointer">
            <Plus className="mr-2 h-4 w-4" /> Add Department
          </Button>
        }
      />

      {/* Search Bar */}
      <div className="relative w-full max-w-md">
        <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
        <input
          type="text"
          placeholder="Search departments by name..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full pl-9 pr-4 py-2 border border-border rounded-lg bg-card text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </div>

      {/* Loading & Error States */}
      {isLoading && <LoadingSpinner className="h-10 w-10 mx-auto mt-12" />}
      
      {isError && (
        <div className="p-4 rounded-lg bg-destructive/10 border border-destructive text-destructive text-sm max-w-lg mx-auto text-center">
          Error loading departments: {error?.message || 'Unknown network error.'}
        </div>
      )}

      {/* Grid Display */}
      {!isLoading && !isError && (
        <>
          {filteredDepts.length > 0 ? (
            <div className="grid gap-6 md:grid-cols-3">
              {filteredDepts.map((dept) => (
<<<<<<< HEAD
                <Card key={dept.id} className="relative hover:-translate-y-1 hover:shadow-2xl hover:shadow-indigo-500/10 transition-all duration-300 flex flex-col justify-between overflow-hidden border border-white/[0.08] bg-[#111827]">
                  <div className="h-1.5 w-full bg-gradient-to-r from-indigo-500 via-indigo-600 to-purple-600" />
                  
                  <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2 mt-2">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/15 text-indigo-400 border border-indigo-500/25 shadow-xs">
=======
                <Card key={dept.id} className="relative hover:shadow-md transition-shadow flex flex-col justify-between overflow-hidden">
                  <div className="h-1 w-full bg-indigo-500" />
                  
                  <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2 mt-2">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-600">
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
                      <Building2 className="h-5 w-5" />
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
<<<<<<< HEAD
                        dept.is_active ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-500/10 text-slate-400 border border-slate-500/20'
=======
                        dept.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
                      }`}>
                        {dept.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div>
<<<<<<< HEAD
                      <CardTitle className="text-lg font-bold text-white">{dept.name} ({dept.code})</CardTitle>
                      <CardDescription className="mt-1.5 line-clamp-2 text-slate-400">
=======
                      <CardTitle className="text-lg font-bold">{dept.name} ({dept.code})</CardTitle>
                      <CardDescription className="mt-1.5 line-clamp-2">
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
                        {dept.description || 'No description provided.'}
                      </CardDescription>
                    </div>

<<<<<<< HEAD
                    <div className="border-t border-white/[0.08] pt-4 flex flex-col gap-2 text-xs text-slate-400">
                      <div className="flex items-center gap-1.5">
                        <ShieldCheck className="h-3.5 w-3.5 text-indigo-400" /> Created by: {dept.created_by}
                      </div>
                      <div className="flex items-center gap-1.5 justify-between">
                        <span className="flex items-center gap-1.5">
                          <Calendar className="h-3.5 w-3.5 text-indigo-400" /> Date: {new Date(dept.created_at).toLocaleDateString()}
=======
                    <div className="border-t border-border pt-4 flex flex-col gap-2 text-xs text-muted-foreground">
                      <div className="flex items-center gap-1.5">
                        <ShieldCheck className="h-3.5 w-3.5 text-indigo-500" /> Created by: {dept.created_by}
                      </div>
                      <div className="flex items-center gap-1.5 justify-between">
                        <span className="flex items-center gap-1.5">
                          <Calendar className="h-3.5 w-3.5" /> Date: {new Date(dept.created_at).toLocaleDateString()}
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
                        </span>
                        
                        {/* Action buttons */}
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => handleEditClick(dept)}
<<<<<<< HEAD
                            className="p-1 hover:bg-white/[0.08] rounded text-slate-400 hover:text-white cursor-pointer transition-colors"
                            title="Edit"
                          >
                            <Edit2 className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => handleDeleteClick(dept.id)}
                            className="p-1 hover:bg-red-500/10 rounded text-slate-400 hover:text-red-400 cursor-pointer transition-colors"
                            title="Delete"
                          >
                            <Trash2 className="h-4 w-4" />
=======
                            className="p-1 hover:bg-secondary rounded text-muted-foreground hover:text-foreground cursor-pointer"
                            title="Edit"
                          >
                            <Edit2 className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => handleDeleteClick(dept.id)}
                            className="p-1 hover:bg-destructive/10 rounded text-destructive cursor-pointer"
                            title="Delete"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
>>>>>>> 0a5dfd9cad8747310b83a8ec85613028abb6d2b4
                          </button>
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No Departments Cataloged"
              description={searchTerm ? 'No departments match search query.' : 'Click "Add Department" to register a departmental subdivision.'}
              icon={<Building2 className="h-12 w-12 text-muted-foreground/60" />}
            />
          )}
        </>
      )}

      {/* Add Department Modal Dialog */}
      <Modal isOpen={isCreateOpen} onClose={() => setIsCreateOpen(false)} title="Add New Department">
        <form onSubmit={handleCreateSubmit} className="space-y-4">
          <Input
            label="Department Name"
            type="text"
            placeholder="e.g. Mechanical Engineering"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />

          <Input
            label="Department Code"
            type="text"
            placeholder="e.g. MECH"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
          />

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Description
            </label>
            <textarea
              placeholder="e.g. Undergraduate curriculum and admission criteria..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="flex min-h-[80px] w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="flex justify-end gap-3 pt-4 border-t border-border">
            <Button type="button" variant="outline" onClick={() => {
              setIsCreateOpen(false)
              setName('')
              setDescription('')
            }}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" isLoading={createMutation.isPending}>
              Create Department
            </Button>
          </div>
        </form>
      </Modal>

      {/* Edit Department Modal Dialog */}
      <Modal isOpen={isEditOpen} onClose={() => setIsEditOpen(false)} title="Edit Department Details">
        <form onSubmit={handleEditSubmit} className="space-y-4">
          <Input
            label="Department Name"
            type="text"
            placeholder="e.g. Mechanical Engineering"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />

          <Input
            label="Department Code"
            type="text"
            placeholder="e.g. MECH"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
          />

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Description
            </label>
            <textarea
              placeholder="e.g. Undergraduate curriculum..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="flex min-h-[80px] w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Status
            </label>
            <select
              value={isActive ? 'active' : 'inactive'}
              onChange={(e) => setIsActive(e.target.value === 'active')}
              className="flex h-10 w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>

          <div className="flex justify-end gap-3 pt-4 border-t border-border">
            <Button type="button" variant="outline" onClick={() => {
              setIsEditOpen(false)
              setName('')
              setDescription('')
            }}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" isLoading={updateMutation.isPending}>
              Save Changes
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
