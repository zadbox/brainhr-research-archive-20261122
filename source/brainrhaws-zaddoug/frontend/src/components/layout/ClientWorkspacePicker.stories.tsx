import { useEffect, useState } from 'react';
import { MemoryRouter } from 'react-router-dom';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { I18nProvider } from '../../i18n/I18nProvider';
import { useI18n } from '../../i18n/useI18n';
import { ClientWorkspacePicker } from './ClientWorkspacePicker';

interface ReferenceProps {
  language: 'en' | 'fr';
  theme: 'light' | 'dark';
  collapsed: boolean;
  status: 'ready' | 'loading' | 'error';
  empty: boolean;
  compact: boolean;
}

const clients = [
  { id: 'alpha', name: 'Cabinet Alpha — recrutement international et accompagnement des entreprises' },
  { id: 'beta', name: 'Cabinet Beta' },
];

function Reference({ language, theme, collapsed, status, empty, compact }: ReferenceProps) {
  const { setLanguage, t } = useI18n();
  const [selectedTenantId, setSelectedTenantId] = useState(empty ? '' : 'alpha');
  const [retried, setRetried] = useState(false);
  useEffect(() => { setLanguage(language); }, [language, setLanguage]);
  useEffect(() => {
    const previous = document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', theme === 'dark');
    return () => { document.documentElement.classList.toggle('dark', previous); };
  }, [theme]);
  const currentStatus = retried ? 'ready' : status;
  return <main data-brain-ops="" className="min-h-screen bg-[var(--brain-ops-canvas)] p-5 text-[var(--brain-ops-text)]">
    <aside data-brain-sidebar="" className={`rounded-md p-3 ${collapsed ? 'w-16' : 'w-64'}`}>
      {!collapsed && <p className="px-4 py-2 text-sm font-medium">{t('sidebar.nav.companies')}</p>}
      <ClientWorkspacePicker clients={empty || currentStatus !== 'ready' ? [] : clients} selectedTenantId={selectedTenantId}
        status={currentStatus} collapsed={collapsed} compact={compact} onSelect={setSelectedTenantId} onRetry={() => setRetried(true)} />
    </aside>
  </main>;
}

function WorkspaceReference(props: ReferenceProps) {
  return <I18nProvider><MemoryRouter><Reference {...props} /></MemoryRouter></I18nProvider>;
}

const meta = {
  title: 'BRAIN Operations/Client workspace',
  component: WorkspaceReference,
  parameters: { layout: 'fullscreen' },
  args: { language: 'en', theme: 'light', collapsed: false, status: 'ready', empty: false, compact: false },
} satisfies Meta<typeof WorkspaceReference>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Default: Story = {};
export const FrenchLongName: Story = { args: { language: 'fr' } };
export const Dark: Story = { args: { language: 'fr', theme: 'dark' } };
export const Collapsed: Story = { args: { collapsed: true } };
export const Loading: Story = { args: { language: 'fr', status: 'loading' } };
export const CatalogueError: Story = { args: { language: 'fr', status: 'error' } };
export const Empty: Story = { args: { empty: true } };
export const Mobile: Story = { args: { language: 'fr' }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const CompactHeader: Story = { args: { compact: true } };
