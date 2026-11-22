import { useEffect, useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { I18nProvider } from '../../i18n/I18nProvider';
import { useI18n } from '../../i18n/useI18n';
import { Button } from '../../components/ui/button';
import { GettingStarted } from './GettingStarted';
import { GuideOverlay } from './GuideOverlay';
import { getPageTour } from './tours';

interface GuideReferenceProps {
  language: 'en' | 'fr';
  theme: 'light' | 'dark';
  companyCount: number;
  projectCount: number;
  role: string;
  openHelp: boolean;
}

function GuideExample({ language, theme, companyCount, projectCount, role, openHelp }: GuideReferenceProps) {
  const { t, setLanguage } = useI18n();
  const [open, setOpen] = useState(openHelp);
  const [step, setStep] = useState(0);
  const tour = getPageTour('/projects', 'recruiter')!;

  useEffect(() => { setLanguage(language); }, [language, setLanguage]);
  useEffect(() => { setOpen(openHelp); }, [openHelp]);
  useEffect(() => {
    const wasDark = document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', theme === 'dark');
    return () => { document.documentElement.classList.toggle('dark', wasDark); };
  }, [theme]);

  return (
    <main data-brain-ops="" className="min-h-screen bg-[var(--brain-ops-canvas)] p-4 text-[var(--brain-ops-text)] sm:p-10">
      <div className="mx-auto max-w-6xl">
        <div data-tour="page-header" className="mb-7 flex items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.14em] text-[var(--brain-ops-text-muted)]">{t('home.operationsCockpit')}</p>
            <h1 className="mt-2 text-3xl font-semibold">{t('home.title')}</h1>
          </div>
          <Button type="button" variant="outline" onClick={() => setOpen((value) => !value)}>{t('guide.help')}</Button>
        </div>
        <GettingStarted
          companyCount={companyCount}
          projectCount={projectCount}
          role={role}
          onNavigate={() => undefined}
        />
        <section data-tour="projects-list" className="mt-8 min-h-40 border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-6">
          <h2 className="text-lg font-semibold">{t('projects.title')}</h2>
          <p className="mt-2 text-sm text-[var(--brain-ops-text-muted)]">{t('projects.description')}</p>
        </section>
        <nav data-tour="sidebar-navigation" aria-label="Example navigation" className="mt-8 flex gap-3 border-t border-[color:var(--brain-ops-border)] pt-5 text-sm text-[var(--brain-ops-text-muted)]">
          <span>{t('sidebar.nav.cockpit')}</span>
          <span>{t('sidebar.nav.projects')}</span>
        </nav>
      </div>
      {open ? (
        <GuideOverlay
          tour={tour}
          step={step}
          onStep={setStep}
          onClose={() => setOpen(false)}
          onFinish={() => setOpen(false)}
        />
      ) : null}
    </main>
  );
}

function GuideReference(props: GuideReferenceProps) {
  return <I18nProvider><GuideExample {...props} /></I18nProvider>;
}

const meta = {
  title: 'BRAIN Operations/Getting started and help',
  component: GuideReference,
  parameters: {
    layout: 'fullscreen',
    docs: { description: { component: 'A real-data onboarding path and an optional, non-modal page help panel.' } },
  },
  args: { language: 'en', theme: 'light', companyCount: 0, projectCount: 0, role: 'recruiter', openHelp: false },
} satisfies Meta<typeof GuideReference>;

export default meta;
type Story = StoryObj<typeof meta>;

export const EmptyWorkspace: Story = {};
export const ProjectReady: Story = { args: { companyCount: 2, projectCount: 1, role: 'client_admin' } };
export const FrenchLongCopy: Story = { args: { language: 'fr', companyCount: 1, projectCount: 0, role: 'recruiter' } };
export const ClientAdminCanStartProject: Story = { args: { companyCount: 1, projectCount: 0, role: 'client_admin' } };
export const PlatformProvisioning: Story = { args: { companyCount: 0, projectCount: 0, role: 'platform_admin' } };
export const HelpOpen: Story = { args: { openHelp: true, companyCount: 1, projectCount: 1 } };
export const Dark: Story = { args: { theme: 'dark', language: 'fr', companyCount: 1, projectCount: 1, openHelp: true } };
export const Mobile: Story = {
  args: { language: 'fr', companyCount: 1, projectCount: 0, openHelp: true },
  parameters: { viewport: { defaultViewport: 'mobile1' } },
};
