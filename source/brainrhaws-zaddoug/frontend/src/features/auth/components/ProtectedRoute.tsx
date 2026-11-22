import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { AlertTriangle, Loader2, LogOut, RefreshCw } from 'lucide-react';
import { Button } from '../../../components/ui/button';
import { SystemState } from '../../../components/operations';
import { useI18n } from '../../../i18n/useI18n';
import { formatMessage } from '../../../i18n/formatMessage';

export const ProtectedRoute = () => {
  const { user, isLoading, checkAuth, logout } = useAuth();
  const { t } = useI18n();
  const location = useLocation();

  if (isLoading) {
    return (
      <div data-brain-ops="" className="flex min-h-screen w-full items-center justify-center bg-[var(--brain-ops-canvas)] text-[var(--brain-ops-text)]">
        <Loader2 className="size-8 animate-spin text-[var(--brain-ops-accent)] motion-reduce:animate-none" />
      </div>
    );
  }

  if (!user) {
    // Redirect them to the /login page, but save the current location they were
    // trying to go to when they were redirected. This allows us to send them
    // along to that page after they login, which is a nicer user experience
    // than dropping them off on the home page.
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  const ownClientTrialExpired = user.role !== 'platform_admin'
    && Boolean(user.trial_tenant_id)
    && user.trial_status === 'expired';

  if (ownClientTrialExpired) {
    const description = user.tenant_name
      ? formatMessage(t('auth.clientTrialExpiredTenant'), { client: user.tenant_name })
      : t('auth.clientTrialExpired');
    return (
      <main
        data-brain-ops=""
        className="flex min-h-screen items-center bg-[var(--brain-ops-canvas)] px-4 py-12 text-[var(--brain-ops-text)] sm:px-6"
      >
        <div className="mx-auto w-full max-w-2xl">
          <SystemState
            kind="error"
            title={t('auth.clientTrialExpiredTitle')}
            description={description}
            indicator={<AlertTriangle className="size-5" />}
            actionLabel={t('auth.clientTrialExpiredActions')}
            action={(
              <>
                <Button type="button" onClick={() => void checkAuth()}>
                  <RefreshCw data-icon="inline-start" className="size-4" aria-hidden="true" />
                  {t('auth.checkTrialAgain')}
                </Button>
                <Button type="button" variant="outline" onClick={() => void logout()}>
                  <LogOut data-icon="inline-start" className="size-4" aria-hidden="true" />
                  {t('auth.signOut')}
                </Button>
              </>
            )}
          />
        </div>
      </main>
    );
  }

  return <Outlet />;
};
