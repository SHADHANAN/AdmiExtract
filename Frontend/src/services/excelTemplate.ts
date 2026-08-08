import { api } from './api'

export interface ExcelTemplateResponse {
  id: string
  batch_id: string
  template_filename: string
  file_path: string
  headers: string[]
  field_mappings: Record<string, string>
  lookup_column: string
  total_rows: number
  updated_count: number
  remaining_students: number
  created_at: string
  updated_at: string
}

export const excelTemplateService = {
  // Upload .xlsx template file for a batch
  async uploadTemplate(batchId: string, file: File): Promise<ExcelTemplateResponse> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post(`/excel-templates/upload/${batchId}`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  // Get Excel template metadata & headers for a batch
  async getTemplate(batchId: string): Promise<ExcelTemplateResponse | null> {
    try {
      const response = await api.get(`/excel-templates/batch/${batchId}`)
      return response.data
    } catch (err) {
      return null
    }
  },

  // Get Excel headers for a batch (public student endpoint)
  async getBatchExcelHeaders(batchId: string): Promise<string[]> {
    try {
      const response = await api.get(`/student-submissions/batch/${batchId}/excel-headers`)
      return response.data.headers || []
    } catch (err) {
      return []
    }
  },


  // Save column field mappings
  async saveMappings(
    batchId: string,
    fieldMappings: Record<string, string>,
    lookupColumn: string
  ): Promise<ExcelTemplateResponse> {
    const response = await api.put(`/excel-templates/mappings/${batchId}`, {
      field_mappings: fieldMappings,
      lookup_column: lookupColumn,
    })
    return response.data
  },

  // Trigger Excel row update for a student candidate
  async updateStudentRow(
    batchId: string,
    registerNumber: string,
    extractedFields: Record<string, any>
  ): Promise<{ status: string; message: string; updated?: boolean }> {
    const response = await api.post(`/excel-templates/update-row/${batchId}`, {
      register_number: registerNumber,
      extracted_fields: extractedFields,
    })
    return response.data
  },

  // Download updated Excel workbook
  async downloadExcel(batchId: string, filename?: string): Promise<void> {
    const response = await api.get(`/excel-templates/download/${batchId}`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', filename || `${batchId}_Updated_Admissions.xlsx`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  },
}
