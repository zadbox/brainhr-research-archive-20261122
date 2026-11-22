import { apiClient as client } from './client';
import type {
  Connector,
  ConnectorScopePolicy,
  IntegrationAccount,
  IntegrationAccountCreate,
  IntegrationEvent,
  OutlookOAuthConfiguration,
  TurnoverApplicationSimulation,
  TurnoverApplicationReceipt,
  TurnoverConfiguration,
  TurnoverConnectionTest,
  TurnoverPublication,
  TurnoverPublicationCreate,
} from './types';

// Connectors
export const getConnectors = async (
  family?: string,
  availableOnly?: boolean
): Promise<Connector[]> => {
  const params = new URLSearchParams();
  if (family) params.append('family', family);
  if (availableOnly !== undefined) params.append('available_only', String(availableOnly));

  const qs = params.toString();
  const res = await client.get(`/integrations/connectors${qs ? `?${qs}` : ''}`);
  return res.data;
};

export const updateConnectorScopePolicy = async (
  connectorId: string,
  scopePolicy: ConnectorScopePolicy,
): Promise<{ connector_id: string; scope_policy: ConnectorScopePolicy }> => {
  const res = await client.patch(
    `/integrations/connectors/${encodeURIComponent(connectorId)}/scope-policy`,
    { scope_policy: scopePolicy },
  );
  return res.data;
};

// Accounts
export const getAccounts = async (tenantId?: string): Promise<IntegrationAccount[]> => {
  const params = new URLSearchParams();
  if (tenantId) params.append('tenant_id', tenantId);

  const qs = params.toString();
  const res = await client.get(`/integrations/accounts${qs ? `?${qs}` : ''}`);
  return res.data;
};

export const createAccount = async (
  payload: IntegrationAccountCreate,
): Promise<IntegrationAccount> => {
  const res = await client.post('/integrations/accounts', payload);
  return res.data;
};

export const getOutlookOAuthConfiguration = async (
  tenantId?: string,
): Promise<OutlookOAuthConfiguration> => {
  const params = new URLSearchParams();
  if (tenantId) params.append('tenant_id', tenantId);
  const qs = params.toString();
  const res = await client.get(
    `/integrations/connectors/outlook/oauth/configuration${qs ? `?${qs}` : ''}`,
  );
  return res.data;
};

export const startOutlookOAuth = async (
  tenantId?: string,
): Promise<OutlookOAuthConfiguration> => {
  const res = await client.post('/integrations/connectors/outlook/oauth/start', {
    tenant_id: tenantId,
  });
  return res.data;
};

export const getTurnoverConfiguration = async (
  tenantId?: string,
): Promise<TurnoverConfiguration> => {
  const params = new URLSearchParams();
  if (tenantId) params.append('tenant_id', tenantId);
  const qs = params.toString();
  const res = await client.get(
    `/integrations/turnover-it/configuration${qs ? `?${qs}` : ''}`,
  );
  return res.data;
};

export const configureTurnover = async (
  token: string,
  tenantId?: string,
): Promise<TurnoverConfiguration> => {
  const res = await client.put('/integrations/turnover-it/configuration', {
    tenant_id: tenantId,
    token,
  });
  return res.data;
};

export const testTurnoverConnection = async (
  tenantId?: string,
): Promise<TurnoverConnectionTest> => {
  const res = await client.post('/integrations/turnover-it/test-connection', {
    tenant_id: tenantId,
  });
  return res.data;
};

export const createTurnoverPublication = async (
  payload: TurnoverPublicationCreate,
): Promise<TurnoverPublication> => {
  const res = await client.post('/integrations/turnover-it/publications', payload);
  return res.data;
};

export const getTurnoverProjectPublications = async (
  projectId: string,
): Promise<TurnoverPublication[]> => {
  const res = await client.get(
    `/integrations/turnover-it/publications/project/${encodeURIComponent(projectId)}`,
  );
  return res.data;
};

export const simulateTurnoverApplication = async (
  publicationId: string,
  payload: TurnoverApplicationSimulation,
): Promise<TurnoverApplicationReceipt> => {
  const res = await client.post(
    `/integrations/turnover-it/publications/${encodeURIComponent(publicationId)}/simulate-application`,
    payload,
  );
  return res.data;
};

// Events (Outbox)
export const getEvents = async (
  limit?: number,
  status?: string,
  enterpriseId?: string
): Promise<IntegrationEvent[]> => {
  const params = new URLSearchParams();
  if (limit !== undefined) params.append('limit', String(limit));
  if (status) params.append('status', status);
  if (enterpriseId) params.append('enterprise_id', enterpriseId); // Assuming passing enterprise_id if not resolved from auth context

  const qs = params.toString();
  const res = await client.get(`/integrations/events${qs ? `?${qs}` : ''}`);
  return res.data;
};
