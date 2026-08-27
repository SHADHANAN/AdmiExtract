export type UserRole = 'super_admin' | 'department_admin' | 'student';

export interface User {
  id: string;
  name: string;
  username?: string;
  email?: string;
  role: UserRole;
  department_code?: string;
  is_active?: boolean;
}

export interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  login: (token: string, user: User) => void;
  logout: () => void;
}

export interface Department {
  id: string;
  name: string;
  code: string;
  description?: string;
  created_by: string;
  created_at: string;
  is_active: boolean;
}

export type BatchStatus = 'active' | 'closed' | 'archived';

export interface BatchStats {
  students: number;
  pending: number;
  verified: number;
  rejected: number;
}

export type RequirementType = 'MANDATORY' | 'OPTIONAL' | 'DISABLED';

export interface DocumentRequirement {
  id: string;
  name: string;
  required: boolean;
  allowedTypes: string[]; // e.g. ['PDF', 'JPG', 'PNG']
  maxSizeMb: number; // e.g. 5, 10
  description?: string;
  type?: RequirementType; // For backward compatibility
  extractionFields?: string[];
}

export type StudentDocStatus = 'Uploaded' | 'Not Available' | 'Pending';
export type StudentVerificationStatus = 
  | 'Submitted' 
  | 'AI Processing' 
  | 'Verification Pending' 
  | 'Verified' 
  | 'Rejected'
  | 'Pending';
export type AiProcessingStatus = 'Complete' | 'Processing' | 'Requires Review';

export interface StudentDocumentSubmission {
  reqId?: string;
  reqName: string;
  fileName?: string;
  fileSizeMb?: number;
  fileType?: string;
  status: StudentDocStatus;
  uploadedAt?: string;
  fileUrl?: string;
}

export interface DocumentConfigurationVersion {
  id: string;
  batchId: string;
  version: number;
  documents: DocumentRequirement[];
  isCurrent: boolean;
  changeSummary?: string;
  createdBy: string;
  createdAt: string;
}

export interface BatchClass {
  id: string;
  batch_id: string;
  class_name: string;
  department: string;
  section: string;
  academic_year: string;
  created_at: string;
  updated_at: string;
}

export interface StudentSubmission {
  id: string;
  batchId: string;
  batchName?: string;
  classId?: string;
  className?: string;
  registerNum: string;
  name: string;
  mobile: string;
  email?: string;
  status: StudentVerificationStatus;
  aiStatus: AiProcessingStatus;
  documentVersion?: number;
  documentVersionId?: string;
  documentSnapshot?: DocumentRequirement[];
  submittedAt: string;
  documents: StudentDocumentSubmission[];
}

export interface Batch {
  id: string;
  name: string;
  department: string;
  academicYear: string;
  description?: string;
  startDate?: string;
  endDate?: string;
  status: BatchStatus;
  stats: BatchStats;
  classes?: BatchClass[];
  currentDocVersion?: number;
  docRequirements?: DocumentRequirement[];
}

export interface UploadLink {
  id: string;
  batchId: string;
  token: string;
  slug?: string;
  class_id?: string | null;
  title?: string;
  expiresAt: string;
  isActive: boolean;
  submissionCount: number;
}

export interface BatchState {
  batches: Batch[];
  uploadLinks: UploadLink[];
  docVersions: Record<string, DocumentConfigurationVersion[]>;
  classesByBatch: Record<string, BatchClass[]>;
  fetchBatches: () => Promise<void>;
  fetchUploadLinks: () => Promise<void>;
  fetchClassesForBatch: (batchId: string) => Promise<BatchClass[]>;
  createClass: (batchId: string, data: { class_name: string; department: string; section: string; academic_year: string }) => Promise<BatchClass>;
  updateClass: (classId: string, data: Partial<{ class_name: string; department: string; section: string; academic_year: string }>) => Promise<BatchClass>;
  deleteClass: (classId: string) => Promise<void>;
  addBatch: (batch: Omit<Batch, 'id' | 'stats'>) => void;
  updateBatch: (batchId: string, data: Partial<Omit<Batch, 'id' | 'stats'>>) => Promise<void>;
  deleteBatch: (batchId: string) => Promise<void>;
  updateBatchRequirements: (
    batchId: string,
    requirements: DocumentRequirement[],
    changeSummary?: string,
    createdBy?: string
  ) => void;
  getBatchDocVersions: (batchId: string) => DocumentConfigurationVersion[];
  addUploadLink: (link: Partial<UploadLink> & { batchId: string }) => Promise<UploadLink>;
  toggleUploadLink: (linkId: string) => void;
  updateUploadLinkExpiry: (linkId: string, expiresAt: string | null) => Promise<void>;
  deleteUploadLink: (linkId: string) => void;
}


