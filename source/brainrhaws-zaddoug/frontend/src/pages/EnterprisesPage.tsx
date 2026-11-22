import { EnterpriseDirectory } from '../features/enterprise-directory/EnterpriseDirectory';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Building2, X } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Select } from '../components/ui/select';
import {
  ContextStrip,
  MetricStrip,
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
import { enterprisesApi } from '../api/enterprises';
import { adminUsersApi } from '../api/adminUsers';
import type { AdminClient, Enterprise, Contact, APIError } from '../api/types';
import { useAuth } from '../features/auth/context/AuthContext';
import { filterEnterprisesByTenant } from '../lib/tenantScope';
import { useAppStore } from '../stores/useAppStore';
import { formatMessage } from '../i18n/formatMessage';
import { useI18n } from '../i18n/useI18n';

export const EnterprisesPage: React.FC = () => {
  const navigate = useNavigate();
  const { t } = useI18n();
  const { user } = useAuth();
  const isPlatformAdmin = user?.role === 'platform_admin';
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);
  const invalidateEnterpriseCatalog = useAppStore((state) => state.invalidateEnterpriseCatalog);
  const requestEpoch = useRef(0);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const [clients, setClients] = useState<AdminClient[]>([]);
  const [clientsLoading, setClientsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [dialogError, setDialogError] = useState<APIError | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [editingEnterprise, setEditingEnterprise] = useState<Enterprise | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [formData, setFormData] = useState({
    nom: '',
    site_web: '',
    secteur: '',
    notes: '',
    contacts: [] as Contact[],
  });
  const [submitting, setSubmitting] = useState(false);
  const [creationTenantId, setCreationTenantId] = useState('');

  const fetchEnterprises = useCallback(async () => {
    const epoch = ++requestEpoch.current;
    try {
      setLoading(true);
      setError(null);
      setEnterprises([]);
      const data = await enterprisesApi.getAll(selectedTenantId || undefined);
      if (epoch !== requestEpoch.current) return;
      setEnterprises(data);
    } catch (err) {
      if (epoch !== requestEpoch.current) return;
      setError(err as APIError);
    } finally {
      if (epoch === requestEpoch.current) {
        setLoadedScope(selectedTenantId);
        setLoading(false);
      }
    }
  }, [selectedTenantId]);

  useEffect(() => {
    setDialogOpen(false);
    setDeleteDialogOpen(false);
    void fetchEnterprises();
    return () => { requestEpoch.current += 1; };
  }, [fetchEnterprises]);

  useEffect(() => {
    if (!isPlatformAdmin) {
      setClients([]);
      return;
    }
    let active = true;
    setClientsLoading(true);
    void adminUsersApi.getClients()
      .then((data) => {
        if (active) setClients([...data].sort((left, right) => left.name.localeCompare(right.name)));
      })
      .catch(() => {
        if (active) setClients([]);
      })
      .finally(() => {
        if (active) setClientsLoading(false);
      });
    return () => { active = false; };
  }, [isPlatformAdmin]);

  const handleOpenDialog = async (enterprise?: Enterprise) => {
    const openingScope = selectedTenantId;
    setDialogError(null);
    setCreationTenantId(selectedTenantId);
    if (enterprise) {
      let detailedEnterprise = enterprise;
      try {
        detailedEnterprise = await enterprisesApi.getById(enterprise.id);
      } catch (err) {
        if (useAppStore.getState().selectedTenantId !== openingScope) return;
        setDialogError(err as APIError);
      }
      if (useAppStore.getState().selectedTenantId !== openingScope) return;
      setEditingEnterprise(detailedEnterprise);
      setFormData({
        nom: detailedEnterprise.nom,
        site_web: detailedEnterprise.site_web || '',
        secteur: detailedEnterprise.secteur || '',
        notes: detailedEnterprise.notes || '',
        contacts: detailedEnterprise.contacts || [],
      });
    } else {
      setEditingEnterprise(null);
      setFormData({
        nom: '',
        site_web: '',
        secteur: '',
        notes: '',
        contacts: [],
      });
    }
    setDialogOpen(true);
  };

  const handleCloseDialog = () => {
    setDialogOpen(false);
    setDialogError(null);
    setEditingEnterprise(null);
    setFormData({
      nom: '',
      site_web: '',
      secteur: '',
      notes: '',
      contacts: [],
    });
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
          notes: '',
        },
      ],
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setDialogError(null);
    if (!editingEnterprise && !clients.some((client) => client.id === creationTenantId)) {
      setDialogError({ code: 'CLIENT_REQUIRED', message: t('clients.creation.missingCabinet') });
      return;
    }
    setSubmitting(true);
    try {
      if (editingEnterprise) {
        await enterprisesApi.update(editingEnterprise.id, formData);
      } else {
        await enterprisesApi.create({ ...formData, tenant_id: creationTenantId });
      }
      invalidateEnterpriseCatalog();
      if (useAppStore.getState().selectedTenantId !== selectedTenantId) return;
      await fetchEnterprises();
      if (useAppStore.getState().selectedTenantId !== selectedTenantId) return;
      handleCloseDialog();
    } catch (err) {
      if (useAppStore.getState().selectedTenantId === selectedTenantId) setDialogError(err as APIError);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!deletingId) return;
    setDialogError(null);
    setSubmitting(true);
    try {
      await enterprisesApi.delete(deletingId);
      invalidateEnterpriseCatalog();
      if (useAppStore.getState().selectedTenantId !== selectedTenantId) return;
      await fetchEnterprises();
      if (useAppStore.getState().selectedTenantId !== selectedTenantId) return;
      handleCloseDeleteDialog();
    } catch (err) {
      if (useAppStore.getState().selectedTenantId === selectedTenantId) setDialogError(err as APIError);
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

  const scopedEnterprises = selectedTenantId
    ? enterprises
    : filterEnterprisesByTenant(enterprises, selectedTenantId);
  const totalProjects = scopedEnterprises.reduce((acc, enterprise) => acc + (enterprise.projects_count || 0), 0);
  const activeEnterprises = scopedEnterprises.length;
  const industries = new Set(scopedEnterprises.map((enterprise) => enterprise.secteur).filter(Boolean));
  const normalizedSearch = searchTerm.trim().toLowerCase();
  const filteredEnterprises = scopedEnterprises.filter((enterprise) =>
    enterprise.nom.toLowerCase().includes(normalizedSearch)
  );
  const hasSearch = normalizedSearch.length > 0;
  const hasFilteredResults = filteredEnterprises.length > 0;

  if (loading || loadedScope !== selectedTenantId) {
    return (
      <PageFrame>
        <SystemState
          kind="loading"
          title={t('clients.loading')}
          indicator={<Building2 className="size-5" />}
        />
      </PageFrame>
    );
  }

  return (
    <PageFrame>
      <PageHeader
        eyebrow={t('clients.badge')}
        title={t('clients.title')}
        description={t('clients.description')}
        backAction={(
          <PageBackButton
            onClick={() => navigate('/')}
            aria-label={t('common.backToDashboard')}
          />
        )}
        actionsLabel={t('clients.list.actions')}
        actions={
          isPlatformAdmin ? (
            <Button onClick={() => void handleOpenDialog()}>
              <Plus data-icon="inline-start" />
              {t('clients.action.add')}
            </Button>
          ) : undefined
        }
      />

      {error && <OperationsErrorBanner error={error} />}

      <ContextStrip
        ariaLabel={t('clients.searchLabel')}
        items={[]}
        className="border-0 bg-transparent"
        actionsLabel={t('clients.searchLabel')}
        actions={
          <>
            <div className="flex w-full min-w-0 flex-col gap-1 sm:w-72">
              <Label htmlFor="client-search">{t('clients.searchLabel')}</Label>
              <Input
                id="client-search"
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder={t('clients.searchPlaceholder')}
              />
            </div>
          </>
        }
      />

      <MetricStrip
        ariaLabel={t('clients.snapshot')}
        items={[
          { id: 'active', label: t('clients.metric.active'), value: activeEnterprises },
          { id: 'projects', label: t('clients.metric.projects'), value: totalProjects },
          { id: 'industries', label: t('clients.metric.industries'), value: industries.size },
        ]}
      />

      {scopedEnterprises.length === 0 ? (
        <SystemState
          kind="empty"
          indicator={<Building2 className="size-5" />}
          title={selectedTenantId ? t('clients.empty.scopeTitle') : t('clients.empty.title')}
          description={
            selectedTenantId
              ? t('clients.empty.scopeDescription')
              : t('clients.empty.description')
          }
        />
      ) : hasFilteredResults ? (
        <Section data-tour="companies-list" ariaLabel={t('clients.title')} divided={false}>
          <EnterpriseDirectory
            key={selectedTenantId || 'all'}
            enterprises={filteredEnterprises}
            canDelete={isPlatformAdmin}
            onEdit={(enterprise) => void handleOpenDialog(enterprise)}
            onDelete={openDeleteDialog}
          />
        </Section>
      ) : (
        <SystemState
          kind="empty"
          indicator={<Building2 className="size-5" />}
          title={hasSearch ? t('clients.noSearchResults') : t('clients.noDisplayResults')}
        />
      )}

      {/* Create/Edit Dialog */}
      <OperationsDialog
        open={dialogOpen}
        onOpenChange={(open) => {
          if (open) setDialogOpen(true);
          else handleCloseDialog();
        }}
      >
        <OperationsDialogContent className="max-w-3xl">
          <OperationsDialogClose />
          <form onSubmit={handleSubmit} className="flex flex-col gap-6">
            <OperationsDialogHeader>
              <OperationsDialogTitle>
                {editingEnterprise ? t('clients.dialog.editTitle') : t('clients.dialog.newTitle')}
              </OperationsDialogTitle>
              {!editingEnterprise && (
                <OperationsDialogDescription>
                  {t('clients.creation.companyHelp')}
                </OperationsDialogDescription>
              )}
              {editingEnterprise?.tenant_id && (
                <OperationsDialogDescription>
                  {t('clients.creation.companyCabinet')} : {editingEnterprise.tenant_name || editingEnterprise.tenant_id}
                </OperationsDialogDescription>
              )}
            </OperationsDialogHeader>
            {dialogError && <OperationsErrorBanner error={dialogError} />}
            <div className="flex flex-col gap-6 py-2">
              {!editingEnterprise && (
                <div className="flex flex-col gap-2">
                  <Label htmlFor="creation-cabinet">{t('clients.creation.companyCabinet')} *</Label>
                  <Select id="creation-cabinet" required value={creationTenantId}
                    disabled={submitting || clientsLoading} onChange={(event) => setCreationTenantId(event.target.value)}>
                    <option value="">{t('clients.creation.selectCabinet')}</option>
                    {clients.map((client) => (
                      <option key={client.id} value={client.id}>{client.name}</option>
                    ))}
                  </Select>
                </div>
              )}
              <fieldset className="flex flex-col gap-4">
                <legend className="mb-4 text-sm font-semibold text-foreground">
                  {t('clients.dialog.basicInfo')}
                </legend>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="nom">{t('clients.creation.companyName')} *</Label>
                  <Input
                    id="nom"
                    value={formData.nom}
                    onChange={(e) => setFormData({ ...formData, nom: e.target.value })}
                    placeholder={t('clients.dialog.namePlaceholder')}
                    required
                    disabled={submitting}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="site_web">{t('clients.dialog.website')}</Label>
                  <Input
                    id="site_web"
                    type="url"
                    value={formData.site_web}
                    onChange={(e) => setFormData({ ...formData, site_web: e.target.value })}
                    placeholder={t('clientDetail.fiche.websitePlaceholder')}
                    disabled={submitting}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="secteur">{t('clients.dialog.industry')}</Label>
                  <Input
                    id="secteur"
                    value={formData.secteur}
                    onChange={(e) => setFormData({ ...formData, secteur: e.target.value })}
                    placeholder={t('clients.dialog.industryPlaceholder')}
                    disabled={submitting}
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="notes">{t('common.notes')}</Label>
                  <Textarea
                    id="notes"
                    value={formData.notes}
                    onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                    placeholder={t('clients.dialog.notesPlaceholder')}
                    rows={3}
                    disabled={submitting}
                  />
                </div>
              </fieldset>

              <fieldset className="flex flex-col gap-4">
                <legend className="mb-4 text-sm font-semibold text-foreground">
                  {t('clients.dialog.contacts')}
                </legend>
                <div className="flex justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={addContact}
                    disabled={submitting}
                  >
                    <Plus data-icon="inline-start" />
                    {t('clients.dialog.addContact')}
                  </Button>
                </div>

                {formData.contacts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t('clients.dialog.noContacts')}</p>
                ) : (
                  <div className="flex flex-col gap-4">
                    {formData.contacts.map((contact, index) => (
                      <div key={index} className="flex flex-col gap-3 rounded-md border bg-muted/20 p-4">
                        <div className="flex items-center justify-between">
                          <h4 className="text-sm font-medium">
                            {t('clients.dialog.contact')} {index + 1}
                          </h4>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            onClick={() => removeContact(index)}
                            disabled={submitting}
                            aria-label={formatMessage(t('clients.dialog.removeContact'), { index: index + 1 })}
                          >
                            <X data-icon="inline-start" />
                          </Button>
                        </div>
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                          <div className="flex flex-col gap-2">
                            <Label htmlFor={`contact-nom-${index}`}>{t('clients.dialog.fullName')} *</Label>
                            <Input
                              id={`contact-nom-${index}`}
                              value={contact.nom_complet}
                              onChange={(e) => updateContact(index, 'nom_complet', e.target.value)}
                              placeholder={t('clientDetail.contacts.fullNamePlaceholder')}
                              required
                              disabled={submitting}
                            />
                          </div>
                          <div className="flex flex-col gap-2">
                            <Label htmlFor={`contact-poste-${index}`}>{t('clients.dialog.jobTitle')}</Label>
                            <Input
                              id={`contact-poste-${index}`}
                              value={contact.poste || ''}
                              onChange={(e) => updateContact(index, 'poste', e.target.value)}
                              placeholder={t('clients.dialog.jobTitlePlaceholder')}
                              disabled={submitting}
                            />
                          </div>
                          <div className="flex flex-col gap-2">
                            <Label htmlFor={`contact-email-${index}`}>
                              {t('clientDetail.contacts.email')} *
                            </Label>
                            <Input
                              id={`contact-email-${index}`}
                              type="email"
                              value={contact.email}
                              onChange={(e) => updateContact(index, 'email', e.target.value)}
                              placeholder={t('clientDetail.contacts.emailPlaceholder')}
                              required
                              disabled={submitting}
                            />
                          </div>
                          <div className="flex flex-col gap-2">
                            <Label htmlFor={`contact-telephone-${index}`}>{t('clients.dialog.phone')}</Label>
                            <Input
                              id={`contact-telephone-${index}`}
                              type="tel"
                              value={contact.telephone || ''}
                              onChange={(e) => updateContact(index, 'telephone', e.target.value)}
                              placeholder={t('clientDetail.contacts.phonePlaceholder')}
                              disabled={submitting}
                            />
                          </div>
                          <div className="flex flex-col gap-2">
                            <Label htmlFor={`contact-canal-${index}`}>{t('clients.dialog.preferredChannel')}</Label>
                            <Select
                              id={`contact-canal-${index}`}
                              value={contact.canal_prefere || 'email'}
                              onChange={(e) => updateContact(index, 'canal_prefere', e.target.value)}
                              disabled={submitting}
                            >
                              <option value="email">{t('clientDetail.contacts.email')}</option>
                              <option value="telephone">{t('clients.dialog.phone')}</option>
                              <option value="slack">Slack</option>
                              <option value="autre">{t('common.other')}</option>
                            </Select>
                          </div>
                          <div className="flex flex-col gap-2 sm:col-span-2">
                            <Label htmlFor={`contact-notes-${index}`}>{t('common.notes')}</Label>
                            <Textarea
                              id={`contact-notes-${index}`}
                              value={contact.notes || ''}
                              onChange={(e) => updateContact(index, 'notes', e.target.value)}
                              placeholder={t('clients.dialog.additionalInfo')}
                              rows={2}
                              disabled={submitting}
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </fieldset>
            </div>
            <OperationsDialogFooter>
              <Button type="button" variant="outline" onClick={handleCloseDialog} disabled={submitting}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? t('common.saving') : editingEnterprise ? t('common.saveChanges')
                  : t('clients.action.create')}
              </Button>
            </OperationsDialogFooter>
          </form>
        </OperationsDialogContent>
      </OperationsDialog>

      {/* Delete Confirmation Dialog */}
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
            <OperationsDialogTitle>{t('clients.delete.title')}</OperationsDialogTitle>
            <OperationsDialogDescription>{t('clients.delete.description')}</OperationsDialogDescription>
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
    </PageFrame>
  );
};
