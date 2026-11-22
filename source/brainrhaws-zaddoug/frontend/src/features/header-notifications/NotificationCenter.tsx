import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Bell, CalendarDays, Clock3, ExternalLink, MapPin } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../../components/ui/button';
import {
  OperationsDialog,
  OperationsDialogClose,
  OperationsDialogContent,
  OperationsDialogDescription,
  OperationsDialogFooter,
  OperationsDialogHeader,
  OperationsDialogTitle,
} from '../../components/operations/OperationsDialogContent';
import { SystemState } from '../../components/operations/SystemState';
import { useAuth } from '../auth/context/AuthContext';
import { useI18n } from '../../i18n/useI18n';
import { useAppStore } from '../../stores/useAppStore';
import { loadHeaderInterviewReminders } from './api';
import { dispatchBrowserInterviewReminders } from './browser-reminders';
import { notificationMessage, type NotificationLanguage } from './notification-messages';
import {
  browserAlertsOptedIn,
  readReminderIds,
  rememberBrowserAlertsOptIn,
  rememberReminderIds,
} from './storage';
import { isDueReminder, type HeaderInterviewReminder, type NotificationLoadState } from './types';
import { subscribeInterviewScheduleUpdates } from '../../lib/interviewScheduleUpdates';

const POLL_INTERVAL_MS = 60_000;
const PERMISSION_TIMEOUT_MS = 15_000;

function createMessage(language: NotificationLanguage) {
  return (key: Parameters<typeof notificationMessage>[1], values?: Record<string, string | number>) => (
    notificationMessage(language, key, values)
  );
}

export interface NotificationPanelProps {
  state: NotificationLoadState;
  reminders: readonly HeaderInterviewReminder[];
  readIds: ReadonlySet<string>;
  now: number;
  language: NotificationLanguage;
  browserAlertsEnabled: boolean;
  permissionPending?: boolean;
  permissionStatus?: string;
  onRetry: () => void;
  onEnableBrowserAlerts: () => void;
  onOpenReminder: (reminder: HeaderInterviewReminder) => void;
  onMarkAllRead: () => void;
  onOpenAgenda: () => void;
}

function formatAppointment(language: NotificationLanguage, startsAt: string): { date: string; time: string } {
  const date = new Date(startsAt);
  return {
    date: new Intl.DateTimeFormat(language, { weekday: 'short', day: 'numeric', month: 'short' }).format(date),
    time: new Intl.DateTimeFormat(language, { hour: '2-digit', minute: '2-digit' }).format(date),
  };
}

export function NotificationPanel({
  state,
  reminders,
  readIds,
  now,
  language,
  browserAlertsEnabled,
  permissionPending = false,
  permissionStatus,
  onRetry,
  onEnableBrowserAlerts,
  onOpenReminder,
  onMarkAllRead,
  onOpenAgenda,
}: NotificationPanelProps) {
  const message = useMemo(() => createMessage(language), [language]);
  const unreadReminders = reminders.filter((reminder) => !readIds.has(reminder.id));

  return (
    <>
      <OperationsDialogClose aria-label={message('headerNotifications.close')} className="brain-shell-touch-target brain-shell-square-target" />
      <OperationsDialogHeader className="border-b border-[color:var(--brain-ops-border)] pb-4 pr-10 text-left">
        <OperationsDialogTitle className="flex items-center gap-2">
          <Bell aria-hidden="true" className="size-5" />
          {message('headerNotifications.title')}
        </OperationsDialogTitle>
        <OperationsDialogDescription className="max-w-lg leading-6">
          {message('headerNotifications.description')}
        </OperationsDialogDescription>
      </OperationsDialogHeader>

      <div className="min-h-28" aria-live="polite" aria-busy={state === 'loading' || undefined}>
        {state === 'loading' && (
          <SystemState kind="loading" title={message('headerNotifications.loading')} indicator={<Clock3 className="size-4" />} />
        )}
        {state === 'scope-required' && (
          <SystemState
            kind="info"
            title={message('headerNotifications.scopeTitle')}
            description={message('headerNotifications.scopeDescription')}
          />
        )}
        {state === 'error' && (
          <SystemState
            kind="error"
            title={message('headerNotifications.errorTitle')}
            description={message('headerNotifications.errorDescription')}
            actionLabel={message('headerNotifications.retry')}
            action={<Button type="button" variant="outline" size="sm" onClick={onRetry}>{message('headerNotifications.retry')}</Button>}
          />
        )}
        {state === 'ready' && reminders.length === 0 && (
          <SystemState
            kind="empty"
            title={message('headerNotifications.emptyTitle')}
            description={message('headerNotifications.emptyDescription')}
            indicator={<CalendarDays className="size-5" />}
          />
        )}
        {state === 'ready' && reminders.length > 0 && (
          <div className="max-h-[min(24rem,52vh)] divide-y divide-[color:var(--brain-ops-border)] overflow-y-auto border-y border-[color:var(--brain-ops-border)]" role="list">
            {reminders.map((reminder) => {
              const due = isDueReminder(reminder, now);
              const read = readIds.has(reminder.id);
              const formatted = formatAppointment(language, reminder.startsAt);
              return (
                <div key={reminder.id} role="listitem">
                  <button
                    type="button"
                    aria-label={message('headerNotifications.openSheet', { candidate: reminder.candidateName })}
                    onClick={() => onOpenReminder(reminder)}
                    className="grid min-h-20 w-full grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3 px-2 py-3 text-left transition-colors hover:bg-[var(--brain-ops-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--brain-ops-focus-ring)] sm:px-3"
                  >
                  <span
                    aria-hidden="true"
                    className={`mt-1.5 size-2 rounded-full ${!read ? 'bg-[var(--brain-ops-danger)]' : 'bg-[var(--brain-ops-border)]'}`}
                  />
                  <span className="min-w-0">
                    <span className="block break-words text-sm font-semibold text-[var(--brain-ops-text)]">{reminder.candidateName}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs text-[var(--brain-ops-text-muted)]">
                      <span>{formatted.date}</span>
                      <span>{formatted.time}</span>
                      {reminder.location && <span className="inline-flex min-w-0 items-center gap-1"><MapPin aria-hidden="true" className="size-3" /><span className="truncate">{reminder.location}</span></span>}
                    </span>
                    <span className={`mt-1 block text-xs font-medium ${due ? 'text-[var(--brain-ops-danger)]' : 'text-[var(--brain-ops-text-muted)]'}`}>
                      {message(due ? 'headerNotifications.due' : 'headerNotifications.upcoming')}
                    </span>
                  </span>
                    <ExternalLink aria-hidden="true" className="mt-1 size-4 text-[var(--brain-ops-text-muted)]" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="space-y-2 border-t border-[color:var(--brain-ops-border)] pt-4">
        <div className="flex flex-wrap items-center gap-2">
          {!browserAlertsEnabled && (
            <Button type="button" variant="outline" size="sm" disabled={permissionPending} onClick={onEnableBrowserAlerts}>
              <Bell aria-hidden="true" className="size-4" />
              {message('headerNotifications.enableAlerts')}
            </Button>
          )}
          {unreadReminders.length > 0 && (
            <Button type="button" variant="ghost" size="sm" onClick={onMarkAllRead}>
              {message('headerNotifications.markAllRead')}
            </Button>
          )}
        </div>
        {permissionStatus && <p role="status" className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">{permissionStatus}</p>}
        <p className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">{message('headerNotifications.readHelp')}</p>
        <p className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">{message('headerNotifications.openAppHelp')}</p>
      </div>

      <OperationsDialogFooter>
        <Button type="button" variant="ghost" onClick={onOpenAgenda}>
          <CalendarDays aria-hidden="true" className="size-4" />
          {message('headerNotifications.fullAgenda')}
        </Button>
      </OperationsDialogFooter>
    </>
  );
}

export function NotificationCenter() {
  const navigate = useNavigate();
  const { language } = useI18n();
  const notificationLanguage: NotificationLanguage = language === 'fr' ? 'fr' : 'en';
  const message = useMemo(() => createMessage(notificationLanguage), [notificationLanguage]);
  const { user } = useAuth();
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);
  const tenantId = user?.role === 'platform_admin' ? selectedTenantId || undefined : undefined;
  const scope = `${user?.id || ''}:${tenantId || 'own-tenant'}`;
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<NotificationLoadState>('loading');
  const [reminders, setReminders] = useState<HeaderInterviewReminder[]>([]);
  const [readIds, setReadIds] = useState<Set<string>>(new Set());
  const [now, setNow] = useState(() => Date.now());
  const [alertsEnabled, setAlertsEnabled] = useState(false);
  const [permissionPending, setPermissionPending] = useState(false);
  const [permissionStatus, setPermissionStatus] = useState('');
  const scopeRef = useRef(scope);
  const epochRef = useRef(0);
  const activeRequestRef = useRef<{
    scope: string;
    controller: AbortController;
    promise: Promise<HeaderInterviewReminder[]>;
  } | null>(null);

  const markRead = useCallback((ids: readonly string[]) => {
    if (!user?.id) return;
    const stored = rememberReminderIds(user.id, tenantId, ids);
    setReadIds((current) => new Set([...current, ...stored, ...ids]));
  }, [tenantId, user?.id]);

  const openReminder = useCallback((reminder: HeaderInterviewReminder) => {
    markRead([reminder.id]);
    setOpen(false);
    navigate(`/interviews/${encodeURIComponent(reminder.sheetId)}`);
  }, [markRead, navigate]);

  const refresh = useCallback(async () => {
    if (!user?.id) return;
    setNow(Date.now());
    if (user.role === 'platform_admin' && !tenantId) {
      setState('scope-required');
      return;
    }
    const requestScope = `${user.id}:${tenantId || 'own-tenant'}`;
    const epoch = epochRef.current;
    let activeRequest = activeRequestRef.current;
    if (activeRequest && activeRequest.scope !== requestScope) {
      activeRequest.controller.abort();
      activeRequestRef.current = null;
      activeRequest = null;
    }
    if (!activeRequest) {
      const controller = new AbortController();
      const promise = loadHeaderInterviewReminders({
        role: user.role,
        tenantId,
        signal: controller.signal,
      }, message('headerNotifications.candidateFallback'));
      activeRequest = { scope: requestScope, controller, promise };
      activeRequestRef.current = activeRequest;
    }
    try {
      const nextReminders = await activeRequest.promise;
      if (scopeRef.current !== requestScope || epochRef.current !== epoch) return;
      const refreshedAt = Date.now();
      setNow(refreshedAt);
      setReminders(nextReminders);
      setState('ready');
      if (browserAlertsOptedIn(user.id, tenantId, refreshedAt) && 'Notification' in window && Notification.permission === 'granted') {
        await dispatchBrowserInterviewReminders({
          userId: user.id,
          tenantId,
          reminders: nextReminders,
          title: message('headerNotifications.alertTitle'),
          formatTime: (startsAt) => formatAppointment(notificationLanguage, startsAt).time,
          navigate,
          onOpenReminder: openReminder,
          isCurrent: () => scopeRef.current === requestScope && epochRef.current === epoch,
          now: refreshedAt,
        });
      }
    } catch (error) {
      if (scopeRef.current === requestScope && epochRef.current === epoch && !(error instanceof DOMException && error.name === 'AbortError')) {
        setState('error');
      }
    } finally {
      if (activeRequestRef.current === activeRequest) activeRequestRef.current = null;
    }
  }, [message, navigate, notificationLanguage, openReminder, tenantId, user?.id, user?.role]);

  useLayoutEffect(() => {
    const previousScope = scopeRef.current;
    scopeRef.current = scope;
    epochRef.current += 1;
    if (activeRequestRef.current && activeRequestRef.current.scope !== scope) {
      activeRequestRef.current.controller.abort();
      activeRequestRef.current = null;
    }
    setOpen(false);
    setReminders([]);
    setPermissionStatus('');
    setPermissionPending(false);
    if (user?.id) {
      const storedReadIds = readReminderIds(user.id, tenantId);
      setReadIds(storedReadIds);
      setAlertsEnabled(browserAlertsOptedIn(user.id, tenantId) && 'Notification' in window && Notification.permission === 'granted');
    }
    if (previousScope !== scope) setState('loading');
    const epoch = epochRef.current;
    void refresh();
    return () => {
      if (epochRef.current === epoch) epochRef.current += 1;
    };
  }, [refresh, scope, tenantId, user?.id]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      const backgroundAlerts = user?.id && browserAlertsOptedIn(user.id, tenantId)
        && 'Notification' in window && Notification.permission === 'granted';
      if (document.visibilityState === 'visible' || backgroundAlerts) void refresh();
    }, POLL_INTERVAL_MS);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void refresh();
    };
    const readStorageKey = user?.id
      ? `brainrh:header-notifications:read:${user.id}:${tenantId || 'own-tenant'}:`
      : '';
    const alertsStorageKey = user?.id
      ? `brainrh:header-notifications:alerts:${user.id}:${tenantId || 'own-tenant'}`
      : '';
    const onStorage = (event: StorageEvent) => {
      if (!user?.id) return;
      if (event.key?.startsWith(readStorageKey) || event.key === null) {
        const stored = readReminderIds(user.id, tenantId);
        setReadIds(stored);
      }
      if (event.key === alertsStorageKey || event.key === null) {
        setAlertsEnabled(
          browserAlertsOptedIn(user.id, tenantId)
          && 'Notification' in window
          && Notification.permission === 'granted',
        );
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('storage', onStorage);
    window.addEventListener('focus', onVisibilityChange);
    window.addEventListener('online', onVisibilityChange);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('focus', onVisibilityChange);
      window.removeEventListener('online', onVisibilityChange);
    };
  }, [refresh, tenantId, user?.id]);

  useEffect(() => subscribeInterviewScheduleUpdates(() => {
    epochRef.current += 1;
    activeRequestRef.current?.controller.abort();
    activeRequestRef.current = null;
    void refresh();
  }), [refresh]);

  const unreadReminders = reminders.filter((reminder) => !readIds.has(reminder.id));

  const enableBrowserAlerts = async () => {
    if (!user?.id || permissionPending) return;
    if (!('Notification' in window)) {
      setPermissionStatus(message('headerNotifications.alertsUnsupported'));
      return;
    }
    const requestScope = scopeRef.current;
    setPermissionPending(true);
    let timeout: number | undefined;
    try {
      const permission = await Promise.race([
        Notification.requestPermission(),
        new Promise<never>((_, reject) => {
          timeout = window.setTimeout(() => reject(new Error('Notification permission timed out')), PERMISSION_TIMEOUT_MS);
        }),
      ]);
      if (requestScope !== scopeRef.current) return;
      if (permission !== 'granted') {
        setAlertsEnabled(false);
        setPermissionStatus(message('headerNotifications.alertsDenied'));
        return;
      }
      rememberBrowserAlertsOptIn(user.id, tenantId);
      setAlertsEnabled(true);
      setPermissionStatus(message('headerNotifications.alertsEnabled'));
      await dispatchBrowserInterviewReminders({
        userId: user.id,
        tenantId,
        reminders,
        title: message('headerNotifications.alertTitle'),
        formatTime: (startsAt) => formatAppointment(notificationLanguage, startsAt).time,
        navigate,
        onOpenReminder: openReminder,
        isCurrent: () => scopeRef.current === requestScope,
      });
    } catch {
      if (requestScope === scopeRef.current) setPermissionStatus(message('headerNotifications.alertsError'));
    } finally {
      if (timeout !== undefined) window.clearTimeout(timeout);
      if (requestScope === scopeRef.current) setPermissionPending(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={message(
          unreadReminders.length ? 'headerNotifications.openWithCount' : 'headerNotifications.open',
          { count: unreadReminders.length },
        )}
        className="brain-shell-touch-target brain-shell-square-target relative flex shrink-0 items-center justify-center rounded-md text-[var(--brain-ops-text-muted)] transition-colors hover:bg-[var(--brain-ops-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)]"
      >
        <Bell aria-hidden="true" className="brain-shell-icon" />
        {unreadReminders.length > 0 && (
          <span className="absolute right-0 top-0 min-w-4 rounded-full bg-[var(--brain-ops-danger)] px-1 text-center text-[0.625rem] font-semibold leading-4 text-white">
            {unreadReminders.length > 99 ? '99+' : unreadReminders.length}
          </span>
        )}
      </button>

      <OperationsDialog open={open} onOpenChange={setOpen}>
        <OperationsDialogContent className="max-w-xl grid-cols-1 gap-4 p-4 sm:p-6">
          <NotificationPanel
            state={state}
            reminders={reminders}
            readIds={readIds}
            now={now}
            language={notificationLanguage}
            browserAlertsEnabled={alertsEnabled}
            permissionPending={permissionPending}
            permissionStatus={permissionStatus}
            onRetry={() => { setState('loading'); void refresh(); }}
            onEnableBrowserAlerts={() => void enableBrowserAlerts()}
            onOpenReminder={openReminder}
            onMarkAllRead={() => markRead(unreadReminders.map((reminder) => reminder.id))}
            onOpenAgenda={() => { setOpen(false); navigate('/agenda'); }}
          />
        </OperationsDialogContent>
      </OperationsDialog>
    </>
  );
}
