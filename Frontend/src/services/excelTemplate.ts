import { api } from './api'

export interface ExcelTemplateResponse {
  id: string
  batch_id: string
  class_id?: string
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
  // Upload .xlsx template file for a batch or specific class
  async uploadTemplate(batchId: string, file: File, classId?: string): Promise<ExcelTemplateResponse> {
    const formData = new FormData()
    formData.append('file', file)
    const url = classId 
      ? `/excel-templates/upload/${batchId}?classId=${encodeURIComponent(classId)}`
      : `/excel-templates/upload/${batchId}`
    const response = await api.post(url, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  // Get Excel template metadata & headers for a batch or specific class
  async getTemplate(batchId: string, classId?: string): Promise<ExcelTemplateResponse | null> {
    try {
      const url = classId 
        ? `/excel-templates/batch/${batchId}?classId=${encodeURIComponent(classId)}`
        : `/excel-templates/batch/${batchId}`
      const response = await api.get(url)
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
    lookupColumn: string,
    classId?: string
  ): Promise<ExcelTemplateResponse> {
    const url = classId 
      ? `/excel-templates/mappings/${batchId}?classId=${encodeURIComponent(classId)}`
      : `/excel-templates/mappings/${batchId}`
    const response = await api.put(url, {
      field_mappings: fieldMappings,
      lookup_column: lookupColumn,
    })
    return response.data
  },

  // Trigger Excel row update for a student candidate
  async updateStudentRow(
    batchId: string,
    registerNumber: string,
    extractedFields: Record<string, any>,
    classId?: string
  ): Promise<{ status: string; message: string; updated?: boolean }> {
    const response = await api.post(`/excel-templates/update-row/${batchId}`, {
      register_number: registerNumber,
      class_id: classId,
      extracted_fields: extractedFields,
    })
    return response.data
  },

  // Download updated Excel workbook
  async downloadExcel(batchId: string, filename?: string, classId?: string): Promise<void> {
    const url = classId 
      ? `/excel-templates/download/${batchId}?classId=${encodeURIComponent(classId)}`
      : `/excel-templates/download/${batchId}`
    const response = await api.get(url, {
      responseType: 'blob',
    })
    const urlBlob = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = urlBlob
    link.setAttribute('download', filename || `${batchId}${classId ? '_' + classId : ''}_Updated_Admissions.xlsx`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(urlBlob)
  },
}
