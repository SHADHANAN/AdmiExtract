import { create } from 'zustand'
import type { BatchState, Batch, UploadLink, DocumentRequirement, DocumentConfigurationVersion, BatchClass } from '../types'
import { batchService } from '../services/batch'
import { batchClassService } from '../services/batchClass'
import { api } from '../services/api'



const defaultRequirements: DocumentRequirement[] = [
  { id: 'req_1', name: 'Aadhaar Card', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, description: 'Upload front and back side of Aadhaar card', type: 'MANDATORY' },
  { id: 'req_2', name: 'SSLC Marksheet', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, description: '10th grade official marks statement', type: 'MANDATORY' },
  { id: 'req_3', name: 'HSC Marksheet', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, description: '12th grade / Diploma final marks statement', type: 'MANDATORY' },
  { id: 'req_4', name: 'Community Certificate', required: true, allowedTypes: ['PDF', 'JPG'], maxSizeMb: 5, description: 'Caste / Community reservation proof', type: 'MANDATORY' },
]

const initialDocVersions: Record<string, DocumentConfigurationVersion[]> = {}

const initialBatches: Batch[] = []

const initialLinks: UploadLink[] = []

export const useBatchStore = create<BatchState>((set, get) => ({
  batches: initialBatches,
  uploadLinks: initialLinks,
  docVersions: initialDocVersions,
  classesByBatch: {},

  fetchBatches: async () => {
    try {
      const data = await batchService.getAll()
      const formattedBatches = await Promise.all(
        data.map(async (b) => {
          let requirements: DocumentRequirement[] = []
          let version = 1
          try {
            const currentV = await batchService.getCurrentDocVersion(b.id)
            requirements = (currentV.documents || []).map((d: any) => ({
              id: d.id,
              name: d.name,
              required: d.required,
              allowedTypes: d.allowed_types || ['PDF', 'JPG', 'PNG'],
              maxSizeMb: d.max_size_mb || 5,
              description: d.description || '',
              type: d.type || 'MANDATORY',
            }))
            version = currentV.version || 1
          } catch {
            requirements = [...defaultRequirements]
          }

          // Fetch classes for this batch
          let classes: BatchClass[] = []
          try {
            classes = await batchClassService.getClassesByBatch(b.id)
          } catch {
            classes = []
          }

          // Fetch student submissions to calculate stats dynamically
          let submissions: any[] = []
          try {
            const subRes = await api.get(`/student-submissions/batch/${b.id}`)
            submissions = subRes.data || []
          } catch {
            // ignore
          }

          const stats = {
            students: submissions.length,
            pending: submissions.filter(
              (s) => s.submission_status === 'Verification Pending' || s.submission_status === 'Submitted' || s.submission_status === 'AI Processing'
            ).length,
            verified: submissions.filter((s) => s.submission_status === 'Verified').length,
            rejected: submissions.filter((s) => s.submission_status === 'Rejected').length,
          }

          return {
            id: b.id,
            name: b.name,
            department: b.department_id,
            academicYear: b.academic_year,
            description: b.description || '',
            startDate: b.start_date || '',
            endDate: b.end_date || '',
            status: b.status as any,
            stats,
            classes,
            currentDocVersion: version,
            docRequirements: requirements,
          }
        })
      )

      const classesMap: Record<string, BatchClass[]> = {}
      formattedBatches.forEach((b) => {
        if (b.classes) {
          classesMap[b.id] = b.classes
        }
      })

      set({ batches: formattedBatches, classesByBatch: classesMap })
    } catch (err) {
      console.warn('API connection failed. Using fallback mock batches.', err)
    }
  },

  fetchClassesForBatch: async (batchId: string) => {
    try {
      const classes = await batchClassService.getClassesByBatch(batchId)
      set((state) => ({
        classesByBatch: { ...state.classesByBatch, [batchId]: classes },
        batches: state.batches.map((b) => (b.id === batchId ? { ...b, classes } : b)),
      }))
      return classes
    } catch (err) {
      console.warn('Failed to fetch classes for batch', batchId, err)
      return get().classesByBatch[batchId] || []
    }
  },

  createClass: async (batchId: string, data) => {
    const newClass = await batchClassService.createClass(batchId, data)
    set((state) => {
      const existing = state.classesByBatch[batchId] || []
      const updatedClasses = [...existing, newClass]
      return {
        classesByBatch: { ...state.classesByBatch, [batchId]: updatedClasses },
        batches: state.batches.map((b) => (b.id === batchId ? { ...b, classes: updatedClasses } : b)),
      }
    })
    return newClass
  },

  updateClass: async (classId: string, data) => {
    const updatedClass = await batchClassService.updateClass(classId, data)
    set((state) => {
      const batchId = updatedClass.batch_id
      const existing = state.classesByBatch[batchId] || []
      const updatedClasses = existing.map((c) => (c.id === classId ? updatedClass : c))
      return {
        classesByBatch: { ...state.classesByBatch, [batchId]: updatedClasses },
        batches: state.batches.map((b) => (b.id === batchId ? { ...b, classes: updatedClasses } : b)),
      }
    })
    return updatedClass
  },

  deleteClass: async (classId: string) => {
    await batchClassService.deleteClass(classId)
    set((state) => {
      const newClassesByBatch: Record<string, BatchClass[]> = {}
      Object.keys(state.classesByBatch).forEach((bId) => {
        newClassesByBatch[bId] = state.classesByBatch[bId].filter((c) => c.id !== classId)
      })
      return {
        classesByBatch: newClassesByBatch,
        batches: state.batches.map((b) => ({
          ...b,
          classes: (b.classes || []).filter((c) => c.id !== classId),
        })),
      }
    })
  },

  fetchUploadLinks: async () => {
    try {
      const links = await batchService.getAllUploadLinks()
      set({ uploadLinks: links })
    } catch (err) {
      console.warn('API connection failed. Using fallback mock upload links.', err)
    }
  },

  addBatch: async (batchData) => {
    try {
      await batchService.create({
        name: batchData.name,
        department_id: batchData.department,
        academic_year: batchData.academicYear,
        description: batchData.description,
        start_date: batchData.startDate,
        end_date: batchData.endDate,
        status: batchData.status,
      })
      const { fetchBatches } = get()
      await fetchBatches()
    } catch (err) {
      console.error('Failed to add batch', err)
      // Optimistic local state update in case backend fails
      const newId = `batch_${Math.random().toString(36).substring(2, 9)}`
      const newBatch: Batch = {
        ...batchData,
        id: newId,
        stats: { students: 0, pending: 0, verified: 0, rejected: 0 },
        classes: [],
        currentDocVersion: 1,
        docRequirements: [...defaultRequirements],
      }
      set((state) => ({ batches: [newBatch, ...state.batches] }))
    }
  },

  updateBatch: async (batchId, data) => {
    try {
      await batchService.update(batchId, {
        name: data.name,
        department_id: data.department,
        academic_year: data.academicYear,
        description: data.description,
        start_date: data.startDate,
        end_date: data.endDate,
        status: data.status,
      })
      const { fetchBatches } = get()
      await fetchBatches()
    } catch (err) {
      console.error('Failed to update batch', err)
      set((state) => ({
        batches: state.batches.map((b) => (b.id === batchId ? { ...b, ...data } : b)),
      }))
    }
  },

  deleteBatch: async (batchId) => {
    try {
      await batchService.delete(batchId)
      set((state) => ({
        batches: state.batches.filter((b) => b.id !== batchId),
      }))
    } catch (err) {
      console.error('Failed to delete batch', err)
      set((state) => ({
        batches: state.batches.filter((b) => b.id !== batchId),
      }))
    }
  },

  updateBatchRequirements: async (batchId, requirements, changeSummary) => {
    try {
      await batchService.updateDocRequirements(batchId, {
        documents: requirements.map((r) => ({
          id: r.id,
          name: r.name,
          required: r.required,
          allowed_types: r.allowedTypes,
          max_size_mb: r.maxSizeMb,
          description: r.description,
          type: r.type || 'MANDATORY',
        })),
        change_summary: changeSummary,
      })
      const { fetchBatches } = get()
      await fetchBatches()
    } catch (err) {
      console.error('Failed to update requirements', err)
      // Fallback local update
      set((state) => ({
        batches: state.batches.map((b) =>
          b.id === batchId ? { ...b, docRequirements: requirements } : b
        ),
      }))
    }
  },

  getBatchDocVersions: (batchId) => {
    return get().docVersions[batchId] || []
  },

  addUploadLink: async (linkData) => {
    try {
      const batch = get().batches.find((b) => b.id === linkData.batchId)
      // Fetch departments to find department ObjectId matching batch department code
      const deptsRes = await api.get('/departments')
      const userDept = deptsRes.data.find((d: any) => d.code === batch?.department)
      const deptId = userDept ? userDept.id : (deptsRes.data[0]?.id || '650000000000000000000001')

      let createdItem: UploadLink
      if (linkData.class_id) {
        const res = await api.post(`/classes/${linkData.class_id}/upload-link`, {
          department_id: deptId,
          batch_id: linkData.batchId,
          class_id: linkData.class_id,
          title: linkData.title || 'Public Upload Link',
          expires_at: linkData.expiresAt ? (linkData.expiresAt.includes('T') ? linkData.expiresAt : `${linkData.expiresAt}T23:59:59Z`) : undefined,
          max_submissions: 100,
        })
        createdItem = {
          id: res.data.id,
          batchId: res.data.batch_id || linkData.batchId,
          class_id: res.data.class_id || linkData.class_id,
          token: res.data.token,
          slug: res.data.slug || res.data.token,
          title: res.data.title,
          expiresAt: res.data.expires_at ? res.data.expires_at.split('T')[0] : '',
          isActive: res.data.is_active,
          submissionCount: res.data.submission_count || 0,
        }
      } else {
        createdItem = await batchService.createUploadLink({
          department_id: deptId,
          batch_id: linkData.batchId,
          class_id: linkData.class_id || undefined,
          title: linkData.title || 'Public Upload Link',
          expires_at: linkData.expiresAt ? (linkData.expiresAt.includes('T') ? linkData.expiresAt : `${linkData.expiresAt}T23:59:59Z`) : undefined,
          max_submissions: 100,
        })
      }

      if (linkData.class_id) createdItem.class_id = linkData.class_id
      if (linkData.batchId) createdItem.batchId = linkData.batchId

      set((state) => ({
        uploadLinks: [createdItem, ...state.uploadLinks.filter((l) => l.id !== createdItem.id)],
      }))

      const { fetchUploadLinks } = get()
      await fetchUploadLinks()
      return createdItem
    } catch (err) {
      console.error('Failed to add upload link', err)
      // Fallback local state update
      const newId = `lnk_${Math.random().toString(36).substring(2, 9)}`
      const newLink: UploadLink = {
        id: newId,
        batchId: linkData.batchId,
        class_id: linkData.class_id,
        token: linkData.token || Math.random().toString(36).substring(2, 9),
        slug: linkData.slug || linkData.token || Math.random().toString(36).substring(2, 9),
        title: linkData.title || 'Public Upload Link',
        expiresAt: linkData.expiresAt || '',
        isActive: linkData.isActive ?? true,
        submissionCount: 0,
      }
      set((state) => ({ uploadLinks: [newLink, ...state.uploadLinks] }))
      return newLink
    }
  },

  toggleUploadLink: async (linkId) => {
    try {
      const link = get().uploadLinks.find((l) => l.id === linkId)
      if (link) {
        await batchService.toggleUploadLink(linkId, !link.isActive)
        const { fetchUploadLinks } = get()
        await fetchUploadLinks()
      }
    } catch (err) {
      console.error('Failed to toggle upload link', err)
      set((state) => ({
        uploadLinks: state.uploadLinks.map((l) =>
          l.id === linkId ? { ...l, isActive: !l.isActive } : l
        ),
      }))
    }
  },

  updateUploadLinkExpiry: async (linkId, expiresAt) => {
    try {
      const payloadExpiresAt = expiresAt ? `${expiresAt}T23:59:59Z` : null
      await batchService.updateUploadLink(linkId, { expires_at: payloadExpiresAt })
      const { fetchUploadLinks } = get()
      await fetchUploadLinks()
    } catch (err) {
      console.error('Failed to update upload link expiry', err)
      set((state) => ({
        uploadLinks: state.uploadLinks.map((l) =>
          l.id === linkId ? { ...l, expiresAt: expiresAt || '' } : l
        ),
      }))
    }
  },

  deleteUploadLink: async (linkId) => {
    try {
      await batchService.deleteUploadLink(linkId)
      const { fetchUploadLinks } = get()
      await fetchUploadLinks()
    } catch (err) {
      console.error('Failed to delete upload link', err)
      set((state) => ({
        uploadLinks: state.uploadLinks.filter((l) => l.id !== linkId),
      }))
    }
  },
}))
