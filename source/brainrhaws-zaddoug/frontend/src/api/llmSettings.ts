import { apiClient } from './client';

export interface LLMProviderOption {
  id: string;
  label: string;
  configured: boolean;
  models: string[];
}

export interface LLMProcessSetting {
  process_id: string;
  label: string;
  category: string;
  description: string;
  provider: string;
  model: string;
  source: 'default' | 'database';
  default_provider: string;
  default_model: string;
  locked: boolean;
  lock_reason: string | null;
  providers: LLMProviderOption[];
  updated_at: string | null;
}

interface LLMSettingsResponse {
  processes: LLMProcessSetting[];
}

export const llmSettingsApi = {
  list: async (): Promise<LLMProcessSetting[]> => {
    const response = await apiClient.get<LLMSettingsResponse>('/admin/llm-settings');
    return response.data.processes;
  },

  update: async (
    processId: string,
    provider: string,
    model: string
  ): Promise<LLMProcessSetting[]> => {
    const response = await apiClient.patch<LLMSettingsResponse>(
      `/admin/llm-settings/${processId}`,
      { provider, model }
    );
    return response.data.processes;
  },
};
