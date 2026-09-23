import { api } from './api'

export interface WantedFieldItem {
  field: string
  enabled: boolean
  excel_header?: string | null
  sample_value?: string | null
}

export interface DocumentTypeOverviewItem {
  document_type: string
  display_name: string
  description?: string | null
  wanted_count: number
  mapped_count: number
  unmapped_count: number
  status: 'CONFIGURED' | 'INCOMPLETE' | 'NO_WANTED_FIELDS'
  requirement_status?: 'REQUIRED' | 'OPTIONAL' | 'DISABLED'
  allowed_types?: string[]
  max_size_mb?: number
  version: number
  fields: WantedFieldItem[]
  available_fields?: string[]
  template_headers: string[]
}

export interface DocumentFieldConfigurationResponse {
  id: string
  batch_id: string
  class_id?: string | null
  document_type: string
  display_name: string
  description?: string | null
  requirement_status?: 'REQUIRED' | 'OPTIONAL' | 'DISABLED'
  allowed_types?: string[]
  max_size_mb?: number
  fields: WantedFieldItem[]
  available_fields?: string[]
  is_archived?: boolean
  version: number
  updated_at: string
}

export interface CreateDocumentTypePayload {
  name: string
  code: string
  description?: string
  requirement_status?: 'REQUIRED' | 'OPTIONAL' | 'DISABLED'
  allowed_types?: string[]
  max_size_mb?: number
  initial_fields?: string[]
}

export const wantedFieldService = {
  // Get overview across all document types for an admission batch
  async getBatchOverview(
    batchId: string,
    classId?: string
  ): Promise<DocumentTypeOverviewItem[]> {
    const url = classId
      ? `/wanted-fields/${batchId}/overview?class_id=${encodeURIComponent(classId)}&classId=${encodeURIComponent(classId)}`
      : `/wanted-fields/${batchId}/overview`
    const response = await api.get(url)
    const items: DocumentTypeOverviewItem[] = response.data || []
    const dedupedMap = new Map<string, DocumentTypeOverviewItem>()
    for (const item of items) {
      const code = (item.document_type || '').toUpperCase().trim()
      if (!dedupedMap.has(code)) {
        dedupedMap.set(code, item)
      } else {
        const existing = dedupedMap.get(code)!
        if ((item.version || 1) >= (existing.version || 1)) {
          dedupedMap.set(code, item)
        }
      }
    }
    return Array.from(dedupedMap.values())
  },

  // Create a new document type for this batch
  async createDocumentType(
    batchId: string,
    payload: CreateDocumentTypePayload,
    classId?: string
  ): Promise<DocumentFieldConfigurationResponse> {
    const url = classId
      ? `/wanted-fields/${batchId}/document-type?class_id=${encodeURIComponent(classId)}`
      : `/wanted-fields/${batchId}/document-type`
    const response = await api.post(url, payload)
    return response.data
  },

  // Delete or archive a document type
  async deleteDocumentType(
    batchId: string,
    docType: string,
    classId?: string
  ): Promise<{ success: boolean; archived: boolean; message: string }> {
    const url = classId
      ? `/wanted-fields/${batchId}/${encodeURIComponent(docType)}?class_id=${encodeURIComponent(classId)}`
      : `/wanted-fields/${batchId}/${encodeURIComponent(docType)}`
    const response = await api.delete(url)
    return response.data
  },

  // Add a custom field to a document type
  async addCustomField(
    batchId: string,
    docType: string,
    fieldName: string,
    classId?: string
  ): Promise<DocumentFieldConfigurationResponse> {
    const url = classId
      ? `/wanted-fields/${batchId}/${encodeURIComponent(docType)}/fields?class_id=${encodeURIComponent(classId)}`
      : `/wanted-fields/${batchId}/${encodeURIComponent(docType)}/fields`
    const response = await api.post(url, { field_name: fieldName })
    return response.data
  },

  // Get configuration for a specific document type
  async getDocumentConfig(
    batchId: string,
    docType: string,
    classId?: string
  ): Promise<DocumentFieldConfigurationResponse> {
    const url = classId
      ? `/wanted-fields/${batchId}/${encodeURIComponent(docType)}?class_id=${encodeURIComponent(classId)}`
      : `/wanted-fields/${batchId}/${encodeURIComponent(docType)}`
    const response = await api.get(url)
    return response.data
  },

  // Save/Update configuration for a specific document type
  async saveDocumentConfig(
    batchId: string,
    docType: string,
    fields: WantedFieldItem[],
    classId?: string,
    options?: {
      display_name?: string
      description?: string
      requirement_status?: 'REQUIRED' | 'OPTIONAL' | 'DISABLED'
      allowed_types?: string[]
      max_size_mb?: number
    }
  ): Promise<DocumentFieldConfigurationResponse> {
    const url = classId
      ? `/wanted-fields/${batchId}/${encodeURIComponent(docType)}?class_id=${encodeURIComponent(classId)}`
      : `/wanted-fields/${batchId}/${encodeURIComponent(docType)}`
    const response = await api.put(url, {
      document_type: docType,
      fields,
      class_id: classId || null,
      display_name: options?.display_name,
      description: options?.description,
      requirement_status: options?.requirement_status,
      allowed_types: options?.allowed_types,
      max_size_mb: options?.max_size_mb,
    })
    return response.data
  },
}
