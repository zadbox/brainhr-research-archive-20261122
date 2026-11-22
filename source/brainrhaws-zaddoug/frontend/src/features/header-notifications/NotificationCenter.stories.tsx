import type { Meta, StoryObj } from '@storybook/react-vite';
import { I18nProvider } from '../../i18n/I18nProvider';
import { OperationsDialog, OperationsDialogContent } from '../../components/operations/OperationsDialogContent';
import { NotificationPanel, type NotificationPanelProps } from './NotificationCenter';
import type { HeaderInterviewReminder } from './types';

const now = new Date('2026-09-29T10:00:00Z').getTime();
const dueReminder: HeaderInterviewReminder = {
  id: 'appointment-due:2026-09-29T10:10:00Z',
  appointmentId: 'appointment-due',
  sheetId: 'sheet-due',
  candidateName: 'Samira El Mansouri',
  startsAt: '2026-09-29T10:10:00Z',
  endsAt: '2026-09-29T10:55:00Z',
  location: 'Salle Casablanca',
};

const upcomingReminder: HeaderInterviewReminder = {
  ...dueReminder,
  id: 'appointment-upcoming:2026-09-29T16:30:00Z',
  appointmentId: 'appointment-upcoming',
  sheetId: 'sheet-upcoming',
  candidateName: 'Alex Morgan',
  startsAt: '2026-09-29T16:30:00Z',
  endsAt: '2026-09-29T17:15:00Z',
  location: 'Remote',
};

const noop = () => undefined;
const baseArgs: NotificationPanelProps = {
  state: 'ready', reminders: [dueReminder, upcomingReminder], readIds: new Set(), now, language: 'en',
  browserAlertsEnabled: false, onRetry: noop, onEnableBrowserAlerts: noop, onOpenReminder: noop,
  onMarkAllRead: noop, onOpenAgenda: noop,
};

const meta = {
  title: 'Features/Header notifications',
  component: NotificationPanel,
  decorators: [
    (Story, context) => (
      <I18nProvider>
        <div className="min-h-screen bg-background p-4">
          <OperationsDialog open onOpenChange={noop}>
            <OperationsDialogContent className={`${context.globals.theme === 'dark' ? 'dark' : ''} max-w-xl gap-4 p-4 text-foreground sm:p-6`}><Story /></OperationsDialogContent>
          </OperationsDialog>
        </div>
      </I18nProvider>
    ),
  ],
  args: baseArgs,
  parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof NotificationPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Due: Story = {};
export const UpcomingUnread: Story = { args: { reminders: [upcomingReminder] } };
export const Read: Story = { args: { readIds: new Set([dueReminder.id, upcomingReminder.id]) } };
export const Empty: Story = { args: { reminders: [] } };
export const Error: Story = { args: { state: 'error', reminders: [] } };
export const LongFrench: Story = {
  args: {
    language: 'fr',
    reminders: [{ ...dueReminder, candidateName: 'Anne-Charlotte de La Roche-Montferrand', location: 'Salle de visioconférence internationale — bâtiment administratif principal' }],
  },
};
export const Dark: Story = { globals: { theme: 'dark' } };
export const Mobile: Story = { parameters: { viewport: { defaultViewport: 'mobile1' } } };
