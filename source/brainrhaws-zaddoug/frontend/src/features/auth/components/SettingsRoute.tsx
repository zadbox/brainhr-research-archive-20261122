import { Link, Outlet, useLocation } from 'react-router-dom';
import { LockKeyhole } from 'lucide-react';
import { PageFrame, SystemState } from '../../../components/operations';
import { useI18n } from '../../../i18n/useI18n';
import { useAuth } from '../context/AuthContext';
import { canViewSettingsPath } from '../settingsAccess';

export function SettingsRoute() {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const { t } = useI18n();

  if (!canViewSettingsPath(user, pathname)) {
    return (
      <PageFrame width="content">
        <SystemState kind="warning" title={t('account.accessDenied')} description={t('account.accessDescription')}
          indicator={<LockKeyhole className="size-5" />} actionLabel={t('account.title')}
          action={<Link to="/profile" className="inline-flex min-h-11 items-center rounded-md px-4 text-sm font-medium underline underline-offset-4 focus-visible:outline focus-visible:outline-2">{t('account.open')}</Link>} />
      </PageFrame>
    );
  }

  return <Outlet />;
}
