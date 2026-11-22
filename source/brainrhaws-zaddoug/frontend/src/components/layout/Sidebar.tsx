import { useEffect, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  Building2, CalendarDays, ChartNoAxesColumn, ChevronLeft, ClipboardList,
  FolderClosed, LayoutDashboard, Settings2, UsersRound, X,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { useAppStore } from '../../stores/useAppStore';
import { useAuth } from '../../features/auth/context/AuthContext';
import { AccountLink } from '../../features/auth/components/AccountLink';
import { canViewSettings } from '../../features/auth/settingsAccess';
import { useMobileNavigation } from '../../hooks/useMobileNavigation';
import { Button } from '../ui/button';
import { useI18n } from '../../i18n/useI18n';
import type { TranslationKey } from '../../i18n/messages';
import { TenantScopeSelector } from './TenantScopeSelector';

interface NavItem {
  to: string;
  icon: React.ComponentType<{ className?: string }>;
  labelKey: TranslationKey;
}

const workspaceItems: NavItem[] = [
  { to: '/', icon: LayoutDashboard, labelKey: 'sidebar.nav.cockpit' },
  { to: '/enterprises', icon: Building2, labelKey: 'sidebar.nav.companies' },
  { to: '/projects', icon: FolderClosed, labelKey: 'sidebar.nav.projects' },
  { to: '/talent-pool', icon: UsersRound, labelKey: 'pool.nav' },
];
const operationsItems: NavItem[] = [
  { to: '/results', icon: ChartNoAxesColumn, labelKey: 'sidebar.nav.results' },
  { to: '/interviews', icon: ClipboardList, labelKey: 'sidebar.nav.interviews' },
];
const agendaItem: NavItem = { to: '/agenda', icon: CalendarDays, labelKey: 'sidebar.nav.agenda' };
const settingsItem: NavItem = { to: '/settings', icon: Settings2, labelKey: 'sidebar.nav.settings' };

function isNavItemActive(pathname: string, target: string) {
  if (target === '/') return pathname === '/';
  if (target === '/interviews') {
    return pathname === '/interviews' || pathname.startsWith('/interviews/') || pathname.endsWith('/interviews');
  }
  if (target === '/settings') {
    return pathname === '/settings' || pathname.startsWith('/settings/') || pathname === '/integrations' || pathname === '/admin/users';
  }
  return pathname === target || pathname.startsWith(`${target}/`);
}

interface SidebarViewProps {
  collapsed: boolean;
  showSettings: boolean;
  email?: string;
  mobileControls?: ReactNode;
  /** Upcoming-interview preview, shown above the Agenda link when the sidebar is expanded. */
  onToggle: () => void;
  onNavigate: () => void;
}

/** Presentation shared by the authenticated shell and its Storybook states. */
export function SidebarView({ collapsed, showSettings, email, mobileControls, onToggle, onNavigate }: SidebarViewProps) {
  const { t } = useI18n();
  const location = useLocation();

  const renderLink = (item: NavItem) => {
    const active = isNavItemActive(location.pathname, item.to);
    return (
      <Link key={item.to} to={item.to} onClick={onNavigate}
        aria-label={t(item.labelKey)} aria-current={active ? 'page' : undefined}
        title={collapsed ? t(item.labelKey) : undefined}
        className={cn(
          'brain-shell-touch-target flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
          'hover:bg-[var(--brain-sidebar-active)] hover:text-[var(--brain-ops-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          active ? 'bg-[var(--brain-sidebar-active)] text-[var(--brain-ops-text)]' : 'text-[var(--brain-ops-text-muted)]',
          collapsed && 'justify-center px-0',
        )}>
        <item.icon className="brain-shell-icon shrink-0" aria-hidden="true" />
        {!collapsed && <span>{t(item.labelKey)}</span>}
      </Link>
    );
  };

  return <>
    {!collapsed && <div className="fixed inset-0 z-40 bg-black/50 lg:hidden" onClick={onToggle} aria-hidden="true" />}
    <aside data-brain-ops="" data-brain-sidebar=""
      className={cn(
        'fixed left-0 top-0 z-50 h-dvh border-r border-[color:var(--brain-ops-border)] text-[var(--brain-ops-text)] transition-all duration-300 motion-reduce:transition-none',
        'lg:top-16 lg:h-[calc(100dvh-4rem)]',
        collapsed ? 'invisible -translate-x-full lg:visible lg:w-16 lg:translate-x-0' : 'w-64',
      )}>
      <div className="flex h-full flex-col">
        <div className="flex shrink-0 justify-end p-2">
          <Button variant="ghost" size="icon" onClick={onToggle}
            className="brain-shell-touch-target brain-shell-square-target hidden lg:inline-flex"
            aria-label={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}>
            <ChevronLeft className={cn('brain-shell-icon transition-transform motion-reduce:transition-none', collapsed && 'rotate-180')} />
          </Button>
          <Button variant="ghost" size="icon" onClick={onToggle}
            className="brain-shell-touch-target brain-shell-square-target lg:hidden" aria-label={t('common.close')}>
            <X className="brain-shell-icon" />
          </Button>
        </div>
        <nav data-tour="sidebar-navigation" className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
          {!collapsed && mobileControls}
          <div className="space-y-1">
            {!collapsed && <p className="px-3 pb-2 pt-1 font-mono text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">{t('sidebar.group.workspace')}</p>}
            {workspaceItems.map(renderLink)}
          </div>
          <div className="mt-6 space-y-1">
            {!collapsed && <p className="px-3 pb-2 font-mono text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">{t('sidebar.group.delivery')}</p>}
            {operationsItems.map(renderLink)}
          </div>
        </nav>
        <div className="shrink-0 space-y-1 border-t border-[color:var(--brain-ops-border)] p-2">
          {renderLink(agendaItem)}
          {showSettings && renderLink(settingsItem)}
          {email && <AccountLink email={email} collapsed={collapsed} onNavigate={onNavigate} />}
        </div>
      </div>
    </aside>
  </>;
}

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar, setSidebarCollapsed } = useAppStore();
  const { user } = useAuth();
  const mobileViewport = useMobileNavigation();
  const closeMobile = () => {
    if (mobileViewport) setSidebarCollapsed(true);
  };

  useEffect(() => {
    if (mobileViewport) setSidebarCollapsed(true);
  }, [mobileViewport, setSidebarCollapsed]);

  return <SidebarView collapsed={sidebarCollapsed} showSettings={canViewSettings(user)} email={user?.email}
    onToggle={toggleSidebar} onNavigate={closeMobile}
    mobileControls={mobileViewport && <div className="mb-4 flex items-center gap-2">
      <div className="min-w-0 flex-1"><TenantScopeSelector onNavigate={closeMobile} /></div>
    </div>} />;
}
