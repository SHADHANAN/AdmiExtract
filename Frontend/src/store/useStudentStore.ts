import { create } from 'zustand'
import type { StudentSubmission } from '../types'
import { studentSubmissionService, type CreateSubmissionPayload } from '../services/studentSubmission'

interface StudentState {
  submissions: StudentSubmission[]
  isLoading: boolean
  error: string | null
  fetchSubmissionsByBatch: (batchId: string) => Promise<void>
  fetchAllSubmissions: () => Promise<void>
  addSubmission: (submission: Omit<StudentSubmission, 'id' | 'submittedAt'>) => Promise<StudentSubmission>
  updateStudentStatus: (id: string, status: StudentSubmission['status']) => Promise<void>
  startAiProcessing: (id: string) => Promise<void>
  deleteSubmission: (id: string) => void
}

const initialSubmissions: StudentSubmission[] = [
  {
    id: 'sub_1',
    batchId: 'batch_1',
    batchName: 'AIML 2025-2029',
    registerNum: '24AM001',
    name: 'Rahul Sharma',
    mobile: '9876543210',
    email: 'rahul.s@example.com',
    status: 'Submitted',
    aiStatus: 'Processing',
    submittedAt: '2026-07-30 10:15',
    documents: [
      { reqName: 'Aadhaar Card', fileName: 'Aadhaar_Rahul.pdf', fileSizeMb: 2.1, fileType: 'PDF', status: 'Uploaded', uploadedAt: '2026-07-30 10:10', fileUrl: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=800' },
      { reqName: 'Birth Certificate', fileName: 'BirthCert_Rahul.jpg', fileSizeMb: 1.4, fileType: 'JPG', status: 'Uploaded', uploadedAt: '2026-07-30 10:11', fileUrl: 'https://images.unsplash.com/photo-1586281380349-632531db7ed4?w=800' },
      { reqName: 'Community Certificate', fileName: 'Community_Rahul.pdf', fileSizeMb: 0.9, fileType: 'PDF', status: 'Uploaded', uploadedAt: '2026-07-30 10:12', fileUrl: 'https://images.unsplash.com/photo-1568602471122-7832951cc4c5?w=800' },
      { reqName: 'Income Certificate', status: 'Not Available' },
      { reqName: 'SSLC Marksheet', fileName: 'SSLC_Rahul.pdf', fileSizeMb: 3.2, fileType: 'PDF', status: 'Uploaded', uploadedAt: '2026-07-30 10:13', fileUrl: 'https://images.unsplash.com/photo-1606326608606-aa0b62935f2b?w=800' },
      { reqName: 'HSC Marksheet', fileName: 'HSC_Rahul.pdf', fileSizeMb: 3.5, fileType: 'PDF', status: 'Uploaded', uploadedAt: '2026-07-30 10:14', fileUrl: 'https://images.unsplash.com/photo-1606326608606-aa0b62935f2b?w=800' },
      { reqName: 'Transfer Certificate', status: 'Not Available' },
    ],
  },
  {
    id: 'sub_2',
    batchId: 'batch_1',
    batchName: 'AIML 2025-2029',
    registerNum: '24AM002',
    name: 'Kumar V',
    mobile: '9812345678',
    email: 'kumar.v@example.com',
    status: 'Verified',
    aiStatus: 'Complete',
    submittedAt: '2026-07-29 16:45',
    documents: [
      { reqName: 'Aadhaar Card', fileName: 'Aadhaar_Kumar.pdf', fileSizeMb: 1.8, fileType: 'PDF', status: 'Uploaded', uploadedAt: '2026-07-29 16:40', fileUrl: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=800' },
      { reqName: 'Birth Certificate', fileName: 'BirthCert_Kumar.png', fileSizeMb: 2.3, fileType: 'PNG', status: 'Uploaded', uploadedAt: '2026-07-29 16:41', fileUrl: 'https://images.unsplash.com/photo-1586281380349-632531db7ed4?w=800' },
      { reqName: 'Community Certificate', fileName: 'Community_Kumar.pdf', fileSizeMb: 1.1, fileType: 'PDF', status: 'Uploaded', uploadedAt: '2026-07-29 16:42', fileUrl: 'https://images.unsplash.com/photo-1568602471122-7832951cc4c5?w=800' },
      { reqName: 'Income Certificate', fileName: 'Income_Kumar.pdf', fileSizeMb: 1.5, fileType: 'PDF', status: 'Uploaded', uploadedAt: '2026-07-29 16:42', fileUrl: 'https://images.unsplash.com/photo-1554224155-8d04cb21cd6c?w=800' },
      { reqName: 'SSLC Marksheet', fileName: 'SSLC_Kumar.pdf', fileSizeMb: 2.8, fileType: 'PDF', status: 'Uploaded', uploadedAt: '2026-07-29 16:43', fileUrl: 'https://images.unsplash.com/photo-1606326608606-aa0b62935f2b?w=800' },
      { reqName: 'HSC Marksheet', fileName: 'HSC_Kumar.pdf', fileSizeMb: 3.1, fileType: 'PDF', status: 'Uploaded', uploadedAt: '2026-07-29 16:44', fileUrl: 'https://images.unsplash.com/photo-1606326608606-aa0b62935f2b?w=800' },
      { reqName: 'Transfer Certificate', fileName: 'TC_Kumar.pdf', fileSizeMb: 1.2, fileType: 'PDF', status: 'Uploaded', uploadedAt: '2026-07-29 16:44', fileUrl: 'https://images.unsplash.com/photo-1450133064473-71024230f91b?w=800' },
    ],
  },
]

export const useStudentStore = create<StudentState>((set) => ({
  submissions: initialSubmissions,
  isLoading: false,
  error: null,

  fetchSubmissionsByBatch: async (batchId) => {
    set({ isLoading: true, error: null })
    try {
      const data = await studentSubmissionService.getSubmissionsByBatch(batchId)
      set((state) => {
        // Merge fetched data with local state so initial local data for other batches is preserved
        const otherBatches = state.submissions.filter((s) => s.batchId !== batchId)
        return { submissions: [...data, ...otherBatches], isLoading: false }
      })
    } catch (err: any) {
      set({ isLoading: false })
      // Keep local state if server fails or is starting up
    }
  },

  fetchAllSubmissions: async () => {
    set({ isLoading: true, error: null })
    try {
      const data = await studentSubmissionService.getAllSubmissions()
      set({ submissions: data, isLoading: false })
    } catch (err: any) {
      set({ isLoading: false })
    }
  },

  addSubmission: async (submissionData) => {
    set({ isLoading: true })
    const payload: CreateSubmissionPayload = {
      batch_id: submissionData.batchId,
      batch_name: submissionData.batchName,
      student_name: submissionData.name,
      register_number: submissionData.registerNum,
      mobile_number: submissionData.mobile,
      email: submissionData.email,
      submission_status: submissionData.status || 'Submitted',
      documents: submissionData.documents.map((d) => ({
        document_name: d.reqName,
        status: d.status,
        file_path: d.fileName ? `uploads/${submissionData.registerNum}/${d.fileName}` : undefined,
        file_size_mb: d.fileSizeMb,
        file_type: d.fileType,
        uploaded_at: d.uploadedAt,
      })),
    }

    try {
      const created = await studentSubmissionService.createSubmission(payload)
      set((state) => ({
        submissions: [created, ...state.submissions.filter((s) => s.id !== created.id)],
        isLoading: false,
      }))
      return created
    } catch (err: any) {
      // Fallback local creation if API fails
      const fallback: StudentSubmission = {
        ...submissionData,
        id: `sub_${Math.random().toString(36).substring(2, 9)}`,
        submittedAt: new Date().toISOString().replace('T', ' ').substring(0, 16),
      }
      set((state) => ({
        submissions: [fallback, ...state.submissions],
        isLoading: false,
      }))
      return fallback
    }
  },

  updateStudentStatus: async (id, status) => {
    set((state) => ({
      submissions: state.submissions.map((sub) =>
        sub.id === id ? { ...sub, status } : sub
      ),
    }))

    try {
      await studentSubmissionService.updateStatus(id, status)
    } catch (err) {
      // Keep optimistic update
    }
  },

  startAiProcessing: async (id) => {
    set((state) => ({
      submissions: state.submissions.map((sub) =>
        sub.id === id ? { ...sub, status: 'AI Processing' as const, aiStatus: 'Processing' as const } : sub
      ),
    }))

    try {
      await studentSubmissionService.updateStatus(id, 'AI Processing')
    } catch (err) {
      // Continue optimistic workflow
    }

    setTimeout(async () => {
      set((state) => ({
        submissions: state.submissions.map((sub) =>
          sub.id === id ? { ...sub, status: 'Verification Pending' as const, aiStatus: 'Complete' as const } : sub
        ),
      }))

      try {
        await studentSubmissionService.updateStatus(id, 'Verification Pending')
      } catch (err) {
        // Keep optimistic update
      }
    }, 2500)
  },

  deleteSubmission: (id) => {
    set((state) => ({
      submissions: state.submissions.filter((sub) => sub.id !== id),
    }))
  },
}))
