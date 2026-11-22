import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { BarChart3, Calendar, Eye } from 'lucide-react';
import { projectsApi } from '../api/projects';
import type { APIError, Project, ProjectHistory } from '../api/types';
import {
  ContextStrip,
  MetricStrip,
  OperationalList,
  OperationalListItem,
  OperationsErrorBanner,
  PageBackButton,
  PageFrame,
  PageHeader,
  Section,
  SystemState,
} from '../components/operations';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select } from '../components/ui/select';
import { formatMessage } from '../i18n/formatMessage';
import { useI18n } from '../i18n/useI18n';
import { useAuth } from '../features/auth/context/AuthContext';
import { useAppStore } from '../stores/useAppStore';

export const ResultsPage: React.FC = () => {
  const { projectId: projectIdFromUrl } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { language, t } = useI18n();
  const { user } = useAuth();
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);
  const tenantScope = !projectIdFromUrl && user?.role === 'platform_admin' ? selectedTenantId : '';
  const projectsScopeKey = projectIdFromUrl
    ? `project:${projectIdFromUrl}`
    : `global:${tenantScope || '__all_clients__'}`;
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>(projectIdFromUrl || '');
  const [matchingHistory, setMatchingHistory] = useState<ProjectHistory | null>(null);
  const [dateFilter, setDateFilter] = useState<string>('');
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [projectsError, setProjectsError] = useState<APIError | null>(null);
  const [historyError, setHistoryError] = useState<APIError | null>(null);
  const [loadedProjectsScope, setLoadedProjectsScope] = useState<string | null>(null);
  const projectsRequestEpochRef = useRef(0);
  const historyRequestEpochRef = useRef(0);

  useEffect(() => {
    const requestEpoch = ++projectsRequestEpochRef.current;
    historyRequestEpochRef.current += 1;

    setProjectsLoading(true);
    setHistoryLoading(false);
    setProjectsError(null);
    setHistoryError(null);
    setLoadedProjectsScope(null);
    setProjects([]);
    setMatchingHistory(null);
    setDateFilter('');
    setSelectedProjectId(projectIdFromUrl || '');

    const fetchProjects = async () => {
      try {
        const data = projectIdFromUrl
          ? [await projectsApi.getById(projectIdFromUrl)]
          : await projectsApi.getAll(undefined, tenantScope);
        if (requestEpoch !== projectsRequestEpochRef.current) return;
        setProjects(data);
      } catch (err) {
        if (requestEpoch !== projectsRequestEpochRef.current) return;
        setProjectsError(err as APIError);
      } finally {
        if (requestEpoch === projectsRequestEpochRef.current) {
          setLoadedProjectsScope(projectsScopeKey);
          setProjectsLoading(false);
        }
      }
    };

    void fetchProjects();
    return () => {
      projectsRequestEpochRef.current += 1;
      historyRequestEpochRef.current += 1;
    };
  }, [projectIdFromUrl, projectsScopeKey, tenantScope]);

  useEffect(() => {
    if (loadedProjectsScope !== projectsScopeKey || !selectedProjectId) {
      setHistoryLoading(false);
      setMatchingHistory(null);
      return;
    }

    const requestEpoch = ++historyRequestEpochRef.current;
    setHistoryLoading(true);
    setHistoryError(null);
    setMatchingHistory(null);

    const fetchMatchingHistory = async () => {
      try {
        const history = await projectsApi.getHistory(selectedProjectId);
        if (requestEpoch !== historyRequestEpochRef.current) return;
        setMatchingHistory(history);
      } catch (err) {
        if (requestEpoch !== historyRequestEpochRef.current) return;
        setHistoryError(err as APIError);
      } finally {
        if (requestEpoch === historyRequestEpochRef.current) {
          setHistoryLoading(false);
        }
      }
    };

    void fetchMatchingHistory();
    return () => {
      historyRequestEpochRef.current += 1;
    };
  }, [loadedProjectsScope, projectsScopeKey, selectedProjectId]);

  const filteredHistory = matchingHistory?.items.filter((item) => {
    if (!dateFilter) return true;
    const itemDate = item.timestamp.split('_')[0];
    return itemDate.includes(dateFilter);
  }) || [];

  const formatTimestampLabel = (timestamp?: string) => {
    if (!timestamp) return '—';
    const [datePart, timePart] = timestamp.split('_');
    if (!datePart || !timePart) return timestamp.replace('_', ' · ');
    const isoString = `${datePart}T${timePart.replace(/-/g, ':')}`;
    const date = new Date(isoString);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleString(language === 'fr' ? 'fr-FR' : 'en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    }
    return `${datePart} · ${timePart.replace(/-/g, ':')}`;
  };

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId),
    [projects, selectedProjectId]
  );

  const totalRuns = matchingHistory?.total ?? 0;
  const latestHistoryEntry = matchingHistory?.items?.[0];
  const totalCandidates =
    matchingHistory?.items.reduce((acc, item) => acc + (item.candidats_count || 0), 0) ?? 0;
  const latestRunLabel = latestHistoryEntry
    ? formatTimestampLabel(latestHistoryEntry.timestamp)
    : t('results.noRunsYet');
  const latestVolumeLabel = latestHistoryEntry
    ? `${latestHistoryEntry.candidats_count} ${t('results.resumes')}`
    : '—';

  if (projectsLoading || loadedProjectsScope !== projectsScopeKey) {
    return (
      <PageFrame>
        <SystemState kind="loading" title={t('results.loadingProjects')} />
      </PageFrame>
    );
  }

  return (
    <PageFrame>
      <PageHeader
        eyebrow={t('results.eyebrow')}
        backAction={<PageBackButton onClick={() => navigate(-1)} aria-label={t('common.back')} />}
        title={selectedProject
          ? formatMessage(t('results.archive.projectTitle'), { project: selectedProject.nom })
          : t('results.archive.title')}
        description={selectedProject
          ? t('results.archive.projectDescription')
          : t('results.archive.description')}
        actions={selectedProjectId ? (
          <>
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate(`/projects/${selectedProjectId}`)}
            >
              {t('results.action.viewProject')}
            </Button>
            <Button
              type="button"
              onClick={() => navigate(`/projects/${selectedProjectId}/matching`)}
            >
              {t('results.action.openMatching')}
            </Button>
          </>
        ) : null}
        actionsLabel={t('results.actionsLabel')}
        context={(
          <ContextStrip
            ariaLabel={t('results.contextLabel')}
            items={[
              {
                id: 'project',
                label: t('results.context.project'),
                value: selectedProject?.nom ?? t('results.context.allProjects'),
                detail: selectedProjectId || t('results.context.notSelected'),
              },
              {
                id: 'company',
                label: t('results.context.company'),
                value: selectedProject?.enterprise_id ?? '—',
              },
            ]}
          />
        )}
      />

      {projectsError ? <OperationsErrorBanner error={projectsError} /> : null}
      {historyError ? <OperationsErrorBanner error={historyError} /> : null}

      {!projectIdFromUrl ? (
        <Section
          title={t('results.scope.title')}
          description={t('results.scope.description')}
          divided={false}
          contentClassName="max-w-xl"
        >
          <Label htmlFor="project-select" className="mb-2 block text-sm">
            {t('results.scope.projectLabel')}
          </Label>
          <Select
            id="project-select"
            value={selectedProjectId}
            onChange={(event) => {
              setDateFilter('');
              setSelectedProjectId(event.target.value);
            }}
          >
            <option value="">{t('results.scope.projectPlaceholder')}</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.nom}
              </option>
            ))}
          </Select>
        </Section>
      ) : null}

      {selectedProjectId ? (
        <MetricStrip
          ariaLabel={t('results.metricsLabel')}
          items={[
            { id: 'runs', label: t('results.metric.runs'), value: totalRuns },
            { id: 'candidates', label: t('results.metric.candidates'), value: totalCandidates },
            {
              id: 'latest-run',
              label: t('results.metric.latestRun'),
              value: <span className="block text-base leading-tight">{latestRunLabel}</span>,
            },
            { id: 'latest-volume', label: t('results.metric.latestVolume'), value: latestVolumeLabel },
          ]}
        />
      ) : null}

      {selectedProjectId && historyLoading ? (
        <SystemState kind="loading" title={t('results.loadingHistory')} />
      ) : null}

      {selectedProjectId && matchingHistory && !historyLoading ? (
        <Section
          title={t('results.history.title')}
          description={t('results.history.description')}
          actions={(
            <div className="flex items-center gap-2">
              <Calendar aria-hidden="true" className="size-4 text-[var(--brain-ops-text-muted)]" />
              <Label htmlFor="results-date-filter" className="sr-only">
                {t('results.filter.dateLabel')}
              </Label>
              <Input
                id="results-date-filter"
                type="date"
                lang={language === 'fr' ? 'fr-FR' : 'en-US'}
                value={dateFilter}
                onChange={(event) => setDateFilter(event.target.value)}
                className="w-auto min-w-40"
              />
            </div>
          )}
          actionsLabel={t('common.filters')}
        >
          {filteredHistory.length === 0 ? (
            <SystemState
              kind="empty"
              title={dateFilter ? t('results.empty.filteredTitle') : t('results.empty.historyTitle')}
              description={dateFilter
                ? t('results.empty.filteredDescription')
                : t('results.empty.historyDescription')}
              indicator={<BarChart3 className="size-5" />}
            />
          ) : (
            <OperationalList ariaLabel={t('results.history.listLabel')}>
              {filteredHistory.map((item) => {
                const runDate = formatTimestampLabel(item.timestamp);
                const detailPath = `/projects/${selectedProjectId}/results/${item.matching_id}`;

                return (
                  <OperationalListItem
                    key={item.matching_id}
                    leading={<BarChart3 className="mt-0.5 size-4" />}
                    primary={(
                      <button
                        type="button"
                        className="text-left [font-family:var(--brain-ops-font-command)] hover:underline"
                        onClick={() => navigate(detailPath)}
                      >
                        {runDate}
                      </button>
                    )}
                    secondary={formatMessage(t('results.history.candidateCount'), {
                      count: item.candidats_count,
                    })}
                    metadata={item.matching_id}
                    monospaceMetadata
                    actions={(
                      <>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => navigate(detailPath)}
                        >
                          <Eye className="size-4" />
                          {t('results.action.openRun')}
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => navigate(`${detailPath}?view=matrix`)}
                        >
                          <BarChart3 className="size-4" />
                          {t('results.action.openMatrix')}
                        </Button>
                      </>
                    )}
                    actionsLabel={formatMessage(t('results.history.runActions'), { date: runDate })}
                  />
                );
              })}
            </OperationalList>
          )}
        </Section>
      ) : null}

      {selectedProjectId && !matchingHistory && !historyLoading && !historyError ? (
        <SystemState
          kind="empty"
          title={t('results.empty.historyTitle')}
          description={t('results.empty.historyDescription')}
          indicator={<BarChart3 className="size-5" />}
        />
      ) : null}

      {!selectedProjectId && !projectIdFromUrl && projects.length === 0 && !projectsError ? (
        <SystemState
          kind="empty"
          title={t('results.empty.projectsTitle')}
          description={t('results.empty.projectsDescription')}
          indicator={<BarChart3 className="size-5" />}
        />
      ) : null}

      {!selectedProjectId && !projectIdFromUrl && projects.length > 0 && !projectsError ? (
        <SystemState
          kind="info"
          title={t('results.empty.selectTitle')}
          description={t('results.empty.selectDescription')}
          indicator={<BarChart3 className="size-5" />}
        />
      ) : null}
    </PageFrame>
  );
};
