import { NavLink } from 'react-router-dom';
import { UserRound } from 'lucide-react';
import { cn } from '../../../lib/utils';
import { useI18n } from '../../../i18n/useI18n';

export function AccountLink({ email, collapsed, onNavigate }: { email: string; collapsed: boolean; onNavigate?: () => void }) {
  const { t } = useI18n();
  return (
    <NavLink to="/profile" onClick={onNavigate} aria-label={t('account.open')} title={collapsed ? t('account.open') : undefined}
      className={({ isActive }) => cn(
        'brain-shell-touch-target flex min-w-0 items-center gap-3 rounded-md p-3 text-[var(--brain-ops-text)]',
        'hover:bg-[var(--brain-sidebar-active)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        isActive && 'bg-[var(--brain-sidebar-active)]', collapsed && 'justify-center px-0',
      )}>
      <UserRound aria-hidden="true" className="brain-shell-icon shrink-0" />
      {!collapsed && <span className="flex min-w-0 flex-col gap-1">
        <span className="text-sm font-medium">{t('account.title')}</span>
        <span className="truncate text-xs text-[var(--brain-ops-text-muted)]">{email}</span>
      </span>}
    </NavLink>
  );
}
