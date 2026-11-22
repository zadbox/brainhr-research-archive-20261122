import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import {
  BarChart3,
  Briefcase,
  ChevronDown,
  ClipboardList,
  FileText,
  Send,
  Target,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import {
  ContextStrip,
  PageBackButton,
  PageFrame,
  PageHeader,
  Section,
  SystemState,
} from '../components/operations';
import { projectsApi } from '../api/projects';
import { offresApi } from '../api/offres';
import type { Project, Offre, APIError } from '../api/types';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/utils';
import { TurnoverPublicationPanel } from '../components/integrations/TurnoverPublicationPanel';
import { useAuth } from '../features/auth/context/AuthContext';

export const ProjectDetailPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useI18n();
  const { user } = useAuth();
  const refreshRequested = location.state?.refreshData;

  const [project, setProject] = useState<Project | null>(null);
  const [offre, setOffre] = useState<Offre | null>(null);
  const [candidateCount, setCandidateCount] = useState(0);
  const [enterpriseName, setEnterpriseName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [workflowLoading, setWorkflowLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [turnoverOpen, setTurnoverOpen] = useState(false);
  const loadedRequestTokensRef = useRef<Set<string>>(new Set());

  const fetchData = useCallback(async () => {
    if (!projectId) return;

    try {
      setLoading(true);
      setWorkflowLoading(true);
      setError(null);
      setOffre(null);
      setCandidateCount(0);
      setEnterpriseName(null);

      const projectRequest = projectsApi.getById(projectId);
      const workflowRequest = Promise.all([
        offresApi.getByProject(projectId).catch(() => null),
        projectsApi.getCandidateSummary(projectId).catch(() => ({ count: 0, ready: false, enterprise_name: null })),
      ]);

      const projectData = await projectRequest;
      setProject(projectData);
      setLoading(false);

      const [offreData, candidateSummary] = await workflowRequest;
      setOffre(offreData);
      setCandidateCount(candidateSummary.count);
      setEnterpriseName(candidateSummary.enterprise_name ?? null);
    } catch (err) {
      setError(err as APIError);
    } finally {
      setLoading(false);
      setWorkflowLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;

    const initialRequestToken = `${projectId}:initial`;
    const requestToken = refreshRequested
      ? `${projectId}:refresh:${location.key}`
      : initialRequestToken;

    if (loadedRequestTokensRef.current.has(requestToken)) return;

    loadedRequestTokensRef.current.add(requestToken);
    if (refreshRequested) {
      loadedRequestTokensRef.current.add(initialRequestToken);
    }

    void fetchData();

    if (refreshRequested) {
      navigate(location.pathname, { replace: true, state: {} });
    }
  }, [projectId, refreshRequested, fetchData, navigate, location.key, location.pathname]);

  if (loading) {
    return (
      <PageFrame>
        <SystemState
          kind="loading"
          title={t('projectDetail.loading')}
          indicator={<Briefcase className="size-5" />}
        />
      </PageFrame>
    );
  }

  const errorState = error ? (
    <SystemState
      kind="error"
      title={t('common.error')}
      description={t('projectDetail.error.load')}
      actionLabel={t('common.retry')}
      action={
        <Button type="button" variant="outline" onClick={fetchData}>
          {t('common.retry')}
        </Button>
      }
    />
  ) : null;

  if (!project) {
    return (
      <PageFrame>
        {errorState ?? (
          <SystemState kind="empty" title={t('projectDetail.notFound')} />
        )}
      </PageFrame>
    );
  }

  const isArchived = project.status === 'archive';
  const offerReady = Boolean(offre);
  const cvsReady = candidateCount > 0;
  const canLaunchMatching = offerReady && cvsReady && !isArchived;
  const canManageTurnover = user?.role === 'platform_admin' || user?.role === 'client_admin';
  const workflowSteps = [
    {
      label: t('projectDetail.step.offer'),
      description: offerReady ? t('projectDetail.state.structured') : t('projectDetail.state.toPrepare'),
      icon: Briefcase,
      ready: offerReady,
      to: `/projects/${projectId}/offre`,
      tourTarget: 'project-offer-step',
    },
    {
      label: t('projectDetail.step.candidates'),
      description: cvsReady ? `${candidateCount} ${t('projectDetail.state.parsed')}` : t('projectDetail.state.toUpload'),
      icon: FileText,
      ready: cvsReady,
      to: `/projects/${projectId}/cvs`,
      tourTarget: 'project-candidates-step',
    },
    {
      label: t('projectDetail.step.matching'),
      description: canLaunchMatching ? t('projectDetail.state.readyToLaunch') : t('projectDetail.state.locked'),
      icon: Target,
      ready: canLaunchMatching,
      to: `/projects/${projectId}/matching`,
      disabled: !canLaunchMatching,
      tourTarget: 'project-matching-step',
    },
  ];

  return (
    <PageFrame>
      <PageHeader
        eyebrow={t('projectDetail.badge')}
        backAction={(
          <PageBackButton
            onClick={() => (project.enterprise_id ? navigate(`/enterprises/${project.enterprise_id}`) : navigate('/projects'))}
            aria-label={t('common.back')}
          />
        )}
        title={
          <span className="flex min-w-0 flex-wrap items-center gap-3 break-words">
            <span className="min-w-0 break-words">{project.nom}</span>
            <Badge variant={isArchived ? 'secondary' : 'default'}>
              {isArchived ? t('common.archived') : t('common.active')}
            </Badge>
          </span>
        }
        description={t('projectDetail.description')}
      />

      {errorState}

      <ContextStrip
        ariaLabel={t('projectDetail.context.aria')}
        items={[
          {
            id: 'client',
            label: t('common.company'),
            value: project.enterprise_id
              ? enterpriseName || project.enterprise_id
              : '—',
          },
          {
            id: 'hiring-manager',
            label: t('projectDetail.hiringManager'),
            value: project.responsable_offre || t('common.notSpecified'),
            detail: project.contact_responsable || t('projectDetail.noContact'),
          },
          {
            id: 'department',
            label: t('projectDetail.department'),
            value: project.service_demandeur?.trim() || t('common.notSpecified'),
          },
          {
            id: 'status',
            label: t('projectDetail.statusOverview'),
            value: offerReady ? t('projectDetail.offerReady') : t('projectDetail.offerPending'),
            detail: cvsReady ? t('projectDetail.candidatesParsed') : t('projectDetail.candidatesMissing'),
          },
        ]}
      />

      {workflowLoading ? (
        <SystemState
          kind="loading"
          title={t('projectDetail.loading')}
          indicator={<Briefcase className="size-5" />}
        />
      ) : (
        <>
      <Section
        data-tour="project-workflow"
        title={t('projectDetail.workflow.title')}
        description={t('projectDetail.workflow.description')}
        ariaLabel={t('projectDetail.workflow.aria')}
        divided={false}
      >
        <div className="overflow-hidden rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]">
          {workflowSteps.map((step) => {
            const Icon = step.icon;
            return (
              <button
                key={step.label}
                type="button"
                data-tour={step.tourTarget}
                disabled={step.disabled}
                onClick={() => navigate(step.to)}
                className="group flex min-h-16 w-full min-w-0 items-center gap-3 border-b border-[color:var(--brain-ops-border)] px-4 py-3 text-left last:border-b-0 transition-colors duration-[var(--brain-ops-duration-fast)] ease-[var(--brain-ops-ease-ui)] hover:bg-[var(--brain-ops-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--brain-ops-accent)] disabled:cursor-not-allowed disabled:opacity-55 motion-reduce:transition-none"
              >
                <Icon className="size-5 shrink-0 text-[var(--brain-ops-text-muted)]" aria-hidden="true" />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <p className="text-sm font-semibold text-[var(--brain-ops-text)]">{step.label}</p>
                  <p className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">{step.description}</p>
                </div>
                <span
                  aria-hidden="true"
                  className={cn(
                    'size-2.5 shrink-0 rounded-full',
                    step.ready ? 'bg-[var(--brain-ops-success)]' : 'bg-[var(--brain-ops-warning)]'
                  )}
                />
              </button>
            );
          })}
        </div>
        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            <Button
              disabled={!canLaunchMatching}
              onClick={() => navigate(`/projects/${projectId}/matching`)}
            >
              <Target data-icon="inline-start" />
              {t('projectDetail.action.launchMatching')}
            </Button>
            <Button
              variant="outline"
              onClick={() => navigate(`/projects/${projectId}/results`)}
            >
              <BarChart3 data-icon="inline-start" />
              {t('projectDetail.action.viewResults')}
            </Button>
            <Button
              variant="outline"
              onClick={() => navigate(`/projects/${projectId}/interviews`)}
            >
              <ClipboardList data-icon="inline-start" />
              {t('projectDetail.action.openInterviews')}
            </Button>
            {canManageTurnover ? (
              <Button
                type="button"
                variant="outline"
                aria-expanded={turnoverOpen}
                aria-controls="turnover-publication-panel"
                onClick={() => setTurnoverOpen((current) => !current)}
              >
                <Send data-icon="inline-start" />
                {t(turnoverOpen ? 'projectDetail.action.closeTurnover' : 'projectDetail.action.openTurnover')}
                <ChevronDown className={cn('ml-auto size-4 transition-transform motion-reduce:transition-none', turnoverOpen && 'rotate-180')} aria-hidden="true" />
              </Button>
            ) : null}
        </div>
      </Section>

      {canManageTurnover && turnoverOpen ? (
        <Section
          id="turnover-publication-panel"
          title={t('turnover.publication.title')}
          description={t('turnover.publication.description')}
          divided
        >
          <TurnoverPublicationPanel
            projectId={projectId!}
            offerReady={offerReady}
            onOpenCandidates={() => navigate(`/projects/${projectId}/cvs`)}
          />
        </Section>
      ) : null}
        </>
      )}
    </PageFrame>
  );
};
