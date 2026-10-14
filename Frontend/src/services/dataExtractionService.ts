import { api } from './api';
import type {
  BatchExtractionStats,
  BatchExtractionSummary,
  TemplatePreviewData,
  CreateBatchExtractionPayload,
  BatchExtractionDetail,
  StudentExtractionRow,
  CorrectionQueueItem,
} from '../types/dataExtraction';

export const dataExtractionService = {
  /**
   * List all authorized batches with extraction statistics
   */
  listAuthorizedBatches: async (): Promise<BatchExtractionStats[]> => {
    const response = await api.get<BatchExtractionStats[]>('/data-extractions/batches');
    return response.data;
  },

  /**
   * Get stats and overview for a specific admission batch
   */
  getBatchOverview: async (batchId: string): Promise<BatchExtractionStats> => {
    const response = await api.get<BatchExtractionStats>(`/data-extractions/batches/${batchId}`);
    return response.data;
  },

  /**
   * List historical extraction requests for a batch
   */
  listBatchHistory: async (batchId: string): Promise<BatchExtractionSummary[]> => {
    const response = await api.get<BatchExtractionSummary[]>(`/data-extractions/batches/${batchId}/history`);
    return response.data;
  },

  /**
   * Upload & preview/store an Excel field template
   */
  previewExcelTemplate: async (file: File, batchId?: string, classId?: string): Promise<TemplatePreviewData> => {
    const formData = new FormData();
    formData.append('file', file);
    if (batchId) formData.append('batch_id', batchId);
    if (classId) formData.append('class_id', classId);
    const response = await api.post<TemplatePreviewData>('/data-extractions/template-preview', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  /**
   * Get active Excel template for a batch
   */
  getBatchTemplate: async (batchId: string, classId?: string): Promise<TemplatePreviewData | null> => {
    const response = await api.get<TemplatePreviewData | null>(`/data-extractions/batches/${batchId}/template`, {
      params: { class_id: classId },
    });
    return response.data;
  },

  /**
   * Delete active Excel template for a batch
   */
  deleteBatchTemplate: async (batchId: string, classId?: string): Promise<void> => {
    await api.delete(`/data-extractions/batches/${batchId}/template`, {
      params: { class_id: classId },
    });
  },

  /**
   * Trigger a new data extraction for a batch from stored documents
   */
  createBatchExtraction: async (
    batchId: string,
    payload: CreateBatchExtractionPayload
  ): Promise<BatchExtractionSummary> => {
    const response = await api.post<BatchExtractionSummary>(
      `/data-extractions/batches/${batchId}/extract`,
      payload
    );
    return response.data;
  },

  /**
   * Retrieve full extraction details including student records, filters, search, and pagination
   */
  getExtractionDetails: async (
    extractionRequestId: string,
    params?: {
      status_filter?: string;
      search?: string;
      page?: number;
      page_size?: number;
    }
  ): Promise<BatchExtractionDetail> => {
    const response = await api.get<BatchExtractionDetail>(
      `/data-extractions/requests/${extractionRequestId}`,
      { params }
    );
    return response.data;
  },

  /**
   * Retry extraction for a single student
   */
  retryStudentExtraction: async (
    extractionRequestId: string,
    studentId: string
  ): Promise<StudentExtractionRow> => {
    const response = await api.post<StudentExtractionRow>(
      `/data-extractions/requests/${extractionRequestId}/retry-student/${studentId}`
    );
    return response.data;
  },

  /**
   * Cancel an in-progress extraction request safely
   */
  cancelExtraction: async (
    extractionRequestId: string
  ): Promise<BatchExtractionSummary> => {
    const response = await api.post<BatchExtractionSummary>(
      `/data-extractions/requests/${extractionRequestId}/cancel`
    );
    return response.data;
  },

  /**
   * Get dedicated correction queue for an extraction request
   */
  getCorrectionsQueue: async (
    extractionRequestId: string
  ): Promise<CorrectionQueueItem[]> => {
    const response = await api.get<CorrectionQueueItem[]>(
      `/data-extractions/requests/${extractionRequestId}/corrections`
    );
    return response.data;
  },

  /**
   * Staff reviews student correction (Approve or Reject)
   */
  reviewCorrection: async (
    extractionRequestId: string,
    verificationId: string,
    action: 'APPROVE' | 'REJECT',
    staffComment?: string
  ): Promise<any> => {
    const response = await api.post(
      `/data-extractions/requests/${extractionRequestId}/review/${verificationId}`,
      { action, staff_comment: staffComment }
    );
    return response.data;
  },

  /**
   * Download final verified Excel file
   */
  downloadVerifiedExcel: async (extractionRequestId: string, defaultFilename?: string): Promise<void> => {
    const response = await api.get(`/data-extractions/requests/${extractionRequestId}/export`, {
      responseType: 'blob',
      timeout: 60000,
    });

    if (!response.data || (response.data instanceof Blob && response.data.size === 0)) {
      throw new Error('Received an empty file from server. Excel download could not be completed.');
    }

    // Check if the server returned JSON error inside a blob
    if (response.data instanceof Blob && response.data.type?.includes('application/json')) {
      try {
        const text = await response.data.text();
        const json = JSON.parse(text);
        if (json?.detail) {
          throw new Error(json.detail);
        }
      } catch (err: any) {
        if (err?.message) throw err;
      }
    }

    const blob = response.data instanceof Blob
      ? response.data
      : new Blob([response.data], {
          type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        });

    let filename = defaultFilename || `Data_Extraction_${extractionRequestId}.xlsx`;
    const disposition =
      response.headers?.['content-disposition'] ||
      response.headers?.['Content-Disposition'];

    if (disposition) {
      const filenameMatch = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
      if (filenameMatch && filenameMatch[1]) {
        filename = decodeURIComponent(filenameMatch[1].trim());
      }
    }

    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', filename);
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    // Give browser time to process blob before revoking object URL
    setTimeout(() => {
      try {
        window.URL.revokeObjectURL(url);
      } catch {
        // Ignore revocation errors
      }
    }, 2000);
  },
};
