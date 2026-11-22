/**
 * Admin Users API — ADMIN-FIX-001
 *
 * Règles frontend:
 * - platform_admin n'est jamais proposé comme rôle de membership
 * - Le contexte enterprise vient du header X-Enterprise-ID (via MembershipDB)
 * - No enterprise_id="platform" fallback
 */

import { apiClient } from './client';
import type {
  AdminClient,
  AdminUser,
  InviteUserPayload,
  UpdateRolePayload,
  UpdateStatusPayload,
} from './types';

const BASE = '/admin/users';
export type AdminUserStatusScope = 'global' | 'membership';

function enterpriseHeaders(enterpriseId?: string): Record<string, string> {
  const headers: Record<string, string> = {};
  if (enterpriseId) {
    headers['X-Enterprise-ID'] = enterpriseId;
  }
  return headers;
}

export function getAdminApiErrorStatus(error: unknown): number | undefined {
  const directStatus = (error as { response?: { status?: unknown } })?.response?.status;
  if (typeof directStatus === 'number') {
    return directStatus;
  }

  const details = (error as { details?: unknown })?.details;
  if (details && typeof details === 'object' && 'status' in details) {
    const normalizedStatus = (details as { status?: unknown }).status;
    if (typeof normalizedStatus === 'number') {
      return normalizedStatus;
    }
  }

  return undefined;
}

export function getAdminApiErrorMessage(error: unknown, fallback: string): string {
  const message = (error as { message?: unknown })?.message;
  return typeof message === 'string' && message.trim() ? message : fallback;
}

/**
 * Liste les utilisateurs.
 * - platform_admin: retourne tous les users (ou filtrés si enterpriseId fourni)
 * - enterprise_admin: retourne uniquement les membres de son entreprise
 */
async function getUsers(enterpriseId?: string): Promise<AdminUser[]> {
  const headers = enterpriseHeaders(enterpriseId);
  const response = await apiClient.get<AdminUser[]>(BASE, { headers });
  return response.data;
}

async function getClients(): Promise<AdminClient[]> {
  const response = await apiClient.get<AdminClient[]>(`${BASE}/clients`);
  return response.data;
}

async function createClient(name: string, trialDurationDays?: number): Promise<AdminClient> {
  const response = await apiClient.post<AdminClient>(`${BASE}/clients`, {
    name,
    ...(trialDurationDays !== undefined ? { trial_duration_days: trialDurationDays } : {}),
  });
  return response.data;
}

async function extendClientTrial(tenantId: string, extendDays: number): Promise<AdminClient> {
  const response = await apiClient.patch<AdminClient>(
    `${BASE}/clients/${encodeURIComponent(tenantId)}/trial`,
    { extend_days: extendDays }
  );
  return response.data;
}

/**
 * Invite un utilisateur dans une entreprise.
 * Le rôle ne peut être que: enterprise_admin | recruiter | viewer
 * (platform_admin est interdit et rejeté par le backend)
 */
async function inviteUser(
  payload: InviteUserPayload,
  enterpriseId?: string
): Promise<AdminUser> {
  const headers = enterpriseHeaders(enterpriseId);
  const response = await apiClient.post<AdminUser>(`${BASE}/invite`, payload, {
    headers,
    validateStatus: (status) => (status >= 200 && status < 300) || status === 503,
  });
  return response.data;
}

async function resendInvitation(
  invitationId: string,
  language: 'en' | 'fr'
): Promise<AdminUser> {
  const response = await apiClient.post<AdminUser>(
    `${BASE}/invitations/${encodeURIComponent(invitationId)}/resend`,
    { language },
    { validateStatus: (status) => (status >= 200 && status < 300) || status === 503 }
  );
  return response.data;
}

/**
 * Change le rôle de membership d'un utilisateur.
 * Le rôle ne peut être que: enterprise_admin | recruiter | viewer
 */
async function updateUserRole(
  userId: string,
  payload: UpdateRolePayload,
  enterpriseId?: string
): Promise<AdminUser> {
  const headers = enterpriseHeaders(enterpriseId);
  const response = await apiClient.patch<AdminUser>(
    `${BASE}/${userId}/role`,
    payload,
    { headers }
  );
  return response.data;
}

/**
 * Active ou désactive un membership.
 * Ne touche pas à is_user_active (sauf platform_admin sans enterprise).
 */
async function updateUserStatus(
  userId: string,
  payload: UpdateStatusPayload,
  enterpriseId?: string,
  statusScope?: AdminUserStatusScope
): Promise<AdminUser> {
  const headers = enterpriseHeaders(enterpriseId);
  if (statusScope) {
    headers['X-Admin-User-Scope'] = statusScope;
  }
  const response = await apiClient.patch<AdminUser>(
    `${BASE}/${userId}/status`,
    payload,
    { headers }
  );
  return response.data;
}

export const adminUsersApi = {
  getClients,
  createClient,
  extendClientTrial,
  getUsers,
  inviteUser,
  resendInvitation,
  updateUserRole,
  updateUserStatus,
};
