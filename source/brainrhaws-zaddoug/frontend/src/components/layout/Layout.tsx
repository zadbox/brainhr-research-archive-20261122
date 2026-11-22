import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { Toaster } from '../ui/toaster';
import { useAppStore } from '../../stores/useAppStore';
import { cn } from '../../lib/utils';
import { PageGuide } from '../../features/onboarding/PageGuide';

interface LayoutProps {
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children }) => {
  const sidebarCollapsed = useAppStore((state) => state.sidebarCollapsed);

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <div className="flex">
        <Sidebar />
        <main
          className={cn(
            'w-full flex-1 p-4 transition-all duration-300 sm:p-6',
            sidebarCollapsed ? 'lg:pl-20' : 'lg:pl-[272px]'
          )}
        >
          <PageGuide />
          {children}
        </main>
      </div>
      <Toaster />
    </div>
  );
};
