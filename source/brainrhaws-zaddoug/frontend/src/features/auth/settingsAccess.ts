import type { User } from './context/AuthContext';

// UI visibility only. API authorization remains the server's responsibility.
export function canViewSettings(user: User | null): boolean {
  return Boolean(user?.is_active && (
    ['platform_admin', 'client_admin', 'enterprise_admin'].includes(user.role) || user.can_manage_users
  ));
}

export function canViewSettingsPath(user: User | null, pathname: string): boolean {
  let path: string;
  try {
    path = decodeURI(pathname).replace(/\/+$/, '').toLowerCase();
  } catch {
    return false;
  }
  const isSettings = path === '/settings' || path.startsWith('/settings/')
    || path === '/integrations' || path === '/admin/users' || path === '/admin/llm';
  if (!isSettings) return true;
  if (!canViewSettings(user)) return false;
  if (path === '/settings/admin/llm' || path === '/admin/llm' || path === '/settings/admin/crustdata') {
    return user?.role === 'platform_admin';
  }
  if (path === '/settings/admin/users' || path === '/admin/users') return Boolean(user?.can_manage_users);
  return true;
}
