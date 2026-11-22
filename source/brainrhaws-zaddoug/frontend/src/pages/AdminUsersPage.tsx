/**
 * AdminUsersPage — ADMIN-FIX-001
 *
 * Frontend rules:
 * - platform_admin appears only in invite flow as a global role.
 * - client_admin targets a tenant/client access grant.
 * - Membership role editors keep platform/client admin excluded.
 * - The enterprise_id context comes from membership (X-Enterprise-ID), never from UserDB.tenant_id.
 * - No enterprise_id="platform" fallback.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Building2, LoaderCircle, ShieldAlert, UserPlus, X } from 'lucide-react';
import {
  adminUsersApi,
  getAdminApiErrorStatus,
  type AdminUserStatusScope,
} from '../api/adminUsers';
import { enterprisesApi } from '../api/enterprises';
import type { AdminClient, AdminUser, Enterprise } from '../api/types';
import {
  ContextStrip,
  MetricStrip,
  OperationalList,
  OperationalListItem,
  PageFrame,
  PageHeader,
  Section,
  SystemState,
} from '../components/operations';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Select } from '../components/ui/select';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import { formatMessage } from '../i18n/formatMessage';
import { useI18n } from '../i18n/useI18n';
import type { TranslationKey } from '../i18n/messages';
import { useAuth } from '../features/auth/context/AuthContext';
import { useToast } from '../hooks/useToast';
import { filterEnterprisesByTenant } from '../lib/tenantScope';
import { useAppStore } from '../stores/useAppStore';

const INVITE_ROLES = [
  'platform_admin',
  'client_admin',
  'enterprise_admin',
  'recruiter',
  'viewer',
] as const;

const MEMBERSHIP_ROLES = ['enterprise_admin', 'recruiter', 'viewer'] as const;

const ROLE_KEYS: Record<string, TranslationKey> = {
  platform_admin: 'adminUsers.role.platformAdmin',
  client_admin: 'adminUsers.role.clientAdmin',
  enterprise_admin: 'adminUsers.role.enterpriseAdmin',
  project_manager: 'adminUsers.role.projectManager',
  recruiter: 'adminUsers.role.recruiter',
  viewer: 'adminUsers.role.viewer',
};

type InviteRole = (typeof INVITE_ROLES)[number];
type MembershipRole = (typeof MEMBERSHIP_ROLES)[number];
type RowSurface = 'desktop' | 'mobile';
type EnterprisesLoadState = 'loading' | 'ready' | 'error';

function isMembershipInviteRole(role: InviteRole): role is MembershipRole {
  return role === 'enterprise_admin' || role === 'recruiter' || role === 'viewer';
}

function usersRequestKey(enterpriseContextId: string, selectedTenantId: string | null): string {
  return JSON.stringify([enterpriseContextId || null, selectedTenantId]);
}

function adminUserRowKey(user: AdminUser): string {
  const scopeKey = user.membership_id
    ?? user.access_scope_id
    ?? user.enterprise_id
    ?? 'global';
  return `${user.id}-${scopeKey}`;
}

function invitationRecipientName(user: AdminUser): string {
  return [user.invitation_first_name, user.invitation_last_name].filter(Boolean).join(' ');
}

function RoleBadge({ label, role }: { label: string; role: string | null }) {
  if (!role) {
    return <span className="text-xs italic text-[var(--brain-ops-text-muted)]">—</span>;
  }

  return (
    <Badge
      variant="outline"
      className="max-w-full border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] font-medium text-[var(--brain-ops-text)]"
      title={label}
    >
      <span className="truncate">{label}</span>
    </Badge>
  );
}

function StatusIndicator({ active, label }: { active: boolean | null; label: string }) {
  if (active === null) {
    return <span className="text-xs text-[var(--brain-ops-text-muted)]">—</span>;
  }

  return (
    <span
      aria-label={label}
      className={`inline-flex items-center gap-2 text-xs font-medium ${
        active ? 'text-[var(--brain-ops-success)]' : 'text-[var(--brain-ops-danger)]'
      }`}
    >
      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
      {label}
    </span>
  );
}

export function AdminUsersPage() {
  const { t, language } = useI18n();
  const { user: currentUser } = useAuth();
  const { success: showSuccess } = useToast();
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);
  const setSelectedTenantId = useAppStore((state) => state.setSelectedTenantId);
  const invalidateClientCatalog = useAppStore((state) => state.invalidateClientCatalog);
  const translationRef = useRef(t);
  const usersRequestEpochRef = useRef(0);
  const enterpriseContextTenantRef = useRef(selectedTenantId);
  translationRef.current = t;

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [accessibleEnterprises, setAccessibleEnterprises] = useState<Enterprise[]>([]);
  const [clients, setClients] = useState<AdminClient[]>([]);
  const [clientsLoadState, setClientsLoadState] = useState<EnterprisesLoadState>('loading');
  const [enterprisesLoadState, setEnterprisesLoadState] =
    useState<EnterprisesLoadState>('loading');
  const [isLoading, setIsLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // accessDenied is driven by the API 403 response, not by UserDB.role.
  // An enterprise_admin can have UserDB.role=viewer: only the backend knows whether access is allowed.
  const [accessDenied, setAccessDenied] = useState(false);
  const [accessResolved, setAccessResolved] = useState(false);
  const [resolvedUsersRequestKey, setResolvedUsersRequestKey] = useState<string | null>(null);
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [enterpriseContextInput, setEnterpriseContextInput] = useState('');
  const [enterpriseContextId, setEnterpriseContextId] = useState('');

  // Invite form state
  const [showInvite, setShowInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteFirstName, setInviteFirstName] = useState('');
  const [inviteLastName, setInviteLastName] = useState('');
  const [inviteRole, setInviteRole] = useState<InviteRole>('viewer');
  const [inviteEnterpriseId, setInviteEnterpriseId] = useState('');
  const [inviteTenantId, setInviteTenantId] = useState('');
  const [inviteLoading, setInviteLoading] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [resendingInvitationId, setResendingInvitationId] = useState<string | null>(null);

  // Client creation state (platform only)
  const [showCreateClient, setShowCreateClient] = useState(false);
  const [clientName, setClientName] = useState('');
  const [clientTrialMode, setClientTrialMode] = useState<'limited' | 'unlimited'>('limited');
  const [clientTrialDurationDays, setClientTrialDurationDays] = useState('14');
  const [clientAdminEmail, setClientAdminEmail] = useState('');
  const [clientAdminFirstName, setClientAdminFirstName] = useState('');
  const [clientAdminLastName, setClientAdminLastName] = useState('');
  const [createClientLoading, setCreateClientLoading] = useState(false);
  const [clientCreationOutcome, setClientCreationOutcome] = useState<string | null>(null);
  const [clientInviteRetryAfter, setClientInviteRetryAfter] = useState(0);
  const [clientInviteRetryTarget, setClientInviteRetryTarget] = useState<{
    email: string;
    tenantId: string;
  } | null>(null);
  const [trialExtensionDays, setTrialExtensionDays] = useState('14');
  const [trialExtensionLoading, setTrialExtensionLoading] = useState(false);
  const [trialExtensionError, setTrialExtensionError] = useState<string | null>(null);
  const [trialExtensionSuccess, setTrialExtensionSuccess] = useState<string | null>(null);

  // Edit state (role/status)
  const [editingUser, setEditingUser] = useState<string | null>(null);
  const [roleEditingRowKey, setRoleEditingRowKey] = useState<string | null>(null);
  const [roleDraft, setRoleDraft] = useState<MembershipRole>('viewer');

  const roleLabel = (role: string | null): string => {
    if (!role) return '—';
    const key = ROLE_KEYS[role];
    return key ? t(key) : role;
  };

  const formatTrialDate = (value: string | null | undefined): string => {
    if (!value) return t('adminUsers.trial.notAvailable');
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return t('adminUsers.trial.notAvailable');
    return new Intl.DateTimeFormat(language === 'fr' ? 'fr-FR' : 'en-GB', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date);
  };

  const scopedEnterprises = useMemo(
    () => filterEnterprisesByTenant(accessibleEnterprises, selectedTenantId),
    [accessibleEnterprises, selectedTenantId]
  );
  const availableInviteRoles: readonly InviteRole[] = currentUser?.role === 'platform_admin'
    ? INVITE_ROLES
    : MEMBERSHIP_ROLES;
  const selectedInvitationClient = clients.find((client) => client.id === inviteTenantId);
  const isCreatedClientInviteTarget = inviteRole === 'client_admin'
    && inviteEmail.trim().toLowerCase() === clientInviteRetryTarget?.email.toLowerCase()
    && inviteTenantId === clientInviteRetryTarget?.tenantId;
  const clientInviteRetryBlocked = clientInviteRetryAfter > 0 && isCreatedClientInviteTarget;
  const selectedInvitationClientTrialExpired = inviteRole === 'client_admin'
    && selectedInvitationClient?.trial_status === 'expired';

  useEffect(() => {
    if (clientInviteRetryAfter <= 0) return;
    const timer = window.setTimeout(() => {
      setClientInviteRetryAfter((seconds) => Math.max(0, seconds - 1));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [clientInviteRetryAfter]);
  const enterpriseContextIsCurrent = enterpriseContextTenantRef.current === selectedTenantId
    && (
      enterprisesLoadState !== 'ready'
      || !enterpriseContextId
      || scopedEnterprises.some((enterprise) => enterprise.id === enterpriseContextId)
    );
  const effectiveEnterpriseContextId = enterpriseContextIsCurrent ? enterpriseContextId : '';

  const fetchUsers = useCallback(async () => {
    // The tenant participates only in the freshness key. It is never sent as a list scope.
    const requestKey = usersRequestKey(effectiveEnterpriseContextId, selectedTenantId);
    const requestEpoch = ++usersRequestEpochRef.current;

    setIsLoading(true);
    setUsers([]);
    setLoadFailed(false);
    setAccessDenied(false);
    setError(null);

    try {
      // selectedTenantId intentionally triggers a refresh but never scopes this call.
      // The list scope remains the explicit enterprise context or backend resolution.
      const data = await adminUsersApi.getUsers(effectiveEnterpriseContextId || undefined);
      if (requestEpoch !== usersRequestEpochRef.current) return;
      setUsers(data);
    } catch (err: unknown) {
      if (requestEpoch !== usersRequestEpochRef.current) return;
      const status = getAdminApiErrorStatus(err);
      if (status === 403) {
        setAccessDenied(true);
        setUsers([]);
      } else {
        setUsers([]);
        setLoadFailed(true);
        setError(translationRef.current('adminUsers.error.load'));
      }
    } finally {
      if (requestEpoch === usersRequestEpochRef.current) {
        setResolvedUsersRequestKey(requestKey);
        setAccessResolved(true);
        setIsLoading(false);
      }
    }
  }, [effectiveEnterpriseContextId, selectedTenantId]);

  useEffect(() => {
    // Always call the API: the backend is the source of truth for admin access.
    // Do not filter here on user.role because enterprise_admin can have UserDB.role=viewer.
    void fetchUsers();
    return () => {
      usersRequestEpochRef.current += 1;
    };
  }, [fetchUsers, refreshRevision]);

  useEffect(() => {
    let active = true;
    const loadEnterprises = async () => {
      setEnterprisesLoadState('loading');
      try {
        const data = await enterprisesApi.getAll();
        if (active) {
          setAccessibleEnterprises(data);
          setEnterprisesLoadState('ready');
        }
      } catch {
        if (active) {
          setAccessibleEnterprises([]);
          setEnterprisesLoadState('error');
        }
      }
    };

    void loadEnterprises();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (currentUser?.role !== 'platform_admin') {
      setClients([]);
      setClientsLoadState('ready');
      return;
    }
    let active = true;
    setClientsLoadState('loading');
    void adminUsersApi.getClients()
      .then((data) => {
        if (!active) return;
        setClients([...data].sort((left, right) => left.name.localeCompare(right.name)));
        setClientsLoadState('ready');
      })
      .catch(() => {
        if (!active) return;
        setClients([]);
        setClientsLoadState('error');
      });
    return () => { active = false; };
  }, [currentUser?.role]);

  useEffect(() => {
    const tenantChanged = enterpriseContextTenantRef.current !== selectedTenantId;
    if (tenantChanged) {
      enterpriseContextTenantRef.current = selectedTenantId;
      setEnterpriseContextId('');
      setEnterpriseContextInput('');
      return;
    }

    if (enterprisesLoadState !== 'ready') {
      return;
    }

    const isVisible = (enterpriseId: string) =>
      scopedEnterprises.some((enterprise) => enterprise.id === enterpriseId);

    if (enterpriseContextId && !isVisible(enterpriseContextId)) {
      setEnterpriseContextId('');
    }
    if (enterpriseContextInput && !isVisible(enterpriseContextInput)) {
      setEnterpriseContextInput('');
      return;
    }

    if (selectedTenantId && !enterpriseContextId && scopedEnterprises.length === 1) {
      setEnterpriseContextId(scopedEnterprises[0].id);
      setEnterpriseContextInput(scopedEnterprises[0].id);
    }
  }, [
    enterpriseContextId,
    enterpriseContextInput,
    enterprisesLoadState,
    scopedEnterprises,
    selectedTenantId,
  ]);

  useEffect(() => {
    if (
      inviteEnterpriseId
      && enterprisesLoadState === 'ready'
      && !scopedEnterprises.some((enterprise) => enterprise.id === inviteEnterpriseId)
    ) {
      setInviteEnterpriseId('');
    }
  }, [enterprisesLoadState, inviteEnterpriseId, scopedEnterprises]);

  const handleEnterpriseContextChange = (enterpriseId: string) => {
    enterpriseContextTenantRef.current = selectedTenantId;
    setEnterpriseContextInput(enterpriseId);
    setEnterpriseContextId(enterpriseId);
  };

  const handleInviteVisibilityChange = (visible: boolean) => {
    setInviteError(null);
    if (visible && !inviteEnterpriseId && enterpriseContextId) {
      setInviteEnterpriseId(enterpriseContextId);
    }
    if (visible && !inviteTenantId && clients.some((client) => client.id === selectedTenantId)) {
      setInviteTenantId(selectedTenantId);
    }
    setShowInvite(visible);
  };

  const handleInviteClientChange = (tenantId: string) => {
    setInviteTenantId(tenantId);
    setTrialExtensionError(null);
    setTrialExtensionSuccess(null);
  };

  const flash = (msg: string, isError = false) => {
    if (isError) {
      setError(msg);
      setTimeout(() => {
        setError(null);
      }, 4000);
    } else {
      showSuccess(msg);
      setError(null);
    }
  };

  const handleToggleStatus = async (u: AdminUser) => {
    if (editingUser === u.id) return;
    setEditingUser(u.id);
    try {
      const currentActive = u.is_membership_active ?? u.is_user_active;
      const newActive = !currentActive;
      const statusScope: AdminUserStatusScope = u.enterprise_id ? 'membership' : 'global';
      await adminUsersApi.updateUserStatus(
        u.id,
        { is_active: newActive },
        statusScope === 'membership' ? u.enterprise_id ?? undefined : undefined,
        statusScope
      );
      const target = t(
        statusScope === 'membership'
          ? 'adminUsers.target.membershipAccess'
          : 'adminUsers.target.globalAccount'
      );
      const state = t(
        newActive ? 'adminUsers.state.reactivated' : 'adminUsers.state.disabled'
      );
      flash(formatMessage(t('adminUsers.success.statusChanged'), { email: u.email, target, state }));
      setRefreshRevision((revision) => revision + 1);
    } catch (err: unknown) {
      console.error('Unable to update user status:', err);
      flash(t('common.error'), true);
    } finally {
      setEditingUser(null);
    }
  };

  const handleChangeRole = async (u: AdminUser, newRole: MembershipRole) => {
    if (editingUser === u.id) return;
    setEditingUser(u.id);
    try {
      await adminUsersApi.updateUserRole(
        u.id,
        { role: newRole },
        u.enterprise_id ?? undefined
      );
      flash(
        formatMessage(t('adminUsers.success.roleChanged'), {
          email: u.email,
          role: roleLabel(newRole),
        })
      );
      setRefreshRevision((revision) => revision + 1);
    } catch (err: unknown) {
      console.error('Unable to update user role:', err);
      flash(t('common.error'), true);
    } finally {
      setEditingUser(null);
    }
  };

  const handleStartRoleEdit = (u: AdminUser) => {
    setRoleEditingRowKey(adminUserRowKey(u));
    setRoleDraft(u.membership_role ?? 'viewer');
  };

  const handleCancelRoleEdit = () => {
    setRoleEditingRowKey(null);
    setRoleDraft('viewer');
  };

  const handleSaveRoleEdit = async (u: AdminUser) => {
    await handleChangeRole(u, roleDraft);
    setRoleEditingRowKey(null);
  };

  const handlePrepareMembershipInvite = (u: AdminUser) => {
    setInviteError(null);
    setInviteEmail(u.email);
    setInviteFirstName(u.invitation_first_name ?? '');
    setInviteLastName(u.invitation_last_name ?? '');
    setInviteRole('viewer');
    setInviteEnterpriseId(enterpriseContextId);
    setInviteTenantId('');
    setShowInvite(true);
    setRoleEditingRowKey(null);
  };

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (
      !inviteEmail
      || inviteLoading
      || clientInviteRetryBlocked
      || selectedInvitationClientTrialExpired
    ) return;
    setInviteError(null);
    const firstName = inviteFirstName.trim();
    const lastName = inviteLastName.trim();
    if (!firstName || !lastName) {
      setInviteError(t('adminUsers.invite.nameRequired'));
      return;
    }
    if (inviteRole === 'client_admin' && !clients.some((client) => client.id === inviteTenantId)) {
      setInviteError(t('adminUsers.error.clientRequired'));
      return;
    }
    setInviteLoading(true);
    try {
      const enterpriseId = isMembershipInviteRole(inviteRole)
        ? inviteEnterpriseId.trim() || enterpriseContextId || undefined
        : undefined;
      const tenantId = inviteRole === 'client_admin'
        ? inviteTenantId.trim() || selectedTenantId || undefined
        : undefined;
      const result = await adminUsersApi.inviteUser(
        {
          email: inviteEmail,
          first_name: firstName,
          last_name: lastName,
          role: inviteRole,
          language,
          ...(tenantId ? { tenant_id: tenantId } : {}),
        },
        enterpriseId
      );
      if (result.invitation_status === 'delivery_failed') {
        setInviteError(t('adminUsers.error.emailUnavailable'));
        setRefreshRevision((revision) => revision + 1);
        return;
      }
      flash(
        formatMessage(t('adminUsers.success.invited'), {
          email: inviteEmail,
          role: roleLabel(inviteRole),
        })
      );
      if (isCreatedClientInviteTarget) {
        setClientCreationOutcome(null);
        setClientInviteRetryAfter(0);
        setClientInviteRetryTarget(null);
      }
      setInviteEmail('');
      setInviteFirstName('');
      setInviteLastName('');
      setInviteRole('viewer');
      setInviteEnterpriseId('');
      setInviteTenantId('');
      setShowInvite(false);
      setRefreshRevision((revision) => revision + 1);
    } catch (err: unknown) {
      console.error('Unable to invite user:', err);
      setInviteError(
        getAdminApiErrorStatus(err) === 429
          ? t('adminUsers.error.rateLimited')
          : t('common.error')
      );
    } finally {
      setInviteLoading(false);
    }
  };

  const handleCreateClient = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = clientName.trim();
    const email = clientAdminEmail.trim();
    if (!name || !email || createClientLoading) return;
    const firstName = clientAdminFirstName.trim();
    const lastName = clientAdminLastName.trim();
    const trialDurationDays = Number(clientTrialDurationDays);
    if (!firstName || !lastName) {
      flash(t('adminUsers.invite.nameRequired'), true);
      return;
    }
    if (
      clientTrialMode === 'limited'
      && (!Number.isInteger(trialDurationDays) || trialDurationDays < 1 || trialDurationDays > 365)
    ) {
      flash(t('adminUsers.createClient.trialDurationInvalid'), true);
      return;
    }

    setCreateClientLoading(true);
    setClientCreationOutcome(null);
    setClientInviteRetryAfter(0);
    setClientInviteRetryTarget(null);
    let createdClient: AdminClient | null = null;
    try {
      createdClient = await adminUsersApi.createClient(
        name,
        clientTrialMode === 'limited' ? trialDurationDays : undefined
      );
      setClients((current) => [...current.filter((client) => client.id !== createdClient?.id), createdClient!]
        .sort((left, right) => left.name.localeCompare(right.name)));
      invalidateClientCatalog();
      setSelectedTenantId(createdClient.id);
      setShowCreateClient(false);
      setClientName('');
      setClientTrialMode('limited');
      setClientTrialDurationDays('14');
      setClientAdminEmail('');
      setClientAdminFirstName('');
      setClientAdminLastName('');

      const invitation = await adminUsersApi.inviteUser({
        email,
        first_name: firstName,
        last_name: lastName,
        role: 'client_admin',
        tenant_id: createdClient.id,
        language,
      });
      if (invitation.invitation_status === 'delivery_failed') {
        const retryAfter = Math.max(1, invitation.invitation_retry_after_seconds ?? 60);
        setClientCreationOutcome(formatMessage(t('adminUsers.error.clientCreatedInviteFailed'), {
          client: createdClient.name,
          email,
          seconds: retryAfter,
        }));
        setClientInviteRetryAfter(retryAfter);
        setClientInviteRetryTarget({ email, tenantId: createdClient.id });
        setInviteEmail(email);
        setInviteFirstName(firstName);
        setInviteLastName(lastName);
        setInviteRole('client_admin');
        setInviteTenantId(createdClient.id);
        setInviteEnterpriseId('');
        setShowInvite(true);
      } else {
        flash(formatMessage(t('adminUsers.success.clientCreated'), {
          client: createdClient.name,
          email,
        }));
      }
      setRefreshRevision((revision) => revision + 1);
    } catch (err: unknown) {
      console.error('Unable to create client or invite its administrator:', err);
      if (createdClient) {
        const retryAfter = 60;
        setClientCreationOutcome(formatMessage(t('adminUsers.error.clientCreatedInviteFailed'), {
          client: createdClient.name,
          email,
          seconds: retryAfter,
        }));
        setClientInviteRetryAfter(retryAfter);
        setClientInviteRetryTarget({ email, tenantId: createdClient.id });
        setInviteEmail(email);
        setInviteFirstName(firstName);
        setInviteLastName(lastName);
        setInviteRole('client_admin');
        setInviteTenantId(createdClient.id);
        setInviteEnterpriseId('');
        setShowInvite(true);
        setRefreshRevision((revision) => revision + 1);
      } else {
        flash(t('adminUsers.error.createClient'), true);
      }
    } finally {
      setCreateClientLoading(false);
    }
  };

  const handleResendInvitation = async (u: AdminUser) => {
    if (!u.invitation_id || resendingInvitationId) return;
    setResendingInvitationId(u.invitation_id);
    try {
      const result = await adminUsersApi.resendInvitation(u.invitation_id, language);
      if (result.invitation_status === 'delivery_failed') {
        flash(t('adminUsers.error.emailUnavailable'), true);
      } else {
        flash(formatMessage(t('adminUsers.success.resent'), { email: u.email }));
      }
      setRefreshRevision((revision) => revision + 1);
    } catch (err: unknown) {
      if (getAdminApiErrorStatus(err) === 429) {
        flash(t('adminUsers.error.rateLimited'), true);
      } else {
        flash(t('adminUsers.error.send'), true);
      }
    } finally {
      setResendingInvitationId(null);
    }
  };

  const handleExtendClientTrial = async () => {
    if (!selectedInvitationClient || trialExtensionLoading) return;
    const extendDays = Number(trialExtensionDays);
    if (!Number.isInteger(extendDays) || extendDays < 1 || extendDays > 365) {
      setTrialExtensionError(t('adminUsers.trial.extensionInvalid'));
      setTrialExtensionSuccess(null);
      return;
    }

    setTrialExtensionLoading(true);
    setTrialExtensionError(null);
    setTrialExtensionSuccess(null);
    try {
      const updatedClient = await adminUsersApi.extendClientTrial(selectedInvitationClient.id, extendDays);
      setClients((current) => current.map((client) => (
        client.id === updatedClient.id ? updatedClient : client
      )));
      setTrialExtensionSuccess(formatMessage(t('adminUsers.trial.extensionSuccess'), {
        client: updatedClient.name,
        days: extendDays,
      }));
    } catch {
      setTrialExtensionError(t('adminUsers.trial.extensionError'));
    } finally {
      setTrialExtensionLoading(false);
    }
  };

  const invitationStatusLabel = (status: AdminUser['invitation_status']): string => {
    if (!status) return '—';
    const keys: Record<NonNullable<AdminUser['invitation_status']>, TranslationKey> = {
      pending_delivery: 'adminUsers.invitationStatus.pending',
      sent: 'adminUsers.invitationStatus.sent',
      delivery_failed: 'adminUsers.invitationStatus.failed',
      accepted: 'adminUsers.invitationStatus.accepted',
      revoked: 'adminUsers.invitationStatus.revoked',
      expired: 'adminUsers.invitationStatus.expired',
    };
    return t(keys[status]);
  };

  const statusActionLabel = (user: AdminUser, isEditing: boolean): string => {
    if (isEditing) return t('adminUsers.action.updating');

    const active = user.is_membership_active ?? user.is_access_grant_active ?? user.is_user_active;
    const target = t(
      user.enterprise_id
        ? 'adminUsers.target.membershipAccess'
        : user.access_scope_id
          ? 'adminUsers.target.clientAccess'
          : 'adminUsers.target.account'
    );
    return formatMessage(
      t(active ? 'adminUsers.action.disableTarget' : 'adminUsers.action.reactivateTarget'),
      { target }
    );
  };

  const statusLabel = (active: boolean | null): string =>
    t(active ? 'common.active' : 'common.inactive');

  const renderAccessRole = (u: AdminUser, surface: RowSurface) => {
    const rowKey = adminUserRowKey(u);

    if (u.membership_id && roleEditingRowKey === rowKey) {
      return (
        <Select
          id={`${surface === 'mobile' ? 'mobile-' : ''}role-select-${rowKey}`}
          value={roleDraft}
          disabled={editingUser === u.id}
          onChange={(e) => setRoleDraft(e.target.value as MembershipRole)}
          aria-label={formatMessage(t('adminUsers.aria.editRole'), { email: u.email })}
          className="min-w-44 border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]"
        >
          {MEMBERSHIP_ROLES.map((role) => (
            <option key={role} value={role}>
              {roleLabel(role)}
            </option>
          ))}
        </Select>
      );
    }

    if (roleEditingRowKey === rowKey) {
      return (
        <span className="block max-w-sm text-xs leading-5 text-[var(--brain-ops-text-muted)]">
          {t('adminUsers.roleEdit.addAccessHelp')}
        </span>
      );
    }

    const accessRole = u.membership_role ?? u.access_role;
    return <RoleBadge role={accessRole} label={roleLabel(accessRole)} />;
  };

  const renderUserActions = (u: AdminUser, surface: RowSurface) => {
    const idPrefix = surface === 'mobile' ? 'mobile-' : '';
    const rowKey = adminUserRowKey(u);
    const invitationAwaitingAcceptance = Boolean(
      u.invitation_id
      && u.invitation_status !== 'accepted'
      && u.invitation_status !== 'revoked'
    );
    return (
      <div className="flex flex-wrap gap-2">
        {roleEditingRowKey !== rowKey ? (
          <Button
            id={`${idPrefix}edit-role-${rowKey}`}
            type="button"
            size="sm"
            variant="outline"
            onClick={() => handleStartRoleEdit(u)}
            disabled={editingUser === u.id || invitationAwaitingAcceptance}
            aria-label={formatMessage(t('adminUsers.aria.editRole'), { email: u.email })}
          >
            {t('adminUsers.action.edit')}
          </Button>
        ) : null}

        {u.invitation_id
          && u.invitation_status !== 'accepted'
          && u.invitation_status !== 'revoked' ? (
          <Button
            id={`${idPrefix}resend-invitation-${rowKey}`}
            type="button"
            size="sm"
            variant="outline"
            onClick={() => handleResendInvitation(u)}
            disabled={
              resendingInvitationId !== null
              || (u.invitation_retry_after_seconds ?? 0) > 0
            }
            aria-label={formatMessage(t('adminUsers.aria.resend'), { email: u.email })}
            title={
              (u.invitation_retry_after_seconds ?? 0) > 0
                ? formatMessage(t('adminUsers.invite.retryAfter'), {
                    seconds: u.invitation_retry_after_seconds ?? 0,
                  })
                : undefined
            }
          >
            {resendingInvitationId === u.invitation_id
              ? t('adminUsers.action.resending')
              : t('adminUsers.action.resend')}
          </Button>
        ) : null}

        {u.membership_id && roleEditingRowKey === rowKey ? (
          <>
            <Button
              id={`${idPrefix}save-role-${rowKey}`}
              type="button"
              size="sm"
              onClick={() => handleSaveRoleEdit(u)}
              disabled={editingUser === u.id}
              aria-label={formatMessage(t('adminUsers.aria.saveRole'), { email: u.email })}
            >
              {t('adminUsers.action.save')}
            </Button>
            <Button
              id={`${idPrefix}cancel-role-${rowKey}`}
              type="button"
              size="sm"
              variant="outline"
              onClick={handleCancelRoleEdit}
              disabled={editingUser === u.id}
              aria-label={formatMessage(t('adminUsers.aria.cancelRole'), { email: u.email })}
            >
              {t('common.cancel')}
            </Button>
          </>
        ) : null}

        {roleEditingRowKey === rowKey ? (
          <>
            {!u.membership_id ? (
              <Button
                id={`${idPrefix}cancel-edit-${rowKey}`}
                type="button"
                size="sm"
                variant="outline"
                onClick={handleCancelRoleEdit}
                disabled={editingUser === u.id}
                aria-label={formatMessage(t('adminUsers.aria.cancelRole'), { email: u.email })}
              >
                {t('common.cancel')}
              </Button>
            ) : null}
            {!u.membership_id ? (
              <Button
                id={`${idPrefix}add-membership-${rowKey}`}
                type="button"
                size="sm"
                variant="secondary"
                onClick={() => handlePrepareMembershipInvite(u)}
                disabled={editingUser === u.id}
                aria-label={formatMessage(t('adminUsers.aria.addMembership'), { email: u.email })}
              >
                {t('adminUsers.action.addMembership')}
              </Button>
            ) : null}
            {!(u.access_scope_id && !u.membership_id) ? (
              <Button
                id={`${idPrefix}toggle-status-${rowKey}`}
                type="button"
                size="sm"
                variant={(u.is_membership_active ?? u.is_user_active) ? 'destructive' : 'outline'}
                onClick={() => handleToggleStatus(u)}
                disabled={editingUser === u.id}
                aria-label={formatMessage(t('adminUsers.aria.status'), { email: u.email })}
              >
                {statusActionLabel(u, editingUser === u.id)}
              </Button>
            ) : null}
          </>
        ) : null}
      </div>
    );
  };

  const currentUsersRequestKey = usersRequestKey(effectiveEnterpriseContextId, selectedTenantId);
  const isCurrentUserList = resolvedUsersRequestKey === currentUsersRequestKey;
  const isUserListLoading = isLoading || !isCurrentUserList;

  if (!accessResolved || !isCurrentUserList) {
    return (
      <PageFrame width="content">
        <PageHeader
          eyebrow={t('adminUsers.badge')}
          title={t('adminUsers.title')}
          description={t('adminUsers.description')}
        />
        <SystemState
          kind="loading"
          title={t('adminUsers.authority.loading')}
          indicator={<LoaderCircle className="size-5 animate-spin motion-reduce:animate-none" />}
        />
      </PageFrame>
    );
  }

  if (accessDenied) {
    return (
      <PageFrame width="content">
        <SystemState
          kind="error"
          title={t('adminUsers.denied.title')}
          description={t('adminUsers.denied.description')}
          indicator={<ShieldAlert className="size-5" />}
        />
      </PageFrame>
    );
  }

  const activeAccess = users.filter((user) =>
    Boolean(user.is_membership_active ?? user.is_access_grant_active ?? user.is_user_active)
  ).length;
  const enterpriseCount = new Set(users.map((user) => user.enterprise_id).filter(Boolean)).size;
  const metricsUnavailable = isUserListLoading || loadFailed;
  const activeEnterprise = accessibleEnterprises.find(
    (enterprise) => enterprise.id === enterpriseContextId
  );
  const invitationTenant = clients.find((client) => client.id === selectedTenantId);
  const invitationTenantLabel = selectedTenantId
    ? invitationTenant?.name || selectedTenantId
    : t('adminUsers.context.noInvitationClient');

  return (
    <PageFrame>
      <PageHeader
        eyebrow={t('adminUsers.badge')}
        title={t('adminUsers.title')}
        description={t('adminUsers.description')}
        actionsLabel={t('adminUsers.action.actions')}
        actions={(
          <>
            {currentUser?.role === 'platform_admin' ? (
              <Button
                type="button"
                variant="outline"
                className="min-h-11 rounded-sm border-[color:var(--brain-ops-border)] px-4 text-xs font-semibold tracking-[0.04em] text-[var(--brain-ops-text)] [font-family:var(--brain-ops-font-command)] hover:bg-[var(--brain-ops-surface-muted)] focus-visible:ring-[var(--brain-ops-focus-ring)]"
                onClick={() => {
                  setShowCreateClient((visible) => !visible);
                  setClientCreationOutcome(null);
                }}
                disabled={isUserListLoading || loadFailed}
                aria-expanded={showCreateClient}
                aria-controls="admin-create-client-section"
              >
                <Building2 data-icon="inline-start" className="size-4 stroke-[1.75]" aria-hidden="true" />
                {t(showCreateClient ? 'adminUsers.action.closeCreateClient' : 'adminUsers.action.createClient')}
              </Button>
            ) : null}
            <Button
              id="admin-invite-btn"
              type="button"
              className="min-h-11 rounded-sm px-4 text-xs font-semibold tracking-[0.04em] [font-family:var(--brain-ops-font-command)] focus-visible:ring-[var(--brain-ops-focus-ring)]"
              onClick={() => handleInviteVisibilityChange(!showInvite)}
              variant={showInvite ? 'outline' : 'default'}
              disabled={isUserListLoading || loadFailed}
              aria-expanded={showInvite}
              aria-controls="admin-invite-section"
            >
              {showInvite ? <X data-icon="inline-start" className="size-4 stroke-[1.75]" aria-hidden="true" /> : <UserPlus data-icon="inline-start" className="size-4 stroke-[1.75]" aria-hidden="true" />}
              {t(showInvite ? 'adminUsers.action.closeInvite' : 'adminUsers.action.inviteUser')}
            </Button>
          </>
        )}
      />

      <ContextStrip
        ariaLabel={t('adminUsers.context.title')}
        items={[
          {
            id: 'user-list-scope',
            label: t('adminUsers.context.listScope'),
            value: activeEnterprise?.nom || enterpriseContextId || t('adminUsers.context.globalList'),
          },
          {
            id: 'invitation-client-target',
            label: t('adminUsers.context.invitationClient'),
            value: invitationTenantLabel,
          },
        ]}
        actionsLabel={t('adminUsers.context.title')}
        actions={(
          <div data-tour="admin-users-workspace" className="w-full max-w-xl">
              <label className="flex min-w-0 flex-col gap-2" htmlFor="admin-enterprise-context-input">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('adminUsers.context.filterLabel')}
                </span>
                <Select
                  id="admin-enterprise-context-input"
                  value={enterpriseContextInput}
                  onChange={(e) => handleEnterpriseContextChange(e.target.value)}
                  disabled={isUserListLoading || enterprisesLoadState !== 'ready'}
                  className="rounded-[var(--brain-ops-radius-structural)] border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]"
                >
                  <option value="">{t('adminUsers.context.globalList')}</option>
                  {scopedEnterprises.map((enterprise) => (
                    <option key={enterprise.id} value={enterprise.id}>
                      {enterprise.nom}
                    </option>
                  ))}
                </Select>
                {enterprisesLoadState === 'loading' ? (
                  <span className="text-xs text-[var(--brain-ops-text-muted)]" role="status">
                    {t('adminUsers.context.companiesLoading')}
                  </span>
                ) : enterprisesLoadState === 'error' ? (
                  <span className="text-xs text-[var(--brain-ops-danger)]" role="alert">
                    {t('adminUsers.context.companiesUnavailable')}
                  </span>
                ) : null}
              </label>
          </div>
        )}
      />

      <MetricStrip
        ariaLabel={t('adminUsers.badge')}
        items={[
          {
            id: 'users',
            label: t('adminUsers.metric.users'),
            value: metricsUnavailable ? '—' : users.length,
            detail: t('adminUsers.metric.usersDescription'),
          },
          {
            id: 'active-access',
            label: t('adminUsers.metric.activeAccess'),
            value: metricsUnavailable ? '—' : activeAccess,
            detail: t('adminUsers.metric.activeAccessDescription'),
            tone: metricsUnavailable ? 'neutral' : 'success',
          },
          {
            id: 'companies',
            label: t('adminUsers.metric.companies'),
            value: metricsUnavailable ? '—' : enterpriseCount,
            detail: t('adminUsers.metric.companiesDescription'),
          },
        ]}
      />

      {error && !loadFailed && !isUserListLoading ? (
        <SystemState
          id="admin-error-alert"
          kind="error"
          title={t('common.error')}
          description={error}
        />
      ) : null}
      {clientCreationOutcome ? (
        <SystemState
          kind="error"
          title={t('adminUsers.createClient.partialTitle')}
          description={clientCreationOutcome}
        />
      ) : null}
      {showCreateClient && currentUser?.role === 'platform_admin' && !isUserListLoading && !loadFailed ? (
        <Section
          id="admin-create-client-section"
          title={t('adminUsers.createClient.title')}
          description={t('adminUsers.createClient.description')}
          aria-label={t('adminUsers.createClient.title')}
        >
          <form onSubmit={handleCreateClient} className="flex max-w-3xl flex-col gap-5">
            <p className="text-sm text-[var(--brain-ops-text-muted)]">{t('adminUsers.invite.nameHelp')}</p>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="flex flex-col gap-2" htmlFor="client-admin-first-name-input">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('adminUsers.invite.firstName')}
                </span>
                <Input id="client-admin-first-name-input" required maxLength={100} autoComplete="section-client-admin given-name"
                  value={clientAdminFirstName} onChange={(event) => setClientAdminFirstName(event.target.value)} disabled={createClientLoading} />
              </label>
              <label className="flex flex-col gap-2" htmlFor="client-admin-last-name-input">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('adminUsers.invite.lastName')}
                </span>
                <Input id="client-admin-last-name-input" required maxLength={100} autoComplete="section-client-admin family-name"
                  value={clientAdminLastName} onChange={(event) => setClientAdminLastName(event.target.value)} disabled={createClientLoading} />
              </label>
              <label className="flex flex-col gap-2" htmlFor="client-name-input">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('adminUsers.createClient.name')}
                </span>
                <Input id="client-name-input" required value={clientName}
                  onChange={(event) => setClientName(event.target.value)} disabled={createClientLoading} />
              </label>
              <label className="flex flex-col gap-2" htmlFor="client-admin-email-input">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('adminUsers.createClient.adminEmail')}
                </span>
                <Input id="client-admin-email-input" type="email" required value={clientAdminEmail}
                  onChange={(event) => setClientAdminEmail(event.target.value)} disabled={createClientLoading} />
              </label>
              <label className="flex flex-col gap-2" htmlFor="client-trial-mode-select">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('adminUsers.createClient.accessPolicy')}
                </span>
                <Select
                  id="client-trial-mode-select"
                  value={clientTrialMode}
                  onChange={(event) => setClientTrialMode(event.target.value as 'limited' | 'unlimited')}
                  disabled={createClientLoading}
                >
                  <option value="limited">{t('adminUsers.createClient.accessPolicyLimited')}</option>
                  <option value="unlimited">{t('adminUsers.createClient.accessPolicyUnlimited')}</option>
                </Select>
              </label>
              {clientTrialMode === 'limited' ? (
                <label className="flex flex-col gap-2" htmlFor="client-trial-duration-input">
                  <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                    {t('adminUsers.createClient.trialDuration')}
                  </span>
                  <Input
                    id="client-trial-duration-input"
                    type="number"
                    min={1}
                    max={365}
                    step={1}
                    required
                    inputMode="numeric"
                    value={clientTrialDurationDays}
                    onChange={(event) => setClientTrialDurationDays(event.target.value)}
                    disabled={createClientLoading}
                    aria-describedby="client-trial-duration-help"
                  />
                  <span id="client-trial-duration-help" className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">
                    {t('adminUsers.createClient.trialDurationHelp')}
                  </span>
                </label>
              ) : (
                <p className="self-end text-xs leading-5 text-[var(--brain-ops-text-muted)]">
                  {t('adminUsers.createClient.unlimitedHelp')}
                </p>
              )}
            </div>
            <div className="flex flex-wrap gap-3">
              <Button type="submit" disabled={createClientLoading}>
                {createClientLoading ? <LoaderCircle data-icon="inline-start" className="animate-spin motion-reduce:animate-none" /> : null}
                {t(createClientLoading ? 'adminUsers.createClient.processing' : 'adminUsers.createClient.submit')}
              </Button>
              <Button type="button" variant="outline" disabled={createClientLoading}
                onClick={() => setShowCreateClient(false)}>
                {t('common.cancel')}
              </Button>
            </div>
          </form>
        </Section>
      ) : null}
      {showInvite && !isUserListLoading && !loadFailed ? (
        <Section
          id="admin-invite-section"
          title={t('adminUsers.invite.title')}
          description={t('adminUsers.invite.nameHelp')}
          aria-label={t('adminUsers.invite.title')}
        >
          <form onSubmit={handleInvite} className="flex max-w-4xl flex-col gap-5">
            {inviteError ? (
              <SystemState id="admin-invite-error" kind="error" title={t('common.error')} description={inviteError} />
            ) : null}
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              <label className="flex flex-col gap-2" htmlFor="invite-first-name-input">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('adminUsers.invite.firstName')}
                </span>
                <Input id="invite-first-name-input" required maxLength={100} autoComplete="section-invitation given-name"
                  value={inviteFirstName} onChange={(event) => setInviteFirstName(event.target.value)} disabled={inviteLoading}
                  className="rounded-[var(--brain-ops-radius-structural)] border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]" />
              </label>
              <label className="flex flex-col gap-2" htmlFor="invite-last-name-input">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('adminUsers.invite.lastName')}
                </span>
                <Input id="invite-last-name-input" required maxLength={100} autoComplete="section-invitation family-name"
                  value={inviteLastName} onChange={(event) => setInviteLastName(event.target.value)} disabled={inviteLoading}
                  className="rounded-[var(--brain-ops-radius-structural)] border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]" />
              </label>
              <label className="flex flex-col gap-2" htmlFor="invite-email-input">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('adminUsers.invite.email')}
                </span>
                <Input
                  id="invite-email-input"
                  type="email"
                  required
                  value={inviteEmail}
                  disabled={inviteLoading}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="first.last@company.com"
                  className="rounded-[var(--brain-ops-radius-structural)] border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]"
                />
              </label>

              <label className="flex flex-col gap-2" htmlFor="invite-role-select">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('adminUsers.invite.role')}
                </span>
                <Select
                  id="invite-role-select"
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as InviteRole)}
                  className="rounded-[var(--brain-ops-radius-structural)] border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]"
                >
                  {availableInviteRoles.map((role) => (
                    <option key={role} value={role}>
                      {roleLabel(role)}
                    </option>
                  ))}
                </Select>
              </label>

              {isMembershipInviteRole(inviteRole) ? (
                <label className="flex flex-col gap-2" htmlFor="invite-enterprise-input">
                  <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                    {t('adminUsers.invite.enterpriseId')}
                  </span>
                  <Select
                    id="invite-enterprise-input"
                    value={inviteEnterpriseId}
                    onChange={(e) => setInviteEnterpriseId(e.target.value)}
                    disabled={enterprisesLoadState !== 'ready'}
                    className="rounded-[var(--brain-ops-radius-structural)] border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]"
                  >
                    <option value="">{t('adminUsers.invite.enterpriseIdPlaceholder')}</option>
                    {scopedEnterprises.map((enterprise) => (
                      <option key={enterprise.id} value={enterprise.id}>
                        {enterprise.nom}
                      </option>
                    ))}
                  </Select>
                </label>
              ) : null}

              {inviteRole === 'client_admin' ? (
                <label className="flex flex-col gap-2" htmlFor="invite-tenant-input">
                  <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                    {t('adminUsers.invite.client')}
                  </span>
                  <Select
                    id="invite-tenant-input"
                    required
                    value={inviteTenantId}
                    onChange={(e) => handleInviteClientChange(e.target.value)}
                    disabled={clientsLoadState !== 'ready'}
                    className="rounded-[var(--brain-ops-radius-structural)] border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]"
                  >
                    <option value="">{t('adminUsers.invite.selectClient')}</option>
                    {clients.map((client) => (
                      <option key={client.id} value={client.id}>{client.name}</option>
                    ))}
                  </Select>
                </label>
              ) : null}
            </div>

            {inviteRole === 'client_admin' && selectedInvitationClient ? (
              <div
                role="group"
                aria-label={t('adminUsers.trial.contextTitle')}
                className="border-y border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] px-4 py-3"
              >
                <p className="mb-3 text-xs font-semibold uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t('adminUsers.trial.contextTitle')}
                </p>
                <dl className="grid gap-3 sm:grid-cols-3">
                  <div>
                    <dt className="text-xs text-[var(--brain-ops-text-muted)]">{t('adminUsers.trial.status')}</dt>
                    <dd className="mt-1 text-sm font-medium text-[var(--brain-ops-text)]">
                      {t(selectedInvitationClient.trial_status === 'expired'
                        ? 'adminUsers.trial.expired'
                        : selectedInvitationClient.trial_status === 'active'
                          ? 'adminUsers.trial.active'
                          : selectedInvitationClient.trial_status === 'pending'
                            ? 'adminUsers.trial.pending'
                            : 'adminUsers.createClient.accessPolicyUnlimited')}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-[var(--brain-ops-text-muted)]">{t('adminUsers.trial.duration')}</dt>
                    <dd className="mt-1 text-sm font-medium text-[var(--brain-ops-text)]">
                      {selectedInvitationClient.trial_duration_days
                        ? formatMessage(t('adminUsers.trial.durationValue'), {
                            days: selectedInvitationClient.trial_duration_days,
                          })
                        : '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-[var(--brain-ops-text-muted)]">{t('adminUsers.trial.end')}</dt>
                    <dd className="mt-1 text-sm font-medium text-[var(--brain-ops-text)]">
                      {selectedInvitationClient.trial_expires_at
                        ? formatTrialDate(selectedInvitationClient.trial_expires_at)
                        : t(selectedInvitationClient.trial_duration_days
                          ? 'adminUsers.trial.endAfterActivation'
                          : 'adminUsers.createClient.accessPolicyUnlimited')}
                    </dd>
                  </div>
                </dl>
                {currentUser?.role === 'platform_admin'
                  && (selectedInvitationClient.trial_status === 'active'
                    || selectedInvitationClient.trial_status === 'expired') ? (
                  <div className="mt-4 border-t border-[color:var(--brain-ops-border)] pt-4">
                    <p className="text-sm font-medium text-[var(--brain-ops-text)]">
                      {t('adminUsers.trial.extendTitle')}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-[var(--brain-ops-text-muted)]">
                      {t('adminUsers.trial.extendHelp')}
                    </p>
                    <div className="mt-3 flex flex-wrap items-end gap-3">
                      <label className="flex min-w-40 flex-col gap-2" htmlFor="client-trial-extension-days">
                        <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                          {t('adminUsers.trial.extensionDays')}
                        </span>
                        <Input
                          id="client-trial-extension-days"
                          type="number"
                          min={1}
                          max={365}
                          step={1}
                          inputMode="numeric"
                          value={trialExtensionDays}
                          onChange={(event) => setTrialExtensionDays(event.target.value)}
                          disabled={trialExtensionLoading}
                        />
                      </label>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => void handleExtendClientTrial()}
                        disabled={trialExtensionLoading}
                      >
                        {trialExtensionLoading ? (
                          <LoaderCircle data-icon="inline-start" className="animate-spin motion-reduce:animate-none" />
                        ) : null}
                        {t(trialExtensionLoading
                          ? 'adminUsers.trial.extending'
                          : 'adminUsers.trial.extendAction')}
                      </Button>
                    </div>
                    {trialExtensionError ? (
                      <p className="mt-3 text-sm text-[var(--brain-ops-danger)]" role="alert">
                        {trialExtensionError}
                      </p>
                    ) : null}
                    {trialExtensionSuccess ? (
                      <p className="mt-3 text-sm text-[var(--brain-ops-success)]" role="status">
                        {trialExtensionSuccess}
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}

            {inviteRole === 'client_admin' && selectedInvitationClient?.trial_duration_days ? (
              <p className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">
                {t('adminUsers.trial.invitationSeparation')}
              </p>
            ) : null}
            {selectedInvitationClientTrialExpired ? (
              <p className="text-sm text-[var(--brain-ops-danger)]" role="alert">
                {t('adminUsers.trial.extendBeforeInvite')}
              </p>
            ) : null}

            <div className="flex flex-wrap gap-3">
              <Button
                id="invite-submit-btn"
                type="submit"
                disabled={inviteLoading || clientInviteRetryBlocked || selectedInvitationClientTrialExpired}
              >
                {inviteLoading ? (
                  <LoaderCircle data-icon="inline-start" className="animate-spin motion-reduce:animate-none" />
                ) : null}
                {t(inviteLoading ? 'adminUsers.invite.processing' : 'adminUsers.invite.submit')}
              </Button>
              {clientInviteRetryBlocked ? (
                <span className="self-center text-xs text-[var(--brain-ops-text-muted)]" role="status">
                  {formatMessage(t('adminUsers.invite.retryAfter'), {
                    seconds: clientInviteRetryAfter,
                  })}
                </span>
              ) : null}
              <Button
                id="invite-cancel-btn"
                type="button"
                variant="outline"
                onClick={() => handleInviteVisibilityChange(false)}
              >
                {t('common.cancel')}
              </Button>
            </div>
          </form>
        </Section>
      ) : null}

      <Section
        title={t('adminUsers.list.title')}
        description={t('adminUsers.metric.usersDescription')}
      >
        {isUserListLoading ? (
          <SystemState
            kind="loading"
            title={t('adminUsers.list.loading')}
            indicator={<LoaderCircle className="size-5 animate-spin motion-reduce:animate-none" />}
          />
        ) : loadFailed ? (
          <SystemState
            id="admin-load-error"
            kind="error"
            title={t('common.error')}
            description={error ?? t('adminUsers.error.load')}
          />
        ) : users.length === 0 ? (
          <SystemState kind="empty" title={t('adminUsers.list.empty')} />
        ) : (
          <>
            <div className="hidden overflow-hidden rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] min-[1360px]:block">
              <Table className="min-w-[64rem]">
                <TableCaption className="sr-only">{t('adminUsers.list.title')}</TableCaption>
                <TableHeader className="bg-[var(--brain-ops-surface-muted)]">
                  <TableRow>
                    <TableHead>{t('adminUsers.table.email')}</TableHead>
                    <TableHead>{t('adminUsers.table.globalRole')}</TableHead>
                    <TableHead>{t('adminUsers.table.accessRole')}</TableHead>
                    <TableHead>{t('adminUsers.table.scope')}</TableHead>
                    <TableHead>{t('adminUsers.table.userActive')}</TableHead>
                    <TableHead>{t('adminUsers.table.accessActive')}</TableHead>
                    <TableHead>{t('adminUsers.table.invitation')}</TableHead>
                    <TableHead>{t('adminUsers.table.actions')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((u) => (
                    <TableRow key={adminUserRowKey(u)}>
                      <TableCell className="max-w-64 whitespace-normal font-medium">
                        {invitationRecipientName(u) ? (
                          <span className="block break-words text-xs text-[var(--brain-ops-text-muted)]">
                            {invitationRecipientName(u)}
                          </span>
                        ) : null}
                        <span className="break-all">{u.email}</span>
                      </TableCell>
                      <TableCell>
                        <RoleBadge role={u.global_role} label={roleLabel(u.global_role)} />
                      </TableCell>
                      <TableCell>{renderAccessRole(u, 'desktop')}</TableCell>
                      <TableCell>
                        <span className="break-all text-xs text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                          {u.enterprise_id ?? u.access_scope_id ?? '—'}
                        </span>
                      </TableCell>
                      <TableCell>
                        <StatusIndicator
                          active={u.is_user_active}
                          label={statusLabel(u.is_user_active)}
                        />
                      </TableCell>
                      <TableCell>
                        <StatusIndicator
                          active={u.is_membership_active ?? u.is_access_grant_active}
                          label={statusLabel(u.is_membership_active ?? u.is_access_grant_active)}
                        />
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className="border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)]"
                        >
                          {invitationStatusLabel(u.invitation_status)}
                        </Badge>
                      </TableCell>
                      <TableCell>{renderUserActions(u, 'desktop')}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <OperationalList ariaLabel={t('adminUsers.list.title')} className="min-[1360px]:hidden">
              {users.map((u) => {
                const accessActive = u.is_membership_active ?? u.is_access_grant_active;
                return (
                  <OperationalListItem
                    key={`${adminUserRowKey(u)}-mobile`}
                    primary={(
                      <span>
                        {invitationRecipientName(u) ? (
                          <span className="block break-words text-xs text-[var(--brain-ops-text-muted)]">
                            {invitationRecipientName(u)}
                          </span>
                        ) : null}
                        <span className="break-all">{u.email}</span>
                      </span>
                    )}
                    secondary={(
                      <dl className="grid gap-3 pt-2 sm:grid-cols-2">
                        <div className="flex flex-col gap-1">
                          <dt className="text-xs text-[var(--brain-ops-text-muted)]">
                            {t('adminUsers.table.globalRole')}
                          </dt>
                          <dd><RoleBadge role={u.global_role} label={roleLabel(u.global_role)} /></dd>
                        </div>
                        <div className="flex flex-col gap-1">
                          <dt className="text-xs text-[var(--brain-ops-text-muted)]">
                            {t('adminUsers.table.accessRole')}
                          </dt>
                          <dd>{renderAccessRole(u, 'mobile')}</dd>
                        </div>
                        <div className="flex flex-col gap-1">
                          <dt className="text-xs text-[var(--brain-ops-text-muted)]">
                            {t('adminUsers.table.userActive')}
                          </dt>
                          <dd>
                            <StatusIndicator
                              active={u.is_user_active}
                              label={statusLabel(u.is_user_active)}
                            />
                          </dd>
                        </div>
                        <div className="flex flex-col gap-1">
                          <dt className="text-xs text-[var(--brain-ops-text-muted)]">
                            {t('adminUsers.table.accessActive')}
                          </dt>
                          <dd>
                            <StatusIndicator
                              active={accessActive}
                              label={statusLabel(accessActive)}
                            />
                          </dd>
                        </div>
                        <div className="flex flex-col gap-1">
                          <dt className="text-xs text-[var(--brain-ops-text-muted)]">
                            {t('adminUsers.table.invitation')}
                          </dt>
                          <dd>{invitationStatusLabel(u.invitation_status)}</dd>
                        </div>
                      </dl>
                    )}
                    metadata={(
                      <span>
                        {t('adminUsers.table.scope')}: {u.enterprise_id ?? u.access_scope_id ?? '—'}
                      </span>
                    )}
                    monospaceMetadata
                    actions={renderUserActions(u, 'mobile')}
                    actionsLabel={`${t('adminUsers.table.actions')}: ${u.email}`}
                  />
                );
              })}
            </OperationalList>
          </>
        )}
      </Section>
    </PageFrame>
  );
}
