import { apiClient } from './client';
import type { InvitationState } from './types';

const BASE = '/auth/invitations';

async function inspect(token: string): Promise<InvitationState> {
  const response = await apiClient.post<InvitationState>(`${BASE}/inspect`, { token });
  return response.data;
}

async function accept(token: string, password?: string): Promise<InvitationState> {
  const response = await apiClient.post<InvitationState>(`${BASE}/accept`, {
    token,
    ...(password ? { password } : {}),
  });
  return response.data;
}

export const invitationsApi = { inspect, accept };
