import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { apiClient } from '../../../api/client';
import { useAppStore } from '../../../stores/useAppStore';

export interface User {
  id: string;
  email: string;
  role: string;
  tenant_id: string | null;
  is_active: boolean;
  can_manage_users: boolean;
  display_name?: string | null;
  google_linked?: boolean;
  google_auth_enabled?: boolean;
  tenant_name?: string | null;
  trial_duration_days?: number | null;
  trial_tenant_id?: string | null;
  trial_started_at?: string | null;
  trial_expires_at?: string | null;
  trial_status?: 'pending' | 'active' | 'expired' | null;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  accessIssue: 'CLIENT_TRIAL_EXPIRED' | null;
  login: (data: LoginCredentials) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [accessIssue, setAccessIssue] = useState<'CLIENT_TRIAL_EXPIRED' | null>(null);

  const checkAuth = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await apiClient.get('/auth/me');
      // The platform selector is a view preference, never a client's authority.
      if (res.data.role !== 'platform_admin') useAppStore.getState().setSelectedTenantId('');
      setUser(res.data);
      setAccessIssue(null);
    } catch (error: unknown) {
      setUser(null);
      const code = typeof error === 'object' && error !== null && 'code' in error
        ? String(error.code)
        : null;
      setAccessIssue(code === 'CLIENT_TRIAL_EXPIRED' ? 'CLIENT_TRIAL_EXPIRED' : null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void checkAuth();
  }, [checkAuth]);

  useEffect(() => {
    if (
      !user?.trial_expires_at
      || user.role === 'platform_admin'
      || user.trial_status !== 'active'
    ) {
      return;
    }

    const expiresAt = new Date(user.trial_expires_at).getTime();
    if (Number.isNaN(expiresAt)) return;
    const browserTimeoutLimit = 2_147_000_000;
    const remaining = expiresAt - Date.now();
    const delay = remaining > 0
      ? Math.min(remaining + 1000, browserTimeoutLimit)
      : 60_000;
    const timer = window.setTimeout(() => {
      void checkAuth();
    }, delay);
    return () => window.clearTimeout(timer);
  }, [checkAuth, user?.role, user?.trial_expires_at, user?.trial_status]);

  const login = async (credentials: LoginCredentials) => {
    const res = await apiClient.post('/auth/login', credentials);
    useAppStore.getState().setSelectedTenantId('');
    setAccessIssue(null);
    setUser(res.data);
  };

  const logout = async () => {
    // Do not report a successful sign-out while the HttpOnly session is still valid.
    await apiClient.post('/auth/logout', undefined, { timeout: 15000 });
    useAppStore.getState().setSelectedTenantId('');
    setAccessIssue(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, accessIssue, login, logout, checkAuth }}>
      {children}
    </AuthContext.Provider>
  );
};

// The hook intentionally shares this module with its provider for compatibility
// with the existing import surface used throughout the application.
// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
