import { useEffect } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { MemoryRouter } from 'react-router-dom';
import { I18nProvider } from '../../i18n/I18nProvider';
import { useI18n } from '../../i18n/useI18n';
import { UpcomingInterviews } from './UpcomingInterviews';
import type { CockpitInterview } from '../header-notifications/api';

const now = new Date(2026, 8, 30, 10).getTime();
const interviews: CockpitInterview[] = Array.from({ length: 12 }, (_, index) => ({
  id: `appointment-${index}`, appointmentId: `appointment-${index}`, sheetId: `sheet-${index}`,
  candidateName: ['Thomas Renaud', 'Nadia Berrada', 'Anne-Charlotte de La Roche-Montferrand'][index % 3],
  projectId: 'project', startsAt: new Date(now + index * 30 * 60_000).toISOString(), endsAt: null,
  status: index === 0 ? 'in_progress' : 'scheduled', location: null,
}));
function Preview({ language, theme, empty, error, loading }: { language: 'fr' | 'en'; theme: string; empty: boolean; error: boolean; loading: boolean }) {
  const { setLanguage } = useI18n();
  useEffect(() => { setLanguage(language); }, [language, setLanguage]);
  return <div data-brain-ops="" className={`${theme === 'dark' ? 'dark' : ''} min-h-screen bg-background p-4 text-foreground`}><div className="mx-auto max-w-lg"><UpcomingInterviews interviews={empty || loading ? [] : interviews} projectNames={new Map([['project', 'Senior data scientist · Norvia']])} error={error} loading={loading} now={now} onRetry={() => undefined} /></div></div>;
}
function Reference(props: Parameters<typeof Preview>[0]) { return <I18nProvider><MemoryRouter><Preview {...props} /></MemoryRouter></I18nProvider>; }
const meta = { title: 'BRAIN Operations/Cockpit interviews', component: Reference, parameters: { layout: 'fullscreen' }, args: { language: 'en', theme: 'light', empty: false, error: false, loading: false } } satisfies Meta<typeof Reference>;
export default meta;
type Story = StoryObj<typeof meta>;
export const BusyDay: Story = {};
export const French: Story = { args: { language: 'fr' } };
export const Dark: Story = { args: { language: 'fr', theme: 'dark' } };
export const Empty: Story = { args: { empty: true } };
export const Error: Story = { args: { error: true, empty: true } };
export const Loading: Story = { args: { loading: true } };
