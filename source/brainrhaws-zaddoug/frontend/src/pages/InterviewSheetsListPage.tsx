import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertCircle, ClipboardList, Calendar, CheckCircle2, Clock, FileText, ChevronRight } from 'lucide-react';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Label } from '../components/ui/label';
import { Select } from '../components/ui/select';
import {
  ContextStrip,
  MetricStrip,
  OperationalList,
  OperationalListItem,
  PageFrame,
  PageHeader,
  Section,
  SystemState,
} from '../components/operations';
import { interviewSheetApi, type InterviewSheet } from '../api/interviewSheet';
import { projectsApi } from '../api/projects';
import type { Project, APIError } from '../api/types';
import { useI18n } from '../i18n/useI18n';
import { candidateLabel } from '../lib/candidateLabel';
import { loadProjectInterviewSheets } from '../lib/interviewScope';
import { useAppStore } from '../stores/useAppStore';
import { useAuth } from '../features/auth/context/AuthContext';

export const InterviewSheetsListPage: React.FC = () => {
  const navigate = useNavigate();
  const { language, t } = useI18n();
  const { user } = useAuth();
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);
  const tenantScope = user?.role === 'platform_admin' ? selectedTenantId : '';
  const { projectId: projectIdFromUrl } = useParams<{ projectId: string }>();
  const [sheets, setSheets] = useState<InterviewSheet[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [selectedProject, setSelectedProject] = useState<string>(projectIdFromUrl || 'all');
  const requestEpoch = useRef(0);
  const scopeKey = `${tenantScope}::${projectIdFromUrl || ''}`;
  const [loadedScope, setLoadedScope] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    const epoch = ++requestEpoch.current;
    try {
      setLoading(true);
      setError(null);
      setSheets([]);
      setProjects([]);

      let projectsData: Project[];
      let scopedSheets: InterviewSheet[];
      if (tenantScope) {
        projectsData = await projectsApi.getAll(undefined, tenantScope);
        scopedSheets = await loadProjectInterviewSheets(
          projectIdFromUrl ? projectsData.filter((project) => project.id === projectIdFromUrl) : projectsData
        );
      } else {
        const [projectResponse, sheetResponse] = await Promise.all([
          projectsApi.getAll(),
          interviewSheetApi.listAll(projectIdFromUrl ? { job_id: projectIdFromUrl } : undefined),
        ]);
        projectsData = projectResponse;
        scopedSheets = sheetResponse.sheets;
      }
      if (epoch !== requestEpoch.current) return;

      setProjects(projectsData);
      setSheets(scopedSheets);
      setSelectedProject(projectIdFromUrl || 'all');
    } catch (err) {
      if (epoch !== requestEpoch.current) return;
      setError(err as APIError);
    } finally {
      if (epoch === requestEpoch.current) {
        setLoadedScope(scopeKey);
        setLoading(false);
      }
    }
  }, [projectIdFromUrl, scopeKey, tenantScope]);

  useEffect(() => {
    void fetchData();
    return () => { requestEpoch.current += 1; };
  }, [fetchData]);

  const handleProjectFilter = (projectId: string) => {
    setSelectedProject(projectId);
    const currentProject = projectIdFromUrl || 'all';
    if (projectId === currentProject) {
      return;
    }

    setLoading(true);
    setError(null);
    if (projectId === 'all') {
      navigate('/interviews');
    } else {
      navigate(`/projects/${projectId}/interviews`);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return <Badge variant="success"><CheckCircle2 className="mr-1 h-3 w-3" /> {t('common.completed')}</Badge>;
      case 'in_progress':
        return <Badge variant="default"><Clock className="mr-1 h-3 w-3" /> {t('common.inProgress')}</Badge>;
      case 'draft':
        return <Badge variant="secondary"><FileText className="mr-1 h-3 w-3" /> {t('common.draft')}</Badge>;
      default:
        return <Badge>{status}</Badge>;
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return new Intl.DateTimeFormat(language, {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    }).format(date);
  };

  if (loading || loadedScope !== scopeKey) {
    return (
      <PageFrame>
        <SystemState
          kind="loading"
          title={t('interviews.loading')}
          indicator={<ClipboardList className="size-5" />}
        />
      </PageFrame>
    );
  }

  const completedCount = sheets.filter((sheet) => sheet.status === 'completed').length;
  const inProgressCount = sheets.filter((sheet) => sheet.status === 'in_progress').length;
  const selectedProjectRecord = projects.find((project) => project.id === selectedProject);
  const pageTitle = selectedProjectRecord ? `${t('interviews.title.project')} ${selectedProjectRecord.nom}` : t('interviews.title.global');
  const pageDescription = selectedProjectRecord
    ? t('interviews.description.project')
    : t('interviews.description.global');

  const pageHeader = (
    <PageHeader
        eyebrow={t('interviews.badge')}
        title={pageTitle}
        description={pageDescription}
    />
  );

  if (error) {
    return (
      <PageFrame>
        {pageHeader}
        <SystemState
          kind="error"
          indicator={<AlertCircle className="size-5" />}
          title={t('interviews.error.title')}
          description={t('interviews.error.description')}
          actionLabel={t('common.retry')}
          action={<Button onClick={() => void fetchData()}>{t('common.retry')}</Button>}
        />
      </PageFrame>
    );
  }

  return (
    <PageFrame>
      {pageHeader}

      <MetricStrip
        ariaLabel={t('interviews.metric.aria')}
        items={[
          { id: 'total', label: t('interviews.metric.total'), value: sheets.length },
          { id: 'completed', label: t('common.completed'), value: completedCount, tone: 'success' },
          { id: 'in-progress', label: t('common.inProgress'), value: inProgressCount },
        ]}
      />

      <ContextStrip
        data-tour="interviews-filter"
        ariaLabel={t('common.filters')}
        items={[]}
        className="border-0 bg-transparent"
        actionsLabel={t('common.filters')}
        actions={
          <div className="flex w-full min-w-0 flex-col gap-1 sm:w-72">
            <Label htmlFor="project-filter">{t('common.project')}</Label>
            <Select
              id="project-filter"
              value={selectedProject}
              onChange={(e) => handleProjectFilter(e.target.value)}
            >
              <option value="all">{t('interviews.filter.allProjects')}</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.nom}
                </option>
              ))}
            </Select>
          </div>
        }
      />

      {sheets.length === 0 ? (
        <SystemState
          kind="empty"
          indicator={<ClipboardList className="size-5" />}
          title={t('interviews.empty.title')}
          description={t('interviews.empty.description')}
        />
      ) : (
        <Section data-tour="interviews-list" ariaLabel={pageTitle} divided={false}>
          <OperationalList ariaLabel={pageTitle}>
            {sheets.map((sheet) => {
              const project = projects.find(p => p.id === sheet.job_id);
              const displayName = candidateLabel(
                { candidateId: sheet.candidate_id, identity: sheet.data.identite },
                t('candidates.fallbackLabel')
              );

              return (
                <OperationalListItem
                  key={sheet.id}
                  leading={
                    <span className="flex size-10 items-center justify-center rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] text-sm font-semibold text-[var(--brain-ops-text)]">
                      {displayName.slice(0, 2).toUpperCase()}
                    </span>
                  }
                  primary={
                    <span className="flex flex-wrap items-center gap-2">
                      <Link
                        to={`/interviews/${sheet.id}`}
                        title={displayName}
                        className="inline-flex min-h-11 max-w-full items-center gap-2 truncate font-medium text-[var(--brain-ops-text)] underline-offset-4 hover:underline"
                      >
                        <span className="truncate">{displayName}</span>
                        <ChevronRight className="size-4 shrink-0 text-[var(--brain-ops-text-muted)]" aria-hidden="true" />
                      </Link>
                      {getStatusBadge(sheet.status)}
                    </span>
                  }
                  secondary={project ? project.nom : t('interviews.projectUnavailable')}
                  metadata={
                    <span className="flex items-center gap-1">
                      <Calendar className="size-3" aria-hidden="true" />
                      {formatDate(sheet.created_at)}
                    </span>
                  }
                />
              );
            })}
          </OperationalList>
        </Section>
      )}
    </PageFrame>
  );
};
