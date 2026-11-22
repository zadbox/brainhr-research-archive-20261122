import type { Meta, StoryObj } from '@storybook/react-vite';
import { MemoryRouter } from 'react-router-dom';
import { GlobalSearchView } from './GlobalSearchView';
import { headerSearchMessages, type HeaderSearchKey } from './searchMessages';

const results = [
  { kind: 'candidate' as const, id: 'cv-1', primary: 'Élodie Martin', secondary: 'Senior Data Scientist · Data Platform · Atlas Conseil', href: '#' },
  { kind: 'project' as const, id: 'project-1', primary: 'Senior Data Scientist', secondary: 'Atlas Conseil', href: '#' },
  { kind: 'company' as const, id: 'company-1', primary: 'Atlas Conseil', secondary: 'Technologies', href: '#' },
];

function Reference({ language = 'fr', theme = 'light', mobile = false }: {
  language?: 'en' | 'fr';
  theme?: 'light' | 'dark';
  mobile?: boolean;
}) {
  const messages = headerSearchMessages[language];
  return (
    <MemoryRouter>
      <main data-brain-ops="" className={`${theme === 'dark' ? 'dark' : ''} min-h-screen bg-[var(--brain-ops-canvas)] p-4 text-[var(--brain-ops-text)]`}>
        <div className={`mx-auto rounded-[var(--brain-ops-radius-panel)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4 ${mobile ? 'max-w-sm' : 'max-w-2xl'}`}>
          <GlobalSearchView query="data" status="ready" results={results} total={24} partial onQueryChange={() => undefined} onRetry={() => undefined} onNavigate={() => undefined} text={(key: HeaderSearchKey) => messages[key]} />
        </div>
      </main>
    </MemoryRouter>
  );
}

const meta = {
  title: 'BRAIN Operations/Header/GlobalSearch',
  component: Reference,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof Reference>;
export default meta;
type Story = StoryObj<typeof meta>;

export const FrenchResults: Story = {};
export const EnglishResults: Story = { args: { language: 'en' } };
export const DarkTheme: Story = { args: { theme: 'dark' } };
export const Mobile: Story = { args: { mobile: true }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const Empty: Story = {
  render: () => (
    <MemoryRouter>
      <main data-brain-ops="" className="min-h-screen bg-[var(--brain-ops-canvas)] p-4 text-[var(--brain-ops-text)]">
        <div className="mx-auto max-w-2xl rounded-[var(--brain-ops-radius-panel)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4">
          <GlobalSearchView query="introuvable" status="ready" results={[]} total={0} partial={false} onQueryChange={() => undefined} onRetry={() => undefined} onNavigate={() => undefined} text={(key) => headerSearchMessages.fr[key]} />
        </div>
      </main>
    </MemoryRouter>
  ),
};
export const ErrorRecovery: Story = {
  render: () => (
    <MemoryRouter>
      <main data-brain-ops="" className="min-h-screen bg-[var(--brain-ops-canvas)] p-4 text-[var(--brain-ops-text)]">
        <div className="mx-auto max-w-2xl rounded-[var(--brain-ops-radius-panel)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4">
          <GlobalSearchView query="data" status="error" results={[]} total={0} partial={false} onQueryChange={() => undefined} onRetry={() => undefined} onNavigate={() => undefined} text={(key) => headerSearchMessages.en[key]} />
        </div>
      </main>
    </MemoryRouter>
  ),
};
