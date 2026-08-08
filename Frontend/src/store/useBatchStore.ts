import { create } from 'zustand'
import type { BatchState, Batch, UploadLink, DocumentRequirement, DocumentConfigurationVersion } from '../types'
import { batchService } from '../services/batch'
import { api } from '../services/api'

const v1Requirements: DocumentRequirement[] = [
  { id: 'req_1', name: 'Aadhaar Card', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, description: 'Upload front and back side of Aadhaar card', type: 'MANDATORY' },
  { id: 'req_5', name: 'SSLC Marksheet', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, description: '10th grade official marks statement', type: 'MANDATORY' },
  { id: 'req_6', name: 'HSC Marksheet', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, description: '12th grade / Diploma final marks statement', type: 'MANDATORY' },
  { id: 'req_3', name: 'Community Certificate', required: true, allowedTypes: ['PDF', 'JPG'], maxSizeMb: 5, description: 'Caste / Community reservation proof', type: 'MANDATORY' },
]

const v2Requirements: DocumentRequirement[] = [
  { id: 'req_1', name: 'Aadhaar Card', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, description: 'Upload front and back side of Aadhaar card', type: 'MANDATORY' },
  { id: 'req_5', name: 'SSLC Marksheet', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, description: '10th grade official marks statement', type: 'MANDATORY' },
  { id: 'req_6', name: 'HSC Marksheet', required: true, allowedTypes: ['PDF', 'JPG', 'PNG'], maxSizeMb: 5, description: '12th grade / Diploma final marks statement', type: 'MANDATORY' },
  { id: 'req_4', name: 'Income Certificate', required: true, allowedTypes: ['PDF', 'JPG'], maxSizeMb: 5, description: 'Annual family income certificate for scholarship eligibility', type: 'MANDATORY' },
]

const initialDocVersions: Record<string, DocumentConfigurationVersion[]> = {
  batch_1: [
    {
      id: 'ver_batch1_v2',
      batchId: 'batch_1',
      version: 2,
      documents: v2Requirements,
      isCurrent: true,
      changeSummary: 'Removed Community Certificate, Added Income Certificate',
      createdBy: 'Admission Officer',
      createdAt: '2026-07-25T10:30:00Z',
    },
    {
      id: 'ver_batch1_v1',
      batchId: 'batch_1',
      version: 1,
      documents: v1Requirements,
      isCurrent: false,
      changeSummary: 'Initial document configuration (Version 1)',
      createdBy: 'System Administrator',
      createdAt: '2026-06-01T08:00:00Z',
    },
  ],
  batch_2: [
    {
      id: 'ver_batch2_v1',
      batchId: 'batch_2',
      version: 1,
      documents: v1Requirements,
      isCurrent: true,
      changeSummary: 'Initial document configuration (Version 1)',
      createdBy: 'System Administrator',
      createdAt: '2026-06-01T08:00:00Z',
    },
  ],
}

const initialBatches: Batch[] = [
  {
    id: 'batch_1',
    name: 'AIML 2025-2029',
    department: 'AIML',
    academicYear: '2025-2029',
    description: 'Admissions batch for AI and Machine Learning specialization courses.',
    startDate: '2025-06-01',
    endDate: '2025-08-30',
    status: 'active',
    stats: { students: 45, pending: 12, verified: 30, rejected: 3 },
    currentDocVersion: 2,
    docRequirements: [...v2Requirements],
  },
  {
    id: 'batch_2',
    name: 'CSE 2025-2029',
    department: 'CSE',
    academicYear: '2025-2029',
    description: 'Admissions batch for standard Computer Science engineering curriculum.',
    startDate: '2025-06-01',
    endDate: '2025-08-30',
    status: 'active',
    stats: { students: 120, pending: 24, verified: 90, rejected: 6 },
    currentDocVersion: 1,
    docRequirements: [...v1Requirements],
  },
  {
    id: 'batch_3',
    name: 'ECE 2025-2029',
    department: 'ECE',
    academicYear: '2025-2029',
    description: 'Admissions batch for Electronics and Communication courses.',
    startDate: '2025-05-15',
    endDate: '2025-07-31',
    status: 'closed',
    stats: { students: 60, pending: 0, verified: 58, rejected: 2 },
    currentDocVersion: 1,
    docRequirements: [...v1Requirements],
  },
]

const initialLinks: UploadLink[] = [
  {
    id: 'lnk_1',
    batchId: 'batch_1',
    token: 'aiml-2025-portal',
    title: 'AIML Public Upload',
    expiresAt: '2026-08-30',
    isActive: true,
    submissionCount: 15,
  },
  {
    id: 'lnk_2',
    batchId: 'batch_2',
    token: 'cse-2025-portal',
    title: 'CSE Public Upload',
    expiresAt: '2026-08-30',
    isActive: true,
    submissionCount: 32,
  },
]

export const useBatchStore = create<BatchState>((set, get) => ({
  batches: initialBatches,
  uploadLinks: initialLinks,
  docVersions: initialDocVersions,

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
            requirements = [...v1Requirements]
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
            currentDocVersion: version,
            docRequirements: requirements,
          }
        })
      )
      set({ batches: formattedBatches })
    } catch (err) {
      console.warn('API connection failed. Using fallback mock batches.', err)
    }
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
        currentDocVersion: 1,
        docRequirements: [...v1Requirements],
      }
      set((state) => ({ batches: [newBatch, ...state.batches] }))
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
      if (!userDept) {
        throw new Error('Assigned department code not found in backend.')
      }

      await batchService.createUploadLink({
        department_id: userDept.id,
        batch_id: linkData.batchId,
        title: linkData.title || 'Public Upload Link',
        expires_at: linkData.expiresAt ? `${linkData.expiresAt}T23:59:59Z` : undefined,
        max_submissions: 100,
      })

      const { fetchUploadLinks } = get()
      await fetchUploadLinks()
    } catch (err) {
      console.error('Failed to add upload link', err)
      // Fallback local state update
      const newId = `lnk_${Math.random().toString(36).substring(2, 9)}`
      const newLink: UploadLink = {
        ...linkData,
        id: newId,
        submissionCount: 0,
      }
      set((state) => ({ uploadLinks: [newLink, ...state.uploadLinks] }))
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
