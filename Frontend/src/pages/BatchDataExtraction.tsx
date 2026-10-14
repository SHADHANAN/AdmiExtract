import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  FileSpreadsheet,
  Plus,
  Download,
  Users,
  Layers,
  Sparkles,
  Upload,
  X,
  RefreshCw,
  Eye,
  FileCheck2,
  FileText,
  CheckCircle2,
  Clock,
  RotateCcw,
  Search,
  Check,
  AlertTriangle,
  Ban,
  Settings2,
  CheckSquare,
  Square,
  Trash2,
  Copy,
  Link2,
  Loader2,
} from 'lucide-react';
import { dataExtractionService } from '../services/dataExtractionService';
import { wantedFieldService, type DocumentTypeOverviewItem, type WantedFieldItem } from '../services/wantedField';
import { useBatchStore } from '../store/useBatchStore';
import type {
  BatchExtractionStats,
  BatchExtractionSummary,
  BatchExtractionDetail,
  StudentExtractionRow,
} from '../types/dataExtraction';
import { useToastStore } from '../store/useToastStore';

// Standard Document Presets Catalog for Indian College Admissions
export const STANDARD_DOC_CATALOG = [
  {
    document_type: 'AADHAAR',
    display_name: 'Aadhaar Card',
    requirement_status: 'REQUIRED' as const,
    description: 'Unique 12-digit Indian National Identity document with permanent address and date of birth.',
    available_fields: [
      'Aadhaar Number',
      'Student Name',
      'Date of Birth',
      'Gender',
      'Permanent Address',
      'District',
      'Taluk',
      'State',
      'Pincode',
      'Mobile Number',
      "Father's Name",
      "Mother's Name",
    ],
  },
  {
    document_type: 'BANK_PASSBOOK',
    display_name: 'Bank Passbook',
    requirement_status: 'REQUIRED' as const,
    description: 'First page of candidate bank passbook containing account number, IFSC code, and branch details.',
    available_fields: [
      'Account Number',
      'IFSC Code',
      'Bank Name',
      'Branch',
      'Account Holder Name',
      'MICR Code',
    ],
  },
  {
    document_type: 'COMMUNITY',
    display_name: 'Community Certificate',
    requirement_status: 'REQUIRED' as const,
    description: 'Permanent Community/Caste Certificate issued by Revenue Authority / Tahsildar.',
    available_fields: [
      'Community Category',
      'Caste',
      'Community Certificate Number',
      'Student Name',
      "Father's Name",
      'Issue Date',
      'District',
      'Taluk',
    ],
  },
  {
    document_type: 'INCOME',
    display_name: 'Income Certificate',
    requirement_status: 'OPTIONAL' as const,
    description: 'Annual Family Income statement issued by Revenue Authority.',
    available_fields: [
      'Annual Family Income',
      'Student Name',
      "Father's Name",
      'Income Certificate Number',
      'Issue Date',
    ],
  },
  {
    document_type: 'TRANSFER_CERTIFICATE',
    display_name: 'Transfer Certificate (TC)',
    requirement_status: 'REQUIRED' as const,
    description: 'School/College Leaving and Transfer Certificate with EMIS ID and academic leaving date.',
    available_fields: [
      'Student Name',
      'Register Number',
      'Date of Birth',
      'Course',
      'Institution',
      'Date of Leaving',
      'EMIS ID',
      "Father's Name",
      "Mother's Name",
      'Admission Number',
      'Issue Date',
      'School Name',
      'Community Category',
      'Caste',
      'Transfer Certificate Number',
    ],
  },
  {
    document_type: 'SSLC',
    display_name: '10th SSLC Marksheet',
    requirement_status: 'REQUIRED' as const,
    description: 'Secondary School Leaving Certificate (10th Standard) marks statement.',
    available_fields: [
      'Student Name',
      'SSLC Register Number',
      'SSLC Total Marks',
      'SSLC Mark Percentage',
      'SSLC Year of Passing',
      'Date of Birth',
      'School Name',
    ],
  },
  {
    document_type: 'HSC',
    display_name: '12th HSC Marksheet',
    requirement_status: 'REQUIRED' as const,
    description: 'Higher Secondary Certificate (12th Standard) marks statement with cutoff score.',
    available_fields: [
      'Student Name',
      'HSC Register Number',
      'HSC Total Marks',
      'HSC Mark Percentage',
      'HSC Cutoff',
      'HSC Year of Passing',
      'School Name',
    ],
  },
  {
    document_type: 'NATIVITY',
    display_name: 'Nativity Certificate',
    requirement_status: 'OPTIONAL' as const,
    description: 'Certificate of Domicile / Nativity issued by Revenue Authority.',
    available_fields: [
      'Student Name',
      "Father's Name",
      'State',
      'District',
      'Taluk',
      'Nativity',
    ],
  },
  {
    document_type: 'BIRTH_CERTIFICATE',
    display_name: 'Birth Certificate',
    requirement_status: 'OPTIONAL' as const,
    description: 'Official birth certificate issued by Municipal Corporation / Panchayat.',
    available_fields: [
      'Student Name',
      'Date of Birth',
      'Gender',
      "Father's Name",
      "Mother's Name",
      'Place of Birth',
      'Registration Number',
    ],
  },
  {
    document_type: 'PASSPORT',
    display_name: 'Passport',
    requirement_status: 'OPTIONAL' as const,
    description: 'Valid Republic of India / International passport copy.',
    available_fields: [
      'Passport Number',
      'Given Name',
      'Surname',
      'Date of Birth',
      'Nationality',
      'Expiry Date',
      'Place of Issue',
    ],
  },
];

const FILTER_OPTIONS = [
  { id: 'ALL', label: 'All Students' },
  { id: 'COMPLETED', label: 'Completed' },
  { id: 'PARTIAL', label: 'Partial' },
  { id: 'FAILED', label: 'Failed' },
  { id: 'MISSING_DOCUMENTS', label: 'Missing Documents' },
  { id: 'PENDING_VERIFICATION', label: 'Pending Verification' },
  { id: 'CORRECTION_REQUESTED', label: 'Correction Requested' },
  { id: 'VERIFIED', label: 'Verified' },
];

export interface FieldMappingValidationResult {
  isWanted: boolean;
  status: 'DISABLED' | 'MAPPED' | 'UNMAPPED' | 'TEMPLATE_HEADER_MISSING';
  statusLabel: string;
  isMapped: boolean;
  reason?: string;
  excelHeader: string | null;
}

/**
 * Canonical mapping validator: determines exact mapping status against the uploaded Excel template headers.
 * The uploaded Excel headers are the sole source of truth.
 */
export function validateMappingAgainstTemplate(
  field: { enabled?: boolean; excel_header?: string | null },
  templateHeaders: string[]
): FieldMappingValidationResult {
  if (!field.enabled) {
    return {
      isWanted: false,
      status: 'DISABLED',
      statusLabel: 'Disabled',
      isMapped: false,
      excelHeader: null,
    };
  }

  const rawHeader = field.excel_header?.trim() || null;
  if (!rawHeader) {
    return {
      isWanted: true,
      status: 'UNMAPPED',
      statusLabel: 'Unmapped',
      isMapped: false,
      reason: 'NO_HEADER_SELECTED',
      excelHeader: null,
    };
  }

  // Check if template is uploaded
  if (templateHeaders.length === 0) {
    return {
      isWanted: true,
      status: 'UNMAPPED',
      statusLabel: 'Template Missing',
      isMapped: false,
      reason: 'NO_TEMPLATE_UPLOADED',
      excelHeader: rawHeader,
    };
  }

  // Exact header check against uploaded template headers
  if (templateHeaders.includes(rawHeader)) {
    return {
      isWanted: true,
      status: 'MAPPED',
      statusLabel: 'Mapped',
      isMapped: true,
      excelHeader: rawHeader,
    };
  }

  // Target header was configured previously, but does not exist in the currently uploaded Excel template
  return {
    isWanted: true,
    status: 'TEMPLATE_HEADER_MISSING',
    statusLabel: 'Template Header Missing',
    isMapped: false,
    reason: 'TEMPLATE_HEADER_MISSING',
    excelHeader: rawHeader,
  };
}

export const BatchDataExtraction: React.FC = () => {
  const { batchId } = useParams<{ batchId: string }>();
  const navigate = useNavigate();
  const { addToast } = useToastStore();
  const { classesByBatch, fetchClassesForBatch } = useBatchStore();

  const [batchStats, setBatchStats] = useState<BatchExtractionStats | null>(null);
  const [_history, setHistory] = useState<BatchExtractionSummary[]>([]);
  const [selectedExtractionId, setSelectedExtractionId] = useState<string | null>(null);
  const [extractionDetail, setExtractionDetail] = useState<BatchExtractionDetail | null>(null);
  const [inspectStudent, setInspectStudent] = useState<StudentExtractionRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [downloadingRequestId, setDownloadingRequestId] = useState<string | null>(null);

  // Section / Class Scope Filtering
  const [selectedClassId, setSelectedClassId] = useState<string>('all');

  // Active Workspace Tab: 'config' | 'students'
  const [activeTab, setActiveTab] = useState<'config' | 'students'>('config');

  // Common Student Verification Portal Link State
  const [copiedCommonLink, setCopiedCommonLink] = useState(false);

  // Document Configuration Overview State
  const [wantedOverview, setWantedOverview] = useState<DocumentTypeOverviewItem[]>([]);
  const [loadingOverview, setLoadingOverview] = useState(false);

  // Configure Document Modal State
  const [activeConfigDoc, setActiveConfigDoc] = useState<DocumentTypeOverviewItem | null>(null);
  const [isConfigModalOpen, setIsConfigModalOpen] = useState(false);
  const [modalFields, setModalFields] = useState<WantedFieldItem[]>([]);
  const [modalAvailableFields, setModalAvailableFields] = useState<string[]>([]);
  const [newCustomFieldName, setNewCustomFieldName] = useState('');
  const [isAddingField, setIsAddingField] = useState(false);
  const [isSavingConfig, setIsSavingConfig] = useState(false);
  const [fieldSearchQuery, setFieldSearchQuery] = useState('');

  // Add Custom Document Type Modal State
  const [isAddDocModalOpen, setIsAddDocModalOpen] = useState(false);
  const [newDocName, setNewDocName] = useState('');
  const [newDocCode, setNewDocCode] = useState('');
  const [newDocDesc, setNewDocDesc] = useState('');
  const [newDocReqStatus, setNewDocReqStatus] = useState<'REQUIRED' | 'OPTIONAL'>('REQUIRED');
  const [isCreatingDocType, setIsCreatingDocType] = useState(false);

  // Extraction Execution & Uploaded Excel Template State
  const [isExtracting, setIsExtracting] = useState(false);
  const [templateFile, setTemplateFile] = useState<File | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Uploaded Excel Headers (Source of truth for available target output fields)
  const [uploadedExcelHeaders, setUploadedExcelHeaders] = useState<string[]>(() => {
    if (!batchId) return [];
    try {
      const saved = localStorage.getItem(`admi_extract_template_${batchId}`);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed.headers) && parsed.headers.length > 0) {
          return parsed.headers;
        }
      }
    } catch (e) {}
    return [];
  });

  const [templateFilename, setTemplateFilename] = useState<string>(() => {
    if (!batchId) return '';
    try {
      const saved = localStorage.getItem(`admi_extract_template_${batchId}`);
      if (saved) {
        const parsed = JSON.parse(saved);
        return parsed.filename || '';
      }
    } catch (e) {}
    return '';
  });

  // Filtering, Searching, & Pagination for Students Table
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [page, setPage] = useState(1);
  const pageSize = 50;

  // Retry state & Cancel
  const [retryingStudentId, setRetryingStudentId] = useState<string | null>(null);
  const [cancellingExtraction, setCancellingExtraction] = useState(false);

  // Polling ref for live extraction progress
  const pollTimerRef = useRef<any>(null);

  // Search debounce
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearch(searchTerm);
      setPage(1);
    }, 300);
    return () => clearTimeout(handler);
  }, [searchTerm]);

  // Load Batch overview, history, and classes
  const fetchBatchData = async () => {
    if (!batchId) return;
    try {
      setLoading(true);
      const [statsData, historyData] = await Promise.all([
        dataExtractionService.getBatchOverview(batchId),
        dataExtractionService.listBatchHistory(batchId),
        fetchClassesForBatch(batchId),
      ]);
      setBatchStats(statsData);
      setHistory(historyData);

      if (historyData.length > 0 && !selectedExtractionId) {
        setSelectedExtractionId(historyData[0].extraction_request_id);
      }
    } catch (err: any) {
      addToast(err?.response?.data?.detail || 'Failed to load batch extraction data', 'error');
    } finally {
      setLoading(false);
    }
  };

  // Load Document Types Overview for Data Extraction
  const loadWantedOverview = useCallback(async () => {
    if (!batchId) return;
    try {
      setLoadingOverview(true);
      const classParam = selectedClassId === 'all' ? undefined : selectedClassId;
      const backendOverview = await wantedFieldService.getBatchOverview(batchId, classParam);

      // Build catalog map for field enrichment
      const catalogMap = new Map<string, typeof STANDARD_DOC_CATALOG[0]>();
      for (const preset of STANDARD_DOC_CATALOG) {
        catalogMap.set(preset.document_type.toUpperCase(), preset);
      }

      // Render only the document types actually configured/available for this batch
      const mergedList: DocumentTypeOverviewItem[] = backendOverview.map((item) => {
        const code = (item.document_type || '').toUpperCase().trim();
        const preset = catalogMap.get(code);
        const avSet = new Set([
          ...(item.available_fields || []),
          ...(item.fields ? item.fields.map((f: any) => f.field) : []),
          ...(preset ? preset.available_fields : []),
        ]);
        return {
          ...item,
          display_name: item.display_name || preset?.display_name || item.document_type,
          available_fields: Array.from(avSet),
        };
      });

      setWantedOverview(mergedList);
    } catch (err: any) {
      console.error('Failed to load wanted fields overview:', err);
      addToast(err?.response?.data?.detail || 'Failed to load document configuration', 'error');
    } finally {
      setLoadingOverview(false);
    }
  }, [batchId, selectedClassId, addToast]);

  useEffect(() => {
    fetchBatchData();
  }, [batchId]);

  useEffect(() => {
    loadWantedOverview();
  }, [loadWantedOverview]);

  // Fetch extraction details when inspecting a run
  const fetchExtractionDetail = useCallback(
    async (requestId: string, silent = false) => {
      try {
        if (!silent) setLoadingDetail(true);
        const detail = await dataExtractionService.getExtractionDetails(requestId, {
          status_filter: statusFilter,
          search: debouncedSearch,
          page,
          page_size: pageSize,
        });
        setExtractionDetail(detail);
      } catch (err: any) {
        if (!silent) {
          addToast(err?.response?.data?.detail || 'Failed to load extraction details', 'error');
        }
      } finally {
        if (!silent) setLoadingDetail(false);
      }
    },
    [statusFilter, debouncedSearch, page, pageSize, addToast]
  );

  useEffect(() => {
    if (selectedExtractionId) {
      fetchExtractionDetail(selectedExtractionId);
    }
  }, [selectedExtractionId, statusFilter, debouncedSearch, page, fetchExtractionDetail]);

  // Live progress polling when extraction is running
  useEffect(() => {
    if (
      selectedExtractionId &&
      extractionDetail &&
      (extractionDetail.summary.status === 'PROCESSING' || extractionDetail.summary.status === 'DRAFT')
    ) {
      pollTimerRef.current = setInterval(() => {
        fetchExtractionDetail(selectedExtractionId, true);
      }, 3000);
    } else if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [selectedExtractionId, extractionDetail, fetchExtractionDetail]);

  // Open Configure Modal for a Document Type
  const handleOpenConfigure = async (doc: DocumentTypeOverviewItem) => {
    setActiveConfigDoc(doc);
    setFieldSearchQuery('');
    setNewCustomFieldName('');
    setIsAddingField(false);
    setIsConfigModalOpen(true);

    try {
      const classParam = selectedClassId === 'all' ? undefined : selectedClassId;
      const freshDoc = await wantedFieldService.getDocumentConfig(batchId!, doc.document_type, classParam);

      const allAv = Array.from(
        new Set([
          ...(freshDoc.available_fields || []),
          ...(doc.available_fields || []),
          ...freshDoc.fields.map((f) => f.field),
        ])
      );
      setModalAvailableFields(allAv);

      const fieldMap = new Map<string, WantedFieldItem>();
      for (const f of freshDoc.fields) {
        fieldMap.set(f.field, { ...f });
      }

      const initialModalFields: WantedFieldItem[] = allAv.map((field) => {
        if (fieldMap.has(field)) {
          return fieldMap.get(field)!;
        }
        return {
          field,
          enabled: false,
          excel_header: null,
        };
      });

      setModalFields(initialModalFields);
      setActiveConfigDoc((prev) =>
        prev
          ? {
              ...prev,
              display_name: freshDoc.display_name || prev.display_name,
              requirement_status: freshDoc.requirement_status || prev.requirement_status,
              version: freshDoc.version || prev.version,
              fields: freshDoc.fields || prev.fields,
              available_fields: allAv,
            }
          : prev
      );
    } catch (e) {
      // Fallback to currently loaded doc item
      const allAv = Array.from(
        new Set([...(doc.available_fields || []), ...doc.fields.map((f) => f.field)])
      );
      setModalAvailableFields(allAv);

      const fieldMap = new Map<string, WantedFieldItem>();
      for (const f of doc.fields) {
        fieldMap.set(f.field, { ...f });
      }

      const initialModalFields: WantedFieldItem[] = allAv.map((field) => {
        if (fieldMap.has(field)) {
          return fieldMap.get(field)!;
        }
        return {
          field,
          enabled: false,
          excel_header: null,
        };
      });

      setModalFields(initialModalFields);
    }
  };

  // Toggle field wanted status in modal
  const handleToggleField = (fieldName: string) => {
    setModalFields((prev) =>
      prev.map((item) => {
        if (item.field === fieldName) {
          const nextEnabled = !item.enabled;
          let newHeader = item.excel_header;
          if (nextEnabled) {
            // Check if existing header is valid in uploadedExcelHeaders, else leave null
            if (!newHeader || !uploadedExcelHeaders.includes(newHeader)) {
              newHeader = null;
            }
          }
          return {
            ...item,
            enabled: nextEnabled,
            excel_header: nextEnabled ? newHeader : item.excel_header,
          };
        }
        return item;
      })
    );
  };

  // Change Excel header mapping for a field in modal
  const handleHeaderChange = (fieldName: string, newHeader: string) => {
    const cleanHeader = newHeader.trim();
    if (cleanHeader) {
      // Check for duplicate header mapping within this document configuration
      const alreadyMappedTo = modalFields.find(
        (f) => f.field !== fieldName && f.enabled && f.excel_header === cleanHeader
      );
      if (alreadyMappedTo) {
        addToast(
          `Excel header "${cleanHeader}" is already mapped to "${alreadyMappedTo.field}". Each column should be mapped to one source field.`,
          'info'
        );
      }
    }

    setModalFields((prev) =>
      prev.map((item) => {
        if (item.field === fieldName) {
          return {
            ...item,
            excel_header: cleanHeader ? cleanHeader : null,
          };
        }
        return item;
      })
    );
  };

  // Select All fields in modal
  const handleSelectAllFields = () => {
    setModalFields((prev) =>
      prev.map((item) => ({
        ...item,
        enabled: true,
        excel_header:
          item.excel_header && uploadedExcelHeaders.includes(item.excel_header)
            ? item.excel_header
            : null,
      }))
    );
  };

  // Deselect All fields in modal
  const handleDeselectAllFields = () => {
    setModalFields((prev) =>
      prev.map((item) => ({
        ...item,
        enabled: false,
      }))
    );
  };

  // Add Custom Field to this document type
  const handleAddCustomField = async () => {
    if (!newCustomFieldName.trim() || !activeConfigDoc || !batchId) return;
    const cleanName = newCustomFieldName.trim();

    if (modalAvailableFields.some((f) => f.toLowerCase() === cleanName.toLowerCase())) {
      addToast(`Field "${cleanName}" already exists in ${activeConfigDoc.display_name}`, 'info');
      setNewCustomFieldName('');
      setIsAddingField(false);
      return;
    }

    setModalAvailableFields((prev) => [...prev, cleanName]);
    setModalFields((prev) => [
      ...prev,
      {
        field: cleanName,
        enabled: true,
        excel_header: null,
      },
    ]);
    setNewCustomFieldName('');
    setIsAddingField(false);
    addToast(`Added field "${cleanName}" to ${activeConfigDoc.display_name}. Please map it to an uploaded Excel header.`, 'success');
  };

  // Save Document Configuration
  const handleSaveDocumentConfig = async () => {
    if (!batchId || !activeConfigDoc) return;
    try {
      setIsSavingConfig(true);
      const classParam = selectedClassId === 'all' ? undefined : selectedClassId;

      await wantedFieldService.saveDocumentConfig(
        batchId,
        activeConfigDoc.document_type,
        modalFields,
        classParam,
        {
          display_name: activeConfigDoc.display_name,
          description: activeConfigDoc.description || undefined,
          requirement_status: activeConfigDoc.requirement_status,
          allowed_types: activeConfigDoc.allowed_types,
          max_size_mb: activeConfigDoc.max_size_mb,
        }
      );

      const wantedCount = modalFields.filter((f) => f.enabled).length;
      const mappedCount = modalFields.filter((f) => {
        const v = validateMappingAgainstTemplate(f, uploadedExcelHeaders);
        return v.isMapped;
      }).length;
      const unmappedCount = wantedCount - mappedCount;

      if (unmappedCount > 0) {
        addToast(
          `Saved ${activeConfigDoc.display_name} configuration (${wantedCount} wanted, ${mappedCount} mapped, ${unmappedCount} unmapped/missing in Excel template). Please resolve all mappings before extraction.`,
          'info'
        );
      } else {
        addToast(
          `Saved ${activeConfigDoc.display_name} configuration (${wantedCount} wanted, ${mappedCount} mapped).`,
          'success'
        );
      }

      setIsConfigModalOpen(false);
      await loadWantedOverview();
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to save document configuration', 'error');
    } finally {
      setIsSavingConfig(false);
    }
  };

  // Delete document type
  const handleDeleteDocumentType = async (docType: string, docName: string) => {
    if (!batchId) return;
    const confirmMsg = `Are you sure you want to delete document configuration for "${docName}" (${docType})? If student files reference this document, it will be safely archived to protect uploaded records.`;
    if (!window.confirm(confirmMsg)) return;

    try {
      const classParam = selectedClassId === 'all' ? undefined : selectedClassId;
      const res = await wantedFieldService.deleteDocumentType(batchId, docType, classParam);
      addToast(res.message, res.archived ? 'info' : 'success');
      if (activeConfigDoc?.document_type === docType) {
        setActiveConfigDoc(null);
      }
      await loadWantedOverview();
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to delete document type.', 'error');
    }
  };

  // Create new document type
  const handleCreateDocumentType = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!batchId) return;
    const nameClean = newDocName.trim();
    const codeClean = newDocCode.trim().toUpperCase().replace(/[\s-]+/g, '_');

    if (!nameClean || !codeClean) {
      addToast('Document Name and Code are required.', 'error');
      return;
    }

    try {
      setIsCreatingDocType(true);
      const classParam = selectedClassId === 'all' ? undefined : selectedClassId;
      await wantedFieldService.createDocumentType(
        batchId,
        {
          name: nameClean,
          code: codeClean,
          description: newDocDesc.trim() || undefined,
          requirement_status: newDocReqStatus,
        },
        classParam
      );

      addToast(`Document type "${nameClean}" created for extraction.`, 'success');
      setIsAddDocModalOpen(false);
      setNewDocName('');
      setNewDocCode('');
      setNewDocDesc('');
      await loadWantedOverview();
    } catch (err: any) {
      addToast(err?.response?.data?.detail || err?.message || 'Failed to create document type', 'error');
    } finally {
      setIsCreatingDocType(false);
    }
  };

  // Upload and Parse Excel Template (Source of truth for available target output fields)
  // Load saved template metadata from backend on batch selection
  useEffect(() => {
    if (!batchId) return;
    const classParam = selectedClassId === 'all' ? undefined : selectedClassId;
    dataExtractionService.getBatchTemplate(batchId, classParam)
      .then((tmpl) => {
        if (tmpl && tmpl.requested_columns && tmpl.requested_columns.length > 0) {
          setUploadedExcelHeaders(tmpl.requested_columns);
          setTemplateFilename(tmpl.template_filename || '');
        }
      })
      .catch(() => {});
  }, [batchId, selectedClassId]);

  // Upload and Parse Excel Template (Source of truth for available target output fields)
  const handleTemplateUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (uploadedExcelHeaders.length > 0 && extractionStatsSummary.totalMapped > 0) {
      const confirmed = window.confirm(
        'Uploading a new template will replace the available Excel headers. Existing mappings that no longer exist in the new template will become Unmapped. Do you wish to proceed?'
      );
      if (!confirmed) {
        e.target.value = '';
        return;
      }
    }

    setTemplateFile(file);
    setTemplateFilename(file.name);
    try {
      setPreviewLoading(true);
      const classParam = selectedClassId === 'all' ? undefined : selectedClassId;
      const preview = await dataExtractionService.previewExcelTemplate(file, batchId, classParam);
      const headers = preview.requested_columns || [];
      setUploadedExcelHeaders(headers);
      if (preview.template_filename) {
        setTemplateFilename(preview.template_filename);
      }

      if (batchId) {
        localStorage.setItem(
          `admi_extract_template_${batchId}`,
          JSON.stringify({ filename: file.name, headers })
        );
      }

      addToast(
        `Uploaded Excel template "${file.name}" with ${headers.length} exact column headers.`,
        'success'
      );
    } catch (err: any) {
      addToast(err?.response?.data?.detail || 'Failed to parse Excel template', 'error');
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleClearTemplate = () => {
    if (extractionStatsSummary.totalMapped > 0) {
      const confirmed = window.confirm(
        'Clearing the template will remove the available Excel headers. Existing field mappings will become Unmapped. Do you wish to proceed?'
      );
      if (!confirmed) return;
    }
    const classParam = selectedClassId === 'all' ? undefined : selectedClassId;
    if (batchId) {
      dataExtractionService.deleteBatchTemplate(batchId, classParam).catch(() => {});
      localStorage.removeItem(`admi_extract_template_${batchId}`);
    }
    setTemplateFile(null);
    setTemplateFilename('');
    setUploadedExcelHeaders([]);
    addToast('Excel template cleared. Upload an Excel template to configure extraction fields.', 'info');
  };

  // Compute Aggregated Wanted, Mapped, Unmapped Fields across all configured documents
  const extractionStatsSummary = useMemo(() => {
    let totalWanted = 0;
    let totalMapped = 0;
    let totalUnmapped = 0;
    let configuredDocsCount = 0;

    const allMappedEntries: {
      docType: string;
      docName: string;
      fieldName: string;
      excelHeader: string;
      validation: FieldMappingValidationResult;
    }[] = [];

    const requestedFieldsList: string[] = [];
    const requestedColumnsList: string[] = [];
    const columnMappingDict: Record<string, string> = {};

    for (const doc of wantedOverview) {
      let docHasWanted = false;
      for (const f of doc.fields) {
        if (f.enabled) {
          docHasWanted = true;
          totalWanted += 1;
          const valRes = validateMappingAgainstTemplate(f, uploadedExcelHeaders);

          if (valRes.isMapped) {
            totalMapped += 1;
            if (valRes.excelHeader) {
              requestedColumnsList.push(valRes.excelHeader);
              const canonKey = (f.field || '').toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_').trim();
              columnMappingDict[valRes.excelHeader] = canonKey;
            }
          } else {
            totalUnmapped += 1;
          }

          const canonKey = (f.field || '').toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_').trim();
          requestedFieldsList.push(canonKey);

          allMappedEntries.push({
            docType: doc.document_type,
            docName: doc.display_name,
            fieldName: f.field,
            excelHeader: f.excel_header?.trim() || '(Unmapped)',
            validation: valRes,
          });
        }
      }
      if (docHasWanted) {
        configuredDocsCount += 1;
      }
    }

    return {
      totalWanted,
      totalMapped,
      totalUnmapped,
      configuredDocsCount,
      allMappedEntries,
      requestedFieldsList: Array.from(new Set(requestedFieldsList)),
      requestedColumnsList: uploadedExcelHeaders.length > 0 ? uploadedExcelHeaders : Array.from(new Set(requestedColumnsList)),
      columnMappingDict,
    };
  }, [wantedOverview, uploadedExcelHeaders]);

  // Execute Data Extraction for ALL Students
  const handleStartExtraction = async () => {
    if (!batchId) return;

    if (uploadedExcelHeaders.length === 0) {
      addToast('Upload an Excel template and configure field mappings before extraction.', 'error');
      return;
    }

    if (extractionStatsSummary.totalWanted === 0) {
      addToast('Please configure at least one document and select wanted fields for extraction.', 'error');
      return;
    }

    if (extractionStatsSummary.totalUnmapped > 0) {
      addToast(
        `Cannot extract: ${extractionStatsSummary.totalUnmapped} wanted field(s) have missing or unmapped Excel template headers. Resolve all mappings before extraction.`,
        'error'
      );
      return;
    }

    try {
      setIsExtracting(true);
      const classParam = selectedClassId === 'all' ? undefined : selectedClassId;

      const payload: any = {
        requested_fields: extractionStatsSummary.requestedFieldsList,
        requested_columns: extractionStatsSummary.requestedColumnsList,
        column_mapping: extractionStatsSummary.columnMappingDict,
        template_filename: templateFile?.name,
        class_id: classParam,
      };

      const result = await dataExtractionService.createBatchExtraction(batchId, payload);
      addToast(
        `Extraction started for ALL ${batchStats?.students_count || 0} students from permanently stored documents!`,
        'success'
      );

      await fetchBatchData();
      setSelectedExtractionId(result.extraction_request_id);
      setActiveTab('students');
      setPage(1);
    } catch (err: any) {
      addToast(err?.response?.data?.detail || 'Failed to start data extraction', 'error');
    } finally {
      setIsExtracting(false);
    }
  };

  // Safe Cancel Extraction
  const handleCancelExtraction = async () => {
    if (!selectedExtractionId) return;
    try {
      setCancellingExtraction(true);
      await dataExtractionService.cancelExtraction(selectedExtractionId);
      addToast('Extraction request cancelled. Source documents remain intact.', 'info');
      fetchExtractionDetail(selectedExtractionId);
      fetchBatchData();
    } catch (err: any) {
      addToast(err?.response?.data?.detail || 'Failed to cancel extraction', 'error');
    } finally {
      setCancellingExtraction(false);
    }
  };

  // Retry Student Extraction
  const handleRetryStudent = async (studentId: string) => {
    if (!selectedExtractionId) return;
    try {
      setRetryingStudentId(studentId);
      await dataExtractionService.retryStudentExtraction(selectedExtractionId, studentId);
      addToast(`Re-extracted fields for student ${studentId}`, 'success');
      fetchExtractionDetail(selectedExtractionId, true);
    } catch (err: any) {
      addToast(err?.response?.data?.detail || `Failed to retry extraction for ${studentId}`, 'error');
    } finally {
      setRetryingStudentId(null);
    }
  };

  // Batch verification metrics & lock calculation
  const currentSummary = extractionDetail?.summary;
  const totalStudentsCount = currentSummary?.total_students ?? extractionDetail?.students.length ?? 0;
  const verifiedStudentsCount = currentSummary?.verified_count ?? 0;
  const pendingVerificationCount =
    currentSummary?.pending_verification_count ?? Math.max(0, totalStudentsCount - verifiedStudentsCount);
  const isAllVerified =
    totalStudentsCount > 0 && verifiedStudentsCount === totalStudentsCount && pendingVerificationCount === 0;

  // Single common verification link for all students in the batch
  const commonVerificationUrl = useMemo(() => {
    const origin = window.location.origin;
    const extId = currentSummary?.extraction_request_id || selectedExtractionId;
    const extParam = extId ? `&extraction_id=${encodeURIComponent(extId)}` : '';
    return `${origin}/student-verification?batch_id=${encodeURIComponent(batchId || '')}${extParam}`;
  }, [batchId, currentSummary?.extraction_request_id, selectedExtractionId]);

  const handleCopyCommonLink = () => {
    navigator.clipboard
      .writeText(commonVerificationUrl)
      .then(() => {
        setCopiedCommonLink(true);
        addToast('Common verification link copied to clipboard!', 'success');
        setTimeout(() => setCopiedCommonLink(false), 2500);
      })
      .catch(() => {
        addToast('Failed to copy common verification link', 'error');
      });
  };

  // Helper for Export Status Badge
  const renderExportBadge = (status?: string) => {
    switch (status) {
      case 'READY':
        return (
          <span className="px-2.5 py-1 rounded-full text-[11px] font-black uppercase tracking-wider bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 inline-flex items-center gap-1.5">
            <Check className="h-3 w-3" />
            READY
          </span>
        );
      case 'EXPORTED':
        return (
          <span className="px-2.5 py-1 rounded-full text-[11px] font-black uppercase tracking-wider bg-purple-500/10 text-purple-600 dark:text-purple-400 border border-purple-500/30 inline-flex items-center gap-1.5">
            <Download className="h-3 w-3" />
            EXPORTED
          </span>
        );
      case 'PARTIALLY_VERIFIED':
        return (
          <span className="px-2.5 py-1 rounded-full text-[11px] font-black uppercase tracking-wider bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/30 inline-flex items-center gap-1.5">
            <Clock className="h-3 w-3" />
            PARTIALLY VERIFIED
          </span>
        );
      default:
        return (
          <span className="px-2.5 py-1 rounded-full text-[11px] font-black uppercase tracking-wider bg-slate-500/10 text-slate-600 dark:text-slate-400 border border-slate-500/30 inline-flex items-center gap-1.5">
            <AlertTriangle className="h-3 w-3" />
            NOT READY
          </span>
        );
    }
  };

  // Download Batch Excel (enforces all eligible students verified)
  const handleDownload = async (requestId?: string) => {
    const targetId = requestId || selectedExtractionId;
    if (!targetId) return;
    if (downloadingRequestId) return;

    if (!isAllVerified) {
      addToast(
        `Cannot download final Excel: All eligible students must complete verification before export (${verifiedStudentsCount} / ${totalStudentsCount} students verified • ${pendingVerificationCount} students pending).`,
        'error'
      );
      return;
    }

    setDownloadingRequestId(targetId);
    try {
      addToast('Preparing final verified Excel download...', 'info');
      await dataExtractionService.downloadVerifiedExcel(targetId);
      addToast('Final verified Excel file downloaded successfully!', 'success');
      fetchBatchData();
      if (selectedExtractionId === targetId) {
        fetchExtractionDetail(targetId, true);
      }
    } catch (err: any) {
      const errorMessage =
        err?.message ||
        err?.response?.data?.detail ||
        'Failed to download batch Excel export';
      addToast(errorMessage, 'error');
    } finally {
      setDownloadingRequestId(null);
    }
  };

  if (loading && !batchStats) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <RefreshCw className="h-8 w-8 text-primary animate-spin" />
      </div>
    );
  }

  const batchClasses = (batchId ? classesByBatch[batchId] : []) || [];
  const totalPages = Math.ceil((extractionDetail?.total_matching_students || 0) / pageSize);


  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-16">
      {/* Top Navigation & Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <button
            onClick={() => navigate('/data-extraction')}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted-foreground hover:text-foreground transition-colors mb-2 cursor-pointer"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Data Extraction Batches
          </button>
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-foreground flex items-center gap-2.5">
              <span className="p-2 rounded-xl bg-primary/10 text-primary border border-primary/20">
                <FileSpreadsheet className="h-6 w-6" />
              </span>
              DATA EXTRACTION WORKSPACE
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-primary/10 text-primary border border-primary/20">
              {batchStats?.academic_year}
            </span>
          </div>
          <p className="text-xs sm:text-sm text-muted-foreground mt-1">
            Batch: <span className="font-bold text-foreground">{batchStats?.batch_name}</span> • Department:{' '}
            <span className="font-semibold text-foreground">{batchStats?.department_id}</span> • Scope:{' '}
            <span className="font-bold text-emerald-600 dark:text-emerald-400">
              ALL {batchStats?.students_count || 0} Students
            </span>
          </p>
        </div>

        {/* Scope & Fast Actions */}
        <div className="flex items-center gap-2.5 flex-wrap">
          {batchClasses.length > 0 && (
            <div className="flex items-center gap-2 bg-card px-3 py-1.5 rounded-xl border border-border shadow-2xs">
              <span className="text-xs font-bold text-muted-foreground uppercase flex items-center gap-1.5">
                <Layers className="h-4 w-4 text-primary" /> Scope:
              </span>
              <select
                value={selectedClassId}
                onChange={(e) => setSelectedClassId(e.target.value)}
                className="px-3 py-1 rounded-lg border border-border bg-background text-xs font-bold text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary cursor-pointer"
              >
                <option value="all">Entire Batch ({batchStats?.students_count || 0} Students)</option>
                {batchClasses.map((cls) => (
                  <option key={cls.id} value={cls.id}>
                    {cls.class_name} (Sec {cls.section})
                  </option>
                ))}
              </select>
            </div>
          )}

          <button
            onClick={() => {
              const extId = extractionDetail?.summary?.extraction_request_id || selectedExtractionId;
              const extParam = extId ? `&extraction_id=${encodeURIComponent(extId)}` : '';
              const url = `${window.location.origin}/student-verification?batch_id=${encodeURIComponent(batchId || '')}${extParam}`;
              navigator.clipboard.writeText(url);
              addToast('Copied Common Verification Link to clipboard!', 'success');
            }}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-bold rounded-xl border border-primary/40 bg-primary/10 hover:bg-primary/20 text-primary transition-all cursor-pointer shadow-2xs"
            title="Copy one common verification URL for all students in this batch"
          >
            <Copy className="h-3.5 w-3.5" />
            Copy Common Verification Link
          </button>

          <button
            onClick={() => {
              loadWantedOverview();
              fetchBatchData();
            }}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold rounded-xl border border-border bg-card hover:bg-muted text-foreground transition-all cursor-pointer shadow-2xs"
            title="Refresh configurations"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loadingOverview ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Architectural Separation Banner */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-emerald-950/90 via-slate-900 to-slate-950 border border-emerald-500/30 p-5 text-white shadow-xl">
        <div className="relative z-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="space-y-1.5 max-w-3xl">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 text-[11px] font-bold uppercase tracking-wider border border-emerald-400/30">
              <Sparkles className="h-3.5 w-3.5" />
              Document Intelligence Architecture
            </div>
            <h2 className="text-lg font-bold tracking-tight text-white">
              STORE ONCE • CONFIGURE WANTED FIELDS • EXTRACT FOR ALL STUDENTS
            </h2>
            <p className="text-xs text-slate-300 leading-relaxed">
              Student certificates are collected once during Admission and stored permanently. Configure exactly which
              fields you want from each document type below. Extraction runs across <strong>all stored student documents</strong> without asking students to re-upload.
            </p>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 shrink-0 bg-white/5 p-2.5 rounded-xl border border-white/10 backdrop-blur-xs text-center w-full md:w-auto">
            <div className="p-1.5">
              <div className="text-[10px] font-bold text-slate-400 uppercase">Scope</div>
              <div className="text-sm font-black text-blue-400">
                {selectedClassId === 'all'
                  ? `ALL ${batchStats?.students_count || 0} Students`
                  : `${batchClasses.find((c) => c.id === selectedClassId)?.class_name || 'Section'} (${(batchClasses.length === 1 ? (batchStats?.students_count || batchClasses.find((c) => c.id === selectedClassId)?.stats?.students) : batchClasses.find((c) => c.id === selectedClassId)?.stats?.students) || 0} Students)`}
              </div>
            </div>
            <div className="p-1.5 border-l border-white/10">
              <div className="text-[10px] font-bold text-slate-400 uppercase">Stored Docs</div>
              <div className="text-sm font-black text-emerald-400">{batchStats?.stored_documents_count || 0}</div>
            </div>
            <div className="p-1.5 border-l border-white/10">
              <div className="text-[10px] font-bold text-slate-400 uppercase">Wanted</div>
              <div className="text-sm font-black text-lime-400">{extractionStatsSummary.totalWanted}</div>
            </div>
            <div className="p-1.5 border-l border-white/10">
              <div className="text-[10px] font-bold text-slate-400 uppercase">Mapped</div>
              <div className="text-sm font-black text-emerald-300">{extractionStatsSummary.totalMapped}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Workspace Navigation Tabs - Exactly Two Tabs */}
      <div className="border-b border-border flex items-center gap-2 sm:gap-6 overflow-x-auto pb-0">
        <button
          onClick={() => setActiveTab('config')}
          className={`pb-3 text-xs sm:text-sm font-bold border-b-2 transition-all cursor-pointer flex items-center gap-2 whitespace-nowrap ${
            activeTab === 'config'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <Settings2 className="h-4 w-4" />
          Data Configuration & Extraction
          <span className="px-2 py-0.5 rounded-full text-[10px] font-extrabold bg-primary/10 text-primary">
            {extractionStatsSummary.totalWanted} Fields
          </span>
        </button>

        <button
          onClick={() => setActiveTab('students')}
          className={`pb-3 text-xs sm:text-sm font-bold border-b-2 transition-all cursor-pointer flex items-center gap-2 whitespace-nowrap ${
            activeTab === 'students'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <FileCheck2 className="h-4 w-4" />
          Student Details
          {selectedExtractionId && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-muted text-muted-foreground">
              {selectedExtractionId}
            </span>
          )}
        </button>
      </div>

      {/* ========================================================================= */}
      {/* TAB 1: DOCUMENT CONFIGURATION & EXTRACT WORKFLOW                          */}
      {/* ========================================================================= */}
      {activeTab === 'config' && (
        <div className="space-y-8">
          {/* Section Header */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-3 border-b border-border">
            <div>
              <div className="flex items-center gap-2">
                <FileText className="h-5 w-5 text-emerald-400" />
                <h2 className="text-xl font-black text-foreground tracking-tight uppercase">DOCUMENT CONFIGURATION</h2>
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                Configure extraction field selections and map them to Excel headers.
              </p>
            </div>

            <div className="flex items-center gap-3 flex-wrap">
              {batchClasses.length > 0 && (
                <div className="flex items-center gap-2 bg-card px-3 py-1.5 rounded-xl border border-border">
                  <span className="text-[11px] font-bold text-muted-foreground uppercase flex items-center gap-1.5">
                    <Layers className="h-3.5 w-3.5 text-emerald-400" /> CLASS SCOPE:
                  </span>
                  <select
                    value={selectedClassId}
                    onChange={(e) => setSelectedClassId(e.target.value)}
                    className="px-2.5 py-1 rounded-lg border border-border bg-background text-xs font-bold text-foreground focus:outline-none focus:ring-1 focus:ring-emerald-500 cursor-pointer"
                  >
                    <option value="all">Batch Level (Default)</option>
                    {batchClasses.map((cls) => (
                      <option key={cls.id} value={cls.id}>
                        {cls.class_name} (Sec {cls.section})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <button
                type="button"
                onClick={() => setIsAddDocModalOpen(true)}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs shadow-xs transition-colors cursor-pointer"
              >
                <Plus className="h-3.5 w-3.5 stroke-[3]" /> Add Document Type
              </button>

              <button
                type="button"
                onClick={() => {
                  loadWantedOverview();
                  fetchBatchData();
                }}
                disabled={loadingOverview}
                className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold rounded-xl border border-border bg-card hover:bg-muted text-foreground transition-all cursor-pointer disabled:opacity-50"
                title="Refresh configurations"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loadingOverview ? 'animate-spin' : ''}`} />
                Refresh
              </button>
            </div>
          </div>

          {/* ========================================================================= */}
          {/* STEP 1: EXCEL TEMPLATE UPLOADER (SOURCE OF TRUTH FOR TARGET OUTPUT FIELDS) */}
          {/* ========================================================================= */}
          <div className="rounded-2xl border border-zinc-800 bg-zinc-950/70 p-5 space-y-4 shadow-md">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-zinc-800/80">
              <div className="space-y-0.5">
                <div className="flex items-center gap-2">
                  <FileSpreadsheet className="h-4 w-4 text-emerald-400" />
                  <h3 className="text-sm font-black text-foreground uppercase tracking-tight">
                    UPLOAD EXCEL TEMPLATE
                  </h3>
                  {uploadedExcelHeaders.length > 0 && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-400 border border-emerald-800/40 flex items-center gap-1">
                      <Check className="h-3 w-3 stroke-[3]" /> Active Template ({uploadedExcelHeaders.length} Columns)
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  Upload an Excel template to configure extraction fields and output columns. The uploaded column headers define the available target Excel fields.
                </p>
              </div>

              {uploadedExcelHeaders.length > 0 && (
                <button
                  type="button"
                  onClick={handleClearTemplate}
                  className="text-xs text-rose-400 hover:text-rose-300 hover:underline cursor-pointer self-start sm:self-auto font-semibold"
                >
                  Clear Template
                </button>
              )}
            </div>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3 flex-wrap">
                <label className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs shadow-sm cursor-pointer transition-colors">
                  <Upload className="h-4 w-4 stroke-[2.5]" />
                  <span>{uploadedExcelHeaders.length > 0 ? 'Replace Excel Template' : 'Choose Excel Template File'}</span>
                  <input type="file" accept=".xlsx, .xls" onChange={handleTemplateUpload} className="hidden" />
                </label>

                {previewLoading && (
                  <span className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
                    <RefreshCw className="h-3.5 w-3.5 animate-spin text-emerald-400" />
                    Reading Excel column headers...
                  </span>
                )}

                {uploadedExcelHeaders.length > 0 && !previewLoading && (
                  <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-zinc-900 border border-zinc-700 text-xs font-bold text-foreground">
                    <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-400" />
                    <span>{templateFilename || 'Student_Details_Columns.xlsx'}</span>
                    <span className="text-muted-foreground font-mono text-[11px]">
                      ({uploadedExcelHeaders.length} columns available for mapping)
                    </span>
                  </div>
                )}
              </div>

              {uploadedExcelHeaders.length === 0 && !previewLoading && (
                <div className="text-xs font-medium text-amber-400 bg-amber-950/30 border border-amber-800/40 px-3 py-1.5 rounded-xl">
                  ⚠ No template uploaded. Upload an Excel file to enable target header selection.
                </div>
              )}
            </div>
          </div>

          {/* Document Types Grid */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                <Layers className="h-3.5 w-3.5 text-emerald-400" /> DOCUMENT TYPES ({wantedOverview.length})
              </span>
              <span className="text-xs text-muted-foreground">
                Click <strong>Configure</strong> on any card below to select its wanted fields
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {wantedOverview.map((item) => {
                const reqStatus = item.requirement_status || 'REQUIRED';
                const docWantedCount = item.fields.filter((f) => f.enabled).length;
                const docMappedCount = item.fields.filter((f) => {
                  const v = validateMappingAgainstTemplate(f, uploadedExcelHeaders);
                  return v.isMapped;
                }).length;
                const docUnmappedCount = docWantedCount - docMappedCount;
                const isFullyConfigured = docWantedCount > 0 && docUnmappedCount === 0 && uploadedExcelHeaders.length > 0;
                const isActive = activeConfigDoc?.document_type.toUpperCase() === item.document_type.toUpperCase();

                return (
                  <div
                    key={item.document_type}
                    className={`p-5 rounded-2xl border transition-all flex flex-col justify-between space-y-4 shadow-sm ${
                      isActive
                        ? 'bg-card border-emerald-500/50 shadow-emerald-500/5 ring-1 ring-emerald-500/30'
                        : 'bg-card border-border/80 hover:border-border'
                    }`}
                  >
                    <div className="space-y-3">
                      {/* Card Top Row: Name, Code, Badges */}
                      <div className="flex items-start justify-between gap-2">
                        <div className="space-y-0.5 min-w-0">
                          <span className="font-bold text-sm text-foreground block truncate uppercase tracking-tight">
                            {item.display_name}
                          </span>
                          <span className="text-3xs font-mono font-bold text-muted-foreground block">
                            {item.document_type}
                          </span>
                        </div>

                        <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
                          {reqStatus === 'REQUIRED' ? (
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-blue-950/80 text-blue-400 border border-blue-800/40 uppercase">
                              REQUIRED
                            </span>
                          ) : (
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-purple-950/80 text-purple-400 border border-purple-800/40 uppercase">
                              OPTIONAL
                            </span>
                          )}

                          {isFullyConfigured ? (
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-400 border border-emerald-800/40 uppercase flex items-center gap-1">
                              <Check className="h-3 w-3 text-emerald-400 stroke-[3]" /> Configured
                            </span>
                          ) : docWantedCount > 0 ? (
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-950/80 text-amber-400 border border-amber-800/40 uppercase flex items-center gap-1">
                              <AlertTriangle className="h-3 w-3 text-amber-400" /> {docUnmappedCount} Unmapped
                            </span>
                          ) : (
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-zinc-800/80 text-zinc-400 border border-zinc-700/40 uppercase">
                              Not Configured
                            </span>
                          )}

                          <button
                            type="button"
                            onClick={() => handleDeleteDocumentType(item.document_type, item.display_name)}
                            className="p-1 text-muted-foreground hover:text-red-400 hover:bg-red-950/30 rounded transition-colors cursor-pointer"
                            title="Delete Document Type"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>

                      {/* Counters Box: Wanted, Mapped, Unmapped (strictly validated against uploaded template) */}
                      <div className="grid grid-cols-3 gap-2 p-3 rounded-xl bg-zinc-950/70 border border-zinc-800/80 text-center">
                        <div className="space-y-0.5">
                          <div className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                            Wanted
                          </div>
                          <div className="text-base font-black text-foreground">{docWantedCount}</div>
                        </div>

                        <div className="space-y-0.5 border-l border-zinc-800/80">
                          <div className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider">
                            Mapped
                          </div>
                          <div className="text-base font-black text-emerald-400">{docMappedCount}</div>
                        </div>

                        <div className="space-y-0.5 border-l border-zinc-800/80">
                          <div
                            className={`text-[10px] font-bold uppercase tracking-wider ${
                              docUnmappedCount > 0 ? 'text-amber-400' : 'text-muted-foreground'
                            }`}
                          >
                            Unmapped
                          </div>
                          <div
                            className={`text-base font-black ${
                              docUnmappedCount > 0 ? 'text-amber-400' : 'text-foreground'
                            }`}
                          >
                            {docUnmappedCount}
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Card Bottom Row: Status Indicator and Configure Button */}
                    <div className="pt-3 border-t border-border/60 flex items-center justify-between gap-2">
                      <div>
                        {isActive ? (
                          <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                            Currently Configuring
                          </div>
                        ) : (
                          <div className="text-xs text-muted-foreground">
                            Status: {isFullyConfigured ? 'Configured' : docWantedCount > 0 ? 'Incomplete Mappings' : 'Not Configured'}
                          </div>
                        )}
                      </div>

                      <button
                        type="button"
                        onClick={() => handleOpenConfigure(item)}
                        className="px-3.5 py-1.5 rounded-lg text-xs font-bold border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10 cursor-pointer transition-colors"
                      >
                        Configure
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* ========================================================================= */}
            {/* SELECTED DOCUMENT CONFIGURATION PANEL (EXACT REFERENCE DESIGN)             */}
            {/* ========================================================================= */}
            {activeConfigDoc && (
              <div
                id="selected-doc-config-panel"
                className="mt-6 rounded-2xl border border-emerald-500/30 bg-card/90 p-6 shadow-xl space-y-6 animate-in fade-in slide-in-from-top-4 duration-300"
              >
                {/* Panel Header */}
                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-4 border-b border-border">
                  <div className="space-y-2">
                    <div className="flex items-center gap-2.5 flex-wrap">
                      <h3 className="text-xl font-black text-foreground uppercase tracking-tight">
                        {activeConfigDoc.display_name}
                      </h3>
                      <span className="text-xs font-mono font-bold bg-emerald-950/60 text-emerald-300 border border-emerald-800/40 px-2 py-0.5 rounded">
                        {activeConfigDoc.document_type}
                      </span>
                      <span className="text-xs font-mono font-bold bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded">
                        v{activeConfigDoc.version || 2}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 text-xs font-bold text-muted-foreground">
                      <span className="uppercase">PORTAL STATUS:</span>
                      <select
                        value={activeConfigDoc.requirement_status || 'REQUIRED'}
                        onChange={(e) => {
                          const val = e.target.value as 'REQUIRED' | 'OPTIONAL' | 'DISABLED';
                          setActiveConfigDoc((prev) => (prev ? { ...prev, requirement_status: val } : prev));
                        }}
                        className="bg-zinc-900 border border-zinc-700 text-foreground font-bold text-xs px-2.5 py-1 rounded-lg focus:outline-none focus:ring-1 focus:ring-emerald-500 cursor-pointer uppercase"
                      >
                        <option value="REQUIRED">REQUIRED</option>
                        <option value="OPTIONAL">OPTIONAL</option>
                        <option value="DISABLED">DISABLED (Hidden)</option>
                      </select>
                    </div>

                    <p className="text-xs text-muted-foreground">
                      Wanted Fields:{' '}
                      <strong className="text-foreground">
                        {modalFields.filter((f) => f.enabled).length} of {modalFields.length}
                      </strong>{' '}
                      selected for extraction • Saving updates this document&apos;s wanted fields and requirement status
                    </p>
                  </div>

                  {/* Header Actions */}
                  <div className="flex flex-col items-end gap-2 shrink-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <button
                        type="button"
                        onClick={() => setIsAddingField((prev) => !prev)}
                        className="px-3 py-1.5 rounded-lg border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-semibold transition-colors cursor-pointer inline-flex items-center gap-1.5"
                      >
                        <Plus className="h-3.5 w-3.5 text-emerald-400" />
                        Add Field
                      </button>

                      <button
                        type="button"
                        onClick={handleSelectAllFields}
                        className="px-3 py-1.5 rounded-lg border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-semibold transition-colors cursor-pointer"
                      >
                        Select All
                      </button>

                      <button
                        type="button"
                        onClick={handleDeselectAllFields}
                        className="px-3 py-1.5 rounded-lg border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-semibold transition-colors cursor-pointer"
                      >
                        Deselect All
                      </button>

                      <button
                        type="button"
                        disabled={isSavingConfig}
                        onClick={handleSaveDocumentConfig}
                        className="px-4 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs shadow-xs transition-colors cursor-pointer disabled:opacity-50 inline-flex items-center gap-1.5"
                      >
                        {isSavingConfig ? (
                          <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Check className="h-3.5 w-3.5 stroke-[3]" />
                        )}
                        <span>Save {activeConfigDoc?.display_name ? activeConfigDoc.display_name.split(' ')[0] : 'Document'} Configuration</span>
                      </button>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => handleDeleteDocumentType(activeConfigDoc.document_type, activeConfigDoc.display_name)}
                        className="px-3 py-1 rounded-lg border border-red-900/60 bg-red-950/40 hover:bg-red-950/70 text-red-400 text-xs font-semibold transition-colors cursor-pointer inline-flex items-center gap-1.5"
                        title="Delete this document type"
                      >
                        <Trash2 className="h-3.5 w-3.5 text-red-400" />
                        Delete Doc
                      </button>
                    </div>
                  </div>
                </div>

                {/* Optional Inline Add Field Input */}
                {isAddingField && (
                  <div className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800 flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
                    <div className="flex-1">
                      <input
                        type="text"
                        value={newCustomFieldName}
                        onChange={(e) => setNewCustomFieldName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            handleAddCustomField();
                          }
                        }}
                        placeholder={`e.g. Guardian Name, Birth Place, Blood Group for ${activeConfigDoc.display_name}...`}
                        className="w-full px-3.5 py-2 text-xs bg-background border border-input rounded-xl text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-emerald-500"
                        autoFocus
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={handleAddCustomField}
                        className="px-4 py-2 rounded-xl bg-emerald-500 text-slate-950 text-xs font-bold shadow-xs cursor-pointer"
                      >
                        Add to {activeConfigDoc.display_name}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setIsAddingField(false);
                          setNewCustomFieldName('');
                        }}
                        className="px-3 py-2 rounded-xl border border-border bg-card text-foreground text-xs font-semibold cursor-pointer"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}

                {/* Field Configuration Table */}
                <div className="rounded-xl border border-zinc-800 bg-zinc-950/40 overflow-hidden shadow-xs">
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="bg-zinc-900/80 border-b border-zinc-800 text-muted-foreground font-bold uppercase tracking-wider text-[11px]">
                          <th className="py-3 px-4 w-16 text-center">WANTED</th>
                          <th className="py-3 px-4">FIELD NAME</th>
                          <th className="py-3 px-4 min-w-[320px]">TARGET EXCEL HEADER COLUMN</th>
                          <th className="py-3 px-4 w-44 text-center">STATUS</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-800/80">
                        {modalFields.map((item) => {
                          const isWanted = item.enabled;
                          const valRes = validateMappingAgainstTemplate(item, uploadedExcelHeaders);

                          return (
                            <tr
                              key={item.field}
                              className={`transition-colors ${
                                isWanted ? 'bg-emerald-950/[0.04] hover:bg-emerald-950/[0.08]' : 'hover:bg-zinc-900/30 opacity-60'
                              }`}
                            >
                              {/* Wanted Checkbox */}
                              <td className="py-3.5 px-4 text-center">
                                <input
                                  type="checkbox"
                                  checked={isWanted}
                                  onChange={() => handleToggleField(item.field)}
                                  className="h-4 w-4 rounded border-zinc-700 bg-zinc-900 text-emerald-500 focus:ring-emerald-500 cursor-pointer accent-emerald-500"
                                />
                              </td>

                              {/* Field Name & Fixed Source Document */}
                              <td className="py-3.5 px-4">
                                <div className="font-bold text-foreground text-sm">{item.field}</div>
                                <div className="text-[11px] text-muted-foreground flex items-center gap-1 mt-0.5">
                                  <span>Source:</span>
                                  <span className="font-medium text-emerald-400">{activeConfigDoc.display_name}</span>
                                </div>
                              </td>

                              {/* Target Excel Header Column Dropdown */}
                              <td className="py-3.5 px-4">
                                {isWanted ? (
                                  uploadedExcelHeaders.length > 0 ? (
                                    <div className="space-y-1">
                                      <select
                                        value={uploadedExcelHeaders.includes(item.excel_header || '') ? item.excel_header! : ''}
                                        onChange={(e) => handleHeaderChange(item.field, e.target.value)}
                                        className={`w-full px-3 py-2 text-xs bg-zinc-900/90 border rounded-lg text-foreground font-medium focus:outline-none focus:ring-1 focus:ring-emerald-500 cursor-pointer shadow-2xs ${
                                          valRes.status === 'TEMPLATE_HEADER_MISSING'
                                            ? 'border-amber-500/80 ring-1 ring-amber-500/40 text-amber-200'
                                            : 'border-zinc-700'
                                        }`}
                                      >
                                        <option value="">-- Select Target Excel Header --</option>
                                        {item.excel_header && !uploadedExcelHeaders.includes(item.excel_header) && (
                                          <option value="" disabled className="text-amber-400 bg-zinc-950 font-bold">
                                            ⚠ Missing in template: &quot;{item.excel_header}&quot;
                                          </option>
                                        )}
                                        {uploadedExcelHeaders.map((opt) => (
                                          <option key={opt} value={opt}>
                                            {opt}
                                          </option>
                                        ))}
                                      </select>
                                      {valRes.status === 'TEMPLATE_HEADER_MISSING' && (
                                        <div className="text-[11px] text-amber-400 font-semibold flex items-center gap-1">
                                          <AlertTriangle className="h-3 w-3 shrink-0" />
                                          <span>Configured header &quot;{item.excel_header}&quot; not found in template. Please select an uploaded column.</span>
                                        </div>
                                      )}
                                    </div>
                                  ) : (
                                    <select
                                      disabled
                                      className="w-full px-3 py-2 text-xs bg-zinc-950/60 border border-amber-800/40 rounded-lg text-amber-400 italic opacity-80 cursor-not-allowed"
                                    >
                                      <option>-- Upload Excel template first --</option>
                                    </select>
                                  )
                                ) : (
                                  <select
                                    disabled
                                    className="w-full px-3 py-2 text-xs bg-zinc-950/60 border border-zinc-800 rounded-lg text-zinc-500 italic opacity-50 cursor-not-allowed"
                                  >
                                    <option>-- Extraction Disabled --</option>
                                  </select>
                                )}
                              </td>

                              {/* Status Badge */}
                              <td className="py-3.5 px-4 text-center">
                                {!isWanted ? (
                                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-zinc-800/80 text-zinc-400 border border-zinc-700/60">
                                    Disabled
                                  </span>
                                ) : valRes.status === 'MAPPED' ? (
                                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-950/80 text-emerald-400 border border-emerald-800/40">
                                    <Check className="h-3 w-3 stroke-[3]" /> Mapped
                                  </span>
                                ) : valRes.status === 'TEMPLATE_HEADER_MISSING' ? (
                                  <span
                                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-amber-950/80 text-amber-400 border border-amber-800/40"
                                    title="Saved target header is not present in the currently uploaded Excel template"
                                  >
                                    <AlertTriangle className="h-3 w-3" /> Template Header Missing
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-amber-950/80 text-amber-400 border border-amber-800/40">
                                    ⚠ Unmapped
                                  </span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Bottom Save Action Bar */}
                <div className="flex justify-end pt-2">
                  <button
                    type="button"
                    disabled={isSavingConfig}
                    onClick={handleSaveDocumentConfig}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-black text-xs shadow-md transition-all cursor-pointer disabled:opacity-50"
                  >
                    {isSavingConfig ? (
                      <RefreshCw className="h-4 w-4 animate-spin" />
                    ) : (
                      <Check className="h-4 w-4 stroke-[3]" />
                    )}
                    <span>Save {activeConfigDoc.display_name} Configuration</span>
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* ========================================================================= */}
          {/* EXCEL / OUTPUT FIELD MAPPING & EXTRACTION LAUNCH PANEL                     */}
          {/* ========================================================================= */}
          <div className="rounded-2xl border border-border bg-card p-6 shadow-md space-y-6">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
              <div>
                <h3 className="text-base font-bold text-foreground flex items-center gap-2">
                  <FileSpreadsheet className="h-5 w-5 text-primary" />
                  Excel Output Field Mapping & Extraction Launch
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Review the mapped fields from configured documents that will be extracted for all students.
                </p>
              </div>

              {/* Extraction Scope Indicator */}
              <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-primary/10 text-primary border border-primary/20 text-xs font-bold">
                <Users className="h-4 w-4" />
                <span>Scope: ALL {batchStats?.students_count || 0} Students</span>
              </div>
            </div>

            {/* Summary Counters */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3.5">
              <div className="p-4 rounded-xl bg-muted/30 border border-border space-y-1">
                <div className="text-[10px] font-bold uppercase text-muted-foreground">Configured Documents</div>
                <div className="text-2xl font-black text-foreground">
                  {extractionStatsSummary.configuredDocsCount}
                </div>
              </div>

              <div className="p-4 rounded-xl bg-muted/30 border border-border space-y-1">
                <div className="text-[10px] font-bold uppercase text-muted-foreground">Total Wanted Fields</div>
                <div className="text-2xl font-black text-blue-600 dark:text-blue-400">
                  {extractionStatsSummary.totalWanted}
                </div>
              </div>

              <div className="p-4 rounded-xl bg-muted/30 border border-border space-y-1">
                <div className="text-[10px] font-bold uppercase text-emerald-600 dark:text-emerald-400">
                  Mapped Columns
                </div>
                <div className="text-2xl font-black text-emerald-600 dark:text-emerald-400">
                  {extractionStatsSummary.totalMapped}
                </div>
              </div>

              <div className="p-4 rounded-xl bg-muted/30 border border-border space-y-1">
                <div
                  className={`text-[10px] font-bold uppercase ${
                    extractionStatsSummary.totalUnmapped > 0
                      ? 'text-amber-600 dark:text-amber-400'
                      : 'text-muted-foreground'
                  }`}
                >
                  Unmapped Fields
                </div>
                <div
                  className={`text-2xl font-black ${
                    extractionStatsSummary.totalUnmapped > 0
                      ? 'text-amber-600 dark:text-amber-400'
                      : 'text-foreground'
                  }`}
                >
                  {extractionStatsSummary.totalUnmapped}
                </div>
              </div>
            </div>

            {/* Live Field Mapping Breakdown Table / Chips */}
            {extractionStatsSummary.totalWanted > 0 ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between text-xs font-bold text-muted-foreground uppercase">
                  <span>Output Column Mapping Breakdown:</span>
                  <span>{extractionStatsSummary.allMappedEntries.length} field mappings configured</span>
                </div>

                <div className="rounded-xl border border-border bg-background overflow-hidden">
                  <div className="max-h-72 overflow-y-auto divide-y divide-border text-xs">
                    {extractionStatsSummary.allMappedEntries.map((entry, idx) => {
                      return (
                        <div
                          key={`${entry.docType}_${entry.fieldName}_${idx}`}
                          className="p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2 hover:bg-muted/30 transition-colors"
                        >
                          <div className="flex items-center gap-2.5 min-w-0 flex-1 flex-wrap">
                            <span className="font-bold text-foreground truncate">{entry.fieldName}</span>
                            <span className="text-muted-foreground">←</span>
                            <span className="px-2 py-0.5 rounded bg-muted text-muted-foreground font-mono text-[10px] shrink-0">
                              {entry.docName}
                            </span>
                            <span
                              className={`font-medium text-xs ${
                                entry.validation.status === 'TEMPLATE_HEADER_MISSING'
                                  ? 'text-amber-400 font-bold'
                                  : entry.validation.status === 'MAPPED'
                                  ? 'text-emerald-400'
                                  : 'text-muted-foreground'
                              }`}
                            >
                              ({entry.excelHeader})
                            </span>
                          </div>

                          <div className="shrink-0 flex items-center gap-2">
                            {entry.validation.status === 'MAPPED' ? (
                              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                <Check className="h-3 w-3" /> Mapped
                              </span>
                            ) : entry.validation.status === 'TEMPLATE_HEADER_MISSING' ? (
                              <span
                                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20"
                                title="This configured target header was not found in the uploaded template columns"
                              >
                                <AlertTriangle className="h-3 w-3" /> Template Header Missing
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                                <AlertTriangle className="h-3 w-3" /> Unmapped
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            ) : (
              <div className="p-8 text-center rounded-xl border border-dashed border-border bg-muted/20 space-y-2">
                <FileText className="h-8 w-8 text-muted-foreground mx-auto" />
                <h4 className="text-sm font-bold text-foreground">No Wanted Extraction Fields Selected</h4>
                <p className="text-xs text-muted-foreground max-w-md mx-auto">
                  Click <strong>Configure</strong> on any document card above (such as Aadhaar Card or Transfer Certificate) to select the fields you want to extract.
                </p>
              </div>
            )}

            {/* Template Status / Launch Area */}
            <div className="pt-4 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="text-xs text-muted-foreground space-y-1 text-center sm:text-left">
                <div>
                  Extracting <strong>{extractionStatsSummary.totalWanted} fields</strong> across{' '}
                  <strong>{extractionStatsSummary.configuredDocsCount} document types</strong>.
                </div>
                <div className="font-semibold text-foreground">
                  Applied to:{' '}
                  {selectedClassId === 'all'
                    ? `ALL ${batchStats?.students_count || 0} Students in ${batchStats?.batch_name || 'Batch'}`
                    : `${batchClasses.find((c) => c.id === selectedClassId)?.class_name || 'Selected Section'} (${(batchClasses.length === 1 ? (batchStats?.students_count || batchClasses.find((c) => c.id === selectedClassId)?.stats?.students) : batchClasses.find((c) => c.id === selectedClassId)?.stats?.students) || 0} Students)`}
                </div>
                {uploadedExcelHeaders.length === 0 ? (
                  <div className="text-amber-400 font-medium">
                    ⚠ Upload an Excel template above and configure field mappings before extraction.
                  </div>
                ) : extractionStatsSummary.totalUnmapped > 0 ? (
                  <div className="text-amber-400 font-medium">
                    ⚠ {extractionStatsSummary.totalUnmapped} field(s) are unmapped or missing from the uploaded Excel template. Resolve all mappings before extraction.
                  </div>
                ) : (
                  <div className="text-emerald-400 font-medium">
                    ✓ All {extractionStatsSummary.totalMapped} fields mapped to uploaded Excel headers. Ready for extraction.
                  </div>
                )}
              </div>

              <button
                disabled={
                  isExtracting ||
                  uploadedExcelHeaders.length === 0 ||
                  extractionStatsSummary.totalWanted === 0 ||
                  extractionStatsSummary.totalUnmapped > 0
                }
                onClick={handleStartExtraction}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2.5 px-6 py-3.5 rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-black shadow-md hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed transition-all cursor-pointer"
              >
                {isExtracting ? (
                  <>
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    <span>
                      Extracting for{' '}
                      {selectedClassId === 'all'
                        ? `ALL ${batchStats?.students_count || 0} Students`
                        : `${batchClasses.find((c) => c.id === selectedClassId)?.class_name || 'Section'} (${(batchClasses.length === 1 ? (batchStats?.students_count || batchClasses.find((c) => c.id === selectedClassId)?.stats?.students) : batchClasses.find((c) => c.id === selectedClassId)?.stats?.students) || 0} Students)`}...
                    </span>
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4" />
                    <span>
                      Extract from Stored Documents ({selectedClassId === 'all'
                        ? `ALL ${batchStats?.students_count || 0} Students`
                        : `${batchClasses.find((c) => c.id === selectedClassId)?.class_name || 'Section'} (${(batchClasses.length === 1 ? (batchStats?.students_count || batchClasses.find((c) => c.id === selectedClassId)?.stats?.students) : batchClasses.find((c) => c.id === selectedClassId)?.stats?.students) || 0} Students)`})
                    </span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* CONFIGURE DOCUMENT MODAL                                                  */}
      {/* ========================================================================= */}
      {isConfigModalOpen && activeConfigDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="relative w-full max-w-3xl rounded-2xl bg-card border border-border shadow-2xl p-6 space-y-5 max-h-[92vh] flex flex-col">
            {/* Modal Header */}
            <div className="flex items-start justify-between border-b border-border pb-4 shrink-0">
              <div className="space-y-1">
                <div className="flex items-center gap-2.5 flex-wrap">
                  <h3 className="text-lg font-black text-foreground uppercase tracking-tight">
                    {activeConfigDoc.display_name}
                  </h3>
                  <code className="text-xs font-mono font-bold bg-muted px-2 py-0.5 rounded text-primary">
                    {activeConfigDoc.document_type}
                  </code>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-primary/10 text-primary">
                    Version v{activeConfigDoc.version || 1}
                  </span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-extrabold uppercase bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                    {activeConfigDoc.requirement_status || 'REQUIRED'}
                  </span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-muted text-muted-foreground border border-border">
                    {selectedClassId !== 'all'
                      ? `Scope: Section Override (${classesByBatch[batchId || '']?.find((c) => c.id === selectedClassId)?.class_name || 'Selected Section'})`
                      : 'Scope: Batch Level (All Sections)'}
                  </span>
                </div>
                <div className="text-xs font-bold text-muted-foreground flex items-center gap-2">
                  <span>
                    Wanted Fields:{' '}
                    <strong className="text-primary font-black">
                      {modalFields.filter((f) => f.enabled).length} of {modalFields.length} selected for extraction
                    </strong>
                  </span>
                </div>
              </div>

              <button
                onClick={() => setIsConfigModalOpen(false)}
                className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Controls Bar: Add Field, Select All, Deselect All */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 shrink-0 bg-muted/40 p-3 rounded-xl border border-border">
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  type="button"
                  onClick={() => setIsAddingField(!isAddingField)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-card hover:bg-muted border border-border text-xs font-bold text-foreground transition-all cursor-pointer shadow-2xs"
                >
                  <Plus className="h-3.5 w-3.5 text-primary" />
                  + Add Field
                </button>

                <button
                  type="button"
                  onClick={handleSelectAllFields}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-card hover:bg-muted border border-border text-xs font-bold text-foreground transition-all cursor-pointer shadow-2xs"
                >
                  <CheckSquare className="h-3.5 w-3.5 text-emerald-600" />
                  Select All
                </button>

                <button
                  type="button"
                  onClick={handleDeselectAllFields}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-card hover:bg-muted border border-border text-xs font-bold text-foreground transition-all cursor-pointer shadow-2xs"
                >
                  <Square className="h-3.5 w-3.5 text-muted-foreground" />
                  Deselect All
                </button>
              </div>

              {/* Search Within Fields */}
              <div className="relative w-full sm:w-56">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="Filter fields..."
                  value={fieldSearchQuery}
                  onChange={(e) => setFieldSearchQuery(e.target.value)}
                  className="w-full pl-8 pr-3 py-1 text-xs bg-background rounded-lg border border-input focus:ring-1 focus:ring-primary text-foreground"
                />
              </div>
            </div>

            {/* Inline Add Field Form */}
            {isAddingField && (
              <div className="p-3 rounded-xl bg-primary/5 border border-primary/20 flex items-center gap-2 shrink-0">
                <input
                  type="text"
                  placeholder="Enter custom field name (e.g. Guardian Name, Blood Group)..."
                  value={newCustomFieldName}
                  onChange={(e) => setNewCustomFieldName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      handleAddCustomField();
                    }
                  }}
                  className="flex-1 px-3 py-1.5 text-xs bg-background rounded-lg border border-input focus:ring-1 focus:ring-primary text-foreground"
                  autoFocus
                />
                <button
                  onClick={handleAddCustomField}
                  disabled={!newCustomFieldName.trim()}
                  className="px-3.5 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-bold disabled:opacity-50 cursor-pointer shadow-2xs"
                >
                  Add
                </button>
                <button
                  onClick={() => {
                    setIsAddingField(false);
                    setNewCustomFieldName('');
                  }}
                  className="px-3 py-1.5 rounded-lg border border-border bg-card text-xs font-bold text-muted-foreground hover:text-foreground cursor-pointer"
                >
                  Cancel
                </button>
              </div>
            )}

            {/* Fields List Grid / Table */}
            <div className="flex-1 overflow-y-auto pr-1 space-y-2">
              <div className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider flex items-center justify-between pb-1">
                <span>AVAILABLE FIELDS FOR {activeConfigDoc.document_type}</span>
                <span>OUTPUT EXCEL HEADER MAPPING</span>
              </div>

              {(() => {
                const filtered = modalFields.filter((item) =>
                  (item.field || '').toLowerCase().includes((fieldSearchQuery || '').toLowerCase())
                );

                if (filtered.length === 0) {
                  return (
                    <div className="p-8 text-center text-xs text-muted-foreground">
                      No fields match "{fieldSearchQuery}". Click "+ Add Field" to create it.
                    </div>
                  );
                }

                return filtered.map((item) => {
                  const isChecked = item.enabled;
                  const valRes = validateMappingAgainstTemplate(item, uploadedExcelHeaders);

                  return (
                    <div
                      key={item.field}
                      className={`p-3 rounded-xl border transition-all flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${
                        isChecked
                          ? 'bg-primary/5 border-primary/40 shadow-2xs'
                          : 'bg-card border-border hover:border-border/80'
                      }`}
                    >
                      {/* Checkbox + Field Name */}
                      <label className="flex items-center gap-3 cursor-pointer select-none min-w-0 flex-1">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => handleToggleField(item.field)}
                          className="h-4 w-4 rounded text-primary focus:ring-primary cursor-pointer shrink-0"
                        />
                        <div className="min-w-0">
                          <span
                            className={`text-xs font-bold block truncate ${
                              isChecked ? 'text-foreground font-black' : 'text-muted-foreground'
                            }`}
                          >
                            {item.field}
                          </span>
                        </div>
                      </label>

                      {/* Output Excel Header Mapping Input */}
                      <div className="flex items-center gap-2 shrink-0 w-full sm:w-80">
                        <div className="relative flex-1">
                          {isChecked ? (
                            uploadedExcelHeaders.length > 0 ? (
                              <select
                                value={uploadedExcelHeaders.includes(item.excel_header || '') ? item.excel_header! : ''}
                                onChange={(e) => handleHeaderChange(item.field, e.target.value)}
                                className={`w-full px-2.5 py-1 text-xs rounded-lg border font-medium focus:ring-1 focus:ring-primary cursor-pointer ${
                                  valRes.status === 'TEMPLATE_HEADER_MISSING'
                                    ? 'bg-amber-950/20 border-amber-500 text-amber-300'
                                    : 'bg-background border-input text-foreground'
                                }`}
                              >
                                <option value="">-- Select Excel Header --</option>
                                {item.excel_header && !uploadedExcelHeaders.includes(item.excel_header) && (
                                  <option value="" disabled className="text-amber-400 font-bold">
                                    ⚠ Missing: &quot;{item.excel_header}&quot;
                                  </option>
                                )}
                                {uploadedExcelHeaders.map((opt) => (
                                  <option key={opt} value={opt}>
                                    {opt}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              <select
                                disabled
                                className="w-full px-2.5 py-1 text-xs rounded-lg border border-amber-800/40 bg-muted/40 text-amber-400 italic cursor-not-allowed"
                              >
                                <option>-- Upload Excel template first --</option>
                              </select>
                            )
                          ) : (
                            <select
                              disabled
                              className="w-full px-2.5 py-1 text-xs rounded-lg border border-transparent bg-muted/40 text-muted-foreground italic cursor-not-allowed"
                            >
                              <option>-- Not Wanted --</option>
                            </select>
                          )}
                        </div>

                        {/* Status Badge */}
                        <div className="w-28 text-right shrink-0">
                          {!isChecked ? (
                            <span className="text-[10px] font-semibold text-muted-foreground">Disabled</span>
                          ) : valRes.status === 'MAPPED' ? (
                            <span className="text-[10px] font-extrabold text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20 inline-flex items-center gap-1">
                              <Check className="h-2.5 w-2.5" /> Mapped
                            </span>
                          ) : valRes.status === 'TEMPLATE_HEADER_MISSING' ? (
                            <span
                              className="text-[10px] font-extrabold text-amber-600 dark:text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full border border-amber-500/20 inline-flex items-center gap-1"
                              title="Header missing from uploaded template"
                            >
                              <AlertTriangle className="h-2.5 w-2.5" /> Missing Header
                            </span>
                          ) : (
                            <span className="text-[10px] font-extrabold text-amber-600 dark:text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full border border-amber-500/20 inline-flex items-center gap-1">
                              <AlertTriangle className="h-2.5 w-2.5" /> Unmapped
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                });
              })()}
            </div>

            {/* Modal Footer */}
            <div className="pt-4 border-t border-border flex items-center justify-between shrink-0">
              <button
                type="button"
                onClick={() => setIsConfigModalOpen(false)}
                className="px-4 py-2 text-xs font-bold rounded-xl border border-border bg-card hover:bg-muted text-foreground cursor-pointer"
              >
                Cancel
              </button>

              <button
                type="button"
                disabled={isSavingConfig}
                onClick={handleSaveDocumentConfig}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground text-xs font-black shadow-md cursor-pointer disabled:opacity-50"
              >
                {isSavingConfig ? (
                  <>
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    <span>Saving...</span>
                  </>
                ) : (
                  <>
                    <Check className="h-4 w-4" />
                    <span>Save {activeConfigDoc.display_name} Configuration</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* ADD DOCUMENT TYPE MODAL                                                   */}
      {/* ========================================================================= */}
      {isAddDocModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="relative w-full max-w-md rounded-2xl bg-card border border-border shadow-2xl p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <h3 className="text-base font-bold text-foreground flex items-center gap-2">
                <Plus className="h-4 w-4 text-primary" /> Add Document Type
              </h3>
              <button
                onClick={() => setIsAddDocModalOpen(false)}
                className="p-1 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleCreateDocumentType} className="space-y-3.5 text-xs">
              <div>
                <label className="font-bold text-foreground block mb-1">Document Display Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Hostel Application Form"
                  value={newDocName}
                  onChange={(e) => {
                    setNewDocName(e.target.value);
                    const autoCode = e.target.value
                      .toUpperCase()
                      .replace(/[^A-Z0-9\s_-]/g, '')
                      .trim()
                      .replace(/[\s-]+/g, '_');
                    setNewDocCode(autoCode);
                  }}
                  className="w-full px-3 py-2 bg-background rounded-lg border border-input focus:ring-1 focus:ring-primary text-foreground text-xs"
                />
              </div>

              <div>
                <label className="font-bold text-foreground block mb-1">Document Type Code *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. HOSTEL_FORM"
                  value={newDocCode}
                  onChange={(e) => setNewDocCode(e.target.value.toUpperCase())}
                  className="w-full px-3 py-2 bg-background rounded-lg border border-input focus:ring-1 focus:ring-primary text-foreground font-mono text-xs"
                />
              </div>

              <div>
                <label className="font-bold text-foreground block mb-1">Requirement Status</label>
                <select
                  value={newDocReqStatus}
                  onChange={(e) => setNewDocReqStatus(e.target.value as 'REQUIRED' | 'OPTIONAL')}
                  className="w-full px-3 py-2 bg-background rounded-lg border border-input focus:ring-1 focus:ring-primary text-foreground text-xs font-bold"
                >
                  <option value="REQUIRED">REQUIRED</option>
                  <option value="OPTIONAL">OPTIONAL</option>
                </select>
              </div>

              <div>
                <label className="font-bold text-foreground block mb-1">Description (Optional)</label>
                <textarea
                  rows={2}
                  placeholder="Brief description of this document..."
                  value={newDocDesc}
                  onChange={(e) => setNewDocDesc(e.target.value)}
                  className="w-full px-3 py-2 bg-background rounded-lg border border-input focus:ring-1 focus:ring-primary text-foreground text-xs"
                />
              </div>

              <div className="pt-3 border-t border-border flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsAddDocModalOpen(false)}
                  className="px-3.5 py-1.5 text-xs font-bold rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isCreatingDocType}
                  className="px-4 py-1.5 text-xs font-bold rounded-lg bg-primary text-primary-foreground shadow-xs disabled:opacity-50"
                >
                  {isCreatingDocType ? 'Creating...' : 'Create Document Type'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: STUDENT EXTRACTION DETAILS & TABLE                                 */}
      {/* ========================================================================= */}
      {activeTab === 'students' && (
        <div className="space-y-5">
          {!selectedExtractionId ? (
            <div className="p-12 text-center rounded-2xl border border-dashed border-border bg-card/40 space-y-3">
              <FileSpreadsheet className="h-10 w-10 text-muted-foreground mx-auto" />
              <h3 className="text-sm font-bold text-foreground">No Extraction Run Selected</h3>
              <p className="text-xs text-muted-foreground max-w-sm mx-auto">
                Configure your document fields in the first tab and click <strong>Extract from Stored Documents</strong> to start.
              </p>
              <button
                onClick={() => setActiveTab('config')}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-xs font-bold cursor-pointer"
              >
                Go to Document Configuration
              </button>
            </div>
          ) : loadingDetail && !extractionDetail ? (
            <div className="p-12 text-center bg-card rounded-2xl border border-border">
              <RefreshCw className="h-6 w-6 text-primary animate-spin mx-auto mb-2" />
              <div className="text-xs font-semibold text-muted-foreground">Loading extraction results...</div>
            </div>
          ) : extractionDetail ? (
            <div className="space-y-5">
              {/* Header Details Card */}
              <div className="p-5 rounded-2xl bg-card border border-border shadow-xs space-y-4">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2.5 flex-wrap">
                      <span className="font-mono text-sm font-extrabold text-foreground bg-muted px-2.5 py-0.5 rounded-md">
                        Extraction Request: {currentSummary?.extraction_request_id}
                      </span>
                      <span
                        className={`px-2.5 py-0.5 rounded text-[11px] font-black uppercase ${
                          currentSummary?.status === 'COMPLETED' || currentSummary?.status === 'VERIFIED'
                            ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20'
                            : currentSummary?.status === 'PARTIAL'
                            ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20'
                            : currentSummary?.status === 'PROCESSING'
                            ? 'bg-blue-500/10 text-blue-600 dark:text-blue-400'
                            : currentSummary?.status === 'CANCELLED'
                            ? 'bg-rose-500/10 text-rose-600 dark:text-rose-400'
                            : 'bg-slate-500/10 text-slate-500'
                        }`}
                      >
                        {currentSummary?.status}
                      </span>
                      {renderExportBadge(currentSummary?.export_status)}
                      <span
                        className={`px-2.5 py-0.5 rounded text-[11px] font-black tracking-wide border inline-flex items-center gap-1.5 ${
                          isAllVerified
                            ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30'
                            : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30'
                        }`}
                      >
                        <Users className="h-3 w-3" />
                        {verifiedStudentsCount} / {totalStudentsCount} students verified
                        {pendingVerificationCount > 0 && (
                          <span className="text-amber-500 font-extrabold">• {pendingVerificationCount} students pending</span>
                        )}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground pt-0.5">
                      Batch: <span className="font-semibold text-foreground">{batchStats?.batch_name}</span> (
                      {batchStats?.academic_year}) • Scope:{' '}
                      <span className="font-semibold text-foreground">
                        ALL {currentSummary?.total_students || batchStats?.students_count} Students
                      </span>{' '}
                      • Created by: <span className="font-semibold text-foreground">{currentSummary?.created_by}</span> on{' '}
                      {currentSummary?.created_at ? new Date(currentSummary.created_at).toLocaleString() : '—'}
                    </p>
                  </div>

                  <div className="flex items-center gap-2.5 flex-wrap">
                    {currentSummary?.status === 'PROCESSING' && (
                      <button
                        disabled={cancellingExtraction}
                        onClick={handleCancelExtraction}
                        className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-rose-500/30 text-rose-600 hover:bg-rose-500/10 text-xs font-bold transition-all cursor-pointer"
                      >
                        <Ban className="h-4 w-4" />
                        <span>Cancel Extraction</span>
                      </button>
                    )}

                    <button
                      disabled={loadingDetail}
                      onClick={() => fetchExtractionDetail(selectedExtractionId)}
                      className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-border bg-card hover:bg-muted text-xs font-bold transition-all cursor-pointer text-foreground"
                      title="Refresh student verification statuses"
                    >
                      <RefreshCw className={`h-3.5 w-3.5 ${loadingDetail ? 'animate-spin' : ''}`} />
                      <span>Refresh</span>
                    </button>

                    <button
                      disabled={downloadingRequestId !== null || !isAllVerified}
                      onClick={() => handleDownload()}
                      className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-white text-xs font-bold shadow-xs hover:shadow-sm transition-all ${
                        isAllVerified
                          ? 'bg-emerald-600 hover:bg-emerald-700 cursor-pointer'
                          : 'bg-slate-500/70 cursor-not-allowed opacity-80'
                      }`}
                      title={
                        isAllVerified
                          ? `Download final Excel with student verified values (${verifiedStudentsCount} / ${totalStudentsCount} verified)`
                          : `Download locked: ${verifiedStudentsCount} / ${totalStudentsCount} students verified (${pendingVerificationCount} students pending)`
                      }
                    >
                      {downloadingRequestId && (!selectedExtractionId || downloadingRequestId === selectedExtractionId) ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          <span>Preparing Download...</span>
                        </>
                      ) : !isAllVerified ? (
                        <>
                          <Ban className="h-4 w-4 text-amber-200" />
                          <span>Download Locked ({verifiedStudentsCount}/{totalStudentsCount} Verified • {pendingVerificationCount} Pending)</span>
                        </>
                      ) : (
                        <>
                          <Download className="h-4 w-4" />
                          <span>Download Final Verified Excel</span>
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {/* Requested Fields Checklist */}
                <div>
                  <div className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">
                    Extracted Fields:
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    {(currentSummary?.requested_fields || []).map((f) => (
                      <span
                        key={f}
                        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20 text-xs font-semibold"
                      >
                        <Check className="h-3.5 w-3.5" />
                        {(f || '').replace(/_/g, ' ').toUpperCase() || '—'}
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              {/* One Common Student Verification Link Section */}
              <div className="p-4 sm:p-5 rounded-2xl bg-gradient-to-r from-primary/10 via-card to-primary/5 border border-primary/25 space-y-3 shadow-xs">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex items-center gap-2.5">
                    <div className="p-2 rounded-xl bg-primary/20 text-primary">
                      <Link2 className="h-5 w-5" />
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-foreground flex items-center gap-2">
                        Common Student Verification Link
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-extrabold bg-primary/20 text-primary">
                          One Common Link For All Students
                        </span>
                      </h3>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        All students in this batch use this single URL to identify themselves, complete OTP verification, and review their extracted data.
                      </p>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={handleCopyCommonLink}
                    className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 text-xs font-bold transition-all shadow-xs cursor-pointer whitespace-nowrap self-start sm:self-center"
                  >
                    {copiedCommonLink ? (
                      <>
                        <Check className="h-4 w-4 text-emerald-300" />
                        <span>Link Copied!</span>
                      </>
                    ) : (
                      <>
                        <Copy className="h-4 w-4" />
                        <span>Copy Common Link</span>
                      </>
                    )}
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  <div className="flex-1 font-mono text-xs bg-background/80 px-3.5 py-2.5 rounded-xl border border-border text-foreground break-all select-all">
                    {commonVerificationUrl}
                  </div>
                </div>

                <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
                  <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-xl bg-card border border-border">
                    <Users className="h-3.5 w-3.5 text-primary" />
                    <span>Total Students: <strong className="text-foreground">{totalStudentsCount}</strong></span>
                  </span>
                  <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-700 dark:text-emerald-300">
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                    <strong>{verifiedStudentsCount} / {totalStudentsCount} students verified</strong>
                  </span>
                  <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-xl border ${
                    pendingVerificationCount === 0
                      ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-600 dark:text-emerald-400'
                      : 'bg-amber-500/10 border-amber-500/20 text-amber-600 dark:text-amber-400'
                  }`}>
                    <Clock className="h-3.5 w-3.5 text-amber-500" />
                    <strong>{pendingVerificationCount} students pending</strong>
                  </span>
                </div>
              </div>

              {/* Real-time Progress Bar when running */}
              {currentSummary?.status === 'PROCESSING' && (
                <div className="p-4 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-950 dark:text-blue-200 space-y-2">
                  <div className="flex items-center justify-between text-xs font-bold">
                    <span className="flex items-center gap-2">
                      <RefreshCw className="h-4 w-4 animate-spin text-blue-600 dark:text-blue-400" />
                      Processing Extraction from Stored Documents...
                    </span>
                    <span>
                      {currentSummary.processed_count} / {currentSummary.total_students} students (
                      {currentSummary.total_students > 0
                        ? Math.round((currentSummary.processed_count / currentSummary.total_students) * 100)
                        : 0}
                      %)
                    </span>
                  </div>
                  <div className="w-full bg-blue-200 dark:bg-blue-950 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-blue-600 h-2 transition-all duration-300 rounded-full"
                      style={{
                        width: `${
                          currentSummary.total_students > 0
                            ? (currentSummary.processed_count / currentSummary.total_students) * 100
                            : 0
                        }%`,
                      }}
                    />
                  </div>
                </div>
              )}

              {/* 9 SUMMARY METRIC CARDS */}
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-9 gap-2.5">
                <div className="p-3 rounded-xl bg-card border border-border shadow-2xs space-y-0.5">
                  <div className="text-[10px] font-bold text-muted-foreground uppercase">Total Students</div>
                  <div className="text-xl font-black text-foreground">
                    {currentSummary?.total_students || extractionDetail.students.length}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-card border border-border shadow-2xs space-y-0.5">
                  <div className="text-[10px] font-bold text-blue-600 dark:text-blue-400 uppercase">Processed</div>
                  <div className="text-xl font-black text-blue-600 dark:text-blue-400">
                    {currentSummary?.processed_count ?? extractionDetail.students.length}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-card border border-border shadow-2xs space-y-0.5">
                  <div className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400 uppercase">Successful</div>
                  <div className="text-xl font-black text-emerald-600 dark:text-emerald-400">
                    {currentSummary?.successful_count ?? 0}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-card border border-border shadow-2xs space-y-0.5">
                  <div className="text-[10px] font-bold text-indigo-600 dark:text-indigo-400 uppercase">Partial</div>
                  <div className="text-xl font-black text-indigo-600 dark:text-indigo-400">
                    {currentSummary?.partial_count ?? 0}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-card border border-border shadow-2xs space-y-0.5">
                  <div className="text-[10px] font-bold text-amber-600 dark:text-amber-400 uppercase">Missing Docs</div>
                  <div className="text-xl font-black text-amber-600 dark:text-amber-400">
                    {currentSummary?.missing_docs_count ?? 0}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-card border border-border shadow-2xs space-y-0.5">
                  <div className="text-[10px] font-bold text-rose-600 dark:text-rose-400 uppercase">Failed</div>
                  <div className="text-xl font-black text-rose-600 dark:text-rose-400">
                    {currentSummary?.failed_count ?? 0}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-card border border-border shadow-2xs space-y-0.5">
                  <div className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400 uppercase">Verified</div>
                  <div className="text-xl font-black text-emerald-600 dark:text-emerald-400">
                    {currentSummary?.verified_count ?? 0}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-card border border-border shadow-2xs space-y-0.5">
                  <div className="text-[10px] font-bold text-amber-600 dark:text-amber-400 uppercase">Corrections</div>
                  <div className="text-xl font-black text-amber-600 dark:text-amber-400">
                    {currentSummary?.correction_requested_count ?? 0}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-card border border-border shadow-2xs space-y-0.5">
                  <div className="text-[10px] font-bold text-muted-foreground uppercase">Pending Verif.</div>
                  <div className="text-xl font-black text-foreground">
                    {currentSummary?.pending_verification_count ?? 0}
                  </div>
                </div>
              </div>

              {/* Filter and Search Bar for Students */}
              <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
                <div className="relative w-full sm:w-80">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <input
                    type="text"
                    placeholder="Search candidate name or register no..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="w-full pl-9 pr-3 py-1.5 text-xs bg-card rounded-lg border border-input focus:ring-1 focus:ring-primary text-foreground"
                  />
                  {searchTerm && (
                    <button
                      onClick={() => setSearchTerm('')}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </div>

                <div className="flex items-center gap-1.5 self-start sm:self-center overflow-x-auto w-full sm:w-auto">
                  {FILTER_OPTIONS.map((opt) => (
                    <button
                      key={opt.id}
                      onClick={() => {
                        setStatusFilter(opt.id);
                        setPage(1);
                      }}
                      className={`px-3 py-1 rounded-lg text-xs font-bold transition-colors cursor-pointer whitespace-nowrap ${
                        statusFilter === opt.id
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-card text-muted-foreground hover:text-foreground border border-border'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Students Extraction Table */}
              <div className="rounded-2xl border border-border bg-card overflow-hidden shadow-xs">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="bg-muted/60 border-b border-border text-muted-foreground">
                        <th className="py-2.5 px-3.5 font-bold uppercase tracking-wider">Student Candidate</th>
                        <th className="py-2.5 px-3.5 font-bold uppercase tracking-wider">Document Status</th>
                        <th className="py-2.5 px-3.5 font-bold uppercase tracking-wider">Extracted Fields Preview</th>
                        <th className="py-2.5 px-3.5 font-bold uppercase tracking-wider">Verification Status</th>
                        <th className="py-2.5 px-3.5 font-bold uppercase tracking-wider text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {extractionDetail.students.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="p-8 text-center text-muted-foreground">
                            No student records match the selected filter.
                          </td>
                        </tr>
                      ) : (
                        extractionDetail.students.map((student) => {
                          const isRetrying = retryingStudentId === student.student_id;
                          return (
                            <tr key={student.student_id} className="hover:bg-muted/20 transition-colors">
                              {/* Candidate Name & Reg No */}
                              <td className="py-3 px-3.5">
                                <div className="font-bold text-foreground">
                                  {student.student_name || student.student_id}
                                </div>
                                <div className="font-mono text-[11px] text-muted-foreground">
                                  {student.register_number || student.student_id}
                                </div>
                              </td>

                              {/* Document Status */}
                              <td className="py-3 px-3.5">
                                <span
                                  className={`px-2 py-0.5 rounded text-[10px] font-extrabold uppercase ${
                                    student.missing_documents?.length === 0
                                      ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                                      : 'bg-amber-500/10 text-amber-600 dark:text-amber-400'
                                  }`}
                                >
                                  {student.missing_documents?.length === 0 ? 'Ready' : 'Missing Documents'}
                                </span>
                                {student.missing_documents && student.missing_documents.length > 0 && (
                                  <div className="text-[10px] text-rose-600 dark:text-rose-400 mt-1 font-medium">
                                    <span className="font-bold">MISSING:</span>{' '}
                                    {student.missing_documents.map(d => (d ? d.replace(/_/g, ' ') : '')).filter(Boolean).join(', ')}
                                  </div>
                                )}
                              </td>

                              {/* Extracted Fields Preview */}
                              <td className="py-3 px-3.5">
                                <div className="flex flex-wrap gap-1.5 max-w-md">
                                  {Object.entries(student.fields || {})
                                    .slice(0, 5)
                                    .map(([key, field]) => {
                                      const isMissing = field.ai_value === 'NOT_AVAILABLE' || field.field_state === 'SOURCE_DOCUMENT_MISSING';
                                      return (
                                        <span
                                          key={key}
                                          className={`px-2 py-0.5 rounded text-[10px] font-medium truncate max-w-[160px] ${
                                            isMissing
                                              ? 'bg-muted/50 text-muted-foreground border border-dashed border-border'
                                              : 'bg-muted text-foreground'
                                          }`}
                                          title={`${field.column_label}: ${field.final_value ?? field.ai_value ?? 'NOT_AVAILABLE'}${
                                            field.reason ? ` (${field.reason})` : ''
                                          }`}
                                        >
                                          <span className="text-muted-foreground">{field.column_label}:</span>{' '}
                                          <b className={isMissing ? 'text-amber-600 dark:text-amber-400' : ''}>
                                            {String(field.final_value ?? field.ai_value ?? 'NOT_AVAILABLE')}
                                          </b>
                                        </span>
                                      );
                                    })}
                                  {Object.keys(student.fields || {}).length > 5 && (
                                    <span className="text-[10px] text-muted-foreground self-center">
                                      +{Object.keys(student.fields || {}).length - 5} more
                                    </span>
                                  )}
                                </div>
                              </td>

                              {/* Verification Status */}
                              <td className="py-3 px-3.5">
                                {(() => {
                                  const isStudentVerified = student.verification_status === 'STUDENT_VERIFIED';
                                  const isVerified = student.verification_status === 'VERIFIED' || isStudentVerified;
                                  const isCorrection = student.verification_status === 'CORRECTION_REQUESTED';
                                  const isExpired = student.verification_token_status === 'EXPIRED';
                                  const hasLink = Boolean(student.verification_link);
                                  const isLinkReady = hasLink && !isExpired && !isVerified && !isCorrection;

                                  let badgeLabel = 'Pending';
                                  let badgeClass = 'bg-muted text-muted-foreground border-border';

                                  if (isStudentVerified) {
                                    badgeLabel = 'Student Verified';
                                    badgeClass = 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20';
                                  } else if (isVerified) {
                                    badgeLabel = 'Verified';
                                    badgeClass = 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20';
                                  } else if (isCorrection) {
                                    badgeLabel = 'Correction Requested';
                                    badgeClass = 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20';
                                  } else if (isExpired) {
                                    badgeLabel = 'Expired';
                                    badgeClass = 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20';
                                  } else if (isLinkReady) {
                                    badgeLabel = 'Link Ready';
                                    badgeClass = 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20';
                                  }

                                  return (
                                    <div className="space-y-1">
                                      <span
                                        className={`px-2 py-0.5 rounded-full text-[10px] font-extrabold uppercase inline-block border ${badgeClass}`}
                                      >
                                        {badgeLabel}
                                      </span>
                                      <div className="text-[9px] font-semibold text-muted-foreground">
                                        Extraction:{' '}
                                        <span
                                          className={
                                            student.extraction_status === 'COMPLETED'
                                              ? 'text-emerald-600 dark:text-emerald-400 font-bold'
                                              : student.extraction_status === 'PARTIAL'
                                              ? 'text-amber-600 dark:text-amber-400 font-bold'
                                              : 'text-rose-600 dark:text-rose-400 font-bold'
                                          }
                                        >
                                          {student.extraction_status || 'PENDING'}
                                        </span>
                                      </div>
                                    </div>
                                  );
                                })()}
                              </td>

                              {/* Actions */}
                              <td className="py-3 px-3.5 text-right">
                                {student.extraction_status === 'FAILED' ? (
                                  <button
                                    disabled={isRetrying}
                                    onClick={() => handleRetryStudent(student.student_id)}
                                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-rose-500/30 bg-rose-500/10 hover:bg-rose-500/20 text-[11px] font-bold text-rose-600 dark:text-rose-400 cursor-pointer shadow-2xs"
                                    title="Retry extraction for this student"
                                  >
                                    <RotateCcw className={`h-3 w-3 ${isRetrying ? 'animate-spin' : ''}`} />
                                    Retry
                                  </button>
                                ) : (
                                  <div className="inline-flex items-center gap-1.5 justify-end">
                                    <button
                                      onClick={() => setInspectStudent(student)}
                                      className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-border bg-card hover:bg-muted text-[11px] font-bold text-foreground cursor-pointer shadow-2xs"
                                      title="Inspect field evidence and source document provenance"
                                    >
                                      <Eye className="h-3 w-3 text-primary" />
                                      Inspect
                                    </button>

                                    <button
                                      disabled={isRetrying}
                                      onClick={() => handleRetryStudent(student.student_id)}
                                      className="inline-flex items-center gap-1 p-1 rounded border border-border hover:bg-muted text-muted-foreground hover:text-foreground cursor-pointer"
                                      title="Re-run extraction"
                                    >
                                      <RotateCcw className={`h-3 w-3 ${isRetrying ? 'animate-spin' : ''}`} />
                                    </button>
                                  </div>
                                )}
                              </td>

                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="p-3 border-t border-border flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">
                      Page {page} of {totalPages} ({extractionDetail.total_matching_students} students)
                    </span>
                    <div className="flex items-center gap-1.5">
                      <button
                        disabled={page <= 1}
                        onClick={() => setPage(page - 1)}
                        className="px-2.5 py-1 rounded border border-border bg-card disabled:opacity-50 cursor-pointer font-bold"
                      >
                        Prev
                      </button>
                      <button
                        disabled={page >= totalPages}
                        onClick={() => setPage(page + 1)}
                        className="px-2.5 py-1 rounded border border-border bg-card disabled:opacity-50 cursor-pointer font-bold"
                      >
                        Next
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>
      )}


      {/* ========================================================================= */}
      {/* MODAL: ADD CUSTOM DOCUMENT TYPE                                           */}
      {/* ========================================================================= */}
      {isAddDocModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="relative w-full max-w-md rounded-2xl bg-card border border-border shadow-2xl p-6 space-y-5">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <h3 className="text-base font-bold text-foreground flex items-center gap-2">
                <Plus className="h-4 w-4 text-primary" />
                Add New Document Type
              </h3>
              <button
                onClick={() => setIsAddDocModalOpen(false)}
                className="p-1 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleCreateDocumentType} className="space-y-4 text-xs">
              <div>
                <label className="text-[11px] font-bold text-foreground">Document Display Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Income Certificate, Nativity Certificate"
                  value={newDocName}
                  onChange={(e) => {
                    setNewDocName(e.target.value);
                    if (!newDocCode) {
                      setNewDocCode(e.target.value.toUpperCase().replace(/[\s-]+/g, '_'));
                    }
                  }}
                  className="w-full mt-1 px-3.5 py-2 text-xs bg-background border border-input rounded-xl text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>

              <div>
                <label className="text-[11px] font-bold text-foreground">Document Type Code (UPPERCASE) *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. INCOME, NATIVITY, BONAFIDE"
                  value={newDocCode}
                  onChange={(e) => setNewDocCode(e.target.value.toUpperCase().replace(/[\s-]+/g, '_'))}
                  className="w-full mt-1 px-3.5 py-2 text-xs font-mono bg-background border border-input rounded-xl text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>

              <div>
                <label className="text-[11px] font-bold text-foreground">Requirement Status</label>
                <select
                  value={newDocReqStatus}
                  onChange={(e) => setNewDocReqStatus(e.target.value as 'REQUIRED' | 'OPTIONAL')}
                  className="w-full mt-1 px-3.5 py-2 text-xs bg-background border border-input rounded-xl text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  <option value="REQUIRED">REQUIRED (Mandatory for Admission)</option>
                  <option value="OPTIONAL">OPTIONAL (Optional Document)</option>
                </select>
              </div>

              <div>
                <label className="text-[11px] font-bold text-foreground">Description (Optional)</label>
                <textarea
                  rows={2}
                  placeholder="Brief description of the document purpose..."
                  value={newDocDesc}
                  onChange={(e) => setNewDocDesc(e.target.value)}
                  className="w-full mt-1 px-3.5 py-2 text-xs bg-background border border-input rounded-xl text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>

              <div className="pt-3 border-t border-border flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsAddDocModalOpen(false)}
                  className="px-4 py-2 rounded-xl border border-border bg-card text-foreground font-semibold hover:bg-muted"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isCreatingDocType}
                  className="px-5 py-2 rounded-xl bg-primary text-primary-foreground font-bold shadow-xs hover:bg-primary/90 disabled:opacity-50 inline-flex items-center gap-2"
                >
                  {isCreatingDocType ? (
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Plus className="h-3.5 w-3.5" />
                  )}
                  <span>Create Document Type</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {/* MODAL: INSPECT STUDENT EXTRACTION FIELDS & EVIDENCE */}
      {inspectStudent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="relative w-full max-w-2xl max-h-[85vh] flex flex-col rounded-2xl bg-card border border-border shadow-2xl p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div>
                <h3 className="text-base font-bold text-foreground flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-primary" />
                  Field Extraction Evidence & Provenance
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Candidate: <strong className="text-foreground">{inspectStudent.student_name || inspectStudent.student_id}</strong> (Reg: {inspectStudent.register_number})
                </p>
              </div>
              <button
                onClick={() => setInspectStudent(null)}
                className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto space-y-3 pr-1">
              {Object.entries(inspectStudent.fields || {}).map(([key, field]) => {
                const state = (field.field_state || '').toUpperCase();
                const isInvalidDoc = state === 'DOCUMENT_INVALID';
                const isMissingDoc = state === 'DOCUMENT_MISSING' || state === 'SOURCE_DOCUMENT_MISSING';
                const isLowQualityOcr = state === 'OCR_LOW_QUALITY';
                const isAiFailed = ['AI_EXTRACTION_FAILED', 'EXTRACTION_FAILED', 'AI_EXTRACTION_UNAVAILABLE', 'AI_RATE_LIMITED', 'OCR_FAILED', 'OCR_RATE_LIMITED', 'OCR_UNAVAILABLE'].includes(state);
                const hasConflict = state === 'CONFLICTING_VALUES' || (field.conflicts && field.conflicts.length > 1);
                const rawVal = field.final_value ?? field.ai_value;
                const hasExtractedVal = rawVal !== undefined && rawVal !== null && rawVal !== 'NOT_AVAILABLE' && rawVal !== 'NOT_FOUND' && rawVal !== '';
                const isExtracted = !isInvalidDoc && !isMissingDoc && !isLowQualityOcr && !isAiFailed && !hasConflict && hasExtractedVal && (state === 'EXTRACTED' || state === 'HIGH_CONFIDENCE');
                const isNotFound = !isExtracted && !isInvalidDoc && !isMissingDoc && !isLowQualityOcr && !isAiFailed && !hasConflict;

                let badgeLabel = 'NOT_FOUND';
                let badgeClass = 'bg-slate-500/10 text-slate-500 border border-slate-500/20';
                if (hasConflict) {
                  badgeLabel = 'Needs Review';
                  badgeClass = 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20';
                } else if (isInvalidDoc) {
                  badgeLabel = 'DOCUMENT_INVALID';
                  badgeClass = 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20';
                } else if (isMissingDoc) {
                  badgeLabel = 'DOCUMENT_MISSING';
                  badgeClass = 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20';
                } else if (isLowQualityOcr) {
                  badgeLabel = 'OCR_LOW_QUALITY';
                  badgeClass = 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20';
                } else if (isAiFailed) {
                  badgeLabel = 'AI_EXTRACTION_FAILED';
                  badgeClass = 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20';
                } else if (isExtracted) {
                  badgeLabel = 'EXTRACTED';
                  badgeClass = 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20';
                } else {
                  badgeLabel = 'NOT_FOUND';
                  badgeClass = 'bg-slate-500/10 text-slate-500 border border-slate-500/20';
                }

                const canShowValue = isExtracted || hasConflict;
                const canShowSource = !isInvalidDoc && !isMissingDoc && Boolean(field.source_document_name || (field.source_document_type && field.source_document_type !== 'OTHER'));

                return (
                  <div
                    key={key}
                    className={`p-3.5 rounded-xl border transition-all ${
                      hasConflict
                        ? 'border-amber-500/40 bg-amber-500/5'
                        : isInvalidDoc || isAiFailed
                        ? 'border-rose-500/40 bg-rose-500/5'
                        : isMissingDoc || isLowQualityOcr
                        ? 'border-amber-500/40 bg-amber-500/5'
                        : isNotFound
                        ? 'border-border/60 bg-muted/20'
                        : 'border-border bg-card'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-xs font-bold text-foreground flex items-center gap-2">
                          <span>{field.column_label}</span>
                          <span className="font-mono text-[10px] text-muted-foreground font-normal">({field.field_name})</span>
                        </div>
                        <div className="mt-1 flex items-center gap-2">
                          <span className="text-[11px] font-semibold text-muted-foreground">Value:</span>
                          {canShowValue ? (
                            <span className="font-mono text-xs font-bold text-foreground bg-muted/60 px-2 py-0.5 rounded">
                              {String(field.final_value ?? field.ai_value)}
                            </span>
                          ) : (
                            <span className="text-xs font-semibold text-muted-foreground italic">—</span>
                          )}
                        </div>
                      </div>

                      <div className="flex flex-col items-end gap-1 shrink-0">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${badgeClass}`}>
                          {badgeLabel}
                        </span>
                        <span className="text-[10px] text-muted-foreground">
                          Confidence: <strong className="text-foreground">{isExtracted ? `${field.confidence_score ? Math.round(field.confidence_score * 100) : 96}%` : '—'}</strong>
                        </span>
                        <span className="text-[10px] text-muted-foreground">
                          Source: <strong className="text-foreground">
                            {canShowSource
                              ? `${field.source_document_name || field.source_document_type}${field.source_document_version ? ` (v${field.source_document_version})` : ''}`
                              : '—'}
                          </strong>
                        </span>
                      </div>
                    </div>

                    {field.evidence_snippet && (
                      <div className="mt-2.5 pt-2 border-t border-border/40 text-[11px]">
                        <span className="text-muted-foreground font-semibold">Evidence:</span>{' '}
                        <span className="font-mono text-foreground italic">{field.evidence_snippet}</span>
                      </div>
                    )}

                    {hasConflict && field.conflicts && field.conflicts.length > 0 && (
                      <div className="mt-2.5 pt-2 border-t border-amber-500/30 text-[11px] space-y-1">
                        <div className="font-bold text-amber-700 dark:text-amber-300">Conflicting Document Sources:</div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                          {field.conflicts.map((c, idx) => (
                            <div key={idx} className="p-1.5 rounded bg-amber-500/10 text-[10px] font-mono">
                              <strong>{c.document_name || c.document_type}:</strong> {String(c.value)}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="pt-3 border-t border-border flex justify-end">
              <button
                onClick={() => setInspectStudent(null)}
                className="px-4 py-2 rounded-xl bg-primary text-primary-foreground text-xs font-bold shadow-xs hover:bg-primary/90 cursor-pointer"
              >
                Close Inspector
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
