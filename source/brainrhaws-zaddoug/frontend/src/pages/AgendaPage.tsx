import { watchInterviewSchedule } from '../lib/interviewScheduleUpdates';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, Calendar, CalendarDays, ChevronLeft, ChevronRight, FileText } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import {
  OperationalList,
  OperationalListItem,
  OperationsDialog,
  OperationsDialogClose,
  OperationsDialogContent,
  OperationsDialogDescription,
  OperationsDialogFooter,
  OperationsDialogHeader,
  OperationsDialogTitle,
  OperationsErrorBanner,
  PageFrame,
  PageBackButton,
  PageHeader,
  Section,
  SystemState,
} from '../components/operations';
import { SchedulerButton } from '../components/interview/scheduler/SchedulerButton';
import { InterviewSchedulerModal } from '../components/interview/scheduler/InterviewSchedulerModal';
import {
  interviewAppointmentsApi,
  type ScheduleInterviewRequest,
  type ScheduledInterviewResult,
} from '../api/interviewAppointments';
import { interviewSheetApi, type InterviewSheet } from '../api/interviewSheet';
import type { APIError } from '../api/types';
import { cn } from '../lib/utils';
import { formatMessage } from '../i18n/formatMessage';
import { useI18n } from '../i18n/useI18n';
import { candidateLabel } from '../lib/candidateLabel';
import { loadProjectInterviewSheets } from '../lib/interviewScope';
import { projectsApi } from '../api/projects';
import { useAuth } from '../features/auth/context/AuthContext';
import { useAppStore } from '../stores/useAppStore';
import { AgendaLegend, AgendaWeekCalendar } from '../features/agenda/AgendaWeekCalendar';
import {
  addDays,
  dayKey,
  startOfWeek,
  interviewKind,
  toAgendaEvent,
  visibleWeekDays,
  type AgendaEvent,
} from '../features/agenda/agendaWeek';

type ViewMode = 'list' | 'calendar';
type SheetsFetchOptions = {
  reuseInFlightRequest?: boolean;
  showLoadingState?: boolean;
};

const NOW_REFRESH_MS = 60_000;

const getCandidateEmail = (data: InterviewSheet['data']) => {
  return typeof data.identite?.email === 'string' && data.identite.email.trim().length > 0
    ? data.identite.email
    : null;
};

export const AgendaPage: React.FC = () => {
  const navigate = useNavigate();
  const { language, t } = useI18n();
  const { user } = useAuth();
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);
  const scopeKey = user?.role === 'platform_admin' ? selectedTenantId : '';
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [sheets, setSheets] = useState<InterviewSheet[]>([]);
  const [allSheets, setAllSheets] = useState<InterviewSheet[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('calendar');
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()));
  const [now, setNow] = useState(() => Date.now());
  const [quickScheduleDate, setQuickScheduleDate] = useState<Date | null>(null);
  const [quickSchedulePickerOpen, setQuickSchedulePickerOpen] = useState(false);
  const [quickScheduleSheet, setQuickScheduleSheet] = useState<InterviewSheet | null>(null);
  const [quickScheduleModalOpen, setQuickScheduleModalOpen] = useState(false);
  const initialSheetsRequestRef = useRef<{
    scope: string;
    promise: Promise<{ sheets: InterviewSheet[] }>;
  } | null>(null);
  const sheetsRequestEpochRef = useRef(0);

  const fetchScheduledInterviews = useCallback(async ({
    reuseInFlightRequest = false,
    showLoadingState = true,
  }: SheetsFetchOptions = {}) => {
    const requestEpoch = ++sheetsRequestEpochRef.current;
    try {
      if (showLoadingState) {
        setLoading(true);
        setSheets([]);
        setAllSheets([]);
      }
      setError(null);
      const loadScope = async () => {
        if (!scopeKey) return interviewSheetApi.listAll();
        const scopedProjects = await projectsApi.getAll(undefined, scopeKey);
        return { sheets: await loadProjectInterviewSheets(scopedProjects) };
      };
      const request = reuseInFlightRequest && initialSheetsRequestRef.current?.scope === scopeKey
        ? initialSheetsRequestRef.current.promise
        : loadScope();
      if (reuseInFlightRequest) {
        initialSheetsRequestRef.current = { scope: scopeKey, promise: request };
        const clearRequest = () => {
          if (initialSheetsRequestRef.current?.promise === request) {
            initialSheetsRequestRef.current = null;
          }
        };
        void request.then(clearRequest, clearRequest);
      }
      const res = await request;
      if (requestEpoch !== sheetsRequestEpochRef.current) return;
      setAllSheets(res.sheets);

      // Filter only scheduled interviews and sort by date
      const scheduled = res.sheets
        .filter(sheet => sheet.scheduled_at)
        .sort((a, b) => {
          const dateA = new Date(a.scheduled_at!).getTime();
          const dateB = new Date(b.scheduled_at!).getTime();
          return dateA - dateB; // Sort ascending (upcoming first)
        });

      setSheets(scheduled);
    } catch (err) {
      if (requestEpoch !== sheetsRequestEpochRef.current) return;
      setError(err as APIError);
    } finally {
      if (requestEpoch === sheetsRequestEpochRef.current) {
        setLoadedScope(scopeKey);
        setLoading(false);
      }
    }
  }, [scopeKey]);

  useEffect(() => {
    void fetchScheduledInterviews({ reuseInFlightRequest: true });
    return () => {
      sheetsRequestEpochRef.current += 1;
    };
  }, [fetchScheduledInterviews]);

  useEffect(() => watchInterviewSchedule(() => {
    void fetchScheduledInterviews({ showLoadingState: false });
  }), [fetchScheduledInterviews]);

  useEffect(() => {
    setQuickSchedulePickerOpen(false);
    setQuickScheduleModalOpen(false);
    setQuickScheduleDate(null);
    setQuickScheduleSheet(null);
  }, [scopeKey]);

  // Keeps the current-time line and in-progress interviews accurate while the page stays open.
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), NOW_REFRESH_MS);
    return () => window.clearInterval(interval);
  }, []);

  const formatDateTime = (dateStr: string) => {
    const date = new Date(dateStr);
    return {
      date: new Intl.DateTimeFormat(language, {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      }).format(date),
      time: new Intl.DateTimeFormat(language, {
        hour: '2-digit',
        minute: '2-digit'
      }).format(date)
    };
  };

  const isUpcoming = (dateStr: string) => {
    return new Date(dateStr) > new Date();
  };

  const isPast = (dateStr: string) => {
    return new Date(dateStr) < new Date();
  };

  const getCandidateName = useCallback((sheet: InterviewSheet) =>
    candidateLabel({ candidateId: sheet.candidate_id, identity: sheet.data.identite }, t('candidates.fallbackLabel')),
  [t]);

  const events = useMemo(
    () => sheets
      .map((sheet) => toAgendaEvent(sheet, getCandidateName(sheet)))
      .filter((event): event is AgendaEvent => event !== null),
    [getCandidateName, sheets]
  );

  const schedulableSheets = useMemo(
    () => allSheets.filter(
      (sheet) => sheet.status === 'draft'
        && !sheet.scheduled_at
        && !sheet.data.scheduling?.appointment_id
    ),
    [allSheets]
  );

  const canScheduleOnDay = (day: Date) => {
    const endOfDay = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 23, 59, 59, 999);
    return endOfDay.getTime() >= Date.now();
  };

  const openQuickSchedule = (day: Date) => {
    setQuickScheduleDate(new Date(day.getFullYear(), day.getMonth(), day.getDate()));
    setQuickScheduleSheet(null);
    setQuickSchedulePickerOpen(true);
  };

  const chooseQuickScheduleCandidate = (sheet: InterviewSheet) => {
    setQuickScheduleSheet(sheet);
    setQuickSchedulePickerOpen(false);
    setQuickScheduleModalOpen(true);
  };

  const quickScheduleStart = useMemo(() => {
    if (!quickScheduleDate) return null;
    const selectedStart = new Date(
      quickScheduleDate.getFullYear(),
      quickScheduleDate.getMonth(),
      quickScheduleDate.getDate(),
      9,
      0,
      0,
      0,
    );
    if (selectedStart.getTime() > Date.now()) return selectedStart.toISOString();
    return new Date(Date.now() + 15 * 60 * 1000).toISOString();
  }, [quickScheduleDate]);
  const quickScheduleInitialData = useMemo(
    () => ({ scheduled_at: quickScheduleStart }),
    [quickScheduleStart]
  );

  const handleQuickScheduleCreate = async (
    request: ScheduleInterviewRequest,
  ): Promise<ScheduledInterviewResult> => {
    if (!quickScheduleSheet) {
      throw new Error(t('agenda.quickSchedule.candidateRequired'));
    }
    return interviewAppointmentsApi.scheduleFromSheet(quickScheduleSheet.id, request);
  };

  if (loading || loadedScope !== scopeKey) {
    return (
      <PageFrame>
        <SystemState
          kind="loading"
          title={t('agenda.loading')}
          indicator={<Calendar className="size-5" />}
        />
      </PageFrame>
    );
  }

  const upcomingInterviews = sheets.filter(s => s.scheduled_at && isUpcoming(s.scheduled_at));
  const pastInterviews = sheets.filter(s => s.scheduled_at && isPast(s.scheduled_at));

  const today = new Date(now);
  const weekDays = visibleWeekDays(weekStart, events, today);
  const weekEnd = addDays(weekStart, 7);
  const weekEvents = events.filter((event) => event.start >= weekStart && event.start < weekEnd);
  const nextEvent = events.find((event) => event.start >= weekEnd);
  const latestEvent = [...events].reverse().find((event) => event.start < weekStart);
  const jumpTarget = nextEvent ?? latestEvent;
  const weekRangeLabel = new Intl.DateTimeFormat(language, {
    day: 'numeric',
    month: 'long',
    ...(weekStart.getFullYear() !== today.getFullYear() || weekEnd.getFullYear() !== today.getFullYear()
      ? { year: 'numeric' as const }
      : {}),
  }).formatRange(weekDays[0], weekDays[weekDays.length - 1]);
  const shortDate = new Intl.DateTimeFormat(language, { weekday: 'short', day: 'numeric', month: 'short' });

  const quickScheduleDateLabel = quickScheduleDate
    ? new Intl.DateTimeFormat(language, {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      }).format(quickScheduleDate)
    : '';

  const renderInterviewActions = (sheet: InterviewSheet) => {
    const name = getCandidateName(sheet);
    return (
      <>
        <SchedulerButton
          candidateId={sheet.candidate_id}
          jobId={sheet.job_id}
          matchingId={sheet.matching_id}
          candidateName={name}
          candidateEmail={getCandidateEmail(sheet.data)}
          existingSheetId={sheet.id}
          initialData={{
            scheduled_at: sheet.scheduled_at,
            end_at: sheet.data.scheduling?.end_at,
            location: sheet.location,
            scheduler_notes: sheet.scheduler_notes,
            interviewer: sheet.interviewer,
            appointment_id: sheet.data.scheduling?.appointment_id,
          }}
          variant="outline"
          size="sm"
        />
        <Button
          variant="ghost"
          size="icon"
          onClick={() => navigate(`/interviews/${sheet.id}`)}
          aria-label={formatMessage(t('agenda.aria.viewSheet'), { candidate: name })}
        >
          <FileText data-icon="inline-start" />
        </Button>
      </>
    );
  };

  const renderInterviewGroup = (
    interviews: InterviewSheet[],
    label: string,
    statusBadge: ReactNode,
    divided: boolean,
  ) => (
    <Section
      data-tour={divided ? 'agenda-past-interviews' : 'agenda-upcoming-interviews'}
      title={`${label} (${interviews.length})`}
      divided={divided}
    >
      <OperationalList ariaLabel={label}>
        {interviews.map((sheet) => {
          const { date, time } = formatDateTime(sheet.scheduled_at!);
          const name = getCandidateName(sheet);
          return (
            <OperationalListItem
              key={sheet.id}
              primary={
                <Link
                  to={`/interviews/${sheet.id}`}
                  className="inline-flex min-h-11 items-center font-medium text-[var(--brain-ops-text)] underline-offset-4 hover:underline"
                >
                  {name}
                </Link>
              }
              secondary={
                <div className="flex flex-wrap items-center gap-2">
                  {statusBadge}
                  <Badge variant="outline">
                    {t(interviewKind(sheet) === 'ai' ? 'agenda.kind.ai' : 'agenda.kind.recruiter')}
                  </Badge>
                  <span>{t('agenda.projectContext')}</span>
                </div>
              }
              metadata={
                <dl className="grid gap-2">
                  <div>
                    <dt className="inline">{t('agenda.table.date')}: </dt>
                    <dd className="inline capitalize">{date}</dd>
                  </div>
                  <div>
                    <dt className="inline">{t('agenda.table.time')}: </dt>
                    <dd className="inline">{time}</dd>
                  </div>
                  <div>
                    <dt className="inline">{t('agenda.table.location')}: </dt>
                    <dd className="inline">{sheet.location || t('agenda.locationMissing')}</dd>
                  </div>
                  <div>
                    <dt className="inline">{t('agenda.table.interviewer')}: </dt>
                    <dd className="inline">{sheet.interviewer || t('agenda.interviewerMissing')}</dd>
                  </div>
                </dl>
              }
              actionsLabel={name}
              actions={renderInterviewActions(sheet)}
            />
          );
        })}
      </OperationalList>
    </Section>
  );

  const summary = (
    <section data-tour="agenda-summary" aria-label={t('agenda.statistics')}>
    <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--brain-ops-text-muted)]">
      {[
        { id: 'upcoming', label: t('agenda.upcoming'), value: upcomingInterviews.length },
        { id: 'past', label: t('agenda.past'), value: pastInterviews.length },
        { id: 'total', label: t('common.total'), value: sheets.length },
      ].map((item) => (
        <div key={item.id} className="flex items-baseline gap-1.5">
          <dt>{item.label}</dt>
          <dd className="font-semibold tabular-nums text-[var(--brain-ops-text)] [font-family:var(--brain-ops-font-command)]">{item.value}</dd>
        </div>
      ))}
    </dl>
    </section>
  );

  const viewModeButton = (mode: ViewMode, label: string) => (
    <button
      type="button"
      aria-pressed={viewMode === mode}
      onClick={() => setViewMode(mode)}
      className={cn(
        'brain-shell-touch-target inline-flex items-center rounded-[calc(var(--brain-ops-radius-panel)-2px)] px-3 text-sm font-medium transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)]',
        viewMode === mode
          ? 'bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text)] shadow-sm'
          : 'text-[var(--brain-ops-text-muted)] hover:text-[var(--brain-ops-text)]'
      )}
    >
      {label}
    </button>
  );

  return (
    <PageFrame>
      <PageHeader
        eyebrow={(
          <nav aria-label={t('agenda.breadcrumb')}>
            <ol className="flex items-center gap-2">
              <li>{t('sidebar.group.workspace')}</li>
              <li aria-hidden="true">›</li>
              <li aria-current="page" className="text-[var(--brain-ops-text)]">{t('sidebar.nav.agenda')}</li>
            </ol>
          </nav>
        )}
        title={t('agenda.title')}
        description={t('agenda.description')}
        backAction={(
          <PageBackButton
            onClick={() => navigate('/')}
            aria-label={t('common.backToDashboard')}
          />
        )}
        actionsLabel={t('agenda.table.actions')}
        actions={(
          <>
            {viewMode === 'calendar' ? (
              <div className="flex min-w-0 max-w-full items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  className="brain-shell-touch-target brain-shell-square-target"
                  aria-label={t('agenda.previousWeek')}
                  onClick={() => setWeekStart((current) => addDays(current, -7))}
                >
                  <ChevronLeft aria-hidden="true" />
                </Button>
                <p
                  aria-live="polite"
                  className="inline-flex min-h-9 min-w-0 items-center gap-2 px-1 text-sm font-semibold text-[var(--brain-ops-text)] sm:whitespace-nowrap"
                >
                  <CalendarDays aria-hidden="true" className="size-4 shrink-0" />
                  <span className="sr-only">{t('agenda.displayedWeek')}: </span>
                  {weekRangeLabel}
                </p>
                <Button
                  variant="ghost"
                  size="icon"
                  className="brain-shell-touch-target brain-shell-square-target"
                  aria-label={t('agenda.nextWeek')}
                  onClick={() => setWeekStart((current) => addDays(current, 7))}
                >
                  <ChevronRight aria-hidden="true" />
                </Button>
              </div>
            ) : null}
            {viewMode === 'calendar' ? (
              <Button
                variant="outline"
                size="sm"
                className="brain-shell-touch-target"
                onClick={() => setWeekStart(startOfWeek(new Date()))}
              >
                {t('agenda.today')}
              </Button>
            ) : null}
            <div
              data-tour="agenda-workspace"
              role="group"
              aria-label={t('agenda.viewMode')}
              className="inline-flex shrink-0 items-center gap-0.5 rounded-[var(--brain-ops-radius-panel)] bg-[var(--brain-ops-surface-muted)] p-1"
            >
              {viewModeButton('calendar', t('agenda.calendarView'))}
              {viewModeButton('list', t('agenda.listView'))}
            </div>
          </>
        )}
      />

      {error && <OperationsErrorBanner error={error} />}

      <div data-tour="agenda-events" className="flex min-w-0 flex-col gap-6 lg:gap-8">
      {sheets.length === 0 ? (
        <SystemState
          kind="empty"
          indicator={<Calendar className="size-5" />}
          title={t('agenda.empty.title')}
          description={t('agenda.empty.description')}
          actionLabel={t('agenda.empty.action')}
          action={
            <Button variant="outline" onClick={() => navigate('/projects')}>
              {t('agenda.empty.action')}
              <ArrowRight data-icon="inline-end" aria-hidden="true" />
            </Button>
          }
        />
      ) : null}
      {viewMode === 'list' ? (
        <>
          {summary}
          {upcomingInterviews.length > 0
            ? renderInterviewGroup(
                upcomingInterviews,
                t('agenda.upcomingInterviews'),
                <Badge
                  variant="outline"
                  className="border-[color:var(--brain-ops-success)] text-[var(--brain-ops-success)]"
                >
                  {t('agenda.upcoming')}
                </Badge>,
                false,
              )
            : null}
          {pastInterviews.length > 0
            ? renderInterviewGroup(
                pastInterviews,
                t('agenda.pastInterviews'),
                <Badge variant="secondary">{t('agenda.past')}</Badge>,
                true,
              )
            : null}
        </>
      ) : (
        <Section data-tour="agenda-calendar" ariaLabel={t('agenda.calendarView')} divided={false}>
          <div className="flex min-w-0 flex-col gap-3">
            {sheets.length > 0 && weekEvents.length === 0 ? (
              <p role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-[var(--brain-ops-text-muted)]">
                {t('agenda.weekEmpty')}
                {jumpTarget ? (
                  <Button
                    variant="link"
                    size="sm"
                    className="h-auto min-h-9 p-0 text-sm"
                    onClick={() => setWeekStart(startOfWeek(jumpTarget.start))}
                  >
                    {formatMessage(t(nextEvent ? 'agenda.weekEmpty.next' : 'agenda.weekEmpty.latest'), {
                      date: shortDate.format(jumpTarget.start),
                    })}
                    <ArrowRight data-icon="inline-end" aria-hidden="true" />
                  </Button>
                ) : null}
              </p>
            ) : null}
            <AgendaWeekCalendar
              key={dayKey(weekStart)}
              days={weekDays}
              events={weekEvents}
              now={now}
              onOpenEvent={(event) => navigate(`/interviews/${event.id}`)}
              canSchedule={canScheduleOnDay}
              onSchedule={openQuickSchedule}
            />
            <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
              <AgendaLegend />
              {summary}
            </div>
          </div>
        </Section>
      )}
      </div>

      <OperationsDialog
        open={quickSchedulePickerOpen}
        onOpenChange={(open) => setQuickSchedulePickerOpen(open)}
      >
        <OperationsDialogContent className="max-h-[85vh] max-w-xl overflow-y-auto">
          <OperationsDialogClose aria-label={t('agenda.quickSchedule.close')} />
          <OperationsDialogHeader>
            <OperationsDialogTitle>{t('agenda.quickSchedule.title')}</OperationsDialogTitle>
            <OperationsDialogDescription>
              {formatMessage(t('agenda.quickSchedule.description'), {
                date: quickScheduleDateLabel,
              })}
            </OperationsDialogDescription>
          </OperationsDialogHeader>

          {schedulableSheets.length > 0 ? (
            <div
              className="flex flex-col divide-y divide-[color:var(--brain-ops-border)] border-y border-[color:var(--brain-ops-border)]"
              role="list"
              aria-label={t('agenda.quickSchedule.candidates')}
            >
              {schedulableSheets.map((sheet) => {
                const name = getCandidateName(sheet);
                const email = getCandidateEmail(sheet.data);
                return (
                  <div key={sheet.id} role="listitem">
                    <button
                      type="button"
                      onClick={() => chooseQuickScheduleCandidate(sheet)}
                      className="flex min-h-14 w-full items-center justify-between gap-4 px-1 py-3 text-left transition-colors hover:bg-[var(--brain-ops-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--brain-ops-focus-ring)]"
                      aria-label={formatMessage(t('agenda.quickSchedule.chooseCandidate'), {
                        candidate: name,
                      })}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-[var(--brain-ops-text)]">
                          {name}
                        </span>
                        <span className="block truncate text-xs text-[var(--brain-ops-text-muted)]">
                          {email || t('agenda.quickSchedule.emailMissing')}
                        </span>
                      </span>
                      <ArrowRight aria-hidden="true" className="size-4 shrink-0 text-[var(--brain-ops-text-muted)]" />
                    </button>
                  </div>
                );
              })}
            </div>
          ) : (
            <SystemState
              kind="empty"
              title={t('agenda.quickSchedule.emptyTitle')}
              description={t('agenda.quickSchedule.emptyDescription')}
              actionLabel={t('agenda.quickSchedule.openSheets')}
              action={(
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => navigate('/interviews')}
                >
                  {t('agenda.quickSchedule.openSheets')}
                  <ArrowRight data-icon="inline-end" aria-hidden="true" />
                </Button>
              )}
            />
          )}

          <OperationsDialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setQuickSchedulePickerOpen(false)}
            >
              {t('common.cancel')}
            </Button>
          </OperationsDialogFooter>
        </OperationsDialogContent>
      </OperationsDialog>

      {quickScheduleSheet ? (
        <InterviewSchedulerModal
          isOpen={quickScheduleModalOpen}
          onClose={() => {
            setQuickScheduleModalOpen(false);
            setQuickScheduleSheet(null);
          }}
          initialData={quickScheduleInitialData}
          initialAppointment={null}
          onCreate={handleQuickScheduleCreate}
          candidateName={getCandidateName(quickScheduleSheet)}
          candidateEmail={getCandidateEmail(quickScheduleSheet.data)}
        />
      ) : null}
    </PageFrame>
  );
};
