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

const initialSubmissions: StudentSubmission[] = []

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
