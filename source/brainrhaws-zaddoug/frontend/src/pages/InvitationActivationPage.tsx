import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { LoaderCircle, Moon, Sun } from 'lucide-react';

import { invitationsApi } from '../api/invitations';
import type { InvitationState } from '../api/types';
import { LanguageSwitcher } from '../components/layout/LanguageSwitcher';
import { ContextStrip, SystemState } from '../components/operations';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { useTheme } from '../hooks/useTheme';
import { useI18n } from '../i18n/useI18n';
import { formatMessage } from '../i18n/formatMessage';
import { GoogleAuthAction } from '../features/auth/components/GoogleAuthAction';

type PageState = InvitationState['status'] | 'loading' | 'submitting' | 'error';

function stateTranslationKey(state: Exclude<PageState, 'loading' | 'submitting' | 'ready'>) {
  const keys = {
    accepted: 'invitation.accepted',
    expired: 'invitation.expired',
    used: 'invitation.used',
    invalid: 'invitation.invalid',
    email_unavailable: 'invitation.emailUnavailable',
    trial_expired: 'invitation.trialExpired',
    error: 'invitation.error',
  } as const;
  return keys[state];
}

export function InvitationActivationPage() {
  const { language, t } = useI18n();
  const { theme, toggleTheme } = useTheme();
  const initialTokenRef = useRef(
    new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token') ?? ''
  );
  const [token] = useState(initialTokenRef.current);
  const [state, setState] = useState<PageState>('loading');
  const [requiresPassword, setRequiresPassword] = useState(false);
  const [changeExistingPassword, setChangeExistingPassword] = useState(false);
  const [password, setPassword] = useState('');
  const [passwordConfirmation, setPasswordConfirmation] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [invitationDetails, setInvitationDetails] = useState<InvitationState | null>(null);

  useEffect(() => {
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    if (!token) {
      setState('invalid');
      return;
    }

    let active = true;
    void invitationsApi.inspect(token)
      .then((result) => {
        if (!active) return;
        setInvitationDetails(result);
        setRequiresPassword(result.requires_password);
        setState(result.status);
      })
      .catch(() => {
        if (active) setState('error');
      });
    return () => {
      active = false;
    };
  }, [token]);

  const handleAccept = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);
    const submitsPassword = requiresPassword || changeExistingPassword;
    if (submitsPassword) {
      if (password.length < 12) {
        setFormError(t('invitation.passwordTooShort'));
        return;
      }
      if (password !== passwordConfirmation) {
        setFormError(t('invitation.passwordMismatch'));
        return;
      }
    }

    setState('submitting');
    try {
      const result = await invitationsApi.accept(
        token,
        submitsPassword ? password : undefined
      );
      setInvitationDetails(result);
      setState(result.status);
    } catch {
      setState('error');
    }
  };

  const resolvedState: PageState = state === 'ready' && invitationDetails?.trial_status === 'expired'
    ? 'trial_expired'
    : state;
  const terminalState = resolvedState !== 'loading' && resolvedState !== 'submitting' && resolvedState !== 'ready'
    ? resolvedState
    : null;
  const hasTrialDetails = Boolean(
    invitationDetails?.tenant_name
    || invitationDetails?.trial_duration_days
    || invitationDetails?.trial_status
  );
  const formatTrialDate = (value: string | null | undefined): string => {
    if (!value) return t('invitation.trial.endAfterActivation');
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return t('invitation.trial.endAfterActivation');
    return new Intl.DateTimeFormat(language === 'fr' ? 'fr-FR' : 'en-GB', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date);
  };
  const trialStatusKey = invitationDetails?.trial_status === 'expired'
    ? 'invitation.trial.expired'
    : invitationDetails?.trial_status === 'active'
      ? 'invitation.trial.active'
      : 'invitation.trial.pending';

  return (
    <main
      data-brain-ops=""
      className="relative flex min-h-screen flex-col bg-[var(--brain-ops-canvas)] px-4 py-12 text-[var(--brain-ops-text)] sm:px-6"
    >
      <div className="absolute right-4 top-4 flex items-center gap-2 sm:right-6 sm:top-6">
        <LanguageSwitcher />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          aria-label={theme === 'light' ? t('header.switchToDark') : t('header.switchToLight')}
        >
          {theme === 'light' ? <Moon className="size-5" /> : <Sun className="size-5" />}
        </Button>
      </div>

      <div className="mx-auto flex w-full max-w-lg flex-1 flex-col justify-center">
        <div className="mb-7">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
            BRAIN Operations
          </p>
          <h1 className="mt-3 text-3xl font-semibold tracking-[-0.03em]">
            {t('invitation.title')}
          </h1>
          <p className="mt-2 text-sm leading-6 text-[var(--brain-ops-text-muted)]">
            {t('invitation.description')}
          </p>
        </div>

        {state === 'loading' || state === 'submitting' ? (
          <SystemState
            kind="loading"
            title={t(state === 'loading' ? 'invitation.loading' : 'invitation.submitting')}
            indicator={<LoaderCircle className="size-5 animate-spin motion-reduce:animate-none" />}
          />
        ) : null}

        {hasTrialDetails && state !== 'loading' ? (
          <ContextStrip
            ariaLabel={t('invitation.trial.contextTitle')}
            items={[
              ...(invitationDetails?.tenant_name ? [{
                id: 'invitation-trial-client',
                label: t('invitation.trial.client'),
                value: invitationDetails.tenant_name,
              }] : []),
              {
                id: 'invitation-trial-status',
                label: t('invitation.trial.status'),
                value: t(trialStatusKey),
              },
              ...(invitationDetails?.trial_duration_days ? [{
                id: 'invitation-trial-duration',
                label: t('invitation.trial.duration'),
                value: formatMessage(t('invitation.trial.durationValue'), {
                  days: invitationDetails.trial_duration_days,
                }),
              }] : []),
              {
                id: 'invitation-trial-end',
                label: t('invitation.trial.end'),
                value: formatTrialDate(invitationDetails?.trial_expires_at),
              },
            ]}
          />
        ) : null}

        {resolvedState === 'ready' ? (
          <form
            onSubmit={handleAccept}
            className="flex flex-col gap-5 border-y border-[color:var(--brain-ops-border)] py-6"
          >
            <GoogleAuthAction mode="invite" invitationToken={token} />
            <p className="text-sm leading-6 text-[var(--brain-ops-text-muted)]">
              {t(requiresPassword ? 'invitation.newAccountHelp' : 'invitation.existingAccountHelp')}
            </p>
            {!requiresPassword ? (
              <label className="flex cursor-pointer items-start gap-3 text-sm leading-6 text-[var(--brain-ops-text-muted)]">
                <input
                  id="invitation-change-existing-password"
                  type="checkbox"
                  checked={changeExistingPassword}
                  onChange={(event) => {
                    setChangeExistingPassword(event.target.checked);
                    setFormError(null);
                    if (!event.target.checked) {
                      setPassword('');
                      setPasswordConfirmation('');
                    }
                  }}
                  className="mt-1 size-4 rounded border-[color:var(--brain-ops-border)] accent-[var(--brain-ops-accent)]"
                />
                <span>{t('invitation.changeExistingPassword')}</span>
              </label>
            ) : null}
            {requiresPassword || changeExistingPassword ? (
              <>
                <label className="flex flex-col gap-2" htmlFor="invitation-password">
                  <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                    {t('invitation.password')}
                  </span>
                  <Input
                    id="invitation-password"
                    type="password"
                    autoComplete="new-password"
                    minLength={12}
                    maxLength={72}
                    required
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    aria-describedby={formError ? 'invitation-form-error' : undefined}
                  />
                </label>
                <label className="flex flex-col gap-2" htmlFor="invitation-password-confirmation">
                  <span className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                    {t('invitation.passwordConfirmation')}
                  </span>
                  <Input
                    id="invitation-password-confirmation"
                    type="password"
                    autoComplete="new-password"
                    minLength={12}
                    maxLength={72}
                    required
                    value={passwordConfirmation}
                    onChange={(event) => setPasswordConfirmation(event.target.value)}
                    aria-describedby={formError ? 'invitation-form-error' : undefined}
                  />
                </label>
              </>
            ) : null}
            {formError ? (
              <p id="invitation-form-error" role="alert" className="text-sm text-[var(--brain-ops-danger)]">
                {formError}
              </p>
            ) : null}
            <Button id="invitation-accept" type="submit">
              {t(
                requiresPassword
                  ? 'invitation.createPassword'
                  : changeExistingPassword
                    ? 'invitation.resetPasswordAndAccept'
                    : 'invitation.acceptWithoutGoogle'
              )}
            </Button>
          </form>
        ) : null}

        {terminalState ? (
          <SystemState
            kind={terminalState === 'accepted' ? 'success' : 'error'}
            title={t(stateTranslationKey(terminalState))}
            description={t(
              terminalState === 'accepted'
                ? 'invitation.acceptedHelp'
                : terminalState === 'trial_expired'
                  ? 'invitation.trialRecoveryHelp'
                : 'invitation.recoveryHelp'
            )}
          />
        ) : null}

        {terminalState && terminalState !== 'trial_expired' ? (
          <Link
            to="/login"
            className="mt-5 inline-flex h-9 items-center justify-center rounded-md border border-[color:var(--brain-ops-border)] px-4 py-2 text-sm font-medium hover:bg-[var(--brain-ops-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-accent)]"
          >
            {t('invitation.goToLogin')}
          </Link>
        ) : null}
      </div>
    </main>
  );
}
