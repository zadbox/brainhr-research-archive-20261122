import { apiClient } from './client';

export type CreditAmount = string;

export interface CrustdataLocationCriterion {
  label: string;
  radius_km: number;
}

export interface CrustdataSearchCriteria {
  titles: string[];
  required_skills: string[];
  locations: CrustdataLocationCriterion[];
  min_years_experience: number | null;
  seniority_levels: string[];
  max_profile_age_days: number | null;
  result_limit: number;
}

export interface CrustdataCriteriaResponse {
  offer_derived_criteria: CrustdataSearchCriteria;
  current_criteria: CrustdataSearchCriteria;
  stale: boolean;
  generated_at?: string | null;
  offer_updated_at?: string | null;
}

export interface CrustdataCredits {
  estimated?: CreditAmount;
  consumed?: CreditAmount | null;
  available?: CreditAmount | null;
  tenant_balance?: CreditAmount;
  status: string;
  search_cost_per_result: CreditAmount;
  enrich_cost_per_person: CreditAmount;
  error_code?: string | null;
}

export interface CrustdataSearchProfile {
  result_id: string;
  name: string;
  headline: string | null;
  current_title: string | null;
  current_company: string | null;
  location: string | null;
  updated_at: string | null;
  profile_url: string | null;
  selectable: boolean;
}

export interface CrustdataSearchResponse {
  session_id: string;
  profiles: CrustdataSearchProfile[];
  next_cursor: string | null;
  total_count: number | null;
  requested_count: number;
  returned_count: number;
  credits: CrustdataCredits;
}

export interface CrustdataImportItem {
  result_id: string;
  candidate_id?: string | null;
  status?: string;
  code?: string;
  message?: string | null;
}

export interface CrustdataImportResponse {
  imported_count: number;
  already_imported_count: number;
  failed_count: number;
  imported: CrustdataImportItem[];
  already_imported: CrustdataImportItem[];
  failed: CrustdataImportItem[];
  credits: CrustdataCredits;
  warnings: string[];
}

export interface CrustdataAutocompleteResponse {
  suggestions: string[];
}

export interface CrustdataAdminWallet {
  scope_kind: 'platform' | 'tenant';
  scope_id: string;
  balance: CreditAmount;
  reserved: CreditAmount;
  updated_at: string;
  provider_last_synced_at: string | null;
}

export interface CrustdataAdminCreditSync {
  balance: CreditAmount;
  reserved: CreditAmount;
  provider_last_synced_at: string | null;
}

export interface CrustdataCreditOperation {
  operation_id: string;
  tenant_id: string;
  user_id: string | null;
  project_id: string | null;
  operation_type: 'search' | 'enrich';
  requested_count: number;
  returned_or_matched_count: number;
  estimated_credits: CreditAmount;
  reported_credits_exact: CreditAmount | null;
  settled_credits: CreditAmount | null;
  status: string;
  created_at: string;
  error_code: string | null;
}

export interface CrustdataTenantWallet {
  tenant_id: string;
  balance: CreditAmount;
  reserved: CreditAmount;
}

export interface CrustdataReconcileResponse {
  operation_id: string;
  status: string;
  settled_credits: CreditAmount;
  provider_balance: CreditAmount;
}

export const crustdataApi = {
  getCriteria: async (projectId: string): Promise<CrustdataCriteriaResponse> => {
    const response = await apiClient.get<CrustdataCriteriaResponse>(`/crustdata/projects/${projectId}/criteria`);
    return response.data;
  },

  updateCriteria: async (
    projectId: string,
    currentCriteria: CrustdataSearchCriteria
  ): Promise<CrustdataCriteriaResponse> => {
    const response = await apiClient.patch<CrustdataCriteriaResponse>(
      `/crustdata/projects/${projectId}/criteria`,
      { current_criteria: currentCriteria }
    );
    return response.data;
  },

  resetCriteria: async (projectId: string): Promise<CrustdataCriteriaResponse> => {
    const response = await apiClient.post<CrustdataCriteriaResponse>(
      `/crustdata/projects/${projectId}/criteria/reset`
    );
    return response.data;
  },

  clearCriteria: async (projectId: string): Promise<CrustdataCriteriaResponse> => {
    const response = await apiClient.delete<CrustdataCriteriaResponse>(
      `/crustdata/projects/${projectId}/criteria/current`
    );
    return response.data;
  },

  regenerateCriteria: async (projectId: string): Promise<CrustdataCriteriaResponse> => {
    const response = await apiClient.post<CrustdataCriteriaResponse>(
      `/crustdata/projects/${projectId}/criteria/regenerate`
    );
    return response.data;
  },

  search: async (
    projectId: string,
    criteria: CrustdataSearchCriteria,
    operationId: string
  ): Promise<CrustdataSearchResponse> => {
    const response = await apiClient.post<CrustdataSearchResponse>(`/crustdata/projects/${projectId}/searches`, {
      criteria,
      operation_id: operationId,
    });
    return response.data;
  },

  nextPage: async (
    sessionId: string,
    cursor: string,
    operationId: string
  ): Promise<CrustdataSearchResponse> => {
    const response = await apiClient.post<CrustdataSearchResponse>(
      `/crustdata/searches/${sessionId}/next`,
      { operation_id: operationId, cursor }
    );
    return response.data;
  },

  importProfiles: async (
    projectId: string,
    sessionId: string,
    resultIds: string[],
    operationId: string
  ): Promise<CrustdataImportResponse> => {
    const response = await apiClient.post<CrustdataImportResponse>(`/crustdata/projects/${projectId}/imports`, {
      session_id: sessionId,
      result_ids: resultIds,
      operation_id: operationId,
    });
    return response.data;
  },

  getCredits: async (projectId: string): Promise<CrustdataCredits> => {
    const response = await apiClient.get<CrustdataCredits>(`/crustdata/projects/${projectId}/credits`);
    return response.data;
  },

  autocomplete: async (projectId: string, field: string, query: string): Promise<CrustdataAutocompleteResponse> => {
    const response = await apiClient.post<CrustdataAutocompleteResponse>(`/crustdata/projects/${projectId}/autocomplete`, {
      field,
      query,
    });
    return response.data;
  },

  getAdminCredits: async (): Promise<CrustdataAdminWallet[]> => {
    const response = await apiClient.get<CrustdataAdminWallet[]>('/crustdata/admin/credits');
    return response.data;
  },

  syncAdminCredits: async (): Promise<CrustdataAdminCreditSync> => {
    const response = await apiClient.post<CrustdataAdminCreditSync>('/crustdata/admin/credits/sync');
    return response.data;
  },

  getAdminOperations: async (): Promise<CrustdataCreditOperation[]> => {
    const response = await apiClient.get<CrustdataCreditOperation[]>('/crustdata/admin/operations');
    return response.data;
  },

  updateTenantWallet: async (tenantId: string, balance: CreditAmount): Promise<CrustdataTenantWallet> => {
    const response = await apiClient.put<CrustdataTenantWallet>(
      `/crustdata/admin/tenants/${tenantId}/wallet`,
      { balance }
    );
    return response.data;
  },

  reconcileOperation: async (
    operationId: string,
    actualCredits: CreditAmount
  ): Promise<CrustdataReconcileResponse> => {
    const response = await apiClient.post<CrustdataReconcileResponse>(
      `/crustdata/admin/operations/${operationId}/reconcile`,
      { actual_credits: actualCredits }
    );
    return response.data;
  },
};
