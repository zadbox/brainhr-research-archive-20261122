import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Plus, Pencil, Trash2, History, FolderOpen, AlertCircle } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Select } from '../components/ui/select';
import { Badge } from '../components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import {
  ContextStrip,
  MetricStrip,
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
  RowActionMenu,
  Section,
  SystemState,
} from '../components/operations';
import { projectsApi } from '../api/projects';
import { enterprisesApi } from '../api/enterprises';
import type { Project, Enterprise, APIError, ProjectHistory } from '../api/types';
import { filterEnterprisesByTenant, filterProjectsByTenant } from '../lib/tenantScope';
import { useAppStore } from '../stores/useAppStore';
import { formatMessage } from '../i18n/formatMessage';
import { useI18n } from '../i18n/useI18n';

export const ProjectsPage: React.FC = () => {
  const navigate = useNavigate();
  const { language, t } = useI18n();
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);
  const [projects, setProjects] = useState<Project[]>([]);
  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const [projectsScopeKey, setProjectsScopeKey] = useState<string | null>(null);
  const [enterprisesScopeKey, setEnterprisesScopeKey] = useState<string | null>(null);
  const [selectedEnterpriseId, setSelectedEnterpriseId] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [fetchFailed, setFetchFailed] = useState(false);
  const [dialogError, setDialogError] = useState<APIError | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState(false);
  const [historyProjectId, setHistoryProjectId] = useState<string | null>(null);
  const [editingProject, setEditingProject] = useState<Project | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [projectHistory, setProjectHistory] = useState<ProjectHistory | null>(null);
  const [formData, setFormData] = useState({
    nom: '',
    enterprise_id: '',
    service_demandeur: '',
    responsable_offre: '',
    contact_responsable: '',
    notes: ''
  });
  const [submitting, setSubmitting] = useState(false);
  const [refreshRevision, setRefreshRevision] = useState(0);
  const projectsRequestId = useRef(0);
  const enterprisesRequestId = useRef(0);
  const historyRequestId = useRef(0);

  const currentEnterpriseScopeKey = selectedTenantId || '__all_clients__';
  const currentProjectsScopeKey = `${currentEnterpriseScopeKey}::${selectedEnterpriseId || '__all_companies__'}`;
  const currentProjectsScopeKeyRef = useRef(currentProjectsScopeKey);
  currentProjectsScopeKeyRef.current = currentProjectsScopeKey;

  const fetchEnterprises = useCallback(async () => {
    const requestId = ++enterprisesRequestId.current;
    const requestScopeKey = selectedTenantId || '__all_clients__';
    setEnterprises([]);
    setEnterprisesScopeKey(null);
    try {
      const data = await enterprisesApi.getAll(selectedTenantId || undefined);
      if (requestId !== enterprisesRequestId.current) return;
      setEnterprises(data);
      setEnterprisesScopeKey(requestScopeKey);
    } catch (err) {
      if (requestId !== enterprisesRequestId.current) return;
      setEnterprises([]);
      setEnterprisesScopeKey(requestScopeKey);
      console.error('Failed to fetch enterprises:', err);
    }
  }, [selectedTenantId]);

  const fetchProjects = useCallback(async (enterpriseId?: string) => {
    const requestId = ++projectsRequestId.current;
    const requestScopeKey = `${selectedTenantId || '__all_clients__'}::${enterpriseId || '__all_companies__'}`;
    setProjects([]);
    setProjectsScopeKey(null);
    try {
      setLoading(true);
      setError(null);
      setFetchFailed(false);
      const data = await projectsApi.getAll(enterpriseId, selectedTenantId || undefined);
      if (requestId !== projectsRequestId.current) return;
      setProjects(data);
      setProjectsScopeKey(requestScopeKey);
    } catch (err) {
      if (requestId !== projectsRequestId.current) return;
      setProjects([]);
      setProjectsScopeKey(requestScopeKey);
      setFetchFailed(true);
      setError(err as APIError);
    } finally {
      if (requestId === projectsRequestId.current) {
        setLoading(false);
      }
    }
  }, [selectedTenantId]);

  useEffect(() => {
    void fetchEnterprises();
  }, [fetchEnterprises]);

  useEffect(() => {
    void fetchProjects(selectedEnterpriseId || undefined);
  }, [fetchProjects, refreshRevision, selectedEnterpriseId]);

  useEffect(() => {
    historyRequestId.current += 1;
    setHistoryDialogOpen(false);
    setProjectHistory(null);
  }, [currentProjectsScopeKey]);

  const scopedEnterprises = useMemo(
    () => (enterprisesScopeKey === currentEnterpriseScopeKey ? enterprises : []),
    [currentEnterpriseScopeKey, enterprises, enterprisesScopeKey]
  );
  const scopedProjects = useMemo(
    () => (projectsScopeKey === currentProjectsScopeKey ? projects : []),
    [currentProjectsScopeKey, projects, projectsScopeKey]
  );
  const visibleEnterprises = useMemo(
    () => (selectedTenantId
      ? scopedEnterprises
      : filterEnterprisesByTenant(scopedEnterprises, selectedTenantId)),
    [scopedEnterprises, selectedTenantId]
  );
  const visibleProjects = useMemo(
    () => (selectedTenantId
      ? scopedProjects
      : filterProjectsByTenant(scopedProjects, scopedEnterprises, selectedTenantId)),
    [scopedProjects, scopedEnterprises, selectedTenantId]
  );
  const selectedEnterpriseStillVisible = !selectedEnterpriseId
    || visibleEnterprises.some((enterprise) => enterprise.id === selectedEnterpriseId);

  useEffect(() => {
    if (!selectedEnterpriseId || enterprisesScopeKey !== currentEnterpriseScopeKey) {
      return;
    }
    if (!selectedEnterpriseStillVisible) {
      setSelectedEnterpriseId('');
    }
  }, [
    currentEnterpriseScopeKey,
    enterprisesScopeKey,
    selectedEnterpriseId,
    selectedEnterpriseStillVisible,
  ]);

  const handleOpenDialog = (project?: Project) => {
    setDialogError(null);
    if (project) {
      setEditingProject(project);
      setFormData({
        nom: project.nom,
        enterprise_id: project.enterprise_id || '',
        service_demandeur: project.service_demandeur || '',
        responsable_offre: project.responsable_offre || '',
        contact_responsable: project.contact_responsable || '',
        notes: project.notes || ''
      });
    } else {
      setEditingProject(null);
      setFormData({
        nom: '',
        enterprise_id: selectedEnterpriseId,
        service_demandeur: '',
        responsable_offre: '',
        contact_responsable: '',
        notes: ''
      });
    }
    setDialogOpen(true);
  };

  const handleCloseDialog = () => {
    setDialogOpen(false);
    setDialogError(null);
    setEditingProject(null);
    setFormData({
      nom: '',
      enterprise_id: '',
      service_demandeur: '',
      responsable_offre: '',
      contact_responsable: '',
      notes: ''
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setDialogError(null);
    setSubmitting(true);
    try {
      if (editingProject) {
        const updated = await projectsApi.update(editingProject.id, formData);
        console.log('✅ Project updated:', updated);
      } else {
        await projectsApi.create(formData);
      }
      handleCloseDialog();
      setRefreshRevision((revision) => revision + 1);
    } catch (err) {
      console.error('❌ Update error:', err);
      setDialogError(err as APIError);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!deletingId) return;
    setDialogError(null);
    setSubmitting(true);
    try {
      await projectsApi.delete(deletingId);
      handleCloseDeleteDialog();
      setRefreshRevision((revision) => revision + 1);
    } catch (err) {
      setDialogError(err as APIError);
    } finally {
      setSubmitting(false);
    }
  };

  const openDeleteDialog = (id: string) => {
    setDialogError(null);
    setDeletingId(id);
    setDeleteDialogOpen(true);
  };

  const handleCloseDeleteDialog = () => {
    setDeleteDialogOpen(false);
    setDeletingId(null);
    setDialogError(null);
  };

  const openHistoryDialog = async (projectId: string) => {
    const requestId = ++historyRequestId.current;
    const requestScopeKey = currentProjectsScopeKey;
    setHistoryProjectId(projectId);
    setProjectHistory(null);
    setHistoryError(false);
    setHistoryLoading(true);
    setHistoryDialogOpen(true);
    try {
      const history = await projectsApi.getHistory(projectId);
      if (
        requestId !== historyRequestId.current
        || requestScopeKey !== currentProjectsScopeKeyRef.current
      ) return;
      setProjectHistory(history);
    } catch {
      if (
        requestId !== historyRequestId.current
        || requestScopeKey !== currentProjectsScopeKeyRef.current
      ) return;
      setHistoryError(true);
    } finally {
      if (
        requestId === historyRequestId.current
        && requestScopeKey === currentProjectsScopeKeyRef.current
      ) {
        setHistoryLoading(false);
      }
    }
  };

  const handleCloseHistoryDialog = () => {
    historyRequestId.current += 1;
    setHistoryDialogOpen(false);
    setHistoryLoading(false);
    setHistoryError(false);
    setHistoryProjectId(null);
    setProjectHistory(null);
  };

  const getEnterpriseName = (enterpriseId?: string) => {
    if (!enterpriseId) return t('projects.company.unassigned');
    const enterprise = visibleEnterprises.find((e) => e.id === enterpriseId);
    return enterprise?.nom || enterpriseId;
  };

  const formatDate = (value?: string | null) => {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '—';
    return date.toLocaleDateString(language === 'fr' ? 'fr-FR' : 'en-GB', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const totalProjects = visibleProjects.length;
  const activeProjects = visibleProjects.filter((project) => project.status === 'actif').length;
  const archivedProjects = visibleProjects.filter((project) => project.status === 'archive').length;
  const lastUpdatedProject = visibleProjects.reduce<Date | null>((latest, project) => {
    if (!project.last_modified) return latest;
    const current = new Date(project.last_modified);
    if (Number.isNaN(current.getTime())) return latest;
    if (!latest || current > latest) return current;
    return latest;
  }, null);
  const lastUpdatedLabel = lastUpdatedProject
    ? lastUpdatedProject.toLocaleDateString(language === 'fr' ? 'fr-FR' : 'en-GB', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
    : '—';

  const renderProjectActions = (project: Project) => (
    <RowActionMenu
      triggerLabel={t('rowActions.trigger')}
      menuLabel={formatMessage(t('projects.actionsFor'), { project: project.nom })}
      items={[
        {
          id: 'history',
          label: t('rowActions.history'),
          icon: <History className="size-4" />,
          onSelect: () => void openHistoryDialog(project.id),
        },
        {
          id: 'edit',
          label: t('rowActions.edit'),
          icon: <Pencil className="size-4" />,
          onSelect: () => handleOpenDialog(project),
        },
        {
          id: 'delete',
          label: t('rowActions.delete'),
          icon: <Trash2 className="size-4" />,
          onSelect: () => openDeleteDialog(project.id),
          destructive: true,
        },
      ]}
    />
  );

  const currentScopeReady = projectsScopeKey === currentProjectsScopeKey
    && enterprisesScopeKey === currentEnterpriseScopeKey
    && selectedEnterpriseStillVisible;

  if (loading || !currentScopeReady) {
    return (
      <PageFrame>
        <SystemState
          kind="loading"
          title={t('projects.loading')}
          indicator={<FolderOpen className="size-5" />}
        />
      </PageFrame>
    );
  }

  const pageHeader = (
    <PageHeader
        eyebrow={t('projects.badge')}
        title={t('projects.title')}
        description={t('projects.description')}
        backAction={(
          <PageBackButton
            onClick={() => navigate(-1)}
            aria-label={t('projects.aria.back')}
          />
        )}
        actionsLabel={t('projects.table.actions')}
        actions={
          <Button onClick={() => handleOpenDialog()}>
            <Plus data-icon="inline-start" />
            {t('projects.action.new')}
          </Button>
        }
    />
  );

  if (error) {
    return (
      <PageFrame>
        {pageHeader}
        <SystemState
          kind="error"
          indicator={<AlertCircle className="size-5" />}
          title={t('projects.error.title')}
          description={t('projects.error.description')}
          actionLabel={t('common.retry')}
          action={(
            <Button onClick={() => void fetchProjects(selectedEnterpriseId || undefined)}>
              {t('common.retry')}
            </Button>
          )}
        />
      </PageFrame>
    );
  }

  return (
    <PageFrame>
      {pageHeader}

      <ContextStrip
        ariaLabel={t('projects.filter.scope')}
        items={[]}
        className="border-0 bg-transparent"
        actionsLabel={t('projects.filter.scope')}
        actions={
          <>
            <div className="flex w-full min-w-0 flex-col gap-1 sm:w-64">
              <Label htmlFor="enterprise-filter">
                {t('projects.filter.companyLabel')}
              </Label>
              <Select
                id="enterprise-filter"
                value={selectedEnterpriseId}
                onChange={(e) => setSelectedEnterpriseId(e.target.value)}
              >
                <option value="">{t('projects.filter.allCompanies')}</option>
                {visibleEnterprises.map((enterprise) => (
                  <option key={enterprise.id} value={enterprise.id}>
                    {enterprise.nom}
                  </option>
                ))}
              </Select>
            </div>
          </>
        }
      />

      <MetricStrip
        ariaLabel={t('projects.badge')}
        items={[
          { id: 'total', label: t('projects.metric.total'), value: fetchFailed ? '—' : totalProjects },
          { id: 'active', label: t('common.active'), value: fetchFailed ? '—' : activeProjects, tone: fetchFailed ? 'neutral' : 'success' },
          { id: 'archived', label: t('common.archived'), value: fetchFailed ? '—' : archivedProjects },
          { id: 'updated', label: t('projects.metric.lastUpdate'), value: lastUpdatedLabel },
        ]}
      />

      {fetchFailed ? null : visibleProjects.length === 0 ? (
        <SystemState
          kind="empty"
          indicator={<FolderOpen className="size-5" />}
          title={selectedTenantId ? t('projects.empty.clientTitle') : t('projects.empty.title')}
          description={
            selectedTenantId
              ? t('projects.empty.clientDescription')
              : t('projects.empty.description')
          }
        />
      ) : (
        <Section data-tour="projects-list" ariaLabel={t('projects.title')} divided={false}>
          <OperationalList ariaLabel={t('projects.title')}>
            {visibleProjects.map((project) => {
              const statusLabel = project.status === 'actif'
                ? t('common.active')
                : t('common.archived');
              const departmentLabel = project.service_demandeur || t('projects.department.missing');
              const managerLabel = project.responsable_offre || t('projects.manager.missing');

              return (
                <OperationalListItem
                  key={project.id}
                  primary={
                    <Link
                      to={`/projects/${project.id}`}
                      className="inline-flex min-h-11 items-center font-medium text-[var(--brain-ops-text)] underline-offset-4 hover:underline"
                    >
                      {project.nom}
                    </Link>
                  }
                  secondary={
                    <div className="flex flex-wrap items-center gap-2">
                      <span>{getEnterpriseName(project.enterprise_id)}</span>
                      {project.status === 'actif' ? (
                        <Badge
                          variant="outline"
                          className="border-[color:var(--brain-ops-success)] text-[var(--brain-ops-success)]"
                        >
                          {statusLabel}
                        </Badge>
                      ) : (
                        <Badge variant="secondary">{statusLabel}</Badge>
                      )}
                    </div>
                  }
                  metadata={
                    <dl className="grid gap-2">
                      <div>
                        <dt className="inline">{t('projects.field.department')}: </dt>
                        <dd className="inline">{departmentLabel}</dd>
                      </div>
                      <div>
                        <dt className="inline">{t('projects.card.manager')} </dt>
                        <dd className="inline">{managerLabel}</dd>
                      </div>
                      <div>
                        <dt className="inline">{t('projects.card.created')}: </dt>
                        <dd className="inline">{formatDate(project.created_at)}</dd>
                      </div>
                      <div>
                        <dt className="inline">{t('projects.metric.lastUpdate')}: </dt>
                        <dd className="inline">{formatDate(project.last_modified)}</dd>
                      </div>
                    </dl>
                  }
                  actionsLabel={t('projects.table.actions')}
                  actions={renderProjectActions(project)}
                />
              );
            })}
          </OperationalList>
        </Section>
      )}

      {/* Create/Edit Dialog */}
      <OperationsDialog
        open={dialogOpen}
        onOpenChange={(open) => {
          if (open) setDialogOpen(true);
          else handleCloseDialog();
        }}
      >
        <OperationsDialogContent className="max-w-2xl">
          <OperationsDialogClose />
          <form onSubmit={handleSubmit} className="flex flex-col gap-6">
            <OperationsDialogHeader>
              <OperationsDialogTitle>
                {editingProject ? t('projects.dialog.editTitle') : t('projects.action.new')}
              </OperationsDialogTitle>
            </OperationsDialogHeader>
            {dialogError && <OperationsErrorBanner error={dialogError} />}
            <div className="flex flex-col gap-6 py-2">
              <fieldset className="flex flex-col gap-4">
                <legend className="mb-4 text-sm font-semibold text-foreground">
                  {t('projects.dialog.basicInfo')}
                </legend>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="nom">{t('projects.field.name')}</Label>
                  <Input
                    id="nom"
                    value={formData.nom}
                    onChange={(e) => setFormData({ ...formData, nom: e.target.value })}
                    placeholder={t('projects.field.namePlaceholder')}
                    required
                    disabled={submitting}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="enterprise_id">{t('projects.field.company')}</Label>
                  <Select
                    id="enterprise_id"
                    value={formData.enterprise_id}
                    onChange={(e) => setFormData({ ...formData, enterprise_id: e.target.value })}
                    disabled={submitting}
                    required
                  >
                    <option value="">{t('projects.field.companyPlaceholder')}</option>
                    {visibleEnterprises.map((enterprise) => (
                      <option key={enterprise.id} value={enterprise.id}>
                        {enterprise.nom}
                      </option>
                    ))}
                  </Select>
                </div>
              </fieldset>

              <fieldset className="flex flex-col gap-4">
                <legend className="mb-4 text-sm font-semibold text-foreground">
                  {t('projects.dialog.additionalDetails')}
                </legend>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="service_demandeur">{t('projects.field.department')}</Label>
                  <Input
                    id="service_demandeur"
                    value={formData.service_demandeur}
                    onChange={(e) => setFormData({ ...formData, service_demandeur: e.target.value })}
                    placeholder={t('projects.field.departmentPlaceholder')}
                    disabled={submitting}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="responsable_offre">{t('projects.field.hiringManager')}</Label>
                  <Input
                    id="responsable_offre"
                    value={formData.responsable_offre}
                    onChange={(e) => setFormData({ ...formData, responsable_offre: e.target.value })}
                    placeholder={t('projects.field.hiringManagerPlaceholder')}
                    disabled={submitting}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="contact_responsable">{t('projects.field.managerContact')}</Label>
                  <Input
                    id="contact_responsable"
                    value={formData.contact_responsable}
                    onChange={(e) => setFormData({ ...formData, contact_responsable: e.target.value })}
                    placeholder={t('projects.field.managerContactPlaceholder')}
                    disabled={submitting}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="notes">{t('common.notes')}</Label>
                  <Textarea
                    id="notes"
                    value={formData.notes}
                    onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                    placeholder={t('projects.field.notesPlaceholder')}
                    rows={3}
                    disabled={submitting}
                  />
                </div>
              </fieldset>
            </div>
            <OperationsDialogFooter>
              <Button type="button" variant="outline" onClick={handleCloseDialog} disabled={submitting}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting
                  ? t('common.saving')
                  : editingProject
                    ? t('common.saveChanges')
                    : t('projects.action.create')}
              </Button>
            </OperationsDialogFooter>
          </form>
        </OperationsDialogContent>
      </OperationsDialog>

      {/* Delete Dialog */}
      <OperationsDialog
        open={deleteDialogOpen}
        onOpenChange={(open) => {
          if (open) setDeleteDialogOpen(true);
          else handleCloseDeleteDialog();
        }}
      >
        <OperationsDialogContent>
          <OperationsDialogClose />
          <OperationsDialogHeader>
            <OperationsDialogTitle>{t('projects.delete.title')}</OperationsDialogTitle>
            <OperationsDialogDescription>{t('projects.delete.description')}</OperationsDialogDescription>
          </OperationsDialogHeader>
          {dialogError && <OperationsErrorBanner error={dialogError} />}
          <OperationsDialogFooter>
            <Button variant="outline" onClick={handleCloseDeleteDialog} disabled={submitting}>
              {t('common.cancel')}
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={submitting}>
              {submitting ? t('common.deleting') : t('common.delete')}
            </Button>
          </OperationsDialogFooter>
        </OperationsDialogContent>
      </OperationsDialog>

      {/* History Dialog */}
      <OperationsDialog
        open={historyDialogOpen}
        onOpenChange={(open) => {
          if (open) setHistoryDialogOpen(true);
          else handleCloseHistoryDialog();
        }}
      >
        <OperationsDialogContent>
          <OperationsDialogClose />
          <OperationsDialogHeader>
            <OperationsDialogTitle>{t('projects.history.title')}</OperationsDialogTitle>
          </OperationsDialogHeader>
          <div className="py-4">
            {historyLoading ? (
              <SystemState kind="loading" title={t('projects.history.loading')} />
            ) : historyError ? (
              <SystemState
                kind="error"
                title={t('projects.history.error.title')}
                description={t('projects.history.error.description')}
                actionLabel={t('common.retry')}
                action={(
                  <Button
                    onClick={() => {
                      if (historyProjectId) void openHistoryDialog(historyProjectId);
                    }}
                  >
                    {t('common.retry')}
                  </Button>
                )}
              />
            ) : projectHistory && projectHistory.total > 0 ? (
              <Table aria-label={t('projects.history.title')}>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('projects.history.timestamp')}</TableHead>
                    <TableHead>{t('projects.history.candidates')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {projectHistory.items.map((item) => (
                    <TableRow key={item.matching_id}>
                      <TableCell>
                        {new Date(item.timestamp).toLocaleString(
                          language === 'fr' ? 'fr-FR' : 'en-GB'
                        )}
                      </TableCell>
                      <TableCell>{item.candidats_count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8">
                {t('projects.history.empty')}
              </p>
            )}
          </div>
        </OperationsDialogContent>
      </OperationsDialog>
    </PageFrame>
  );
};
