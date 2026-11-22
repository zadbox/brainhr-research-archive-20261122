import { API_BASE_URL, apiClient } from './client';
import type { CompanyCvTemplate } from './types';

export const cvTemplatesApi = {
  list: async (enterpriseId: string): Promise<CompanyCvTemplate[]> => {
    const response = await apiClient.get<CompanyCvTemplate[]>(
      `/enterprises/${enterpriseId}/cv-templates`
    );
    return response.data;
  },

  upload: async (enterpriseId: string, file: File): Promise<CompanyCvTemplate> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await apiClient.post<CompanyCvTemplate>(
      `/enterprises/${enterpriseId}/cv-templates`,
      formData,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
      }
    );
    return response.data;
  },

  activate: async (enterpriseId: string, templateId: string): Promise<CompanyCvTemplate> => {
    const response = await apiClient.post<CompanyCvTemplate>(
      `/enterprises/${enterpriseId}/cv-templates/${templateId}/activate`
    );
    return response.data;
  },

  delete: async (enterpriseId: string, templateId: string): Promise<void> => {
    await apiClient.delete(`/enterprises/${enterpriseId}/cv-templates/${templateId}`);
  },

  getMapping: async (enterpriseId: string, templateId: string): Promise<CompanyCvTemplate> => {
    const response = await apiClient.get<CompanyCvTemplate>(
      `/enterprises/${enterpriseId}/cv-templates/${templateId}/mapping`
    );
    return response.data;
  },

  updateMapping: async (
    enterpriseId: string,
    templateId: string,
    confirmedMappings: Record<string, unknown>
  ): Promise<CompanyCvTemplate> => {
    const response = await apiClient.put<CompanyCvTemplate>(
      `/enterprises/${enterpriseId}/cv-templates/${templateId}/mapping`,
      { confirmed_mappings: confirmedMappings }
    );
    return response.data;
  },

  sampleRender: async (
    enterpriseId: string,
    templateId: string,
    sheetId: string
  ): Promise<{ blob: Blob; filename: string | null }> => {
    const response = await fetch(
      `${API_BASE_URL}/api/v1/enterprises/${enterpriseId}/cv-templates/${templateId}/sample-render`,
      {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sheet_id: sheetId }),
      }
    );

    if (!response.ok) {
      const text = await response.text();
      try {
        const payload = JSON.parse(text) as { detail?: string; message?: string };
        throw new Error(payload.message || payload.detail || 'Unable to generate sample render');
      } catch {
        throw new Error(text || 'Unable to generate sample render');
      }
    }

    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || undefined;
    const match = disposition?.match(/filename="?([^";]+)"?/i);
    return {
      blob,
      filename: match?.[1] || null,
    };
  },

  sampleRenderHtmlDocx: async (
    enterpriseId: string,
    templateId: string,
    sheetId: string
  ): Promise<{ blob: Blob; filename: string | null }> => {
    const response = await fetch(
      `${API_BASE_URL}/api/v1/enterprises/${enterpriseId}/cv-templates/${templateId}/sample-render/html-docx`,
      {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sheet_id: sheetId }),
      }
    );

    if (!response.ok) {
      const text = await response.text();
      try {
        const payload = JSON.parse(text) as { detail?: string; message?: string };
        throw new Error(payload.message || payload.detail || 'Unable to generate HTML DOCX sample render');
      } catch {
        throw new Error(text || 'Unable to generate HTML DOCX sample render');
      }
    }

    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || undefined;
    const match = disposition?.match(/filename="?([^";]+)"?/i);
    return {
      blob,
      filename: match?.[1] || null,
    };
  },

  download: async (enterpriseId: string, templateId: string): Promise<{ blob: Blob; filename: string | null }> => {
    const response = await fetch(
      `${API_BASE_URL}/api/v1/enterprises/${enterpriseId}/cv-templates/${templateId}/download`,
      {
        credentials: 'include',
      }
    );

    if (!response.ok) {
      const text = await response.text();
      try {
        const payload = JSON.parse(text) as { detail?: string; message?: string };
        throw new Error(payload.message || payload.detail || 'Unable to download CV template');
      } catch {
        throw new Error(text || 'Unable to download CV template');
      }
    }

    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || undefined;
    const match = disposition?.match(/filename="?([^";]+)"?/i);
    return {
      blob,
      filename: match?.[1] || null,
    };
  },
};
