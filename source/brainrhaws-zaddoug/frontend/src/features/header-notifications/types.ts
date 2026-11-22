export interface HeaderInterviewReminder {
  id: string;
  sheetId: string;
  appointmentId: string;
  candidateName: string;
  startsAt: string;
  endsAt: string | null;
  location: string | null;
}

export type NotificationLoadState = 'loading' | 'ready' | 'error' | 'scope-required';

export const REMINDER_WINDOW_MS = 15 * 60 * 1000;
export const UPCOMING_WINDOW_MS = 24 * 60 * 60 * 1000;

export function isDueReminder(reminder: HeaderInterviewReminder, now: number): boolean {
  const startsAt = new Date(reminder.startsAt).getTime();
  return Number.isFinite(startsAt) && startsAt >= now && startsAt <= now + REMINDER_WINDOW_MS;
}
