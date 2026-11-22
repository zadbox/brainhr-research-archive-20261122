import { Navigate } from 'react-router-dom';
import { Moon, Sun } from 'lucide-react';
import { LoginForm } from '../components/LoginForm';
import { LanguageSwitcher } from '../../../components/layout/LanguageSwitcher';
import { Loading } from '../../../components/shared/Loading';
import { BrainLogo } from '../../../components/shared/BrainLogo';
import { Button } from '../../../components/ui/button';
import { useTheme } from '../../../hooks/useTheme';
import { useAuth } from '../context/AuthContext';
import { useI18n } from '../../../i18n/useI18n';

export const LoginPage = () => {
  const { t } = useI18n();
  const { user, isLoading } = useAuth();
  const { theme, toggleTheme } = useTheme();

  if (isLoading) {
    return (
      <main
        data-brain-ops=""
        className="flex min-h-screen items-center justify-center bg-[var(--brain-ops-canvas)] text-[var(--brain-ops-text)]"
      >
        <Loading size="lg" text={t('auth.checkingSession')} />
      </main>
    );
  }

  if (user) {
    return <Navigate to="/" replace />;
  }

  return (
    <main
      data-brain-ops=""
      className="relative flex min-h-screen flex-col justify-center overflow-hidden bg-[var(--brain-ops-canvas)] px-4 py-12 text-[var(--brain-ops-text)] sm:px-6 lg:px-8"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-60 [background-image:linear-gradient(to_right,var(--brain-ops-border)_1px,transparent_1px),linear-gradient(to_bottom,var(--brain-ops-border)_1px,transparent_1px)] [background-size:3rem_3rem] [mask-image:linear-gradient(to_bottom,black,transparent_72%)]"
      />
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
      <div className="relative mb-8 sm:mx-auto sm:w-full sm:max-w-md">
        <p className="text-center text-[0.6875rem] font-medium uppercase tracking-[0.14em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
          BRAIN OPERATIONS
        </p>
        <h1 className="mt-3">
          <BrainLogo className="mx-auto w-14 sm:w-16" />
          <span className="sr-only">Brain RH</span>
        </h1>
      </div>

      <div className="relative sm:mx-auto sm:w-full sm:max-w-md">
        <LoginForm />
        <p className="mt-8 text-center text-sm text-[var(--brain-ops-text-muted)]">
          &copy; {new Date().getFullYear()} Brain HR. {t('login.securityNotice')}
        </p>
      </div>
    </main>
  );
};
