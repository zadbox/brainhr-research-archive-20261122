import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Plus,
  FolderOpen,
  Archive,
  Save,
  X,
  Building2,
  Mail,
  Phone,
  Globe,
  FileText,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Select } from '../components/ui/select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import {
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
  PageBackButton,
  PageFrame,
  PageHeader,
  Section,
  SystemState,
} from '../components/operations';
import { cvTemplatesApi } from '../api/cvTemplates';
import { enterprisesApi } from '../api/enterprises';
import { projectsApi } from '../api/projects';
import type { Enterprise, Project, APIError, Contact, CompanyCvTemplate } from '../api/types';
import { useAuth } from '../features/auth/context/AuthContext';
import { useToast } from '../hooks/useToast';
import { formatMessage } from '../i18n/formatMessage';
import { useI18n } from '../i18n/useI18n';

export const EnterpriseDetailPage: React.FC = () => {
  const { enterpriseId } = useParams<{ enterpriseId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { success, error: showError } = useToast();
  const { language, t } = useI18n();
  const [enterprise, setEnterprise] = useState<Enterprise | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [templates, setTemplates] = useState<CompanyCvTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  // Form state for editing the company
  const [formData, setFormData] = useState({
    nom: '',
    site_web: '',
    secteur: '',
    notes: '',
    contacts: [] as Contact[]
  });

  // State for creating a project
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [projectPendingArchive, setProjectPendingArchive] = useState<Project | null>(null);
  const [archivingProject, setArchivingProject] = useState(false);
  const [archiveFailed, setArchiveFailed] = useState(false);
  const [projectFormData, setProjectFormData] = useState({
    nom: '',
    enterprise_id: enterpriseId || '',
    service_demandeur: '',
    responsable_offre: '',
    contact_responsable: '',
    notes: ''
  });
  const [submitting, setSubmitting] = useState(false);

  const fetchData = useCallback(async () => {
    if (!enterpriseId) {
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const [enterpriseData, projectsData] = await Promise.all([
        enterprisesApi.getById(enterpriseId),
        projectsApi.getAll(enterpriseId),
      ]);

      setEnterprise(enterpriseData);
      setFormData({
        nom: enterpriseData.nom,
        site_web: enterpriseData.site_web || '',
        secteur: enterpriseData.secteur || '',
        notes: enterpriseData.notes || '',
        contacts: Array.isArray(enterpriseData.contacts) ? enterpriseData.contacts : [],
      });
      setProjects(projectsData);
    } catch (error: unknown) {
      const errorMessage = error && typeof error === 'object' && 'message' in error
        ? String(error.message)
        : 'Unable to load data';

      setError({
        code: 'ENTERPRISE_LOAD_ERROR',
        message: errorMessage,
        details: error,
      });
      showError('Error', errorMessage);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enterpriseId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const fetchTemplates = useCallback(async () => {
    if (!enterpriseId) return;

    try {
      const data = await cvTemplatesApi.list(enterpriseId);
      setTemplates(data);
    } catch (err) {
      console.error('Unable to load CV templates:', err);
      setTemplates([]);
    }
  }, [enterpriseId]);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const handleSave = async () => {
    if (!enterprise) return;

    try {
      setSaving(true);
      await enterprisesApi.update(enterprise.id, formData);
      success(t('clientDetail.toast.saved'));
      setEditing(false);
      // Reload data
      await fetchData();
    } catch (error: unknown) {
      console.error('Unable to save enterprise:', error);
      showError(t('common.error'), t('clientDetail.toast.saveError'));
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (!enterprise) return;
    // Restore original data
    setFormData({
      nom: enterprise.nom,
      site_web: enterprise.site_web || '',
      secteur: enterprise.secteur || '',
      notes: enterprise.notes || '',
      contacts: enterprise.contacts || []
    });
    setEditing(false);
  };

  const addContact = () => {
    setFormData({
      ...formData,
      contacts: [
        ...formData.contacts,
        {
          nom_complet: '',
          email: '',
          poste: '',
          telephone: '',
          canal_prefere: 'email',
          notes: ''
        }
      ]
    });
  };

  const removeContact = (index: number) => {
    setFormData({
      ...formData,
      contacts: formData.contacts.filter((_, i) => i !== index)
    });
  };

  const updateContact = (index: number, field: keyof Contact, value: string) => {
    const updatedContacts = [...formData.contacts];
    updatedContacts[index] = {
      ...updatedContacts[index],
      [field]: value
    };
    setFormData({
      ...formData,
      contacts: updatedContacts
    });
  };

  const handleCreateProject = () => {
    // Open the modal with the enterprise_id prefilled
    setProjectFormData({
      nom: '',
      enterprise_id: enterpriseId || '',
      service_demandeur: '',
      responsable_offre: '',
      contact_responsable: '',
      notes: ''
    });
    setProjectDialogOpen(true);
  };

  const handleCloseProjectDialog = () => {
    setProjectDialogOpen(false);
    setProjectFormData({
      nom: '',
      enterprise_id: enterpriseId || '',
      service_demandeur: '',
      responsable_offre: '',
      contact_responsable: '',
      notes: ''
    });
  };

  const handleSubmitProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!enterpriseId) return;

    setSubmitting(true);
    try {
      // Create the project via the API with enterprise_id
      await projectsApi.create({
        ...projectFormData,
        enterprise_id: enterpriseId
      });
      success(t('clientDetail.toast.projectCreated'));
      handleCloseProjectDialog();
      // Reload data to display the new project
      await fetchData();
    } catch (error: unknown) {
      console.error('Error creating project:', error);
      showError(t('common.error'), t('clientDetail.toast.projectCreateError'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleOpenProject = (projectId: string) => {
    navigate(`/projects/${projectId}`);
  };

  const handleArchiveProject = async () => {
    if (!projectPendingArchive) return;

    setArchivingProject(true);
    setArchiveFailed(false);
    try {
      await projectsApi.delete(projectPendingArchive.id);
      success(t('clientDetail.toast.projectArchived'));
      setProjectPendingArchive(null);
      await fetchData();
    } catch (error: unknown) {
      console.error('Unable to archive project:', error);
      setArchiveFailed(true);
      showError(t('common.error'), t('clientDetail.toast.projectArchiveError'));
    } finally {
      setArchivingProject(false);
    }
  };

  if (loading) {
    return (
      <PageFrame>
        <SystemState
          kind="loading"
          title={t('clientDetail.loading')}
          indicator={<Building2 className="size-5" />}
        />
      </PageFrame>
    );
  }

  if (!enterprise) {
    return (
      <PageFrame>
        {error ? (
          <OperationsErrorBanner error={error} />
        ) : (
          <SystemState kind="empty" title={t('clientDetail.notFound')} />
        )}
      </PageFrame>
    );
  }

  const totalProjects = projects.length;
  const activeProjects = projects.filter((p) => p.status === 'actif').length;
  const archivedProjects = projects.filter((p) => p.status === 'archive').length;
  const activeProjectList = projects.filter((p) => p.status === 'actif');
  const archivedProjectList = projects.filter((p) => p.status === 'archive');
  const canManageTemplates = Boolean(user?.can_manage_users);

  const handleRestoreProject = async (project: Project) => {
    try {
      await projectsApi.update(project.id, {
        nom: project.nom,
        description: project.description || '',
        enterprise_id: project.enterprise_id || enterpriseId || '',
        service_demandeur: project.service_demandeur || '',
        responsable_offre: project.responsable_offre || '',
        contact_responsable: project.contact_responsable || '',
        notes: project.notes || '',
        status: 'actif',
      });
      success(t('clientDetail.toast.projectRestored'));
      await fetchData();
    } catch (error: unknown) {
      console.error('Unable to restore project:', error);
      showError(t('common.error'), t('clientDetail.toast.projectRestoreError'));
    }
  };

  const handleDownloadTemplate = async (templateId: string) => {
    if (!enterpriseId) return;

    try {
      const { blob, filename } = await cvTemplatesApi.download(enterpriseId, templateId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename || 'cv-template.docx';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Unable to download CV template:', err);
      showError(t('common.error'), t('clientDetail.toast.templateDownloadError'));
    }
  };

  const locale = language === 'fr' ? 'fr-FR' : 'en-GB';
  const formatDate = (value?: string | null) => {
    if (!value) return '—';
    return new Date(value).toLocaleDateString(locale, { month: 'short', day: 'numeric', year: 'numeric' });
  };

  return (
    <PageFrame>
      <PageHeader
        eyebrow={t('clientDetail.badge')}
        backAction={(
          <PageBackButton
            onClick={() => navigate('/enterprises')}
            aria-label={t('clientDetail.back.aria')}
          />
        )}
        title={<span className="break-words">{enterprise.nom}</span>}
        description={t('clientDetail.description')}
        context={enterprise.tenant_id ? (
          <p className="text-sm text-[var(--brain-ops-text-muted)]">
            {t('clients.creation.companyCabinet')} :{' '}
            <span className="font-medium text-[var(--brain-ops-text)]">{enterprise.tenant_name || enterprise.tenant_id}</span>
          </p>
        ) : undefined}
        actionsLabel={t('clientDetail.badge')}
        actions={
          <Button onClick={handleCreateProject}>
            <Plus data-icon="inline-start" />
            {t('clientDetail.action.newProject')}
          </Button>
        }
      />

      {error && <OperationsErrorBanner error={error} />}

      <MetricStrip
        ariaLabel={t('clientDetail.metrics.aria')}
        items={[
          { id: 'total', label: t('clientDetail.metric.total'), value: totalProjects },
          { id: 'active', label: t('clientDetail.metric.active'), value: activeProjects, tone: 'success' },
          { id: 'archived', label: t('clientDetail.metric.archived'), value: archivedProjects },
        ]}
      />

      <Tabs defaultValue="dashboard" className="flex min-w-0 flex-col gap-6">
        <div className="max-w-full overflow-x-auto pb-1">
          <TabsList className="w-max justify-start">
            <TabsTrigger value="dashboard">{t('clientDetail.tab.dashboard')}</TabsTrigger>
            <TabsTrigger value="archived">{t('clientDetail.tab.archived')}</TabsTrigger>
            <TabsTrigger value="templates">{t('clientDetail.tab.templates')}</TabsTrigger>
            <TabsTrigger value="fiche">{t('clientDetail.tab.fiche')}</TabsTrigger>
          </TabsList>
        </div>

        {/* Onglet Tableau de bord */}
        <TabsContent value="dashboard" className="flex min-w-0 flex-col gap-6">
          <Section
            data-tour="company-projects"
            title={t('clientDetail.projects.title')}
            description={t('clientDetail.projects.description')}
            divided={false}
          >
            {activeProjectList.length === 0 ? (
              <SystemState
                kind="empty"
                indicator={<FolderOpen className="size-5" />}
                title={t('clientDetail.projects.empty.title')}
                description={t('clientDetail.projects.empty.description')}
              />
            ) : (
              <OperationalList ariaLabel={t('clientDetail.projects.title')}>
                {activeProjectList.map((project) => (
                  <OperationalListItem
                    key={project.id}
                    leading={<FolderOpen className="size-5" />}
                    primary={
                      <button
                        type="button"
                        className="inline-flex min-h-11 min-w-0 items-center break-words text-left underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)] [overflow-wrap:anywhere]"
                        onClick={() => handleOpenProject(project.id)}
                      >
                        {project.nom}
                      </button>
                    }
                    secondary={
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline" className="border-[color:var(--brain-ops-success)] text-[var(--brain-ops-success)]">
                          {t('common.active')}
                        </Badge>
                        <span>{t('clients.createdOn')} {formatDate(project.created_at)}</span>
                      </div>
                    }
                    metadata={
                      <div>{project.service_demandeur || t('projects.department.missing')}</div>
                    }
                    actionsLabel={formatMessage(t('clientDetail.projects.card.aria'), { project: project.nom })}
                    actions={
                      <Button
                        variant="ghost"
                        size="icon"
                        className="brain-shell-touch-target brain-shell-square-target"
                        aria-label={formatMessage(t('clientDetail.projects.archive.aria'), { project: project.nom })}
                        onClick={() => {
                          setArchiveFailed(false);
                          setProjectPendingArchive(project);
                        }}
                      >
                        <Archive data-icon="inline-start" />
                      </Button>
                    }
                  />
                ))}
              </OperationalList>
            )}
          </Section>
        </TabsContent>

        <TabsContent value="archived" className="flex min-w-0 flex-col gap-6">
          <Section
            title={t('clientDetail.archived.title')}
            description={t('clientDetail.archived.description')}
            divided={false}
          >
            {archivedProjectList.length === 0 ? (
              <SystemState
                kind="empty"
                indicator={<Archive className="size-5" />}
                title={t('clientDetail.archived.empty.title')}
                description={t('clientDetail.archived.empty.description')}
              />
            ) : (
              <OperationalList ariaLabel={t('clientDetail.archived.title')}>
                {archivedProjectList.map((project) => (
                  <OperationalListItem
                    key={project.id}
                    leading={<FolderOpen className="size-5" />}
                    primary={
                      <button
                        type="button"
                        className="inline-flex min-h-11 min-w-0 items-center break-words text-left underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)] [overflow-wrap:anywhere]"
                        onClick={() => handleOpenProject(project.id)}
                      >
                        {project.nom}
                      </button>
                    }
                    secondary={
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="secondary">{t('common.archived')}</Badge>
                        <span>{t('clientDetail.archived.completedOn')} {formatDate(project.updated_at || project.created_at)}</span>
                      </div>
                    }
                    actionsLabel={formatMessage(t('clientDetail.projects.card.aria'), { project: project.nom })}
                    actions={
                      <Button
                        variant="ghost"
                        size="sm"
                        className="min-h-11"
                        onClick={() => handleRestoreProject(project)}
                      >
                        {t('clientDetail.archived.restore')}
                      </Button>
                    }
                  />
                ))}
              </OperationalList>
            )}
          </Section>
        </TabsContent>

        <TabsContent value="templates" className="flex min-w-0 flex-col gap-6">
          <Section
            title={t('clientDetail.templates.title')}
            description={t('clientDetail.templates.description')}
            divided={false}
            actionsLabel={t('clientDetail.templates.title')}
            actions={
              canManageTemplates ? (
                <Button onClick={() => navigate('/settings/client-template')}>
                  <FileText data-icon="inline-start" />
                  {t('clientDetail.templates.manage')}
                </Button>
              ) : undefined
            }
          >
            {templates.length === 0 ? (
              <SystemState
                kind="empty"
                indicator={<FileText className="size-5" />}
                title={t('clientDetail.templates.empty.title')}
                description={t('clientDetail.templates.empty.description')}
              />
            ) : (
              <div className="flex min-w-0 flex-col gap-4">
                {templates.map((template) => (
                  <div
                    key={template.id}
                    className="flex min-w-0 flex-col gap-4 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-5"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="flex min-w-0 flex-col gap-1">
                        <p className="break-words text-lg font-semibold text-[var(--brain-ops-text)] [overflow-wrap:anywhere]">
                          {template.name}
                        </p>
                        <p className="break-words text-sm text-[var(--brain-ops-text-muted)] [overflow-wrap:anywhere]">
                          {template.original_filename} · v{template.version}
                        </p>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {template.scope_kind ? <Badge variant="outline">{template.scope_kind}</Badge> : null}
                          {template.tenant_id ? (
                            <Badge variant="secondary">
                              {formatMessage(t('clientDetail.templates.clientScope'), { id: template.tenant_id })}
                            </Badge>
                          ) : (
                            <Badge variant="secondary">{t('clientDetail.templates.enterpriseScope')}</Badge>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {template.is_active ? <Badge>{t('common.active')}</Badge> : null}
                        {!template.is_valid ? (
                          <Badge variant="destructive">{t('clientDetail.templates.invalid')}</Badge>
                        ) : null}
                      </div>
                    </div>
                    <p className="text-sm text-[var(--brain-ops-text-muted)]">
                      {t('clientDetail.templates.uploadedOn')} {new Date(template.created_at).toLocaleString(locale)}
                    </p>
                    <p className="text-sm text-[var(--brain-ops-text-muted)]">
                      {t('clientDetail.templates.scopeNote')}
                    </p>
                    <MetricStrip
                      ariaLabel={t('clientDetail.templates.summaryAria')}
                      items={[
                        {
                          id: 'placeholders',
                          label: t('clientDetail.templates.placeholders'),
                          value: template.detected_variables.length,
                        },
                        {
                          id: 'unsupported',
                          label: t('clientDetail.templates.unsupported'),
                          value: template.unsupported_variables.length,
                          tone: template.unsupported_variables.length > 0 ? 'danger' : 'neutral',
                        },
                        {
                          id: 'roots',
                          label: t('clientDetail.templates.supportedRoots'),
                          value: template.supported_context_roots.length,
                        },
                      ]}
                    />
                    <div className="flex flex-wrap justify-end gap-2">
                      <Button variant="outline" onClick={() => handleDownloadTemplate(template.id)}>
                        <FileText data-icon="inline-start" />
                        {t('clientDetail.templates.download')}
                      </Button>
                      {canManageTemplates ? (
                        <Button variant="outline" onClick={() => navigate('/settings/client-template')}>
                          {t('clientDetail.templates.manageInSettings')}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Section>
        </TabsContent>

        {/* Onglet Fiche entreprise */}
        <TabsContent value="fiche" className="flex min-w-0 flex-col gap-6">
          <Section
            title={t('clientDetail.fiche.title')}
            description={t('clientDetail.fiche.description')}
            divided={false}
            actionsLabel={t('clientDetail.fiche.title')}
            actions={
              !editing ? (
                <Button onClick={() => setEditing(true)}>{t('clientDetail.fiche.edit')}</Button>
              ) : (
                <>
                  <Button variant="outline" onClick={handleCancel} disabled={saving}>
                    <X data-icon="inline-start" />
                    {t('common.cancel')}
                  </Button>
                  <Button onClick={handleSave} disabled={saving}>
                    <Save data-icon="inline-start" />
                    {saving ? t('realtime.plan.saving') : t('llm.action.save')}
                  </Button>
                </>
              )
            }
          >
            <div className="flex min-w-0 flex-col gap-8">
              {/* Basic information */}
              <div className="flex min-w-0 flex-col gap-4">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--brain-ops-text)]">
                  <Building2 className="size-4" aria-hidden="true" />
                  {t('clientDetail.fiche.general')}
                </h3>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div className="flex min-w-0 flex-col gap-2">
                    <Label htmlFor="nom">{t('common.name')} *</Label>
                    {editing ? (
                      <Input
                        id="nom"
                        value={formData.nom}
                        onChange={(e) => setFormData({ ...formData, nom: e.target.value })}
                        placeholder={t('clientDetail.fiche.namePlaceholder')}
                        required
                      />
                    ) : (
                      <p className="text-base font-medium text-[var(--brain-ops-text)]">{enterprise.nom}</p>
                    )}
                  </div>
                  <div className="flex min-w-0 flex-col gap-2">
                    <Label htmlFor="secteur">{t('clients.dialog.industry')}</Label>
                    {editing ? (
                      <Input
                        id="secteur"
                        value={formData.secteur}
                        onChange={(e) => setFormData({ ...formData, secteur: e.target.value })}
                        placeholder={t('clientDetail.fiche.industryPlaceholder')}
                      />
                    ) : (
                      <p className="text-base text-[var(--brain-ops-text)]">{enterprise.secteur || '-'}</p>
                    )}
                  </div>
                  <div className="flex min-w-0 flex-col gap-2 md:col-span-2">
                    <Label htmlFor="site_web" className="flex items-center gap-2">
                      <Globe className="size-4" aria-hidden="true" />
                      {t('clients.dialog.website')}
                    </Label>
                    {editing ? (
                      <Input
                        id="site_web"
                        type="url"
                        value={formData.site_web}
                        onChange={(e) => setFormData({ ...formData, site_web: e.target.value })}
                        placeholder={t('clientDetail.fiche.websitePlaceholder')}
                      />
                    ) : (
                      enterprise.site_web ? (
                        <a href={enterprise.site_web} target="_blank" rel="noopener noreferrer" className="text-base text-primary hover:underline">
                          {enterprise.site_web}
                        </a>
                      ) : (
                        <p className="text-base text-[var(--brain-ops-text-muted)]">-</p>
                      )
                    )}
                  </div>
                  <div className="flex min-w-0 flex-col gap-2 md:col-span-2">
                    <Label htmlFor="notes">{t('common.notes')}</Label>
                    {editing ? (
                      <Textarea
                        id="notes"
                        value={formData.notes}
                        onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                        placeholder={t('clientDetail.fiche.notesPlaceholder')}
                        rows={3}
                      />
                    ) : (
                      <p className="whitespace-pre-wrap text-base text-[var(--brain-ops-text)]">{enterprise.notes || '-'}</p>
                    )}
                  </div>
                </div>
              </div>

              {/* Contacts */}
              <div className="flex min-w-0 flex-col gap-4">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--brain-ops-text)]">
                    <Mail className="size-4" aria-hidden="true" />
                    {t('clientDetail.contacts.title')}
                  </h3>
                  {editing && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={addContact}
                    >
                      <Plus data-icon="inline-start" />
                      {t('clientDetail.contacts.add')}
                    </Button>
                  )}
                </div>

                {formData.contacts.length === 0 ? (
                  <p className="text-base text-[var(--brain-ops-text-muted)]">{t('clientDetail.contacts.empty')}</p>
                ) : (
                  <div className="flex min-w-0 flex-col gap-4">
                    {formData.contacts.map((contact, index) => (
                      <div
                        key={index}
                        className="rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-4"
                      >
                        {editing && (
                          <div className="mb-2 flex justify-end">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              aria-label={formatMessage(t('clientDetail.contacts.remove.aria'), {
                                contact: contact.nom_complet || `#${index + 1}`,
                              })}
                              onClick={() => removeContact(index)}
                            >
                              <X data-icon="inline-start" />
                            </Button>
                          </div>
                        )}
                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                          <div className="flex min-w-0 flex-col gap-2">
                            <Label>{t('clientDetail.contacts.fullName')}</Label>
                            {editing ? (
                              <Input
                                value={contact.nom_complet}
                                onChange={(e) => updateContact(index, 'nom_complet', e.target.value)}
                                placeholder={t('clientDetail.contacts.fullNamePlaceholder')}
                                required
                              />
                            ) : (
                              <p className="text-base font-medium text-[var(--brain-ops-text)]">{contact.nom_complet}</p>
                            )}
                          </div>
                          <div className="flex min-w-0 flex-col gap-2">
                            <Label>{t('clientDetail.contacts.jobTitle')}</Label>
                            {editing ? (
                              <Input
                                value={contact.poste || ''}
                                onChange={(e) => updateContact(index, 'poste', e.target.value)}
                                placeholder={t('clientDetail.contacts.jobTitlePlaceholder')}
                              />
                            ) : (
                              <p className="text-base text-[var(--brain-ops-text)]">{contact.poste || '-'}</p>
                            )}
                          </div>
                          <div className="flex min-w-0 flex-col gap-2">
                            <Label className="flex items-center gap-2">
                              <Mail className="size-3" aria-hidden="true" />
                              {t('clientDetail.contacts.email')}
                            </Label>
                            {editing ? (
                              <Input
                                type="email"
                                value={contact.email}
                                onChange={(e) => updateContact(index, 'email', e.target.value)}
                                placeholder={t('clientDetail.contacts.emailPlaceholder')}
                              />
                            ) : (
                              <a href={`mailto:${contact.email}`} className="text-base text-primary hover:underline">
                                {contact.email}
                              </a>
                            )}
                          </div>
                          <div className="flex min-w-0 flex-col gap-2">
                            <Label className="flex items-center gap-2">
                              <Phone className="size-3" aria-hidden="true" />
                              {t('clientDetail.contacts.phone')}
                            </Label>
                            {editing ? (
                              <Input
                                type="tel"
                                value={contact.telephone || ''}
                                onChange={(e) => updateContact(index, 'telephone', e.target.value)}
                                placeholder={t('clientDetail.contacts.phonePlaceholder')}
                              />
                            ) : (
                              <p className="text-base text-[var(--brain-ops-text)]">{contact.telephone || '-'}</p>
                            )}
                          </div>
                          <div className="flex min-w-0 flex-col gap-2">
                            <Label>{t('clientDetail.contacts.channel')}</Label>
                            {editing ? (
                              <Select
                                value={contact.canal_prefere || 'email'}
                                onChange={(e) => updateContact(index, 'canal_prefere', e.target.value)}
                              >
                                <option value="email">{t('clientDetail.contacts.email')}</option>
                                <option value="telephone">{t('clientDetail.contacts.channel.phone')}</option>
                                <option value="slack">Slack</option>
                                <option value="autre">{t('clientDetail.contacts.channel.other')}</option>
                              </Select>
                            ) : (
                              <p className="text-base capitalize text-[var(--brain-ops-text)]">{contact.canal_prefere || 'email'}</p>
                            )}
                          </div>
                          {(editing || contact.notes) && (
                            <div className="flex min-w-0 flex-col gap-2 md:col-span-2">
                              <Label>{t('common.notes')}</Label>
                              {editing ? (
                                <Textarea
                                  value={contact.notes || ''}
                                  onChange={(e) => updateContact(index, 'notes', e.target.value)}
                                  placeholder={t('clientDetail.contacts.notesPlaceholder')}
                                  rows={2}
                                />
                              ) : (
                                <p className="whitespace-pre-wrap text-base text-[var(--brain-ops-text)]">{contact.notes}</p>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </Section>
        </TabsContent>
      </Tabs>

      <OperationsDialog
        open={projectPendingArchive !== null}
        onOpenChange={(open) => {
          if (!open && !archivingProject) {
            setProjectPendingArchive(null);
            setArchiveFailed(false);
          }
        }}
      >
        <OperationsDialogContent aria-describedby="project-archive-description">
          <OperationsDialogClose disabled={archivingProject} />
          <OperationsDialogHeader>
            <OperationsDialogTitle>{t('clientDetail.projects.archive.title')}</OperationsDialogTitle>
            <OperationsDialogDescription id="project-archive-description">
              {formatMessage(t('clientDetail.projects.archive.description'), {
                project: projectPendingArchive?.nom || '',
              })}
            </OperationsDialogDescription>
          </OperationsDialogHeader>
          {archiveFailed && (
            <SystemState
              kind="error"
              title={t('clientDetail.projects.archive.error.title')}
              description={t('clientDetail.projects.archive.error.description')}
            />
          )}
          <OperationsDialogFooter>
            <Button
              variant="outline"
              onClick={() => setProjectPendingArchive(null)}
              disabled={archivingProject}
            >
              {t('common.cancel')}
            </Button>
            <Button variant="destructive" onClick={() => void handleArchiveProject()} disabled={archivingProject}>
              {archivingProject
                ? t('clientDetail.projects.archive.archiving')
                : t('clientDetail.projects.archive.confirm')}
            </Button>
          </OperationsDialogFooter>
        </OperationsDialogContent>
      </OperationsDialog>

      {/* Project creation dialog */}
      <OperationsDialog
        open={projectDialogOpen}
        onOpenChange={(open) => {
          if (open) setProjectDialogOpen(true);
          else handleCloseProjectDialog();
        }}
      >
        <OperationsDialogContent className="max-w-2xl">
          <OperationsDialogClose />
          <form onSubmit={handleSubmitProject} className="flex flex-col gap-6">
            <OperationsDialogHeader>
              <OperationsDialogTitle>{t('clientDetail.dialog.title')}</OperationsDialogTitle>
            </OperationsDialogHeader>
            <div className="flex flex-col gap-6 py-2">
              {/* Basic information */}
              <fieldset className="flex flex-col gap-4">
                <legend className="mb-4 text-sm font-semibold text-foreground">
                  {t('clientDetail.dialog.basic')}
                </legend>
                <div className="flex min-w-0 flex-col gap-2">
                  <Label htmlFor="project-nom">{t('clientDetail.dialog.name')} *</Label>
                  <Input
                    id="project-nom"
                    value={projectFormData.nom}
                    onChange={(e) => setProjectFormData({ ...projectFormData, nom: e.target.value })}
                    placeholder={t('clientDetail.dialog.namePlaceholder')}
                    required
                    disabled={submitting}
                  />
                </div>
                <div className="flex min-w-0 flex-col gap-2">
                  <Label htmlFor="project-service">{t('clientDetail.dialog.service')}</Label>
                  <Input
                    id="project-service"
                    value={projectFormData.service_demandeur}
                    onChange={(e) => setProjectFormData({ ...projectFormData, service_demandeur: e.target.value })}
                    placeholder={t('clientDetail.dialog.servicePlaceholder')}
                    disabled={submitting}
                  />
                </div>
              </fieldset>

              {/* Contact and follow-up */}
              <fieldset className="flex flex-col gap-4">
                <legend className="mb-4 text-sm font-semibold text-foreground">
                  {t('clientDetail.dialog.contact')}
                </legend>
                <div className="flex min-w-0 flex-col gap-2">
                  <Label htmlFor="project-responsable">{t('projectDetail.hiringManager')}</Label>
                  <Input
                    id="project-responsable"
                    value={projectFormData.responsable_offre}
                    onChange={(e) => setProjectFormData({ ...projectFormData, responsable_offre: e.target.value })}
                    placeholder={t('clientDetail.dialog.managerPlaceholder')}
                    disabled={submitting}
                  />
                </div>
                <div className="flex min-w-0 flex-col gap-2">
                  <Label htmlFor="project-contact">{t('clientDetail.dialog.contactLabel')}</Label>
                  <Input
                    id="project-contact"
                    type="email"
                    value={projectFormData.contact_responsable}
                    onChange={(e) => setProjectFormData({ ...projectFormData, contact_responsable: e.target.value })}
                    placeholder={t('clientDetail.dialog.contactPlaceholder')}
                    disabled={submitting}
                  />
                </div>
              </fieldset>

              {/* Notes */}
              <div className="flex min-w-0 flex-col gap-2">
                <Label htmlFor="project-notes">{t('clientDetail.dialog.notes')}</Label>
                <Textarea
                  id="project-notes"
                  value={projectFormData.notes}
                  onChange={(e) => setProjectFormData({ ...projectFormData, notes: e.target.value })}
                  placeholder={t('clientDetail.dialog.notesPlaceholder')}
                  rows={3}
                  disabled={submitting}
                />
              </div>
            </div>
            <OperationsDialogFooter>
              <Button type="button" variant="outline" onClick={handleCloseProjectDialog} disabled={submitting}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? t('clientDetail.dialog.creating') : t('clientDetail.dialog.create')}
              </Button>
            </OperationsDialogFooter>
          </form>
        </OperationsDialogContent>
      </OperationsDialog>
    </PageFrame>
  );
};
