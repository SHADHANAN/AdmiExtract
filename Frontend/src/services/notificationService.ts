import { api } from './api';
import type {
  ProviderStatusResponse,
  NotificationResponse,
  StudentNotificationStatusRow,
  BulkNotificationSummaryResponse,
  SendNotificationRequest,
  SendBulkNotificationRequest,
} from '../types/notification';

export const notificationService = {
  /**
   * Retrieve active configuration status for all communication channels
   */
  getProviderStatus: async (): Promise<ProviderStatusResponse> => {
    const response = await api.get<ProviderStatusResponse>('/data-extractions/notifications/providers/status');
    return response.data;
  },

  /**
   * List delivery history logs for an extraction request
   */
  getExtractionNotifications: async (extractionRequestId: string): Promise<NotificationResponse[]> => {
    const response = await api.get<NotificationResponse[]>(`/data-extractions/${extractionRequestId}/notifications`);
    return response.data;
  },

  /**
   * Retrieve student notification candidate status table
   */
  getStudentNotificationTable: async (extractionRequestId: string): Promise<StudentNotificationStatusRow[]> => {
    const response = await api.get<StudentNotificationStatusRow[]>(
      `/data-extractions/${extractionRequestId}/notifications/students`
    );
    return response.data;
  },

  /**
   * Dispatch notification to a single student
   */
  sendSingleNotification: async (
    extractionRequestId: string,
    payload: SendNotificationRequest,
    forceMock = false
  ): Promise<NotificationResponse> => {
    const response = await api.post<NotificationResponse>(
      `/data-extractions/${extractionRequestId}/notifications/send`,
      payload,
      { params: { force_mock: forceMock } }
    );
    return response.data;
  },

  /**
   * Dispatch verification notifications in bulk
   */
  sendBulkNotifications: async (
    extractionRequestId: string,
    payload: SendBulkNotificationRequest,
    forceMock = false
  ): Promise<BulkNotificationSummaryResponse> => {
    const response = await api.post<BulkNotificationSummaryResponse>(
      `/data-extractions/${extractionRequestId}/notifications/send-bulk`,
      payload,
      { params: { force_mock: forceMock } }
    );
    return response.data;
  },

  /**
   * Retry a specific failed or pending notification delivery
   */
  retryNotification: async (
    notificationId: string,
    forceMock = false
  ): Promise<NotificationResponse> => {
    const response = await api.post<NotificationResponse>(
      `/data-extractions/notifications/${notificationId}/retry`,
      {},
      { params: { force_mock: forceMock } }
    );
    return response.data;
  },
};
