import { ArrowRight, Loader2, LogOut, ShieldCheck, UserRound } from 'lucide-react';
import { PageFrame, PageHeader, Section, SystemState } from '../../../components/operations';
import { Button } from '../../../components/ui/button';
import { useI18n } from '../../../i18n/useI18n';
import { Link } from 'react-router-dom';

export interface AccountProfileProps {
  email: string;
  displayName?: string | null;
  showSignInMethods?: boolean;
  signingOut: boolean;
  signOutFailed: boolean;
  onSignOut: () => void;
}

export function AccountProfile({ email, displayName, showSignInMethods, signingOut, signOutFailed, onSignOut }: AccountProfileProps) {
  const { t } = useI18n();
  return (
    <PageFrame width="content">
      <PageHeader title={t('account.title')} description={t('account.description')} />
      <Section title={t('account.identity')} divided={false}>
        <div className="flex min-w-0 items-start gap-4">
          <span aria-hidden="true" className="flex size-12 shrink-0 items-center justify-center rounded-full border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]"><UserRound className="size-5" /></span>
          <dl className="min-w-0 space-y-2">
            {displayName && <>
              <dt className="text-xs uppercase tracking-wider text-[var(--brain-ops-text-muted)]">{t('google.displayName')}</dt>
              <dd className="break-words text-lg font-medium [overflow-wrap:anywhere]">{displayName}</dd>
            </>}
            <dt className="text-xs uppercase tracking-wider text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">{t('auth.email')}</dt>
            <dd className="break-words text-base font-medium [overflow-wrap:anywhere] sm:text-lg">{email}</dd>
          </dl>
        </div>
      </Section>
      {showSignInMethods && <Section title={t('account.signInMethods')} description={t('account.signInMethodsDescription')}>
        <Link to="/account/sign-in" className="inline-flex min-h-11 items-center gap-2 rounded-md text-sm font-medium text-[var(--brain-ops-text)] underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <ShieldCheck aria-hidden="true" className="size-4" />
          {t('account.manageSignIn')}
          <ArrowRight aria-hidden="true" className="size-4" />
        </Link>
      </Section>}
      <Section title={t('account.session')} description={t('account.sessionDescription')} contentClassName="flex flex-col items-start gap-4">
        {signOutFailed && <SystemState kind="error" title={t('account.signOutFailed')} description={t('account.signOutRetry')} className="w-full" />}
        <Button type="button" variant="outline" className="min-h-11" disabled={signingOut} aria-busy={signingOut} onClick={onSignOut}>
          {signingOut ? <Loader2 aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" /> : <LogOut aria-hidden="true" className="size-4" />}
          {t(signingOut ? 'account.signingOut' : 'account.signOut')}
        </Button>
      </Section>
    </PageFrame>
  );
}
