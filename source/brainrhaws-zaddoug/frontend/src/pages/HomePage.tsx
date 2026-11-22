import { useCallback, useMemo, useRef, useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  Building2,
  CalendarClock,
  ClipboardList,
  FolderOpen,
  RefreshCw,
} from 'lucide-react';

import { enterprisesApi } from '../api/enterprises';
import { interviewSheetApi, type InterviewSheet } from '../api/interviewSheet';
import { projectsApi } from '../api/projects';
import type { Enterprise, Project } from '../api/types';
import {
  ContextStrip,
  MetricStrip,
  OperationalList,
  PageFrame,
  PageHeader,
  Section,
  SystemState,
} from '../components/operations';
import { Button } from '../components/ui/button';
import { useAuth } from '../features/auth/context/AuthContext';
import { GettingStarted } from '../features/onboarding/GettingStarted';
import { formatMessage } from '../i18n/formatMessage';
import { useI18n } from '../i18n/useI18n';
import { useAppStore } from '../stores/useAppStore';
import { candidateLabel } from '../lib/candidateLabel';
import { watchInterviewSchedule } from '../lib/interviewScheduleUpdates';
import { loadCockpitInterviews, type CockpitInterview } from '../features/header-notifications/api';
import { UpcomingInterviews } from '../features/cockpit/UpcomingInterviews';

type ResourceState<T> = {
  data: T;
  error: string | null;
  loading: boolean;
};

type RecentItem = {
  id: string;
  title: string;
  detail: string;
  timestamp: string;
  path: string;
  type: 'project' | 'interview';
};

const emptyCompaniesState: ResourceState<Enterprise[]> = {
  data: [],
  error: null,
  loading: true,
};

const emptyProjectsState: ResourceState<Project[]> = {
  data: [],
  error: null,
  loading: true,
};

const emptyInterviewsState: ResourceState<InterviewSheet[]> = {
  data: [],
  error: null,
  loading: true,
};

function timestampValue(value: string): number {
  const timestamp = new Date(value).getTime();
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function formatActivityDate(value: string, locale: string, unavailableText: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return unavailableText;
  }

  return new Intl.DateTimeFormat(locale, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(date);
}

export const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { language, t } = useI18n();
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);
  const requestId = useRef(0);
  const scheduleController = useRef<AbortController | null>(null);
  const [schedule, setSchedule] = useState<ResourceState<CockpitInterview[]>>({ data: [], error: null, loading: true });
  const [now, setNow] = useState(Date.now);
  const [companies, setCompanies] = useState<ResourceState<Enterprise[]>>(emptyCompaniesState);
  const [projects, setProjects] = useState<ResourceState<Project[]>>(emptyProjectsState);
  const [interviews, setInterviews] = useState<ResourceState<InterviewSheet[]>>(emptyInterviewsState);
  const [loadedScopeKey, setLoadedScopeKey] = useState<string | null>(null);

  const canSelectTenant = user?.role === 'platform_admin';
  // Client accounts receive their authorised enterprises from the API grants.
  const effectiveTenantId = canSelectTenant ? selectedTenantId || undefined : undefined;
  const scopeKey = `${user?.id || ''}:${effectiveTenantId || '__all_accessible_clients__'}`;

  const loadDashboard = useCallback(async (background = false) => {
    const currentRequestId = requestId.current + 1;
    requestId.current = currentRequestId;

    scheduleController.current?.abort();
    const controller = new AbortController();
    scheduleController.current = controller;
    setNow(Date.now());
    if (!background) {
      setSchedule({ data: [], error: null, loading: true });
      // Clear the previous scope before loading another client.
      setCompanies({ data: [], error: null, loading: true });
      setProjects({ data: [], error: null, loading: true });
      setInterviews({ data: [], error: null, loading: true });
    }

    const [companiesResult, projectsResult] = await Promise.allSettled([
      enterprisesApi.getAll(effectiveTenantId),
      projectsApi.getAll(undefined, effectiveTenantId),
    ]);

    if (requestId.current !== currentRequestId) {
      return;
    }

    const visibleProjects = projectsResult.status === 'fulfilled' ? projectsResult.value : [];
    const visibleProjectIds = new Set(visibleProjects.map((project) => project.id));

    setCompanies(
      companiesResult.status === 'fulfilled'
        ? { data: companiesResult.value, error: null, loading: false }
        : {
            data: [],
            error: t('home.error.companies'),
            loading: false,
          }
    );

    setProjects(
      projectsResult.status === 'fulfilled'
        ? { data: visibleProjects, error: null, loading: false }
        : {
            data: [],
            error: t('home.error.projects'),
            loading: false,
          }
    );
    setLoadedScopeKey(scopeKey);

    if (projectsResult.status === 'rejected') {
      setSchedule({ data: [], error: t('home.error.interviewsHidden'), loading: false });
      setInterviews({
        data: [],
        error: t('home.error.interviewsHidden'),
        loading: false,
      });
      return;
    }

    if (visibleProjects.length === 0) {
      setSchedule({ data: [], error: null, loading: false });
      setInterviews({
        data: [],
        error: null,
        loading: false,
      });
      return;
    }

    try {
      let sheets: InterviewSheet[];
      let partialInterviewError = false;

      if (effectiveTenantId) {
        const interviewResults: PromiseSettledResult<{ sheets: InterviewSheet[] }>[] = [];
        for (let offset = 0; offset < visibleProjects.length; offset += 4) {
          if (requestId.current !== currentRequestId) return;
          interviewResults.push(...await Promise.allSettled(visibleProjects.slice(offset, offset + 4).map((project) =>
            interviewSheetApi.listAll({ job_id: project.id })
          )));
        }
        partialInterviewError = interviewResults.some((result) => result.status === 'rejected');
        sheets = interviewResults.flatMap((result) =>
          result.status === 'fulfilled' ? result.value.sheets : []
        );
      } else {
        sheets = (await interviewSheetApi.listAll()).sheets;
      }

      if (requestId.current !== currentRequestId) {
        return;
      }

      const uniqueVisibleSheets = Array.from(
        new Map(
          sheets
            .filter((sheet) => visibleProjectIds.has(sheet.job_id))
            .map((sheet) => [sheet.id, sheet])
        ).values()
      );

      setInterviews({
        data: uniqueVisibleSheets,
        error: partialInterviewError ? t('home.error.interviews') : null,
        loading: false,
      });
      try {
        const nextSchedule = await loadCockpitInterviews(uniqueVisibleSheets, controller.signal, t('candidates.fallbackLabel'));
        if (requestId.current !== currentRequestId) return;
        setSchedule({ data: nextSchedule, loading: false, error: partialInterviewError ? t('home.error.interviews') : null });
      } catch {
        if (requestId.current !== currentRequestId) return;
        setSchedule((previous) => ({ ...previous, loading: false, error: t('home.error.interviews') }));
      }
    } catch {
      if (requestId.current !== currentRequestId) {
        return;
      }

      setSchedule((previous) => ({ ...previous, loading: false, error: t('home.error.interviews') }));
      setInterviews({
        data: [],
        error: t('home.error.interviews'),
        loading: false,
      });
    }
  }, [effectiveTenantId, scopeKey, t]);

  useEffect(() => {
    void loadDashboard();
    const unsubscribe = watchInterviewSchedule(() => { void loadDashboard(true); });
    return () => {
      unsubscribe();
      requestId.current += 1;
      scheduleController.current?.abort();
    };
  }, [loadDashboard]);

  // React may paint once before the loading effect runs after a tenant change.
  // Gate every rendered resource by the scope that produced it so data from the
  // previous tenant cannot appear under the newly selected client, even briefly.
  const scopeIsCurrent = loadedScopeKey === scopeKey;
  const displayedSchedule = scopeIsCurrent ? schedule : { data: [], error: null, loading: true };
  const displayedCompanies = scopeIsCurrent ? companies : emptyCompaniesState;
  const displayedProjects = scopeIsCurrent ? projects : emptyProjectsState;
  const displayedInterviews = scopeIsCurrent ? interviews : emptyInterviewsState;

  const activeProjects = useMemo(
    () => displayedProjects.data.filter((project) => project.status === 'actif'),
    [displayedProjects.data]
  );

  const openInterviewSheets = useMemo(
    () => displayedInterviews.data.filter((sheet) => sheet.status === 'draft' || sheet.status === 'in_progress'),
    [displayedInterviews.data]
  );

  const upcomingInterviews = displayedSchedule.data.filter((item) =>
    item.status === 'scheduled' || item.status === 'waiting_candidate'
  );

  const projectNames = useMemo(
    () => new Map(displayedProjects.data.map((project) => [project.id, project.nom])),
    [displayedProjects.data]
  );

  const recentItems = useMemo<RecentItem[]>(() => {
    const projectItems: RecentItem[] = displayedProjects.data.map((project) => ({
      id: `project-${project.id}`,
      title: project.nom,
      detail: project.status === 'actif' ? t('home.activeProject') : t('home.archivedProject'),
      timestamp: project.updated_at || project.last_modified || project.created_at,
      path: `/projects/${project.id}`,
      type: 'project',
    }));

    const interviewItems: RecentItem[] = displayedInterviews.data.map((sheet) => ({
      id: `interview-${sheet.id}`,
      title: candidateLabel(
        { candidateId: sheet.candidate_id, identity: sheet.data.identite },
        t('candidates.fallbackLabel')
      ),
      detail: `${projectNames.get(sheet.job_id) || t('home.visibleProject')} · ${
        sheet.status === 'draft'
          ? t('home.status.draft')
          : sheet.status === 'in_progress'
            ? t('home.status.inProgress')
            : t('home.status.completed')
      }`,
      timestamp: sheet.updated_at || sheet.created_at,
      path: `/interviews/${sheet.id}`,
      type: 'interview',
    }));

    return [...projectItems, ...interviewItems]
      .filter((item) => timestampValue(item.timestamp) > 0)
      .sort((left, right) => timestampValue(right.timestamp) - timestampValue(left.timestamp))
      .slice(0, 6);
  }, [displayedInterviews.data, displayedProjects.data, projectNames, t]);

  const scopeLabel = useMemo(() => {
    if (user?.role === 'platform_admin' && !selectedTenantId) {
      return t('home.allAccessibleClients');
    }

    const scopedCompany = displayedCompanies.data.find(
      (company) => (company.tenant_id || company.id) === (effectiveTenantId || selectedTenantId)
    );
    return scopedCompany?.tenant_name || scopedCompany?.nom || t('home.currentClientScope');
  }, [displayedCompanies.data, effectiveTenantId, selectedTenantId, t, user?.role]);

  const dataErrors = [
    displayedCompanies.error ? { source: t('home.source.companies'), message: displayedCompanies.error } : null,
    displayedProjects.error ? { source: t('home.source.projects'), message: displayedProjects.error } : null,
    displayedInterviews.error ? { source: t('home.source.interviews'), message: displayedInterviews.error } : null,
  ].filter((item): item is { source: string; message: string } => item !== null);

  const isLoading = displayedCompanies.loading || displayedProjects.loading || displayedInterviews.loading;
  const isEmpty =
    !isLoading &&
    dataErrors.length === 0 &&
    displayedCompanies.data.length === 0 &&
    displayedProjects.data.length === 0 &&
    displayedInterviews.data.length === 0;
  const canShowGettingStarted =
    !isLoading &&
    !displayedCompanies.error &&
    !displayedProjects.error &&
    displayedProjects.data.length === 0 &&
    !(user?.role === 'platform_admin' && !selectedTenantId);

  return (
    <PageFrame>
      <PageHeader
        eyebrow={t('home.operationsCockpit')}
        title={t('home.title')}
        actionsLabel={t('home.continueWorking')}
        actions={
          <>
            <Button
              type="button"
              onClick={() => navigate('/projects')}
            >
              {t('home.openProjects')}
              <ArrowRight data-icon="inline-end" aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate('/agenda')}
            >
              {t('home.openAgenda')}
            </Button>
          </>
        }
        context={canSelectTenant && effectiveTenantId ? (
          <ContextStrip
            ariaLabel={t('home.currentClientScope')}
            items={[
              {
                id: 'scope',
                label: t('home.scope'),
                value: displayedCompanies.loading
                  ? formatMessage(t('home.loadingIndicator'), { label: t('home.scope') })
                  : scopeLabel,
              },
            ]}
          />
        ) : undefined}
      />

      {canShowGettingStarted ? (
        <GettingStarted
          companyCount={displayedCompanies.data.length}
          projectCount={displayedProjects.data.length}
          role={user?.role || 'viewer'}
          onNavigate={navigate}
        />
      ) : null}

      {dataErrors.length > 0 ? (
        <SystemState
          kind="warning"
          title={t('home.partialData')}
          description={
            <ul className="mt-2 space-y-1 text-sm">
              {dataErrors.map((error) => (
                <li key={error.source}>
                  <span className="font-medium">{error.source}:</span> {error.message}
                </li>
              ))}
            </ul>
          }
          actionLabel={t('home.retry')}
          action={
            <Button
              type="button"
              variant="outline"
              onClick={() => void loadDashboard()}
              disabled={isLoading}
            >
              <RefreshCw
                data-icon="inline-start"
                className={isLoading ? 'animate-spin motion-reduce:animate-none' : undefined}
                aria-hidden="true"
              />
              {t('home.retry')}
            </Button>
          }
        />
      ) : null}

      <Section
        data-tour="home-overview"
        divided={false}
        ariaLabel={t('home.operatingOverview')}
      >
        <MetricStrip
          ariaLabel={t('home.operatingOverview')}
          items={[
            {
              id: 'active-projects',
              label: t('home.activeProjects'),
              value: displayedProjects.loading ? (
                <span
                  className="inline-block h-6 w-12 animate-pulse bg-[var(--brain-ops-surface-muted)] motion-reduce:animate-none"
                  aria-label={formatMessage(t('home.loadingIndicator'), { label: t('home.activeProjects') })}
                />
              ) : displayedProjects.error ? '—' : activeProjects.length,
              detail: displayedProjects.loading
                ? t('home.loading')
                : displayedProjects.error
                  ? t('home.indicatorUnavailable')
                  : undefined,
            },
            {
              id: 'companies',
              label: t('home.companies'),
              value: displayedCompanies.loading ? (
                <span
                  className="inline-block h-6 w-12 animate-pulse bg-[var(--brain-ops-surface-muted)] motion-reduce:animate-none"
                  aria-label={formatMessage(t('home.loadingIndicator'), { label: t('home.companies') })}
                />
              ) : displayedCompanies.error ? '—' : displayedCompanies.data.length,
              detail: displayedCompanies.loading
                ? t('home.loading')
                : displayedCompanies.error
                  ? t('home.indicatorUnavailable')
                  : undefined,
            },
            {
              id: 'upcoming',
              label: t('home.upcoming'),
              value: displayedSchedule.loading ? (
                <span
                  className="inline-block h-6 w-12 animate-pulse bg-[var(--brain-ops-surface-muted)] motion-reduce:animate-none"
                  aria-label={formatMessage(t('home.loadingIndicator'), { label: t('home.upcoming') })}
                />
              ) : displayedSchedule.error ? '—' : upcomingInterviews.length,
              detail: displayedSchedule.loading
                ? t('home.loading')
                : displayedSchedule.error
                  ? t('home.indicatorUnavailable')
                  : t('home.upcomingWindow'),
            },
            {
              id: 'open-sheets',
              label: t('home.openSheets'),
              value: displayedInterviews.loading ? (
                <span
                  className="inline-block h-6 w-12 animate-pulse bg-[var(--brain-ops-surface-muted)] motion-reduce:animate-none"
                  aria-label={formatMessage(t('home.loadingIndicator'), { label: t('home.openSheets') })}
                />
              ) : displayedInterviews.error ? '—' : openInterviewSheets.length,
              detail: displayedInterviews.loading
                ? t('home.loading')
                : displayedInterviews.error
                  ? t('home.indicatorUnavailable')
                  : undefined,
            },
          ]}
        />
      </Section>

      {isEmpty && !canShowGettingStarted ? (
        <SystemState
          kind="empty"
          title={t('home.noActivity')}
          description={t('home.noActivityDescription')}
          indicator={<FolderOpen aria-hidden="true" />}
          actionLabel={t('home.continueWorking')}
          action={
            <>
              <Button type="button" onClick={() => navigate('/enterprises')}>
                {t('home.openCompanies')}
              </Button>
              <Button type="button" variant="outline" onClick={() => navigate('/projects')}>
                {t('home.openProjects')}
              </Button>
            </>
          }
        />
      ) : null}

      {!isEmpty ? (
        <div className="grid min-w-0 gap-8 xl:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.6fr)]">
          <Section
            data-tour="home-recent-activity"
            divided={false}
            title={t('home.recentActivity')}
          >
            {isLoading && recentItems.length === 0 ? (
              <SystemState
                kind="loading"
                title={formatMessage(t('home.loadingIndicator'), { label: t('home.workspaceFeed') })}
                indicator={
                  <RefreshCw className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                }
              />
            ) : recentItems.length === 0 ? (
              <SystemState kind="empty" title={t('home.noDatedActivity')} />
            ) : (
              <OperationalList ariaLabel={t('home.recentActivity')}>
                {recentItems.map((item) => {
                  const Icon = item.type === 'project' ? FolderOpen : ClipboardList;
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        className="group grid min-h-16 w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 bg-[var(--brain-ops-surface)] px-4 py-3 text-left transition-colors duration-[var(--brain-ops-duration-fast)] hover:bg-[var(--brain-ops-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--brain-ops-focus-ring)] motion-reduce:transition-none sm:px-5"
                        onClick={() => navigate(item.path)}
                      >
                        <Icon className="h-4 w-4 text-[var(--brain-ops-text-muted)]" aria-hidden="true" />
                        <span className="min-w-0">
                          <span className="block break-words font-medium text-[var(--brain-ops-text)]">
                            {item.title}
                          </span>
                          <span className="mt-1 block break-words text-sm capitalize text-[var(--brain-ops-text-muted)]">
                            {item.detail}
                          </span>
                          <span className="mt-1 block text-xs text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                            {formatActivityDate(
                              item.timestamp,
                              language === 'fr' ? 'fr-FR' : 'en-GB',
                              t('home.dateUnavailable')
                            )}
                          </span>
                        </span>
                        <ArrowRight
                          className="h-4 w-4 text-[var(--brain-ops-text-muted)] transition-transform group-hover:translate-x-0.5 motion-reduce:transform-none motion-reduce:transition-none"
                          aria-hidden="true"
                        />
                      </button>
                    </li>
                  );
                })}
              </OperationalList>
            )}
          </Section>

          <div className="min-w-0 space-y-8">
            <UpcomingInterviews
              interviews={displayedSchedule.data}
              projectNames={projectNames}
              loading={displayedSchedule.loading}
              error={Boolean(displayedSchedule.error)}
              now={now}
              onRetry={() => void loadDashboard(true)}
            />
            <Section
              data-tour="home-shortcuts"
              divided={false}
              title={t('home.continueWorking')}
              description={t('home.shortcuts')}
            >
              <OperationalList ariaLabel={t('home.shortcuts')}>
                {[
                  { label: t('home.manageCompanies'), path: '/enterprises', icon: Building2 },
                  { label: t('home.reviewResults'), path: '/results', icon: Activity },
                  { label: t('home.openInterviewSheets'), path: '/interviews', icon: ClipboardList },
                  { label: t('home.planInterviews'), path: '/agenda', icon: CalendarClock },
                ].map((action) => {
                  const Icon = action.icon;
                  return (
                    <li key={action.path}>
                      <button
                        type="button"
                        className="group flex min-h-14 w-full items-center gap-3 bg-[var(--brain-ops-surface)] px-4 py-3 text-left text-sm text-[var(--brain-ops-text)] transition-colors duration-[var(--brain-ops-duration-fast)] hover:bg-[var(--brain-ops-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--brain-ops-focus-ring)] motion-reduce:transition-none sm:px-5"
                        onClick={() => navigate(action.path)}
                      >
                        <Icon className="h-4 w-4 text-[var(--brain-ops-text-muted)]" aria-hidden="true" />
                        <span className="min-w-0 flex-1 break-words">{action.label}</span>
                        <ArrowRight
                          className="h-4 w-4 text-[var(--brain-ops-text-muted)] transition-transform group-hover:translate-x-0.5 motion-reduce:transform-none motion-reduce:transition-none"
                          aria-hidden="true"
                        />
                      </button>
                    </li>
                  );
                })}
              </OperationalList>
            </Section>
          </div>
        </div>
      ) : null}
    </PageFrame>
  );
};
