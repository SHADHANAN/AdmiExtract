export type NotificationChannel = 'EMAIL' | 'SMS' | 'WHATSAPP';

export type NotificationStatus =
  | 'PENDING'
  | 'QUEUED'
  | 'SENT'
  | 'DELIVERED'
  | 'FAILED'
  | 'CANCELLED';

export interface ChannelProviderStatus {
  channel: NotificationChannel;
  is_enabled: boolean;
  provider_name: string;
  is_mock: boolean;
  display_status: string;
  missing_configs?: string[];
}

export interface ProviderStatusResponse {
  providers: Record<string, ChannelProviderStatus>;
  test_mode: boolean;
}

export interface NotificationResponse {
  id: string;
  extraction_request_id: string;
  student_id: string;
  student_name?: string;
  register_number?: string;
  channel: NotificationChannel;
  recipient: string;
  template_identifier: string;
  status: NotificationStatus;
  provider_name: string;
  provider_message_id?: string;
  failure_reason?: string;
  retry_count: number;
  created_at: string;
  sent_at?: string;
  delivered_at?: string;
  failed_at?: string;
  token_str_masked?: string;
  verification_url?: string;
}

export interface StudentNotificationStatusRow {
  student_id: string;
  student_name?: string;
  register_number?: string;
  email?: string;
  mobile_number?: string;
  has_valid_email?: boolean;
  has_valid_mobile?: boolean;
  verification_status?: string;
  has_token?: boolean;
  has_verification_token?: boolean;
  token_is_active?: boolean;
  token_expires_at?: string;
  notification_status?: string;
  latest_notification_status?: string;
  latest_notification_channel?: string;
  last_channel?: NotificationChannel;
  last_sent_at?: string;
  last_notification_id?: string;
  last_failure_reason?: string;
  retry_count?: number;
  notification_count?: number;
  is_eligible_for_notification?: boolean;
}

export interface BulkNotificationSummaryResponse {
  extraction_request_id: string;
  channel: NotificationChannel;
  total_eligible_students: number;
  queued_count: number;
  sent_count: number;
  failed_count: number;
  skipped_count: number;
  notifications: NotificationResponse[];
  message: string;
}

export interface SendNotificationRequest {
  student_id: string;
  channel: NotificationChannel;
  force_resend?: boolean;
  custom_message?: string;
}

export interface SendBulkNotificationRequest {
  channel: NotificationChannel;
  student_ids?: string[];
  force_resend?: boolean;
  filter_status?: string;
}
