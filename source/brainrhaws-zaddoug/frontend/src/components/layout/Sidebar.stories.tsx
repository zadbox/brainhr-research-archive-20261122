import { useEffect, useState } from 'react';
import { MemoryRouter } from 'react-router-dom';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { I18nProvider } from '../../i18n/I18nProvider';
import { useI18n } from '../../i18n/useI18n';
import { SidebarView } from './Sidebar';
import { ClientWorkspacePicker } from './ClientWorkspacePicker';
interface ReferenceProps {
  language: 'en' | 'fr';
  theme: 'light' | 'dark';
  collapsed: boolean;
  showSettings: boolean;
  email: string;
}

function Reference({ language, theme, collapsed, showSettings, email }: ReferenceProps) {
  const { setLanguage } = useI18n();
  const [isCollapsed, setCollapsed] = useState(collapsed);
  const [client, setClient] = useState('');
  useEffect(() => { setLanguage(language); }, [language, setLanguage]);
  useEffect(() => { setCollapsed(collapsed); }, [collapsed]);
  useEffect(() => {
    const previous = document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', theme === 'dark');
    return () => { document.documentElement.classList.toggle('dark', previous); };
  }, [theme]);
  return <main className="min-h-screen bg-background">
    <SidebarView collapsed={isCollapsed} showSettings={showSettings} email={email}
      onToggle={() => setCollapsed((value) => !value)} onNavigate={() => undefined}
      mobileControls={<div className="mb-4 lg:hidden"><ClientWorkspacePicker clients={[]} selectedTenantId={client} status="ready" onSelect={setClient} onRetry={() => undefined} /></div>} />
  </main>;
}

function SidebarReference(props: ReferenceProps) {
  return <I18nProvider><MemoryRouter initialEntries={['/projects']}><Reference {...props} /></MemoryRouter></I18nProvider>;
}

const meta = {
  title: 'BRAIN Operations/Sidebar',
  component: SidebarReference,
  parameters: { layout: 'fullscreen' },
  args: { language: 'en', theme: 'light', collapsed: false, showSettings: true, email: 'recruiter@example.test' },
} satisfies Meta<typeof SidebarReference>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Default: Story = {};
export const FrenchLongAccount: Story = { args: { language: 'fr', email: 'responsable.recrutement.international@example.test' } };
export const Dark: Story = { args: { language: 'fr', theme: 'dark' } };
export const Collapsed: Story = { args: { collapsed: true } };
export const DarkCollapsed: Story = { args: { language: 'fr', theme: 'dark', collapsed: true } };
export const LimitedAccess: Story = { args: { showSettings: false } };
export const Mobile: Story = { args: { language: 'fr' }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
