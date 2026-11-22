import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Building2, FileText, Sparkles, Trash2, Upload } from 'lucide-react';

import { enterprisesApi } from '../api/enterprises';
import { cvTemplatesApi } from '../api/cvTemplates';
import type { APIError, CompanyCvTemplate, CompanyCvTemplateCandidate, Enterprise } from '../api/types';
import { useAuth } from '../features/auth/context/AuthContext';
import { useToast } from '../hooks/useToast';
import { useAppStore } from '../stores/useAppStore';
import {
  buildTenantScopeOptions,
  tenantScopeLabel,
  type TenantScopeOption,
} from '../lib/tenantScope';
import { LoadingPage } from '../components/shared/Loading';
import { ErrorBanner } from '../components/shared/ErrorBanner';
import { EmptyState } from '../components/shared/EmptyState';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select } from '../components/ui/select';
import { PageFrame } from '../components/operations/PageFrame';
import { PageHeader } from '../components/operations/PageHeader';
import { ContextStrip } from '../components/operations/ContextStrip';
import { useI18n } from '../i18n/useI18n';

export const ClientCvTemplatePage: React.FC = () => {
  const { user } = useAuth();
  const { success, error: showError } = useToast();
  const { language, t } = useI18n();
  const tRef = useRef(t);
  tRef.current = t;
  const inputRef = useRef<HTMLInputElement | null>(null);
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);

  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const [templatesByClientScope, setTemplatesByClientScope] = useState<Record<string, CompanyCvTemplate[]>>({});
  const [selectedClientScopeId, setSelectedClientScopeId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [uploading, setUploading] = useState(false);
  const [busyTemplateId, setBusyTemplateId] = useState<string | null>(null);
  const [mappingTemplates, setMappingTemplates] = useState<Record<string, CompanyCvTemplate>>({});
  const [mappingLoadingTemplateId, setMappingLoadingTemplateId] = useState<string | null>(null);
  const [mappingSavingTemplateId, setMappingSavingTemplateId] = useState<string | null>(null);
  const [sampleRenderingTemplateId, setSampleRenderingTemplateId] = useState<string | null>(null);
  const [sampleHtmlRenderingTemplateId, setSampleHtmlRenderingTemplateId] = useState<string | null>(null);
  const [sampleSheetIds, setSampleSheetIds] = useState<Record<string, string>>({});

  const canManageTemplates = Boolean(user?.can_manage_users);
  const canManageSharedTemplates = user?.role === 'platform_admin' || user?.role === 'client_admin';

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const nextEnterprises = await enterprisesApi.getAll();
      setEnterprises(nextEnterprises);
      const nextClientScopes = buildTenantScopeOptions(nextEnterprises);

      const templateEntries = await Promise.all(
        nextClientScopes.map(async (scope) => {
          const anchorEnterpriseId = scope.enterpriseIds[0];
          if (!anchorEnterpriseId) {
            return [scope.id, []] as const;
          }
          try {
            const templates = await cvTemplatesApi.list(anchorEnterpriseId);
            return [scope.id, templates] as const;
          } catch (templateError) {
            console.error(`Unable to load CV templates for client scope ${scope.id}:`, templateError);
            return [scope.id, []] as const;
          }
        })
      );

      setTemplatesByClientScope(Object.fromEntries(templateEntries));
    } catch (loadError: unknown) {
      const message = loadError instanceof Error ? loadError.message : tRef.current('clientTemplate.error.load');
      setError({ code: 'CLIENT_TEMPLATE_LOAD_ERROR', message });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const allClientScopes = useMemo(
    () => buildTenantScopeOptions(enterprises),
    [enterprises]
  );

  const visibleClientScopes = useMemo(
    () =>
      selectedTenantId
        ? allClientScopes.filter((scope) => scope.id === selectedTenantId)
        : allClientScopes,
    [allClientScopes, selectedTenantId]
  );

  useEffect(() => {
    if (visibleClientScopes.length === 0) {
      if (selectedClientScopeId) {
        setSelectedClientScopeId('');
      }
      return;
    }
    const currentVisible = visibleClientScopes.some((scope) => scope.id === selectedClientScopeId);
    if (!currentVisible) {
      setSelectedClientScopeId(visibleClientScopes[0].id);
    }
  }, [selectedClientScopeId, visibleClientScopes]);

  const selectedClientScope = useMemo<TenantScopeOption | null>(
    () => visibleClientScopes.find((scope) => scope.id === selectedClientScopeId) || null,
    [selectedClientScopeId, visibleClientScopes]
  );

  const anchorEnterpriseId = selectedClientScope?.enterpriseIds[0] || '';
  const selectedClientLabel = selectedClientScope ? tenantScopeLabel(selectedClientScope) : '';

  const selectedTemplates = selectedClientScopeId
    ? templatesByClientScope[selectedClientScopeId] || []
    : [];

  const activeTemplate = selectedTemplates.find((template) => template.is_active) || null;
  const sharedEnterpriseCount = selectedClientScope?.enterpriseCount || 0;
  const sharedMutationRestricted = sharedEnterpriseCount > 1 && !canManageSharedTemplates;

  const triggerUpload = () => {
    inputRef.current?.click();
  };

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !anchorEnterpriseId) {
      return;
    }

    try {
      setUploading(true);
      await cvTemplatesApi.upload(anchorEnterpriseId, file);
      success(activeTemplate ? t('clientTemplate.toast.replaced') : t('clientTemplate.toast.uploaded'));
      await loadData();
    } catch (uploadError) {
      const message = uploadError instanceof Error ? uploadError.message : t('clientTemplate.error.upload');
      showError(t('clientTemplate.error.title'), message);
    } finally {
      setUploading(false);
      if (inputRef.current) {
        inputRef.current.value = '';
      }
    }
  };

  const handleActivate = async (templateId: string) => {
    if (!anchorEnterpriseId) {
      return;
    }
    try {
      setBusyTemplateId(templateId);
      await cvTemplatesApi.activate(anchorEnterpriseId, templateId);
      success(t('clientTemplate.toast.activated'));
      await loadData();
    } catch (activateError) {
      const message = activateError instanceof Error ? activateError.message : t('clientTemplate.error.activate');
      showError(t('clientTemplate.error.title'), message);
    } finally {
      setBusyTemplateId(null);
    }
  };

  const handleDelete = async (templateId: string, templateName: string) => {
    if (!anchorEnterpriseId) {
      return;
    }
    const confirmed = window.confirm(
      t('clientTemplate.confirm.delete')
        .replace('{{template}}', templateName)
        .replace('{{client}}', selectedClientLabel || selectedClientScopeId)
    );
    if (!confirmed) {
      return;
    }

    try {
      setBusyTemplateId(templateId);
      await cvTemplatesApi.delete(anchorEnterpriseId, templateId);
      success(t('clientTemplate.toast.deleted'));
      await loadData();
    } catch (deleteError) {
      const message = deleteError instanceof Error ? deleteError.message : t('clientTemplate.error.delete');
      showError(t('clientTemplate.error.title'), message);
    } finally {
      setBusyTemplateId(null);
    }
  };

  const handleDownload = async (templateId: string) => {
    if (!anchorEnterpriseId) {
      return;
    }

    try {
      const { blob, filename } = await cvTemplatesApi.download(anchorEnterpriseId, templateId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename || 'client-cv-template.docx';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (downloadError) {
      const message = downloadError instanceof Error ? downloadError.message : t('clientTemplate.error.download');
      showError(t('clientTemplate.error.title'), message);
    }
  };

  const handleLoadMapping = async (templateId: string) => {
    if (!anchorEnterpriseId) {
      return;
    }
    try {
      setMappingLoadingTemplateId(templateId);
      const template = withSuggestedMappings(
        await cvTemplatesApi.getMapping(anchorEnterpriseId, templateId)
      );
      setMappingTemplates((current) => ({ ...current, [templateId]: template }));
    } catch (mappingError) {
      const message = mappingError instanceof Error ? mappingError.message : t('clientTemplate.error.mappingLoad');
      showError(t('clientTemplate.error.title'), message);
    } finally {
      setMappingLoadingTemplateId(null);
    }
  };

  const handleMappingCandidateChange = (
    templateId: string,
    sectionName: string,
    candidateId: string
  ) => {
    setMappingTemplates((current) => {
      const template = current[templateId];
      if (!template?.layout_spec) {
        return current;
      }
      const supportedSections = template.layout_spec.supported_sections || {};
      const currentMapping = template.layout_spec.confirmed_mappings?.[sectionName];
      const nextRenderType =
        currentMapping?.render_type ||
        supportedSections[sectionName]?.render_type ||
        'block';
      const nextConfirmedMappings = { ...(template.layout_spec.confirmed_mappings || {}) };
      if (!candidateId) {
        delete nextConfirmedMappings[sectionName];
      } else {
        nextConfirmedMappings[sectionName] = {
          candidate_id: candidateId,
          render_type: nextRenderType,
          style_source: candidateId,
        };
      }
      return {
        ...current,
        [templateId]: {
          ...template,
          layout_spec: {
            ...template.layout_spec,
            confirmed_mappings: nextConfirmedMappings,
          },
        },
      };
    });
  };

  const handleMappingRenderTypeChange = (
    templateId: string,
    sectionName: string,
    renderType: string
  ) => {
    setMappingTemplates((current) => {
      const template = current[templateId];
      if (!template?.layout_spec) {
        return current;
      }
      const nextConfirmedMappings = { ...(template.layout_spec.confirmed_mappings || {}) };
      const existing = nextConfirmedMappings[sectionName];
      if (!existing) {
        return current;
      }
      nextConfirmedMappings[sectionName] = {
        ...existing,
        render_type: renderType,
      };
      return {
        ...current,
        [templateId]: {
          ...template,
          layout_spec: {
            ...template.layout_spec,
            confirmed_mappings: nextConfirmedMappings,
          },
        },
      };
    });
  };

  const handleSaveMapping = async (templateId: string) => {
    if (!anchorEnterpriseId || !selectedClientScopeId) {
      return;
    }
    const template = mappingTemplates[templateId];
    if (!template?.layout_spec) {
      return;
    }
    try {
      setMappingSavingTemplateId(templateId);
      const updated = await cvTemplatesApi.updateMapping(
        anchorEnterpriseId,
        templateId,
        template.layout_spec.confirmed_mappings || {}
      );
      setMappingTemplates((current) => ({ ...current, [templateId]: updated }));
      setTemplatesByClientScope((current) => ({
        ...current,
        [selectedClientScopeId]: (current[selectedClientScopeId] || []).map((item) =>
          item.id === templateId ? updated : item
        ),
      }));
      success(t('clientTemplate.toast.mappingSaved'));
    } catch (saveError) {
      const message = saveError instanceof Error ? saveError.message : t('clientTemplate.error.mappingSave');
      showError(t('clientTemplate.error.title'), message);
    } finally {
      setMappingSavingTemplateId(null);
    }
  };

  const handleSampleRender = async (templateId: string) => {
    if (!anchorEnterpriseId) {
      return;
    }
    const sheetId = (sampleSheetIds[templateId] || '').trim();
    if (!sheetId) {
      showError(t('clientTemplate.error.title'), t('clientTemplate.error.sampleSheetRequired'));
      return;
    }
    try {
      setSampleRenderingTemplateId(templateId);
      const { blob, filename } = await cvTemplatesApi.sampleRender(anchorEnterpriseId, templateId, sheetId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename || 'sample-company-cv.docx';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      success(t('clientTemplate.toast.sampleGenerated'));
    } catch (sampleError) {
      const message = sampleError instanceof Error ? sampleError.message : t('clientTemplate.error.sampleGenerate');
      showError(t('clientTemplate.error.title'), message);
    } finally {
      setSampleRenderingTemplateId(null);
    }
  };

  const handleSampleRenderHtmlDocx = async (templateId: string) => {
    if (!anchorEnterpriseId) {
      return;
    }
    const sheetId = (sampleSheetIds[templateId] || '').trim();
    if (!sheetId) {
      showError(t('clientTemplate.error.title'), t('clientTemplate.error.sampleSheetRequired'));
      return;
    }
    try {
      setSampleHtmlRenderingTemplateId(templateId);
      const { blob, filename } = await cvTemplatesApi.sampleRenderHtmlDocx(anchorEnterpriseId, templateId, sheetId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename || 'sample-company-cv-html-docx.docx';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      success(t('clientTemplate.toast.htmlSampleGenerated'));
    } catch (sampleError) {
      const message = sampleError instanceof Error ? sampleError.message : t('clientTemplate.error.htmlSampleGenerate');
      showError(t('clientTemplate.error.title'), message);
    } finally {
      setSampleHtmlRenderingTemplateId(null);
    }
  };

  const withSuggestedMappings = (template: CompanyCvTemplate): CompanyCvTemplate => {
    const layoutSpec = template.layout_spec;
    if (!layoutSpec) {
      return template;
    }

    const supportedSections = layoutSpec.supported_sections || {};
    const candidates = layoutSpec.candidates || [];
    const nextConfirmedMappings = { ...(layoutSpec.confirmed_mappings || {}) };

    Object.entries(supportedSections).forEach(([sectionName, sectionSpec]) => {
      if (nextConfirmedMappings[sectionName]) {
        return;
      }
      const matchingCandidates = candidates.filter((candidate) =>
        candidateMatchesSection(candidate, sectionName)
      );
      const defaultCandidate = matchingCandidates[0];
      if (!defaultCandidate) {
        return;
      }
      nextConfirmedMappings[sectionName] = {
        candidate_id: defaultCandidate.candidate_id,
        render_type: sectionSpec.render_type,
        style_source: defaultCandidate.candidate_id,
      };
    });

    return {
      ...template,
      layout_spec: {
        ...layoutSpec,
        confirmed_mappings: nextConfirmedMappings,
      },
    };
  };

  const candidateMatchesSection = (
    candidate: CompanyCvTemplateCandidate,
    sectionName: string
  ) => {
    return (
      candidate.section_name_hint === sectionName ||
      candidate.anchor === sectionName ||
      candidate.candidate_id === `heuristic:${sectionName}` ||
      candidate.candidate_id === `anchor:sdt:${sectionName}` ||
      candidate.candidate_id === `anchor:bookmark:${sectionName}`
    );
  };

  const candidateDisplayLabel = (
    candidate: CompanyCvTemplateCandidate
  ) => {
    const sourceLabel =
      candidate.anchor_type === 'placeholder_group'
        ? t('clientTemplate.mapping.source.heuristic')
        : candidate.anchor_type === 'sdt'
          ? t('clientTemplate.mapping.source.contentControl')
          : candidate.anchor_type === 'bookmark'
            ? t('clientTemplate.mapping.source.bookmark')
            : candidate.anchor_type || candidate.source || t('clientTemplate.mapping.source.candidate');
    const targetLabel = candidate.section_name_hint || candidate.anchor || candidate.candidate_id;
    return `${sourceLabel} → ${targetLabel}${candidate.inside_fixed_container ? ` (${t('clientTemplate.mapping.fixedContainer')})` : ''}`;
  };

  if (loading) {
    return <LoadingPage text={t('clientTemplate.loading')} />;
  }

  if (error) {
    return (
      <PageFrame>
        <ErrorBanner error={error} />
      </PageFrame>
    );
  }

  return (
    <PageFrame width="wide">
      <input
        ref={inputRef}
        type="file"
        accept=".docx"
        className="hidden"
        onChange={(event) => void handleUpload(event)}
      />

      <PageHeader
        eyebrow={t('clientTemplate.eyebrow')}
        title={t('clientTemplate.title')}
        description={t('clientTemplate.description')}
        context={
          <ContextStrip
            ariaLabel={t('clientTemplate.context.aria')}
            items={[
              {
                id: 'client',
                label: t('clientTemplate.context.client'),
                value: selectedClientLabel || t('clientTemplate.context.notSelected'),
              },
              {
                id: 'companies',
                label: t('clientTemplate.context.companies'),
                value: String(sharedEnterpriseCount),
              },
              {
                id: 'active-template',
                label: t('clientTemplate.context.activeTemplate'),
                value: activeTemplate?.name || t('clientTemplate.context.none'),
              },
            ]}
          />
        }
      />

      {visibleClientScopes.length === 0 ? (
        <EmptyState
          icon={FileText}
          title={selectedTenantId ? t('clientTemplate.empty.filteredTitle') : t('clientTemplate.empty.title')}
          description={
            selectedTenantId
              ? t('clientTemplate.empty.filteredDescription')
              : t('clientTemplate.empty.description')
          }
        />
      ) : (
        <div className="min-w-0 space-y-6">
          <Card className="min-w-0">
            <CardHeader className="min-w-0">
              <CardTitle>{t('clientTemplate.scope.title')}</CardTitle>
              <CardDescription>
                {t('clientTemplate.scope.description')}
              </CardDescription>
            </CardHeader>
            <CardContent className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,320px)_1fr]">
              <div className="min-w-0 space-y-2">
                <Label htmlFor="client-template-select">{t('clientTemplate.scope.client')}</Label>
                <Select
                  id="client-template-select"
                  className="min-w-0 max-w-full"
                  value={selectedClientScopeId}
                  onChange={(event) => setSelectedClientScopeId(event.target.value)}
                >
                  {visibleClientScopes.map((scope) => (
                    <option key={scope.id} value={scope.id}>
                      {tenantScopeLabel(scope)}
                    </option>
                  ))}
                </Select>
              </div>
              {selectedClientScope ? (
                <div className="min-w-0 rounded-2xl border bg-muted/20 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary" className="max-w-full whitespace-normal break-words [overflow-wrap:anywhere]">
                      <Building2 className="mr-1 h-3.5 w-3.5" />
                      {selectedClientLabel}
                    </Badge>
                    <Badge variant="outline">
                      {sharedEnterpriseCount}{' '}
                      {sharedEnterpriseCount > 1
                        ? t('clientTemplate.scope.companies')
                        : t('clientTemplate.scope.company')}
                    </Badge>
                    {activeTemplate
                      ? <Badge>{t('clientTemplate.scope.activeTemplate')}</Badge>
                      : <Badge variant="outline">{t('clientTemplate.scope.noActiveTemplate')}</Badge>}
                  </div>
                  <p className="mt-3 text-sm text-muted-foreground">
                    {t('clientTemplate.scope.sharedDescription')}
                  </p>
                  {sharedEnterpriseCount > 1 ? (
                    <div className="mt-3 flex items-start gap-2 rounded-xl border border-amber-400/40 bg-amber-500/10 p-3 text-sm text-amber-950 dark:text-amber-100">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                      <p>
                        {t('clientTemplate.scope.sharedWarning')
                          .replace('{{count}}', String(sharedEnterpriseCount))}
                      </p>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card className="min-w-0">
            <CardHeader className="min-w-0">
              <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <CardTitle>{t('clientTemplate.management.title')}</CardTitle>
                  <CardDescription>
                    {t('clientTemplate.management.description')}
                  </CardDescription>
                </div>
                <div className="flex flex-wrap gap-2">
                  {canManageTemplates ? (
                    <Button onClick={triggerUpload} disabled={uploading || sharedMutationRestricted || !anchorEnterpriseId}>
                      <Upload className="mr-2 h-4 w-4" />
                      {activeTemplate ? t('clientTemplate.management.replace') : t('clientTemplate.management.upload')}
                    </Button>
                  ) : null}
                </div>
              </div>
            </CardHeader>
            <CardContent className="min-w-0 space-y-4">
              {sharedMutationRestricted ? (
                <div className="rounded-2xl border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
                  {t('clientTemplate.management.restricted')}
                </div>
              ) : null}

              {selectedTemplates.length === 0 ? (
                <EmptyState
                  icon={FileText}
                  title={t('clientTemplate.management.emptyTitle')}
                  description={t('clientTemplate.management.emptyDescription')}
                />
              ) : (
                selectedTemplates.map((template) => {
                  const mappedTemplate = mappingTemplates[template.id] || withSuggestedMappings(template);
                  const layoutSpec = mappedTemplate.layout_spec || null;
                  const supportedSections = layoutSpec?.supported_sections || {};
                  const confirmedMappings = layoutSpec?.confirmed_mappings || {};
                  const candidates = layoutSpec?.candidates || [];

                  return (
                  <Card key={template.id} className="min-w-0 overflow-hidden bg-muted/20">
                    <CardHeader className="min-w-0">
                      <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
                        <div className="min-w-0">
                          <CardTitle className="break-words text-lg [overflow-wrap:anywhere]">{mappedTemplate.name}</CardTitle>
                          <CardDescription className="break-words [overflow-wrap:anywhere]">
                            {mappedTemplate.original_filename} · v{mappedTemplate.version}
                          </CardDescription>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {mappedTemplate.is_active ? <Badge>{t('clientTemplate.template.active')}</Badge> : null}
                            {!mappedTemplate.is_valid ? <Badge variant="destructive">{t('clientTemplate.template.invalid')}</Badge> : null}
                            {mappedTemplate.scope_kind ? <Badge variant="outline">{mappedTemplate.scope_kind}</Badge> : null}
                            {mappedTemplate.render_mode ? <Badge variant="secondary">{mappedTemplate.render_mode}</Badge> : null}
                            {mappedTemplate.layout_spec_status ? <Badge variant="outline">{mappedTemplate.layout_spec_status}</Badge> : null}
                          </div>
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="min-w-0 space-y-4">
                      <p className="text-sm text-muted-foreground">
                        {t('clientTemplate.template.uploadedOn')}{' '}
                        {new Date(mappedTemplate.created_at).toLocaleString(language === 'fr' ? 'fr-FR' : 'en-GB')}
                      </p>
                      <div className="space-y-2">
                        <p className="text-sm font-medium">{t('clientTemplate.template.detectedPlaceholders')}</p>
                        <div className="flex flex-wrap gap-2">
                          {mappedTemplate.detected_variables.length > 0 ? (
                            mappedTemplate.detected_variables.map((variable) => (
                              <Badge key={variable} variant="outline" className="max-w-full whitespace-normal text-left leading-5">
                                <span className="min-w-0 break-all">{variable}</span>
                              </Badge>
                            ))
                          ) : (
                            <span className="text-sm text-muted-foreground">{t('clientTemplate.template.noPlaceholder')}</span>
                          )}
                        </div>
                      </div>
                      {mappedTemplate.unsupported_variables.length > 0 ? (
                        <div className="space-y-2">
                          <p className="text-sm font-medium text-destructive">{t('clientTemplate.template.unsupportedPlaceholders')}</p>
                          <div className="flex flex-wrap gap-2">
                            {mappedTemplate.unsupported_variables.map((variable) => (
                              <Badge key={variable} variant="destructive" className="max-w-full whitespace-normal text-left leading-5">
                                <span className="min-w-0 break-all">{variable}</span>
                              </Badge>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {mappedTemplate.layout_spec_errors && mappedTemplate.layout_spec_errors.length > 0 ? (
                        <div className="space-y-2">
                          <p className="text-sm font-medium text-destructive">{t('clientTemplate.template.layoutErrors')}</p>
                          <ul className="list-disc space-y-1 pl-5 text-sm text-destructive">
                            {mappedTemplate.layout_spec_errors.map((entry) => (
                              <li key={entry}>{entry}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      {mappedTemplate.layout_spec_warnings && mappedTemplate.layout_spec_warnings.length > 0 ? (
                        <div className="space-y-2">
                          <p className="text-sm font-medium text-amber-700 dark:text-amber-300">{t('clientTemplate.template.layoutWarnings')}</p>
                          <ul className="list-disc space-y-1 pl-5 text-sm text-amber-700">
                            {mappedTemplate.layout_spec_warnings.map((entry) => (
                              <li key={entry}>{entry}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      <div className="min-w-0 overflow-hidden rounded-2xl border bg-background/80 p-4">
                        <div className="mb-4 flex min-w-0 flex-wrap items-center justify-between gap-2">
                          <div className="min-w-0">
                            <p className="text-sm font-medium">{t('clientTemplate.mapping.title')}</p>
                            <p className="text-sm text-muted-foreground">
                              {t('clientTemplate.mapping.description')}
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <Button
                              variant="outline"
                              onClick={() => void handleLoadMapping(template.id)}
                              disabled={mappingLoadingTemplateId === template.id}
                            >
                              <Sparkles className="mr-2 h-4 w-4" />
                              {mappingLoadingTemplateId === template.id
                                ? t('clientTemplate.mapping.loading')
                                : t('clientTemplate.mapping.load')}
                            </Button>
                            {layoutSpec ? (
                              <Button
                                variant="outline"
                                onClick={() => void handleSaveMapping(template.id)}
                                disabled={mappingSavingTemplateId === template.id || sharedMutationRestricted}
                              >
                                {mappingSavingTemplateId === template.id
                                  ? t('clientTemplate.mapping.saving')
                                  : t('clientTemplate.mapping.save')}
                              </Button>
                            ) : null}
                          </div>
                        </div>

                        {layoutSpec ? (
                          <div className="min-w-0 space-y-4">
                            <div className="grid min-w-0 gap-4 lg:grid-cols-2">
                              <div className="min-w-0 space-y-2">
                                <Label htmlFor={`sample-sheet-${template.id}`}>{t('clientTemplate.mapping.sampleSheetId')}</Label>
                                <Input
                                  id={`sample-sheet-${template.id}`}
                                  className="min-w-0 max-w-full"
                                  value={sampleSheetIds[template.id] || ''}
                                  onChange={(event) =>
                                    setSampleSheetIds((current) => ({
                                      ...current,
                                      [template.id]: event.target.value,
                                    }))
                                  }
                                  placeholder="3bad431c-b2c1-4426-9574-2b8f2d70214f"
                                />
                              </div>
                              <div className="flex flex-wrap items-end gap-2">
                                <Button
                                  variant="outline"
                                  onClick={() => void handleSampleRender(template.id)}
                                  disabled={sampleRenderingTemplateId === template.id}
                                >
                                  {sampleRenderingTemplateId === template.id
                                    ? t('clientTemplate.mapping.generating')
                                    : t('clientTemplate.mapping.runSample')}
                                </Button>
                                <Button
                                  variant="outline"
                                  onClick={() => void handleSampleRenderHtmlDocx(template.id)}
                                  disabled={sampleHtmlRenderingTemplateId === template.id}
                                >
                                  {sampleHtmlRenderingTemplateId === template.id
                                    ? t('clientTemplate.mapping.generatingHtml')
                                    : t('clientTemplate.mapping.runHtmlSample')}
                                </Button>
                              </div>
                            </div>

                            <div className="space-y-3">
                              <div className="space-y-1">
                                <p className="text-sm font-medium">{t('clientTemplate.mapping.sections')}</p>
                                <p className="text-xs text-muted-foreground">
                                  {t('clientTemplate.mapping.deterministicDescription')}
                                </p>
                                <p className="text-xs text-muted-foreground">
                                  {t('clientTemplate.mapping.localDescription')}
                                </p>
                              </div>
                              {Object.keys(supportedSections).length > 0 ? (
                                Object.entries(supportedSections).map(([sectionName, sectionSpec]) => {
                                  const selectedMapping = confirmedMappings[sectionName];
                                  const sectionCandidates = candidates.filter((candidate) =>
                                    candidateMatchesSection(candidate, sectionName)
                                  );
                                  const selectedCandidate =
                                    sectionCandidates.find((candidate) => candidate.candidate_id === selectedMapping?.candidate_id) ||
                                    candidates.find((candidate) => candidate.candidate_id === selectedMapping?.candidate_id);
                                  return (
                                    <div key={sectionName} className="grid min-w-0 gap-3 overflow-hidden rounded-xl border p-3 lg:grid-cols-[minmax(0,240px)_minmax(0,1fr)_180px]">
                                      <div className="min-w-0">
                                        <p className="break-words text-sm font-medium [overflow-wrap:anywhere]">{sectionName}</p>
                                        <p className="text-xs text-muted-foreground">
                                          {sectionSpec.required
                                            ? t('clientTemplate.mapping.required')
                                            : t('clientTemplate.mapping.optional')}{' '}
                                          · {t('clientTemplate.mapping.default')} {sectionSpec.render_type}
                                        </p>
                                        {selectedCandidate ? (
                                          <p className="mt-1 text-xs text-muted-foreground">
                                            {t('clientTemplate.mapping.selected')}: {candidateDisplayLabel(selectedCandidate)}
                                          </p>
                                        ) : sectionCandidates.length > 0 ? (
                                          <p className="mt-1 text-xs text-muted-foreground">
                                            {t('clientTemplate.mapping.suggested')}: {candidateDisplayLabel(sectionCandidates[0])}
                                          </p>
                                        ) : (
                                          <p className="mt-1 text-xs text-muted-foreground">
                                            {t('clientTemplate.mapping.noMatchingCandidate')}
                                          </p>
                                        )}
                                      </div>
                                      <Select
                                        className="min-w-0 max-w-full"
                                        value={selectedMapping?.candidate_id || ''}
                                        onChange={(event) =>
                                          handleMappingCandidateChange(template.id, sectionName, event.target.value)
                                        }
                                      >
                                        <option value="">{t('clientTemplate.mapping.unmapped')}</option>
                                        {sectionCandidates.map((candidate) => (
                                          <option key={candidate.candidate_id} value={candidate.candidate_id}>
                                            {candidateDisplayLabel(candidate)}
                                          </option>
                                        ))}
                                      </Select>
                                      <Select
                                        className="min-w-0 max-w-full"
                                        value={selectedMapping?.render_type || sectionSpec.render_type}
                                        onChange={(event) =>
                                          handleMappingRenderTypeChange(template.id, sectionName, event.target.value)
                                        }
                                        disabled={!selectedMapping}
                                      >
                                        <option value="block">block</option>
                                        <option value="block_repeat">block_repeat</option>
                                        <option value="table_row_repeat">table_row_repeat</option>
                                        <option value="paragraph_repeat">paragraph_repeat</option>
                                      </Select>
                                    </div>
                                  );
                                })
                              ) : (
                                <p className="text-sm text-muted-foreground">{t('clientTemplate.mapping.noSupportedSections')}</p>
                              )}
                            </div>

                            <div className="space-y-3">
                              <p className="text-sm font-medium">{t('clientTemplate.mapping.detectedCandidates')}</p>
                              {candidates.length > 0 ? (
                                <div className="space-y-2">
                                  {candidates.map((candidate) => (
                                    <div key={candidate.candidate_id} className="min-w-0 overflow-hidden rounded-xl border p-3 text-sm">
                                      <div className="flex flex-wrap gap-2">
                                        <Badge variant="outline">{candidate.anchor_type}</Badge>
                                        {candidate.section_name_hint ? <Badge>{candidate.section_name_hint}</Badge> : null}
                                        {candidate.render_type_hint ? <Badge variant="secondary">{candidate.render_type_hint}</Badge> : null}
                                        {candidate.inside_fixed_container ? (
                                          <Badge variant="destructive">{t('clientTemplate.mapping.fixedContainer')}</Badge>
                                        ) : null}
                                      </div>
                                      <p className="mt-2 break-all font-mono text-xs text-muted-foreground">{candidate.candidate_id}</p>
                                      {candidate.preview_text ? (
                                        <p className="mt-2 break-words text-muted-foreground [overflow-wrap:anywhere]">{candidate.preview_text}</p>
                                      ) : null}
                                      {candidate.placeholders && candidate.placeholders.length > 0 ? (
                                        <div className="mt-2 flex flex-wrap gap-2">
                                          {candidate.placeholders.map((placeholder) => (
                                            <Badge key={placeholder} variant="outline" className="max-w-full whitespace-normal break-words text-left [overflow-wrap:anywhere]">
                                              {placeholder}
                                            </Badge>
                                          ))}
                                        </div>
                                      ) : null}
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <p className="text-sm text-muted-foreground">{t('clientTemplate.mapping.noCandidateZone')}</p>
                              )}
                            </div>
                          </div>
                        ) : (
                          <p className="text-sm text-muted-foreground">
                            {t('clientTemplate.mapping.loadDescription')}
                          </p>
                        )}
                      </div>
                    </CardContent>
                    <CardContent className="flex min-w-0 flex-wrap justify-end gap-2">
                      <Button variant="outline" onClick={() => void handleDownload(template.id)}>
                        <FileText className="mr-2 h-4 w-4" />
                        {t('clientTemplate.actions.download')}
                      </Button>
                      {!template.is_active && canManageTemplates ? (
                        <Button
                          onClick={() => void handleActivate(template.id)}
                          disabled={busyTemplateId === template.id || !template.is_valid || sharedMutationRestricted}
                        >
                          {busyTemplateId === template.id
                            ? t('clientTemplate.actions.activating')
                            : t('clientTemplate.actions.setActive')}
                        </Button>
                      ) : null}
                      {canManageTemplates ? (
                        <Button
                          variant="destructive"
                          onClick={() => void handleDelete(template.id, template.name)}
                          disabled={busyTemplateId === template.id || sharedMutationRestricted}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          {busyTemplateId === template.id
                            ? t('clientTemplate.actions.deleting')
                            : t('clientTemplate.actions.delete')}
                        </Button>
                      ) : null}
                    </CardContent>
                  </Card>
                );
                })
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </PageFrame>
  );
};
