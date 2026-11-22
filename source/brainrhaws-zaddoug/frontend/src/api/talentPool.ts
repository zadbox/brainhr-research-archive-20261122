import { apiClient } from './client';

export interface CatalogCandidate {
  filename: string;
  source_filename: string | null;
  name: string | null;
  title: string | null;
  enterprise_id: string;
  enterprise_name: string;
  project_id: string;
  project_name: string;
  updated_at: string | null;
}

export interface CatalogPage {
  items: CatalogCandidate[];
  total: number;
}

export interface CatalogScope {
  tenant_id: string;
  tenant_name: string;
  enterprise_id: string;
  enterprise_name: string;
}

export const talentPoolApi = {
  scopes: async (): Promise<CatalogScope[]> => {
    const response = await apiClient.get<CatalogScope[]>('/talent-pool/scopes');
    return response.data;
  },
  list: async (params: {
    tenant_id: string;
    enterprise_id?: string;
    search?: string;
    offset?: number;
    limit?: number;
  }): Promise<CatalogPage> => {
    const response = await apiClient.get<CatalogPage>('/talent-pool', { params });
    return response.data;
  },
};
