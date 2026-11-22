import { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { useAuth } from '../context/AuthContext';
import { Button } from '../../../components/ui/button';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '../../../components/ui/card';
import { Alert, AlertDescription } from '../../../components/ui/alert';
import { Loader2 } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useI18n } from '../../../i18n/useI18n';
import type { TranslationKey } from '../../../i18n/messages';
import { GoogleAuthAction, GoogleAuthNotice } from './GoogleAuthAction';

const createLoginSchema = (t: (key: TranslationKey) => string) => z.object({
  email: z.string().email({ message: t('auth.invalidEmail') }),
  password: z.string().min(1, { message: t('auth.passwordRequired') }),
});

type LoginFormValues = z.infer<ReturnType<typeof createLoginSchema>>;

interface LoginLocationState {
  from?: {
    pathname: string;
    search?: string;
    hash?: string;
    state?: unknown;
  };
}

export const LoginForm = () => {
  const { accessIssue, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();
  const googleResult = new URLSearchParams(location.search).get('google');
  const loginSchema = useMemo(() => createLoginSchema(t), [t]);

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      email: '',
      password: '',
    },
  });

  const onSubmit = async (data: LoginFormValues) => {
    try {
      setError(null);
      await login(data);
      const from = (location.state as LoginLocationState | null)?.from;
      if (from?.pathname) {
        navigate(
          {
            pathname: from.pathname,
            search: from.search || '',
            hash: from.hash || '',
          },
          {
            replace: true,
            state: from.state,
          }
        );
      } else {
        navigate('/enterprises', { replace: true });
      }
    } catch (err: unknown) {
      const errorCode = typeof err === 'object' && err !== null && 'code' in err
        ? String(err.code)
        : null;
      if (errorCode === 'CLIENT_TRIAL_EXPIRED') {
        setError(t('auth.clientTrialExpired'));
      } else if (errorCode === 'UNAUTHORIZED' || errorCode === 'BAD_REQUEST') {
        setError(t('auth.invalidCredentials'));
      } else {
        setError(t('auth.backendUnavailable'));
      }
    }
  };

  const { isSubmitting } = form.formState;
  const displayedError = error
    ?? (accessIssue === 'CLIENT_TRIAL_EXPIRED' ? t('auth.clientTrialExpired') : null);

  return (
    <Card className="w-full max-w-md border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text)] shadow-[var(--brain-ops-shadow-raised)]">
      <CardHeader className="space-y-1 text-center">
        <CardTitle className="text-2xl font-semibold">{t('auth.title')}</CardTitle>
        <CardDescription className="text-sm text-[var(--brain-ops-text-muted)]">
          {t('auth.description')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 pb-4">
        <GoogleAuthNotice result={googleResult} />
        <GoogleAuthAction disabled={isSubmitting} />
      </CardContent>
      <form onSubmit={form.handleSubmit(onSubmit)}>
        <CardContent className="space-y-4">
          {displayedError && (
            <Alert variant="destructive">
              <AlertDescription>{displayedError}</AlertDescription>
            </Alert>
          )}
          <div className="space-y-2">
            <Label htmlFor="email">{t('auth.email')}</Label>
            <Input
              id="email"
              type="email"
              placeholder={t('auth.emailPlaceholder')}
              autoComplete="username"
              {...form.register('email')}
              disabled={isSubmitting}
            />
            {form.formState.errors.email && (
              <p className="text-sm text-[var(--brain-ops-danger)]">{form.formState.errors.email.message}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">{t('auth.password')}</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              {...form.register('password')}
              disabled={isSubmitting}
            />
            {form.formState.errors.password && (
              <p className="text-sm text-[var(--brain-ops-danger)]">{form.formState.errors.password.message}</p>
            )}
          </div>
        </CardContent>
        <CardFooter>
          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />}
            {t('auth.submit')}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
};
