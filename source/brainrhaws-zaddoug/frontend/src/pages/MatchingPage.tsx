import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import type { ChangeEvent } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Target, Play, Clock, CheckCircle2, History, FileText, Circle, Square } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select } from '../components/ui/select';
import { Progress } from '../components/ui/progress';
import { Badge } from '../components/ui/badge';
import { LoadingPage } from '../components/shared/Loading';
import {
  ContextStrip,
  MetricStrip,
  OperationsErrorBanner,
  PageBackButton,
  PageFrame,
  PageHeader,
  Section,
  SystemState,
} from '../components/operations';
import { EvidencePanel } from '../components/matching/EvidencePanel';
import { renderTextWithEvidences } from '../components/matching/renderTextWithEvidences';
import { InterviewSheetButton } from '../components/interview/InterviewSheetButton';
import { RealtimeInterviewButton } from '../components/interview/realtime/RealtimeInterviewButton';
import { SchedulerButton } from '../components/interview/scheduler/SchedulerButton';
import { useSSE } from '../hooks/useSSE';
import type { SSEMessage } from '../hooks/useSSE';
import { matchingApi } from '../api/matching';
import { projectsApi } from '../api/projects';
import { enterprisesApi } from '../api/enterprises';
import { interviewSheetApi, type InterviewSheet } from '../api/interviewSheet';
import { createClientId } from '../lib/uuid';
import { downloadOriginalCv } from '../lib/downloadOriginalCv';
import { useToast } from '../hooks/useToast';
import { formatMessage } from '../i18n/formatMessage';
import { useI18n } from '../i18n/useI18n';
import type { Project, APIError, SSEProgressEvent, SSEDoneEvent, Enterprise, ResultatMatching, MatchingResponse } from '../api/types';

interface MatchingStep {
  name: string;
  progress: number;
  message: string;
  completed: boolean;
  skipped?: boolean;
}

const initialSteps: MatchingStep[] = [
  { name: 'Must-have filtering', progress: 0, message: 'Waiting...', completed: false },
  { name: 'Similarity & nice-to-have scoring', progress: 0, message: 'Waiting...', completed: false },
  { name: 'LLM re-ranking', progress: 0, message: 'Waiting...', completed: false },
];

interface MatchingSummary {
  results?: ResultatMatching[];
  metadata?: MatchingResponse['metadata'];
  success_count?: number;
  failed_count?: number;
  total?: number;
}

export const MatchingPage: React.FC = () => {
  const { projectId: projectIdFromUrl } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const { t } = useI18n();
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>(projectIdFromUrl || '');
  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const [selectedEnterpriseId, setSelectedEnterpriseId] = useState<string>('');
  const [topN, setTopN] = useState<number>(10);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<MatchingStep[]>(initialSteps);
  const [results, setResults] = useState<MatchingSummary | null>(null);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [endTime, setEndTime] = useState<number | null>(null);
  const [sheetsByCandidate, setSheetsByCandidate] = useState<Record<string, InterviewSheet>>({});

  // State to force timer re-render
  const [, setTick] = useState(0);

  // 🔑 Unique runId for server idempotency
  const runIdRef = useRef<string>('');
  const runCompletedRef = useRef(false);
  if (!runIdRef.current) {
    runIdRef.current = createClientId();
  }

  // Update timer every 100ms while matching is running
  useEffect(() => {
    if (!running || !startTime) return;

    const interval = setInterval(() => {
      setTick(prev => prev + 1);
    }, 100); // Update every 100ms for smooth display

    return () => clearInterval(interval);
  }, [running, startTime]);

  const handleMessage = useCallback((event: SSEMessage) => {
    if (event.type === 'progress') {
      const progressData = event.data as SSEProgressEvent;
      setSteps((prev) => {
        const newSteps = [...prev];
        const stepMap: Record<string, number> = {
          'must_have_filtering': 0,
          'embedding': 1,
          'reranking': 2,
        };
        const stepIndex = stepMap[progressData.step.toLowerCase()];
        if (stepIndex !== undefined && newSteps[stepIndex]) {
          const isSkipped = Boolean(progressData.skipped);
          newSteps[stepIndex] = {
            ...newSteps[stepIndex],
            progress: (progressData.progress || 0) * 100,
            message: progressData.message || '',
            completed: (progressData.progress || 0) >= 1.0,
            skipped: isSkipped,
          };
        }
        return newSteps;
      });
    } else if (event.type === 'done') {
      const doneData = event.data as SSEDoneEvent;
      runCompletedRef.current = true;
      setResults(doneData.summary as MatchingSummary);
      setError(null);
      setRunning(false);
      setEndTime(Date.now());
      // Only mark steps at 100% if they actually progressed
      setSteps((prev) => prev.map((s) => {
        if (s.progress > 0) {
          return { ...s, completed: true, progress: 100 };
        }
        return s;
      }));

      // No auto-redirect – display results on the same page
    } else if (event.type === 'error') {
      const errorData = event.data as APIError;
      runCompletedRef.current = true;
      setError(errorData);
      setRunning(false);
      setEndTime(Date.now());
    }
  }, []);

  const handleDownloadOriginalCv = async (result: ResultatMatching) => {
    if (!result.original_cv_url) {
      return;
    }

    try {
      const filename = await downloadOriginalCv(result.original_cv_url, result.cv);
      toast.success(t('matching.toast.downloadSuccess'), filename);
    } catch (err) {
      const message = err instanceof Error ? err.message : t('matching.error.unknown');
      toast.error(t('matching.toast.downloadError'), message);
    }
  };

  // 📡 SSE URL with runId for server-side idempotency
  const streamUrl = useMemo(() => {
    if (!running || !selectedProjectId) return '';
    const baseUrl = matchingApi.getRunStreamUrl(selectedProjectId, topN);
    return `${baseUrl}&runId=${runIdRef.current}`;
  }, [running, selectedProjectId, topN]);

  const { close } = useSSE({
    url: streamUrl,
    enabled: running,
    onMessage: handleMessage,
    onError: (err) => {
      if (runCompletedRef.current) {
        return;
      }
      console.error('[MatchingPage] SSE Error:', err);
      setError({ code: 'SSE_ERROR', message: 'Connection lost with the server' });
      setRunning(false);
    },
    closeOn: ['done', 'error'], // Auto-close when matching is finished
    forceSingle: false, // Temporarily disabled for debugging
  });

  const fetchProjects = async () => {
    try {
      setLoading(true);
      const data = await projectsApi.getAll();
      setProjects(data);
    } catch (err) {
      setError(err as APIError);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  useEffect(() => {
    const loadEnterprises = async () => {
      try {
        const data = await enterprisesApi.getAll();
        setEnterprises(data);
      } catch (err) {
        setError(err as APIError);
      }
    };

    loadEnterprises();
  }, []);

  useEffect(() => {
    const fetchSheets = async () => {
      try {
        if (!selectedProjectId) return;
        const res = await interviewSheetApi.listAll({ job_id: selectedProjectId });
        const map: Record<string, InterviewSheet> = {};
        res.sheets.forEach((s) => { map[s.candidate_id] = s; });
        setSheetsByCandidate(map);
      } catch (err) {
        console.error('Erreur chargement fiches entretien', err);
      }
    };
    fetchSheets();
  }, [selectedProjectId]);

  const handleStartMatching = () => {
    if (!selectedProjectId) {
      setError({ code: 'VALIDATION_ERROR', message: 'Please select a project' });
      return;
    }

    // 🔄 Generate a new runId for each run
    runIdRef.current = createClientId();
    runCompletedRef.current = false;
    console.log(`[MatchingPage] New matching run with runId: ${runIdRef.current}`);

    setError(null);
    setResults(null);
    setSteps(initialSteps);
    setStartTime(Date.now());
    setEndTime(null);
    setRunning(true);
  };

  const handleStop = () => {
    close();
    setRunning(false);
    setEndTime(Date.now());
  };

  const activeProjectId = selectedProjectId || projectIdFromUrl || '';

  const filteredProjects = useMemo(() => {
    if (!selectedEnterpriseId) {
      return projects;
    }
    return projects.filter((project) => project.enterprise_id === selectedEnterpriseId);
  }, [projects, selectedEnterpriseId]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === activeProjectId),
    [projects, activeProjectId]
  );

  const selectedEnterprise = useMemo(() => {
    const enterpriseId = selectedEnterpriseId || selectedProject?.enterprise_id;
    if (!enterpriseId) return undefined;
    return enterprises.find((enterprise) => enterprise.id === enterpriseId);
  }, [enterprises, selectedEnterpriseId, selectedProject?.enterprise_id]);

  useEffect(() => {
    if (!selectedProject?.enterprise_id) {
      return;
    }

    setSelectedEnterpriseId((prev) => {
      const enterpriseId = selectedProject.enterprise_id;
      if (!enterpriseId) {
        return prev;
      }
      if (prev === enterpriseId) {
        return prev;
      }
      return enterpriseId;
    });
  }, [selectedProject?.enterprise_id]);

  const handleEnterpriseChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value;
    setSelectedEnterpriseId(value);

    if (!value) {
      setSelectedProjectId('');
      return;
    }

    const currentProject = projects.find((project) => project.id === selectedProjectId);
    if (currentProject && currentProject.enterprise_id !== value) {
      setSelectedProjectId('');
    }
  };

  const handleProjectChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value;
    setSelectedProjectId(value);

    if (!value) {
      return;
    }

    const project = projects.find((item) => item.id === value);
    if (project?.enterprise_id) {
      setSelectedEnterpriseId(project.enterprise_id);
    }
  };

  const handleTopNChange = (event: ChangeEvent<HTMLInputElement>) => {
    const next = Math.min(Math.max(parseInt(event.target.value, 10) || 1, 1), 10);
    setTopN(next);
  };

  const duration = startTime && endTime ? ((endTime - startTime) / 1000).toFixed(1) : null;
  const matchedCandidates = results?.results?.length ?? 0;
  const lastDuration = duration || results?.metadata?.duree_totale_s?.toFixed(1) || null;
  const runStatus = running
    ? t('matching.status.running')
    : results
      ? t('matching.status.complete')
      : t('matching.status.ready');
  const stepLabels = [
    t('matching.step.mustHave'),
    t('matching.step.scoring'),
    t('matching.step.reranking'),
  ];

  if (loading) return <LoadingPage text={t('matching.loading')} />;

  return (
    <PageFrame width="full">
      <PageHeader
        eyebrow={t('matching.eyebrow')}
        backAction={<PageBackButton onClick={() => navigate(-1)} aria-label={t('common.back')} />}
        title={t('matching.title')}
        description={t('matching.description')}
        actionsLabel={t('matching.actions.page')}
        actions={(
          activeProjectId && (
            <Button variant="outline" onClick={() => navigate(`/projects/${activeProjectId}/results`)}>
              <History className="h-4 w-4" aria-hidden="true" />
              {t('matching.action.history')}
            </Button>
          )
        )}
        context={(
          <ContextStrip
            ariaLabel={t('matching.context.label')}
            items={[
              { id: 'company', label: t('matching.field.company'), value: selectedEnterprise?.nom ?? t('matching.value.notSelected') },
              { id: 'project', label: t('matching.field.project'), value: selectedProject?.nom ?? t('matching.value.notSelected') },
              { id: 'scope', label: t('matching.field.rerankingScope'), value: topN },
              { id: 'status', label: t('matching.field.status'), value: runStatus },
            ]}
          />
        )}
      />

      {error && <OperationsErrorBanner error={error} />}

      {!running && !results && projects.length === 0 && (
        <SystemState
          kind="empty"
          title={t('matching.empty.projectsTitle')}
          description={t('matching.empty.projectsDescription')}
          indicator={<Target className="h-5 w-5" />}
          actionLabel={t('matching.actions.empty')}
          action={<Button onClick={() => navigate('/projects')}>{t('matching.action.openProjects')}</Button>}
        />
      )}

      {!running && !results && projects.length > 0 && (
        <Section
          title={t('matching.setup.title')}
          description={t('matching.setup.description')}
          divided={false}
          contentClassName="overflow-hidden rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]"
        >
          <div className="grid min-w-0 lg:grid-cols-[minmax(0,1fr)_22rem]">
            <div className="space-y-6 p-5 sm:p-6 lg:border-r lg:border-[color:var(--brain-ops-border)] lg:p-8">
              <div className="grid gap-5 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="enterprise-select">{t('matching.field.companyRequired')}</Label>
                  <Select id="enterprise-select" value={selectedEnterpriseId} onChange={handleEnterpriseChange}>
                    <option value="">{t('matching.placeholder.company')}</option>
                    {enterprises.map((enterprise) => (
                      <option key={enterprise.id} value={enterprise.id}>{enterprise.nom}</option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="project-select">{t('matching.field.projectRequired')}</Label>
                  <Select id="project-select" value={selectedProjectId} onChange={handleProjectChange}>
                    <option value="">{t('matching.placeholder.project')}</option>
                    {filteredProjects.map((project) => (
                      <option key={project.id} value={project.id}>{project.nom}</option>
                    ))}
                  </Select>
                  {selectedEnterpriseId && filteredProjects.length === 0 && (
                    <p className="text-xs leading-5 text-[var(--brain-ops-warning)]">
                      {t('matching.empty.companyProjects')}
                    </p>
                  )}
                </div>
              </div>

              <div className="grid gap-5 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="top-n">{t('matching.field.topN')}</Label>
                  <Input id="top-n" type="number" min={1} max={10} value={topN} onChange={handleTopNChange} aria-describedby="top-n-help" />
                  <p id="top-n-help" className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">
                    {t('matching.field.topNHelp')}
                  </p>
                </div>
                <div className="border-l-2 border-[color:var(--brain-ops-accent)] bg-[var(--brain-ops-surface-muted)] p-4">
                  <p className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                    {t('matching.model.label')}
                  </p>
                  <p className="mt-2 font-medium text-[var(--brain-ops-text)]">{t('matching.model.adminSetting')}</p>
                  <p className="mt-1 text-xs leading-5 text-[var(--brain-ops-text-muted)]">{t('matching.model.routing')}</p>
                </div>
              </div>

              <Button
                onClick={handleStartMatching}
                size="lg"
                className="w-full sm:w-auto"
                disabled={running || !selectedEnterpriseId || !selectedProjectId}
              >
                <Play className="h-4 w-4" aria-hidden="true" />
                {t('matching.action.start')}
              </Button>
            </div>

            <aside className="border-t border-[color:var(--brain-ops-border)] p-5 sm:p-6 lg:border-t-0 lg:p-8" aria-labelledby="matching-prerequisites-title">
              <h3 id="matching-prerequisites-title" className="text-xs font-medium uppercase tracking-[0.12em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                {t('matching.prerequisites.title')}
              </h3>
              <ol className="mt-4 divide-y divide-[color:var(--brain-ops-border)] border-y border-[color:var(--brain-ops-border)]">
                {[
                  { ready: Boolean(selectedEnterpriseId), title: t('matching.prerequisites.company'), description: t('matching.prerequisites.companyDescription') },
                  { ready: Boolean(selectedProjectId), title: t('matching.prerequisites.project'), description: t('matching.prerequisites.projectDescription') },
                  { ready: true, title: t('matching.prerequisites.routing'), description: t('matching.prerequisites.routingDescription') },
                ].map((item, index) => (
                  <li key={index} className="flex gap-3 py-4">
                    {item.ready ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--brain-ops-success)]" aria-hidden="true" />
                    ) : (
                      <Circle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--brain-ops-text-muted)]" aria-hidden="true" />
                    )}
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-[var(--brain-ops-text)]">{item.title}</p>
                      <p className="mt-1 text-xs leading-5 text-[var(--brain-ops-text-muted)]">{item.description}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </aside>
          </div>
        </Section>
      )}

      {running && (
        <Section title={t('matching.live.title')} description={t('matching.live.description')} divided={false}>
          <div className="grid overflow-hidden rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] lg:grid-cols-[minmax(0,0.8fr)_minmax(24rem,1.2fr)]">
            <div className="flex min-h-64 flex-col justify-between gap-8 border-b border-[color:var(--brain-ops-border)] p-5 sm:p-6 lg:border-b-0 lg:border-r lg:p-8">
              <div>
                <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.12em] text-[var(--brain-ops-accent)] [font-family:var(--brain-ops-font-command)]">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-[var(--brain-ops-accent)] motion-reduce:animate-none" aria-hidden="true" />
                  {t('matching.live.signal')}
                </div>
                <p className="mt-5 text-2xl font-semibold tracking-[-0.02em] text-[var(--brain-ops-text)]">{selectedProject?.nom}</p>
                <p className="mt-2 text-sm leading-6 text-[var(--brain-ops-text-muted)]">{selectedEnterprise?.nom}</p>
              </div>
              <div className="flex flex-col gap-4">
                {startTime && (
                  <div className="flex items-center gap-3 border-t border-[color:var(--brain-ops-border)] pt-4">
                    <Clock className="h-4 w-4 text-[var(--brain-ops-text-muted)]" aria-hidden="true" />
                    <span className="text-sm text-[var(--brain-ops-text-muted)]">{t('matching.live.elapsed')}</span>
                    <span className="ml-auto text-lg font-semibold text-[var(--brain-ops-text)] [font-family:var(--brain-ops-font-command)]">
                      {((Date.now() - startTime) / 1000).toFixed(1)}s
                    </span>
                  </div>
                )}
                <Button variant="destructive" onClick={handleStop} className="w-full">
                  <Square className="h-3.5 w-3.5" aria-hidden="true" />
                  {t('matching.action.stop')}
                </Button>
              </div>
            </div>

            <div className="p-5 sm:p-6 lg:p-8">
              <p className="text-xs font-medium uppercase tracking-[0.12em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                {t('matching.live.inspector')}
              </p>
              <ol className="mt-4 divide-y divide-[color:var(--brain-ops-border)] border-y border-[color:var(--brain-ops-border)]">
                {steps.map((step, index) => (
                  <li key={index} className="py-5">
                    <div className="flex min-w-0 items-start gap-3">
                      {step.skipped ? (
                        <Circle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--brain-ops-text-muted)]" aria-hidden="true" />
                      ) : step.completed ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--brain-ops-success)]" aria-hidden="true" />
                      ) : (
                        <span className="mt-0.5 h-4 w-4 shrink-0 animate-pulse rounded-full border-2 border-[color:var(--brain-ops-accent)] motion-reduce:animate-none" aria-hidden="true" />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-medium text-[var(--brain-ops-text)]">{stepLabels[index]}</span>
                          <Badge variant="outline" className={step.completed ? 'border-[color:var(--brain-ops-success)] text-[var(--brain-ops-success)]' : ''}>
                            {step.skipped ? t('matching.step.skipped') : `${Math.round(step.progress)}%`}
                          </Badge>
                        </div>
                        <p className="mt-1 text-sm leading-6 text-[var(--brain-ops-text-muted)]">
                          {step.message === 'Waiting...' ? t('matching.step.waiting') : step.message}
                        </p>
                        <Progress
                          value={step.progress}
                          max={100}
                          aria-label={formatMessage(t('matching.step.progressLabel'), { step: stepLabels[index], progress: Math.round(step.progress) })}
                          className="mt-3 h-1.5 rounded-none bg-[var(--brain-ops-surface-muted)] [&>div]:bg-[var(--brain-ops-accent)] motion-reduce:[&>div]:transition-none"
                        />
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </Section>
      )}

      {results && !running && (
        <div className="space-y-8">
          <Section
            title={t('matching.results.title')}
            description={formatMessage(t('matching.results.description'), { count: matchedCandidates })}
            divided={false}
            actionsLabel={t('matching.actions.results')}
            actions={(
              <Button
                variant="outline"
                onClick={() => {
                  setResults(null);
                  setSteps(initialSteps);
                  setStartTime(null);
                  setEndTime(null);
                }}
              >
                {t('matching.action.newRun')}
              </Button>
            )}
          >
            <div className="space-y-5">
              {(results.metadata?.filtered_must_have === 0 || results.results?.length === 0) && (
                <SystemState
                  kind="warning"
                  title={t('matching.results.emptyTitle')}
                  description={formatMessage(t('matching.results.emptyDescription'), { count: results.metadata?.total_cvs || 0 })}
                  indicator={<Target className="h-5 w-5" />}
                />
              )}
              <MetricStrip
                ariaLabel={t('matching.results.metricsLabel')}
                items={[
                  { id: 'analysed', label: t('matching.metric.analysed'), value: results.metadata?.total_cvs || 0 },
                  { id: 'validated', label: t('matching.metric.validated'), value: results.metadata?.filtered_must_have || 0, tone: results.metadata?.filtered_must_have === 0 ? 'danger' : 'success' },
                  { id: 'reranked', label: t('matching.metric.reranked'), value: results.metadata?.top_reranked || 0 },
                  { id: 'duration', label: t('matching.metric.duration'), value: lastDuration ? `${lastDuration}s` : '0s' },
                ]}
              />
            </div>
          </Section>

          {results.results && results.results.length > 0 && (
            <Section title={t('matching.ranking.title')} description={t('matching.ranking.description')}>
              <div className="divide-y divide-[color:var(--brain-ops-border)] border-y border-[color:var(--brain-ops-border)]">
                {results.results.map((cv: ResultatMatching, index: number) => {
                  const isRerankFallback = cv.commentaire_scoring?.includes('⚠️ Re-ranking LLM indisponible');

                return (
                  <article
                    key={index}
                    className="py-6 first:pt-0 last:pb-0 sm:py-8"
                  >
                    <div className="flex min-w-0 flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                      <div className="flex min-w-0 items-start gap-4">
                        <span className="shrink-0 text-sm font-semibold text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                          {String(index + 1).padStart(2, '0')}
                        </span>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="break-words text-lg font-semibold text-[var(--brain-ops-text)]">{cv.cv}</h3>
                            {isRerankFallback && (
                              <Badge variant="outline" className="border-[color:var(--brain-ops-warning)] text-[var(--brain-ops-warning)]">
                                {t('matching.ranking.rerankingUnavailable')}
                              </Badge>
                            )}
                          </div>
                          <p className="mt-1 text-sm text-[var(--brain-ops-text-muted)]">
                            {formatMessage(t('matching.ranking.finalScore'), { score: cv.score_final.toFixed(3) })}
                          </p>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2 lg:justify-end">
                          {cv.original_cv_url && (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              title={t('matching.action.downloadCv')}
                              aria-label={formatMessage(t('matching.action.downloadCvLabel'), { candidate: cv.cv })}
                              onClick={() => handleDownloadOriginalCv(cv)}
                            >
                              <FileText className="h-4 w-4" />
                              <span className="sm:hidden xl:inline">{t('matching.action.cv')}</span>
                            </Button>
                          )}
                          {selectedProjectId && results.metadata?.timestamp && (
                            <>
                              <SchedulerButton
                                candidateId={cv.cv}
                                jobId={selectedProjectId}
                                matchingId={results.metadata.timestamp || "manual"}
                                candidateName={cv.cv}
                                candidateEmail={sheetsByCandidate[cv.cv]?.data.identite?.email || null}
                                existingSheetId={sheetsByCandidate[cv.cv]?.id}
                                initialData={{
                                  scheduled_at: sheetsByCandidate[cv.cv]?.scheduled_at,
                                  end_at: sheetsByCandidate[cv.cv]?.data.scheduling?.end_at,
                                  location: sheetsByCandidate[cv.cv]?.location,
                                  scheduler_notes: sheetsByCandidate[cv.cv]?.scheduler_notes,
                                  interviewer: sheetsByCandidate[cv.cv]?.interviewer,
                                  appointment_id: sheetsByCandidate[cv.cv]?.data.scheduling?.appointment_id,
                                }}
                                onUpdate={async () => {
                                  try {
                                    const res = await interviewSheetApi.listAll({ job_id: selectedProjectId });
                                    const map: Record<string, InterviewSheet> = {};
                                    res.sheets.forEach((s) => { map[s.candidate_id] = s; });
                                    setSheetsByCandidate(map);
                                  } catch (err) {
                                    console.error(err);
                                  }
                                }}
                                variant="outline"
                                size="sm"
                              />
                              <InterviewSheetButton
                                candidateId={cv.cv}
                                jobId={selectedProjectId}
                                matchingId={results.metadata.timestamp}
                                variant="outline"
                                size="sm"
                              />
                              <RealtimeInterviewButton
                                projectId={selectedProjectId}
                                candidateId={cv.cv}
                                matchingId={results.metadata.timestamp}
                                interviewSheetId={sheetsByCandidate[cv.cv]?.id}
                                source="matching"
                                candidateName={cv.cv}
                              />
                            </>
                          )}
                      </div>
                    </div>

                    <div className="mt-6 space-y-5 pl-0 sm:pl-10">
                      <dl className="grid gap-px overflow-hidden rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-border)] sm:grid-cols-2 xl:grid-cols-4">
                        <div className="h-full bg-[var(--brain-ops-surface)] p-4">
                          <dt className="text-xs uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">{t('matching.metric.finalScore')}</dt>
                          <dd className="mt-2 text-xl font-semibold text-[var(--brain-ops-text)] [font-family:var(--brain-ops-font-command)]">{cv.score_final.toFixed(3)}</dd>
                        </div>
                        <div className="h-full bg-[var(--brain-ops-surface)] p-4">
                          <dt className="text-xs uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">{t('matching.metric.baseScore')}</dt>
                          <dd className="mt-2 text-xl font-semibold text-[var(--brain-ops-text)] [font-family:var(--brain-ops-font-command)]">{cv.score_base.toFixed(3)}</dd>
                        </div>
                        <div className="h-full bg-[var(--brain-ops-surface)] p-4">
                          <dt className="text-xs uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">{t('matching.metric.niceHave')}</dt>
                          <dd className="mt-2 text-xl font-semibold text-[var(--brain-ops-text)] [font-family:var(--brain-ops-font-command)]">{cv.bonus_nice_have_multiplicateur.toFixed(3)}</dd>
                          {cv.nice_have_manquants?.length > 0 && <p className="mt-1 text-xs text-[var(--brain-ops-warning)]">{formatMessage(t('matching.ranking.missingCount'), { count: cv.nice_have_manquants.length })}</p>}
                        </div>
                        <div className="h-full bg-[var(--brain-ops-surface)] p-4">
                          <dt className="text-xs uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">{t('matching.metric.experience')}</dt>
                          <dd className="mt-2 text-xl font-semibold text-[var(--brain-ops-success)] [font-family:var(--brain-ops-font-command)]">{cv.coefficient_qualite_experience.toFixed(2)}</dd>
                        </div>
                      </dl>

                      {cv.nice_have_manquants && cv.nice_have_manquants.length > 0 && (
                        <div>
                          <p className="mb-2 text-sm font-semibold text-[var(--brain-ops-text)]">{t('matching.ranking.missingNiceHave')}</p>
                          <div className="flex flex-wrap gap-2">
                            {cv.nice_have_manquants.map((item: string, idx: number) => (
                              <Badge key={idx} variant="outline" className="border-[color:var(--brain-ops-warning)] text-[var(--brain-ops-warning)]">
                                {item}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}

                      {cv.commentaire_scoring && (
                        <div>
                          <p className="mb-2 text-sm font-semibold text-[var(--brain-ops-text)]">{t('matching.ranking.scoringAnalysis')}</p>
                          <div className="whitespace-pre-wrap border-l-2 border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-4 text-sm leading-6 text-[var(--brain-ops-text-muted)]">
                            {renderTextWithEvidences(cv.commentaire_scoring, cv.evidences)}
                          </div>
                        </div>
                      )}

                      {cv.appreciation_globale && (
                        <div>
                          <p className="mb-2 text-sm font-semibold text-[var(--brain-ops-text)]">{t('matching.ranking.hrAppreciation')}</p>
                          <div className="whitespace-pre-wrap border-l-2 border-[color:var(--brain-ops-accent)] bg-[var(--brain-ops-accent-soft)] p-4 text-sm leading-6 text-[var(--brain-ops-text)]">
                            {renderTextWithEvidences(cv.appreciation_globale, cv.evidences)}
                          </div>
                        </div>
                      )}

                      <EvidencePanel evidences={cv.evidences} flags={cv.flags} />

                      {isRerankFallback && (
                        <SystemState kind="warning" title={t('matching.ranking.fallbackTitle')} description={t('matching.ranking.fallbackDescription')} />
                      )}
                    </div>
                  </article>
                );
              })}
              </div>
            </Section>
          )}
        </div>
      )}
    </PageFrame>
  );
};
