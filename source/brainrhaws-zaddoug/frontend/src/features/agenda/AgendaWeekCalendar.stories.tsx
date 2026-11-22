import { useEffect } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { I18nProvider } from '../../i18n/I18nProvider';
import { useI18n } from '../../i18n/useI18n';
import { AgendaLegend, AgendaWeekCalendar } from './AgendaWeekCalendar';
import { addDays, startOfWeek, visibleWeekDays, type AgendaEvent } from './agendaWeek';

const weekStart = startOfWeek(new Date(2026, 7, 11));
const now = new Date(2026, 7, 11, 14, 30).getTime();

function event(id: string, candidateName: string, kind: AgendaEvent['kind'], day: number, hour: number, minute: number, minutes: number): AgendaEvent {
  const start = new Date(addDays(weekStart, day).getTime() + (hour * 60 + minute) * 60_000);
  return { id, candidateName, kind, start, end: new Date(start.getTime() + minutes * 60_000) };
}

const week: AgendaEvent[] = [
  event('past-ai', 'Camille Roy', 'ai', 0, 15, 0, 45),
  event('live-ai', 'Thomas Renaud', 'ai', 1, 14, 20, 45),
  event('recruiter', 'Nadia Berrada', 'recruiter', 2, 10, 30, 60),
  event('overlap', 'Lina Haddad', 'ai', 2, 10, 45, 45),
  event('short-ai', 'Julien Petit', 'ai', 3, 9, 0, 30),
  event('recruiter-2', 'Camille Roy', 'recruiter', 3, 11, 0, 60),
];

const longFrench: AgendaEvent[] = [
  event('long-1', 'Marie-Hélène de La Tour-d’Auvergne', 'recruiter', 1, 16, 0, 45),
  event('long-2', 'Anne-Charlotte de La Roche-Montferrand', 'ai', 4, 8, 0, 90),
  event('weekend', 'Jean-Baptiste Lefèvre-Delacroix', 'ai', 5, 10, 0, 45),
];

type Scenario = 'week' | 'longFrench' | 'emptyWeek';
const scenarios: Record<Scenario, AgendaEvent[]> = { week, longFrench, emptyWeek: [] };

interface ReferenceProps {
  language: 'en' | 'fr';
  theme: 'light' | 'dark';
  scenario: Scenario;
}

function Reference({ language, theme, scenario }: ReferenceProps) {
  const { setLanguage } = useI18n();
  useEffect(() => { setLanguage(language); }, [language, setLanguage]);
  useEffect(() => {
    const previous = document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', theme === 'dark');
    return () => { document.documentElement.classList.toggle('dark', previous); };
  }, [theme]);
  const events = scenarios[scenario];
  return (
    <div data-brain-ops="" className="flex min-h-screen flex-col gap-3 bg-[var(--brain-ops-canvas)] p-4 text-[var(--brain-ops-text)] sm:p-6">
      <AgendaWeekCalendar
        key={`${language}-${scenario}`}
        days={visibleWeekDays(weekStart, events, new Date(now))}
        events={events}
        now={now}
        onOpenEvent={() => undefined}
        canSchedule={(day) => addDays(day, 1).getTime() > now}
        onSchedule={() => undefined}
      />
      <AgendaLegend />
    </div>
  );
}

function AgendaWeekReference(props: ReferenceProps) {
  return <I18nProvider><Reference {...props} /></I18nProvider>;
}

const meta = {
  title: 'Features/Agenda week calendar',
  component: AgendaWeekReference,
  parameters: { layout: 'fullscreen' },
  args: { language: 'en', theme: 'light', scenario: 'week' },
  argTypes: {
    language: { control: 'inline-radio', options: ['en', 'fr'] },
    theme: { control: 'inline-radio', options: ['light', 'dark'] },
    scenario: { control: 'select', options: ['week', 'longFrench', 'emptyWeek'] },
  },
} satisfies Meta<typeof AgendaWeekReference>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Week: Story = {};
export const LongFrenchWithWeekend: Story = { args: { language: 'fr', scenario: 'longFrench' } };
export const EmptyWeek: Story = { args: { scenario: 'emptyWeek' } };
export const Dark: Story = { args: { language: 'fr', theme: 'dark' } };
export const Mobile: Story = { parameters: { viewport: { defaultViewport: 'mobile1' } } };
