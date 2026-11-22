import { ArrowRight, CalendarClock, RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '../../components/ui/button';
import { useI18n } from '../../i18n/useI18n';
import type { CockpitInterview } from '../header-notifications/api';

const messages = {
  en: {
    title: 'Up next', calendar: 'Calendar', live: 'Interviews in progress', follow: 'Open interview',
    today: 'Today', tomorrow: 'Tomorrow', empty: 'No interviews planned for today or tomorrow.',
    loading: 'Loading interviews…', error: 'Interviews could not be refreshed.', retry: 'Try again',
    list: 'Scheduled interviews', in_progress: 'In progress', paused: 'Paused', wrapping_up: 'Wrapping up',
    scheduled: 'Scheduled', waiting_candidate: 'Waiting for candidate', candidate: 'Candidate',
  },
  fr: {
    title: 'À venir', calendar: 'Agenda', live: 'Entretiens en cours', follow: 'Ouvrir l’entretien',
    today: 'Aujourd’hui', tomorrow: 'Demain', empty: 'Aucun entretien prévu aujourd’hui ou demain.',
    loading: 'Chargement des entretiens…', error: 'Les entretiens n’ont pas pu être actualisés.', retry: 'Réessayer',
    list: 'Entretiens planifiés', in_progress: 'En cours', paused: 'En pause', wrapping_up: 'Finalisation',
    scheduled: 'Planifié', waiting_candidate: 'En attente du candidat', candidate: 'Candidat',
  },
};

export interface UpcomingInterviewsProps {
  interviews: CockpitInterview[];
  projectNames: ReadonlyMap<string, string>;
  loading: boolean;
  error: boolean;
  now: number;
  onRetry: () => void;
}

export function UpcomingInterviews({ interviews, projectNames, loading, error, now, onRetry }: UpcomingInterviewsProps) {
  const { language } = useI18n();
  const copy = messages[language === 'fr' ? 'fr' : 'en'];
  const locale = language === 'fr' ? 'fr-FR' : 'en-GB';
  const active = interviews.filter((item) => ['in_progress', 'paused', 'wrapping_up'].includes(item.status));
  const scheduled = interviews.filter((item) => !active.includes(item));
  const today = new Date(now);
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const formatTime = (value: string) => new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(new Date(value));
  const statusLabel = (status: string) => copy[status as keyof typeof copy] || copy.scheduled;
  return (
    <section data-tour="home-upcoming" aria-label={copy.title} className="min-w-0 space-y-4">
      {active.length > 0 && (
        <section aria-label={copy.live} className="rounded-xl border border-[var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-5">
          <h2 className="mb-4 text-base font-semibold">{copy.live} <span className="ml-1 text-sm font-normal text-[var(--brain-ops-text-muted)]">{active.length}</span></h2>
          <ul className="max-h-72 space-y-5 overflow-y-auto overscroll-contain" tabIndex={0} aria-label={copy.live}>
            {active.map((item) => (
              <li key={item.id} className="space-y-3">
                <div className="flex items-start gap-3">
                  <span aria-hidden="true" className="flex size-9 shrink-0 items-center justify-center rounded-full bg-[var(--brain-ops-surface-muted)] text-xs font-medium">{item.candidateName.split(/\s+/).slice(0, 2).map((part) => part[0]).join('')}</span>
                  <div className="min-w-0 flex-1">
                    <p className="break-words font-semibold">{item.candidateName}</p>
                    <p className="mt-1 break-words text-sm text-[var(--brain-ops-text-muted)]">{projectNames.get(item.projectId)}</p>
                  </div>
                  <span className="shrink-0 text-xs text-[var(--brain-ops-text-muted)]">{formatTime(item.startsAt)}</span>
                </div>
                <p className="rounded-md bg-[var(--brain-ops-surface-muted)] px-3 py-2 text-sm">{statusLabel(item.status)}</p>
                <Link className="flex min-h-10 w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/80" to={`/interviews/${encodeURIComponent(item.sheetId)}`}>{copy.follow}<ArrowRight className="size-4" aria-hidden="true" /></Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      <div className="rounded-xl border border-[var(--brain-ops-border)] bg-[var(--brain-ops-calendar-surface)] p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold">{copy.title}</h2>
          <Link to="/agenda" className="inline-flex min-h-9 items-center gap-2 text-sm text-[var(--brain-ops-calendar-accent)] hover:text-[var(--brain-ops-text)]"><CalendarClock className="size-4" aria-hidden="true" />{copy.calendar}</Link>
        </div>
        {error ? <div role="status" className="mb-3 space-y-2 text-sm text-[var(--brain-ops-text-muted)]"><p>{copy.error}</p><Button size="sm" variant="outline" onClick={onRetry}><RefreshCw data-icon="inline-start" aria-hidden="true" />{copy.retry}</Button></div> : null}
        {loading ? <p role="status" className="py-4 text-sm text-[var(--brain-ops-text-muted)]">{copy.loading}</p> : scheduled.length === 0 ? (!error && <p className="py-4 text-sm text-[var(--brain-ops-text-muted)]">{copy.empty}</p>) : (
          <div className="max-h-[28rem] overflow-y-auto overscroll-contain pr-1" tabIndex={0} role="region" aria-label={copy.list}>
            {[{ date: today, title: copy.today }, { date: tomorrow, title: copy.tomorrow }].map((group) => {
              const items = scheduled.filter((item) => new Date(item.startsAt).toDateString() === group.date.toDateString());
              if (!items.length) return null;
              return <section key={group.title} className="mb-5 last:mb-0">
                <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2 text-sm text-[var(--brain-ops-text-muted)]"><h3 className="font-medium">{group.title}</h3><span>{new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short' }).format(group.date)}</span></div>
                <ul className="divide-y divide-[var(--brain-ops-border)]">
                  {items.map((item) => <li key={item.id}>
                    <Link to={`/interviews/${encodeURIComponent(item.sheetId)}`} className="grid min-h-20 grid-cols-[3rem_minmax(0,1fr)_auto] items-start gap-3 rounded-md px-2 py-3 hover:bg-[var(--brain-ops-calendar-hover)] focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-current">
                      <time dateTime={item.startsAt} className="text-sm tabular-nums text-[var(--brain-ops-text-muted)]">{formatTime(item.startsAt)}</time>
                      <span className="min-w-0"><span className="block break-words text-sm font-semibold">{item.candidateName}</span><span className="mt-1 block break-words text-xs text-[var(--brain-ops-text-muted)]">{[projectNames.get(item.projectId), statusLabel(item.status)].filter(Boolean).join(' · ')}</span>{item.location && <span className="mt-1 block break-words text-xs text-[var(--brain-ops-text-muted)]">{item.location}</span>}</span>
                      <ArrowRight className="mt-0.5 size-4 text-[var(--brain-ops-text-muted)]" aria-hidden="true" />
                    </Link>
                  </li>)}
                </ul>
              </section>;
            })}
          </div>
        )}
      </div>
    </section>
  );
}
