import { NavLink } from 'react-router-dom';
import {
  Building2,
  FolderOpen,
  FileText,
  Target,
  BarChart3,
  ChevronLeft,
  Home,
  ClipboardList,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { useAppStore } from '../../stores/useAppStore';
import { Button } from '../ui/button';

interface NavItem {
  to: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}

const navItems: NavItem[] = [
  { to: '/', icon: Home, label: 'Accueil' },
  { to: '/enterprises', icon: Building2, label: 'Entreprises' },
  { to: '/projects', icon: FolderOpen, label: 'Projets' },
  { to: '/cvs', icon: FileText, label: 'Base CVs' },
  { to: '/interviews', icon: ClipboardList, label: 'Fiches candidats' },
  { to: '/matching', icon: Target, label: 'Matching' },
  { to: '/results', icon: BarChart3, label: 'Résultats' },
];

export const Sidebar: React.FC = () => {
  const { sidebarCollapsed, toggleSidebar } = useAppStore();

  return (
    <>
      {/* Overlay for mobile */}
      {!sidebarCollapsed && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={toggleSidebar}
          aria-hidden="true"
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed left-0 top-0 z-50 h-full border-r bg-background transition-all duration-300',
          'lg:fixed lg:top-16 lg:h-[calc(100vh-4rem)]',
          sidebarCollapsed ? '-translate-x-full lg:translate-x-0 lg:w-16' : 'w-64'
        )}
      >
        <div className="flex h-full flex-col">
          {/* Toggle button (desktop only) */}
          <div className="hidden lg:flex justify-end p-2 border-b">
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleSidebar}
              aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <ChevronLeft
                className={cn(
                  'h-5 w-5 transition-transform',
                  sidebarCollapsed && 'rotate-180'
                )}
              />
            </Button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 overflow-y-auto p-4 space-y-2">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 rounded-lg px-3 py-2 transition-colors',
                    'hover:bg-accent hover:text-accent-foreground',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    isActive
                      ? 'bg-accent text-accent-foreground font-medium'
                      : 'text-muted-foreground',
                    sidebarCollapsed && 'justify-center'
                  )
                }
                title={sidebarCollapsed ? item.label : undefined}
              >
                <item.icon className={cn('h-5 w-5 flex-shrink-0')} />
                {!sidebarCollapsed && <span>{item.label}</span>}
              </NavLink>
            ))}
          </nav>
        </div>
      </aside>
    </>
  );
};
