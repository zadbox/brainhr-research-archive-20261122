import type { InterviewSheet } from '../../api/interviewSheet';

/** AI interviews run with the BrainRH agent; recruiter interviews are led by a person. */
export type AgendaEventKind = 'ai' | 'recruiter';
export type AgendaEventTiming = 'past' | 'live' | 'upcoming';

export interface AgendaEvent {
  id: string;
  candidateName: string;
  kind: AgendaEventKind;
  start: Date;
  end: Date;
}

export interface PositionedAgendaEvent {
  event: AgendaEvent;
  column: number;
  columns: number;
}

/** Matches the scheduler default when a sheet has no explicit end time. */
export const DEFAULT_INTERVIEW_MINUTES = 45;
export const DEFAULT_FIRST_HOUR = 9;
export const DEFAULT_LAST_HOUR = 18;
const WORK_DAYS = 5;

export function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

export function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

/** Weeks start on Monday, like the reference calendar. */
export function startOfWeek(date: Date): Date {
  return addDays(startOfDay(date), -((date.getDay() + 6) % 7));
}

export function dayKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function isSameDay(left: Date, right: Date): boolean {
  return dayKey(left) === dayKey(right);
}

/** Un entretien recruteur peut aussi avoir un rendez-vous : le mode enregistré prime. */
export function interviewKind(sheet: InterviewSheet): AgendaEventKind {
  const scheduling = sheet.data.scheduling;
  if (scheduling?.interview_mode === 'human') return 'recruiter';
  if (scheduling?.interview_mode === 'ai') return 'ai';
  return scheduling?.appointment_id ? 'ai' : 'recruiter';
}

export function toAgendaEvent(sheet: InterviewSheet, candidateName: string): AgendaEvent | null {
  if (!sheet.scheduled_at) return null;
  const start = new Date(sheet.scheduled_at);
  if (!Number.isFinite(start.getTime())) return null;
  const scheduling = sheet.data.scheduling;
  const explicitEnd = scheduling?.end_at ? new Date(scheduling.end_at) : null;
  const end = explicitEnd && explicitEnd.getTime() > start.getTime()
    ? explicitEnd
    : new Date(start.getTime() + DEFAULT_INTERVIEW_MINUTES * 60_000);
  return {
    id: sheet.id,
    candidateName,
    kind: interviewKind(sheet),
    start,
    end,
  };
}

export function eventTiming(event: AgendaEvent, now: number): AgendaEventTiming {
  if (event.end.getTime() <= now) return 'past';
  if (event.start.getTime() <= now) return 'live';
  return 'upcoming';
}

/**
 * Monday to Friday, extended to the weekend only when the week has a weekend
 * interview or when today falls on it, so scheduling stays reachable.
 */
export function visibleWeekDays(weekStart: Date, events: readonly AgendaEvent[], today: Date): Date[] {
  const week = Array.from({ length: 7 }, (_, index) => addDays(weekStart, index));
  const lastWeekendIndex = week.reduce((last, day, index) => {
    if (index < WORK_DAYS) return last;
    const used = isSameDay(day, today) || events.some((event) => isSameDay(event.start, day));
    return used ? index : last;
  }, WORK_DAYS - 1);
  return week.slice(0, lastWeekendIndex + 1);
}

/** Keeps the working-day frame and widens it only as far as the displayed interviews require. */
export function visibleHourRange(events: readonly AgendaEvent[], days: readonly Date[]): { first: number; last: number } {
  let first = DEFAULT_FIRST_HOUR;
  let last = DEFAULT_LAST_HOUR;
  for (const event of events) {
    const day = days.find((candidate) => isSameDay(candidate, event.start));
    if (!day) continue;
    const startHour = event.start.getHours() + event.start.getMinutes() / 60;
    const endHour = isSameDay(event.end, day) ? event.end.getHours() + event.end.getMinutes() / 60 : 24;
    first = Math.min(first, Math.floor(startHour));
    last = Math.max(last, Math.ceil(endHour));
  }
  return { first: Math.max(0, first), last: Math.min(24, Math.max(last, first + 1)) };
}

/** Places overlapping interviews side by side, like a standard week calendar. */
export function layoutDayEvents(events: readonly AgendaEvent[]): PositionedAgendaEvent[] {
  const sorted = [...events].sort((left, right) => (
    left.start.getTime() - right.start.getTime() || right.end.getTime() - left.end.getTime()
  ));
  const positioned: PositionedAgendaEvent[] = [];
  let cluster: PositionedAgendaEvent[] = [];
  let columnEnds: number[] = [];
  let clusterEnd = -Infinity;

  const closeCluster = () => {
    for (const item of cluster) item.columns = columnEnds.length;
    cluster = [];
    columnEnds = [];
  };

  for (const event of sorted) {
    if (event.start.getTime() >= clusterEnd) closeCluster();
    let column = columnEnds.findIndex((end) => end <= event.start.getTime());
    if (column === -1) {
      column = columnEnds.length;
      columnEnds.push(event.end.getTime());
    } else {
      columnEnds[column] = event.end.getTime();
    }
    const item = { event, column, columns: 1 };
    cluster.push(item);
    positioned.push(item);
    clusterEnd = Math.max(clusterEnd, event.end.getTime());
  }
  closeCluster();
  return positioned;
}
