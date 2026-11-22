import { Moon, Sun, Menu } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '../ui/button';
import { useTheme } from '../../hooks/useTheme';
import { useAppStore } from '../../stores/useAppStore';
import { LanguageSwitcher } from './LanguageSwitcher';
import { useI18n } from '../../i18n/useI18n';
import { BrainLogo } from '../shared/BrainLogo';
import { TenantScopeSelector } from './TenantScopeSelector';
import { useMobileNavigation } from '../../hooks/useMobileNavigation';
import { useAuth } from '../../features/auth/context/AuthContext';
import { GlobalSearch } from '../../features/header-search/GlobalSearch';
import { NotificationCenter } from '../../features/header-notifications/NotificationCenter';

export const Header: React.FC = () => {
  const { theme, toggleTheme } = useTheme();
  const toggleSidebar = useAppStore((state) => state.toggleSidebar);
  const { t } = useI18n();
  const mobileViewport = useMobileNavigation();
  const { user } = useAuth();
  const name = user?.display_name?.trim() || user?.email || '';
  const initials = name.split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((part) => part[0].toUpperCase()).join('');

  return (
    <header data-brain-ops="" className="sticky top-0 z-40 w-full border-b border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]">
      <div className="flex h-16 items-center gap-1 px-2 sm:gap-3 sm:px-4 lg:gap-4 lg:px-6">
        {/* Mobile menu button */}
        <Button
          data-tour="sidebar-navigation"
          variant="ghost"
          size="icon"
          onClick={toggleSidebar}
          className="brain-shell-touch-target brain-shell-square-target shrink-0 lg:hidden"
          aria-label={t('header.toggleMenu')}
        >
          <Menu className="brain-shell-icon" />
        </Button>

        {/* Logo */}
        <Link to="/" className="brain-shell-touch-target flex shrink-0 items-center gap-3 transition-opacity hover:opacity-80 lg:w-56">
          <BrainLogo className="w-7" />
          <span className="hidden whitespace-nowrap text-sm font-semibold tracking-[0.14em] text-foreground sm:block">BRAIN HR</span>
        </Link>

        <div className="flex min-w-0 flex-1 justify-start lg:max-w-lg lg:flex-[0_1_32rem]"><GlobalSearch /></div>
        <div className="hidden flex-1 lg:block" />
        {!mobileViewport && <TenantScopeSelector compact />}
        <NotificationCenter />

        {/* Theme toggle */}
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          className="brain-shell-touch-target brain-shell-square-target shrink-0"
          aria-label={theme === 'light' ? t('header.switchToDark') : t('header.switchToLight')}
        >
          {theme === 'light' ? (
            <Moon className="brain-shell-icon" />
          ) : (
            <Sun className="brain-shell-icon" />
          )}
        </Button>
        <div className="border-l border-[color:var(--brain-ops-border)] pl-1 sm:pl-2"><LanguageSwitcher compact /></div>
        {user && <Link to="/profile" aria-label={t('header.account')} title={name}
          className="brain-shell-touch-target brain-shell-square-target inline-flex shrink-0 items-center justify-center rounded-full border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] text-xs font-semibold text-[var(--brain-ops-text)] transition-colors hover:bg-[var(--brain-ops-surface)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {initials || '?'}
        </Link>}
      </div>
    </header>
  );
};
