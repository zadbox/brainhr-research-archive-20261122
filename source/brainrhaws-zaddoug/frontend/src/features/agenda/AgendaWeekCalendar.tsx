import { useMemo, useState, type CSSProperties } from 'react';
import { Plus } from 'lucide-react';
import { cn } from '../../lib/utils';
import { formatMessage } from '../../i18n/formatMessage';
import { useI18n } from '../../i18n/useI18n';
import type { TranslationKey } from '../../i18n/messages';
import {
  dayKey,
  eventTiming,
  isSameDay,
  layoutDayEvents,
  visibleHourRange,
  type AgendaEvent,
  type AgendaEventKind,
  type AgendaEventTiming,
} from './agendaWeek';

const HOUR_HEIGHT = 72;
const COMPACT_EVENT_HEIGHT = 40;

const agendaKindLabelKeys: Record<AgendaEventKind, TranslationKey> = {
  ai: 'agenda.kind.ai',
  recruiter: 'agenda.kind.recruiter',
};

/** Each kind exposes its hue through one variable so every timing state stays theme-aware. */
const agendaKindClasses: Record<AgendaEventKind, string> = {
  ai: '[--agenda-kind:var(--brain-ops-accent)]',
  recruiter: '[--agenda-kind:var(--brain-ops-success)]',
};

const agendaTimingClasses: Record<AgendaEventTiming, string> = {
  upcoming: cn(
    'border-[color:color-mix(in_srgb,var(--agenda-kind)_45%,var(--brain-ops-border))]',
    'bg-[color-mix(in_srgb,var(--agenda-kind)_10%,var(--brain-ops-surface))]',
    'text-[color:color-mix(in_srgb,var(--agenda-kind)_55%,var(--brain-ops-text))]',
    'hover:bg-[color-mix(in_srgb,var(--agenda-kind)_16%,var(--brain-ops-surface))]',
  ),
  past: cn(
    'border-[color:color-mix(in_srgb,var(--agenda-kind)_22%,var(--brain-ops-border))]',
    'bg-[color-mix(in_srgb,var(--agenda-kind)_4%,var(--brain-ops-surface))]',
    'text-[color:var(--brain-ops-text-muted)]',
    'hover:bg-[color-mix(in_srgb,var(--agenda-kind)_9%,var(--brain-ops-surface))]',
  ),
  live: cn(
    'border-transparent',
    'bg-[color-mix(in_srgb,var(--agenda-kind)_82%,var(--brain-ops-text))]',
    'text-[color:var(--brain-ops-surface)]',
    'shadow-[0_10px_20px_-12px_var(--agenda-kind)]',
  ),
};

export interface AgendaWeekCalendarProps {
  days: readonly Date[];
  events: readonly AgendaEvent[];
  now: number;
  onOpenEvent: (event: AgendaEvent) => void;
  canSchedule?: (day: Date) => boolean;
  onSchedule?: (day: Date) => void;
}

/**
 * Week time grid: one column per displayed day on desktop, a single selected
 * day on narrow screens. Interviews open their sheet; the day action opens scheduling.
 */
export function AgendaWeekCalendar({ days, events, now, onOpenEvent, canSchedule, onSchedule }: AgendaWeekCalendarProps) {
  const { language, t } = useI18n();
  const today = new Date(now);
  const [selectedKey, setSelectedKey] = useState(() => dayKey(days.find((day) => isSameDay(day, today)) ?? days[0]));
  const selectedDayKey = days.some((day) => dayKey(day) === selectedKey) ? selectedKey : dayKey(days[0]);
  const hours = visibleHourRange(events, days);
  const bodyHeight = (hours.last - hours.first) * HOUR_HEIGHT;

  const formatters = useMemo(() => ({
    time: new Intl.DateTimeFormat(language, { hour: '2-digit', minute: '2-digit', hour12: false }),
    weekday: new Intl.DateTimeFormat(language, { weekday: 'short' }),
    fullDate: new Intl.DateTimeFormat(language, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }),
  }), [language]);

  const eventsByDay = useMemo(() => {
    const grouped = new Map<string, AgendaEvent[]>();
    for (const event of events) {
      const key = dayKey(event.start);
      grouped.set(key, [...(grouped.get(key) ?? []), event]);
    }
    return grouped;
  }, [events]);

  const hourLabel = (hour: number) => formatters.time.format(new Date(2000, 0, 1, hour));
  const offsetFor = (date: Date, day: Date) => {
    const hoursFromMidnight = isSameDay(date, day)
      ? date.getHours() + date.getMinutes() / 60
      : 24;
    return (hoursFromMidnight - hours.first) * HOUR_HEIGHT;
  };

  const gridStyle = { '--agenda-days': days.length } as CSSProperties;
  const gridColumns = 'grid grid-cols-[3.5rem_minmax(0,1fr)] md:grid-cols-[3.5rem_repeat(var(--agenda-days),minmax(0,1fr))]';

  return (
    <div
      data-agenda-week=""
      style={gridStyle}
      className="min-w-0 overflow-hidden rounded-[var(--brain-ops-radius-panel)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]"
    >
      <div
        role="group"
        aria-label={t('agenda.dayPicker')}
        className="flex gap-1 overflow-x-auto border-b border-[color:var(--brain-ops-border)] p-2 md:hidden"
      >
        {days.map((day) => {
          const key = dayKey(day);
          const isToday = isSameDay(day, today);
          return (
            <button
              key={key}
              type="button"
              aria-pressed={key === selectedDayKey}
              aria-label={formatters.fullDate.format(day)}
              onClick={() => setSelectedKey(key)}
              className={cn(
                'flex min-h-11 min-w-11 flex-1 flex-col items-center justify-center rounded-md px-1 text-xs capitalize transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)]',
                key === selectedDayKey
                  ? 'bg-[var(--brain-ops-surface-muted)] font-semibold text-[var(--brain-ops-text)]'
                  : 'text-[var(--brain-ops-text-muted)] hover:bg-[var(--brain-ops-surface-muted)]',
                isToday && 'text-[var(--brain-ops-accent)]',
              )}
            >
              <span>{formatters.weekday.format(day)}</span>
              <span className="text-sm tabular-nums">{day.getDate()}</span>
            </button>
          );
        })}
      </div>

      <div className={cn(gridColumns, 'border-b border-[color:var(--brain-ops-border)]')}>
        <div aria-hidden="true" />
        {days.map((day) => {
          const key = dayKey(day);
          const isToday = isSameDay(day, today);
          const dateLabel = formatters.fullDate.format(day);
          const schedulable = onSchedule && (canSchedule?.(day) ?? true);
          return (
            <div
              key={key}
              className={cn(
                'group min-w-0 items-center justify-between gap-2 border-l border-[color:var(--brain-ops-border)] py-2 pl-3 pr-1.5',
                key === selectedDayKey ? 'flex' : 'hidden md:flex',
              )}
            >
              <span
                className={cn(
                  'truncate text-sm capitalize',
                  isToday ? 'font-semibold text-[var(--brain-ops-accent)]' : 'font-medium text-[var(--brain-ops-text-muted)]',
                )}
              >
                <span className="sr-only">{dateLabel}</span>
                <span aria-hidden="true">{formatters.weekday.format(day)} {day.getDate()}</span>
              </span>
              {schedulable ? (
                <button
                  type="button"
                  onClick={() => onSchedule(day)}
                  data-calendar-date={key}
                  aria-label={formatMessage(t('agenda.quickSchedule.open'), { date: dateLabel })}
                  title={formatMessage(t('agenda.quickSchedule.open'), { date: dateLabel })}
                  className={cn(
                    'inline-flex size-9 shrink-0 items-center justify-center rounded-md text-[var(--brain-ops-text-muted)] transition-[color,background-color,opacity] md:size-7',
                    'hover:bg-[var(--brain-ops-surface-muted)] hover:text-[var(--brain-ops-text)]',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)]',
                    '[@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 [@media(hover:hover)]:focus-visible:opacity-100',
                  )}
                >
                  <Plus aria-hidden="true" className="size-4" />
                </button>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className={gridColumns}>
        <div aria-hidden="true" className="relative" style={{ height: bodyHeight }}>
          {Array.from({ length: hours.last - hours.first }, (_, index) => (
            <span
              key={index}
              className="absolute right-2 text-xs tabular-nums text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]"
              style={{ top: index * HOUR_HEIGHT + 6 }}
            >
              {hourLabel(hours.first + index)}
            </span>
          ))}
        </div>

        {days.map((day) => {
          const key = dayKey(day);
          const isToday = isSameDay(day, today);
          const nowOffset = isToday ? offsetFor(today, day) : -1;
          return (
            <div
              key={key}
              role="group"
              aria-label={formatters.fullDate.format(day)}
              className={cn(
                'relative min-w-0 border-l border-[color:var(--brain-ops-border)]',
                'bg-[linear-gradient(to_bottom,var(--brain-ops-border)_1px,transparent_1px)]',
                isToday && 'bg-[color-mix(in_srgb,var(--brain-ops-accent)_3%,var(--brain-ops-surface))]',
                key === selectedDayKey ? 'block' : 'hidden md:block',
              )}
              style={{ height: bodyHeight, backgroundSize: `100% ${HOUR_HEIGHT}px` }}
            >
              {layoutDayEvents(eventsByDay.get(key) ?? []).map(({ event, column, columns }) => {
                const top = Math.max(0, offsetFor(event.start, day));
                const height = Math.max(offsetFor(event.end, day) - top, 28);
                const timing = eventTiming(event, now);
                const kind = t(agendaKindLabelKeys[event.kind]);
                const start = formatters.time.format(event.start);
                const end = formatters.time.format(event.end);
                const accessibleName = formatMessage(t('agenda.event.aria'), {
                  kind,
                  candidate: event.candidateName,
                  date: formatters.fullDate.format(event.start),
                  start,
                  end,
                });
                const compact = height < COMPACT_EVENT_HEIGHT;
                return (
                  <button
                    key={event.id}
                    type="button"
                    onClick={() => onOpenEvent(event)}
                    aria-label={timing === 'live' ? `${accessibleName} · ${t('agenda.event.live')}` : accessibleName}
                    title={`${start} – ${end} · ${kind} · ${event.candidateName}`}
                    data-agenda-timing={timing}
                    className={cn(
                      'absolute z-[1] min-h-11 overflow-hidden rounded-md border px-2 text-left text-[0.8125rem] leading-4 transition-colors md:min-h-0',
                      'hover:z-[3] focus-visible:z-[3] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)] focus-visible:ring-offset-1',
                      compact ? 'flex items-center gap-1.5 py-0.5' : 'flex flex-col gap-0.5 py-1.5',
                      agendaKindClasses[event.kind],
                      agendaTimingClasses[timing],
                      timing === 'live' && 'z-[2]',
                    )}
                    style={{
                      top: top + 2,
                      height: height - 4,
                      left: `calc(${(column / columns) * 100}% + 4px)`,
                      width: `calc(${100 / columns}% - 8px)`,
                    }}
                  >
                    <span className="shrink-0 font-semibold tabular-nums">{start}</span>
                    <span className="min-w-0 truncate">{kind} · {event.candidateName}</span>
                  </button>
                );
              })}
              {nowOffset >= 0 && nowOffset <= bodyHeight ? (
                <div aria-hidden="true" data-agenda-now="" className="pointer-events-none absolute inset-x-0 z-[4]" style={{ top: nowOffset }}>
                  <span className="absolute -left-1 -top-1 size-2 rounded-full bg-[var(--brain-ops-danger)]" />
                  <span className="block h-0.5 -translate-y-1/2 bg-[var(--brain-ops-danger)]" />
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Explains the colours with text, so the calendar never relies on hue alone. */
export function AgendaLegend({ className }: { className?: string }) {
  const { t } = useI18n();
  const items: Array<{ key: string; label: string; swatch: string }> = [
    { key: 'ai', label: t('agenda.kind.ai'), swatch: cn(agendaKindClasses.ai, agendaTimingClasses.upcoming) },
    { key: 'recruiter', label: t('agenda.kind.recruiter'), swatch: cn(agendaKindClasses.recruiter, agendaTimingClasses.upcoming) },
    { key: 'past', label: t('agenda.past'), swatch: cn(agendaKindClasses.ai, agendaTimingClasses.past) },
  ];
  return (
    <ul aria-label={t('agenda.legend')} className={cn('flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-[var(--brain-ops-text-muted)]', className)}>
      {items.map((item) => (
        <li key={item.key} className="flex items-center gap-2">
          <span aria-hidden="true" className={cn('size-3 rounded-[3px] border', item.swatch)} />
          {item.label}
        </li>
      ))}
      <li className="flex items-center gap-2">
        <span aria-hidden="true" className="relative h-0.5 w-4 bg-[var(--brain-ops-danger)] before:absolute before:-left-0.5 before:-top-[3px] before:size-2 before:rounded-full before:bg-[var(--brain-ops-danger)]" />
        {t('agenda.now')}
      </li>
    </ul>
  );
}
