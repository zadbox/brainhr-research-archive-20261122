import { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { MemoryRouter } from 'react-router-dom';
import { I18nContext } from '../../i18n/I18nContext';
import { messages, type Language } from '../../i18n/messages';
import { EnterpriseDirectory } from './EnterpriseDirectory';

function DirectoryExample({ language = 'fr', dark = false, canDelete = true }: { language?: Language; dark?: boolean; canDelete?: boolean }) {
  const [action, setAction] = useState('');
  return <MemoryRouter><I18nContext.Provider value={{ language, setLanguage: () => {}, t: (key) => messages[language][key] }}>
    <main data-brain-ops="" className={`${dark ? 'dark' : ''} bg-[var(--brain-ops-canvas)] p-4 text-[var(--brain-ops-text)]`}>
      <EnterpriseDirectory canDelete={canDelete} onEdit={(enterprise) => setAction(`Edit: ${enterprise.nom}`)} onDelete={(id) => setAction(`Delete: ${id}`)} enterprises={[
        { id: 'silent', nom: 'Silent Believers', tenant_name: 'SILENT BELIEVERS', secteur: 'Industry', contacts: [], projects_count: 1, created_at: '2026-08-03' },
        { id: 'bdf', nom: 'BDF', secteur: 'Services', contacts: [], projects_count: 3, created_at: '2026-04-30' },
        { id: 'long', nom: 'Entreprise de démonstration avec un nom particulièrement long', tenant_name: 'Cabinet de recrutement Méditerranée', secteur: 'Conseil', contacts: [], projects_count: 0, created_at: '2026-09-05' },
      ]} />
      {action && <output className="mt-4 block">{action}</output>}
    </main>
  </I18nContext.Provider></MemoryRouter>;
}
const meta = { title: 'Companies/Directory', component: DirectoryExample, parameters: { layout: 'fullscreen' } } satisfies Meta<typeof DirectoryExample>;
export default meta;
type Story = StoryObj<typeof meta>;
export const French: Story = {};
export const EnglishDark: Story = { args: { language: 'en', dark: true } };
export const Member: Story = { args: { canDelete: false } };
export const Mobile: Story = { parameters: { viewport: { defaultViewport: 'mobile1' } } };
