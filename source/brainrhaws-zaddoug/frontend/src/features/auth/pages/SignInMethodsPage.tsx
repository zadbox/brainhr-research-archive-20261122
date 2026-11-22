import { ArrowLeft } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { PageFrame, PageHeader, Section, SystemState } from '../../../components/operations';
import { useI18n } from '../../../i18n/useI18n';
import { GoogleAuthAction, GoogleAuthNotice } from '../components/GoogleAuthAction';
import { useAuth } from '../context/AuthContext';

export function SignInMethodsPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const location = useLocation();

  if (!user) return null;

  return <PageFrame width="content">
    <Link to="/profile" className="inline-flex min-h-11 items-center gap-2 rounded-md text-sm font-medium text-[var(--brain-ops-text)] underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <ArrowLeft aria-hidden="true" className="size-4" />{t('account.backToProfile')}
    </Link>
    <PageHeader title={t('account.signInMethods')} description={t('account.signInMethodsDescription')} />
    <Section title={t('account.googleSignIn')} description={t('account.googleSignInDescription')}>
      <div className="max-w-xl space-y-5">
        <dl className="space-y-1 border-b border-[color:var(--brain-ops-border)] pb-4">
          <dt className="text-xs uppercase tracking-wider text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">{t('auth.email')}</dt>
          <dd className="break-words text-sm font-medium [overflow-wrap:anywhere]">{user.email}</dd>
        </dl>
        <GoogleAuthNotice result={new URLSearchParams(location.search).get('google')} context="link" />
        {user.google_auth_enabled
          ? user.google_linked
            ? <SystemState kind="success" title={t('google.linked')} />
            : <GoogleAuthAction mode="link" capability />
          : <SystemState kind="warning" title={t('account.googleUnavailable')} />}
      </div>
    </Section>
  </PageFrame>;
}
