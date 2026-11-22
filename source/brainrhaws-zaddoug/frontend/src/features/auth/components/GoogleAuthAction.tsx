import { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { apiClient } from '../../../api/client';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { useI18n } from '../../../i18n/useI18n';
import { Alert, AlertDescription } from '../../../components/ui/alert';

export function GoogleAuthNotice({ result, context = 'login' }: { result: string | null; context?: 'login' | 'link' }) {
  const { t } = useI18n();
  const key = result === 'cancelled' ? context === 'link' ? 'google.linkCancelled' : 'google.cancelled'
    : result === 'denied' ? context === 'link' ? 'google.linkDenied' : 'google.denied'
    : result === 'unavailable' ? 'google.startError' : null;
  return key ? <Alert variant="destructive"><AlertDescription>{t(key)}</AlertDescription></Alert> : null;
}

interface GoogleAuthActionProps {
  mode?: 'login' | 'invite' | 'link';
  invitationToken?: string;
  disabled?: boolean;
  capability?: boolean;
}

export function GoogleAuthAction({ mode = 'login', invitationToken, disabled = false, capability }: GoogleAuthActionProps) {
  const { t } = useI18n();
  const [enabled, setEnabled] = useState<boolean | null>(capability ?? null);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const [password, setPassword] = useState('');
  const inFlight = useRef(false);

  useEffect(() => {
    if (capability !== undefined) {
      setEnabled(capability);
      return;
    }
    const controller = new AbortController();
    void apiClient.get<{ enabled: boolean }>('/auth/google/config', { signal: controller.signal, timeout: 10000 })
      .then(({ data }) => { if (!controller.signal.aborted) setEnabled(data.enabled === true); })
      .catch(() => { if (!controller.signal.aborted) setEnabled(false); });
    return () => controller.abort();
  }, [capability]);

  const start = async () => {
    if (inFlight.current || disabled) return;
    inFlight.current = true;
    setPending(true);
    setFailed(false);
    try {
      const { data } = await apiClient.post<{ authorization_url: string }>(
        mode === 'link' ? '/auth/google/link' : '/auth/google/start',
        mode === 'link' ? { password } : { purpose: mode, ...(mode === 'invite' ? { invitation_token: invitationToken } : {}) },
        { timeout: 15000 },
      );
      const destination = new URL(data.authorization_url);
      if (destination.origin !== 'https://accounts.google.com' || destination.pathname !== '/o/oauth2/v2/auth') {
        throw new Error('Unexpected OAuth destination');
      }
      setPassword('');
      window.location.assign(destination.href);
    } catch {
      setPassword('');
      setFailed(true);
      setPending(false);
      inFlight.current = false;
    }
  };

  if (enabled === null) return mode === 'invite' ? (
    <Button type="button" variant="outline" className="min-h-11 w-full" disabled aria-busy="true">
      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
      {t('google.checking')}
    </Button>
  ) : null;
  if (!enabled) return null;
  const controls = <>
    {mode === 'link' && <div className="space-y-2">
      <Label htmlFor="google-link-password">{t('google.confirmPassword')}</Label>
      <Input id="google-link-password" type="password" autoComplete="current-password" maxLength={128}
        value={password} onChange={event => setPassword(event.target.value)} required disabled={pending || disabled} />
    </div>}
    <Button type={mode === 'link' ? 'submit' : 'button'} variant="outline" className="min-h-11 w-full"
      disabled={pending || disabled || (mode === 'link' && !password)} aria-busy={pending}
      onClick={mode === 'link' ? undefined : () => { void start(); }}>
      {pending && <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />}
      {t(pending ? 'google.redirecting' : mode === 'link' ? 'google.link' : mode === 'invite' ? 'google.accept' : 'google.signIn')}
    </Button>
    <p className="text-sm leading-6 text-[var(--brain-ops-text-muted)]">
      {t(mode === 'link' ? 'google.linkHelp' : mode === 'invite' ? 'google.inviteHelp' : 'google.loginHelp')}
    </p>
    {failed && <p role="alert" className="text-sm text-[var(--brain-ops-danger)]">{t(mode === 'link' ? 'google.linkError' : 'google.startError')}</p>}
  </>;
  return mode === 'link'
    ? <form className="w-full max-w-md space-y-3" onSubmit={event => { event.preventDefault(); void start(); }}>{controls}</form>
    : <div className="space-y-3">{controls}</div>;
}
