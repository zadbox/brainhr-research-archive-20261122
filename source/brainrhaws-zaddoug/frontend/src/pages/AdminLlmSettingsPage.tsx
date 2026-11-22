import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BrainCircuit, LockKeyhole, RefreshCcw, Save } from 'lucide-react';
import { llmSettingsApi, type LLMProcessSetting } from '../api/llmSettings';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Select } from '../components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import {
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
import { useAuth } from '../features/auth/context/AuthContext';
import { useToast } from '../hooks/useToast';
import type { TranslationKey } from '../i18n/messages';
import { useI18n } from '../i18n/useI18n';

type Drafts = Record<string, { provider: string; model: string }>;

type ProcessPresentationKeys = {
  label: TranslationKey;
  category: TranslationKey;
  description: TranslationKey;
};

const PROCESS_PRESENTATION_KEYS: Record<string, ProcessPresentationKeys> = {
  cv_parsing: {
    label: 'llm.process.cv_parsing.label',
    category: 'llm.process.cv_parsing.category',
    description: 'llm.process.cv_parsing.description',
  },
  offer_parsing: {
    label: 'llm.process.offer_parsing.label',
    category: 'llm.process.offer_parsing.category',
    description: 'llm.process.offer_parsing.description',
  },
  offer_enrichment: {
    label: 'llm.process.offer_enrichment.label',
    category: 'llm.process.offer_enrichment.category',
    description: 'llm.process.offer_enrichment.description',
  },
  offer_criteria: {
    label: 'llm.process.offer_criteria.label',
    category: 'llm.process.offer_criteria.category',
    description: 'llm.process.offer_criteria.description',
  },
  matching_prefilter: {
    label: 'llm.process.matching_prefilter.label',
    category: 'llm.process.matching_prefilter.category',
    description: 'llm.process.matching_prefilter.description',
  },
  matching_reranking: {
    label: 'llm.process.matching_reranking.label',
    category: 'llm.process.matching_reranking.category',
    description: 'llm.process.matching_reranking.description',
  },
  interview_sheet_generation: {
    label: 'llm.process.interview_sheet_generation.label',
    category: 'llm.process.interview_sheet_generation.category',
    description: 'llm.process.interview_sheet_generation.description',
  },
  company_cv_generation: {
    label: 'llm.process.company_cv_generation.label',
    category: 'llm.process.company_cv_generation.category',
    description: 'llm.process.company_cv_generation.description',
  },
  realtime_interview_plan: {
    label: 'llm.process.realtime_interview_plan.label',
    category: 'llm.process.realtime_interview_plan.category',
    description: 'llm.process.realtime_interview_plan.description',
  },
  realtime_interview_live: {
    label: 'llm.process.realtime_interview_live.label',
    category: 'llm.process.realtime_interview_live.category',
    description: 'llm.process.realtime_interview_live.description',
  },
};

function providerLabel(process: LLMProcessSetting, providerId: string): string {
  return process.providers.find((provider) => provider.id === providerId)?.label ?? providerId;
}

function modelsFor(process: LLMProcessSetting, providerId: string): string[] {
  return process.providers.find((provider) => provider.id === providerId)?.models ?? [];
}

function isConfigured(process: LLMProcessSetting, providerId: string): boolean {
  return Boolean(process.providers.find((provider) => provider.id === providerId)?.configured);
}

export function AdminLlmSettingsPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const { user } = useAuth();
  const { success: showSuccess } = useToast();
  const [processes, setProcesses] = useState<LLMProcessSetting[]>([]);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [loading, setLoading] = useState(true);
  const [savingProcessId, setSavingProcessId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isPlatformAdmin = user?.role === 'platform_admin';

  const processPresentation = (process: LLMProcessSetting) => {
    const keys = PROCESS_PRESENTATION_KEYS[process.process_id];
    return keys
      ? {
          label: t(keys.label),
          category: t(keys.category),
          description: t(keys.description),
        }
      : {
          label: process.label,
          category: process.category,
          description: process.description,
        };
  };

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await llmSettingsApi.list();
      setProcesses(data);
      setDrafts(
        Object.fromEntries(
          data.map((process) => [
            process.process_id,
            { provider: process.provider, model: process.model },
          ])
        )
      );
    } catch (err: unknown) {
      setError((err as { message?: string })?.message ?? t('llm.error.load'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const metrics = useMemo(() => {
    const overrideCount = processes.filter((process) => process.source === 'database').length;
    const mistralReady = processes.some((process) =>
      process.providers.some((provider) => provider.id === 'mistral' && provider.configured)
    );
    return {
      processCount: processes.length,
      overrideCount,
      mistralReady: mistralReady ? t('llm.mistral.ready') : t('llm.mistral.missing'),
    };
  }, [processes, t]);

  const updateDraftProvider = (process: LLMProcessSetting, provider: string) => {
    const nextModels = modelsFor(process, provider);
    const currentModel = drafts[process.process_id]?.model;
    setDrafts((current) => ({
      ...current,
      [process.process_id]: {
        provider,
        model: currentModel && nextModels.includes(currentModel)
          ? currentModel
          : nextModels[0] ?? process.default_model,
      },
    }));
  };

  const updateDraftModel = (processId: string, model: string) => {
    setDrafts((current) => ({
      ...current,
      [processId]: {
        provider: current[processId]?.provider ?? '',
        model,
      },
    }));
  };

  const saveProcess = async (process: LLMProcessSetting) => {
    const draft = drafts[process.process_id];
    if (!draft) return;
    setSavingProcessId(process.process_id);
    setError(null);
    try {
      const data = await llmSettingsApi.update(process.process_id, draft.provider, draft.model);
      setProcesses(data);
      setDrafts(
        Object.fromEntries(
          data.map((item) => [item.process_id, { provider: item.provider, model: item.model }])
        )
      );
      showSuccess(`${processPresentation(process).label}: ${providerLabel(process, draft.provider)} / ${draft.model}`);
    } catch (err: unknown) {
      setError((err as { message?: string })?.message ?? t('llm.error.save'));
    } finally {
      setSavingProcessId(null);
    }
  };

  if (!isPlatformAdmin) {
    return (
      <PageFrame width="content">
        <SystemState
          kind="warning"
          indicator={<LockKeyhole className="size-5" />}
          title={t('llm.access.title')}
          description={t('llm.access.description')}
        />
      </PageFrame>
    );
  }

  const renderStatusBadge = (configured: boolean) => (
    configured
      ? <Badge variant="success">{t('llm.status.configured')}</Badge>
      : <Badge variant="secondary">{t('llm.status.keyMissing')}</Badge>
  );

  const renderProcessControls = (process: LLMProcessSetting) => {
    const presentation = processPresentation(process);
    const draft = drafts[process.process_id] ?? {
      provider: process.provider,
      model: process.model,
    };
    const configured = isConfigured(process, draft.provider);
    const dirty = draft.provider !== process.provider || draft.model !== process.model;
    const locked = process.locked && process.providers.length === 1;
    const modelOptions = modelsFor(process, draft.provider);

    return (
      <>
        <Select
          aria-label={`${t('llm.table.provider')} — ${presentation.label}`}
          className="w-full sm:w-48"
          value={draft.provider}
          disabled={locked}
          onChange={(event) => updateDraftProvider(process, event.target.value)}
        >
          {process.providers.map((provider) => (
            <option
              key={provider.id}
              value={provider.id}
              disabled={!provider.configured}
            >
              {provider.label}{provider.configured ? '' : t('llm.provider.keyMissingSuffix')}
            </option>
          ))}
        </Select>
        <Select
          aria-label={`${t('llm.table.model')} — ${presentation.label}`}
          className="w-full font-mono text-xs sm:w-48"
          value={draft.model}
          disabled={locked}
          onChange={(event) => updateDraftModel(process.process_id, event.target.value)}
        >
          {modelOptions.map((model) => (
            <option key={model} value={model}>{model}</option>
          ))}
        </Select>
        <Button
          type="button"
          size="sm"
          aria-label={`${t('llm.action.save')} — ${presentation.label}`}
          onClick={() => void saveProcess(process)}
          disabled={!dirty || !configured || savingProcessId === process.process_id}
        >
          <Save data-icon="inline-start" />
          {t('llm.action.save')}
        </Button>
      </>
    );
  };

  return (
    <PageFrame>
      <PageHeader
        eyebrow={t('settings.section.llm.label')}
        backAction={<PageBackButton onClick={() => navigate('/settings')} aria-label={t('settings.back')} />}
        title={t('llm.title')}
        description={t('llm.description')}
        actionsLabel={t('llm.table.actions')}
        actions={
          <Button
            type="button"
            variant="outline"
            onClick={() => void refresh()}
            disabled={loading}
          >
            <RefreshCcw data-icon="inline-start" />
            {t('llm.action.refresh')}
          </Button>
        }
      />

      <MetricStrip
        ariaLabel={t('llm.metrics.aria')}
        items={[
          { id: 'processes', label: t('llm.metric.processes'), value: metrics.processCount },
          { id: 'overrides', label: t('llm.metric.overrides'), value: metrics.overrideCount },
          { id: 'mistral', label: t('llm.metric.mistral'), value: metrics.mistralReady },
        ]}
      />

      {error ? <OperationsErrorBanner error={error} /> : null}
      <Section
        data-tour="admin-llm-workspace"
        title={t('llm.section.title')}
        description={t('llm.section.description')}
        divided={false}
      >
        {loading ? (
          <SystemState
            kind="loading"
            title={t('llm.loading')}
            indicator={<BrainCircuit className="size-5" />}
          />
        ) : (
          <>
            <div className="hidden overflow-hidden rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] min-[1360px]:block">
              <Table aria-label={t('llm.table.aria')} className="min-w-[64rem]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="h-12 px-3">{t('llm.table.process')}</TableHead>
                    <TableHead className="h-12 px-3">{t('llm.table.current')}</TableHead>
                    <TableHead className="h-12 px-3">{t('llm.table.provider')}</TableHead>
                    <TableHead className="h-12 px-3">{t('llm.table.model')}</TableHead>
                    <TableHead className="h-12 px-3">{t('llm.table.status')}</TableHead>
                    <TableHead className="h-12 px-3 text-right">{t('llm.table.actions')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {processes.map((process) => {
                    const presentation = processPresentation(process);
                    const draft = drafts[process.process_id] ?? {
                      provider: process.provider,
                      model: process.model,
                    };
                    const configured = isConfigured(process, draft.provider);
                    const dirty = draft.provider !== process.provider || draft.model !== process.model;
                    const locked = process.locked && process.providers.length === 1;
                    const modelOptions = modelsFor(process, draft.provider);
                    return (
                      <TableRow key={process.process_id}>
                        <TableCell className="px-3 py-2 align-top">
                          <div className="flex min-w-0 flex-col gap-1">
                            <p className="font-medium text-[var(--brain-ops-text)]">{presentation.label}</p>
                            <p className="text-xs uppercase tracking-widest text-[var(--brain-ops-text-muted)]">
                              {presentation.category}
                            </p>
                            <p className="max-w-sm text-sm leading-5 text-[var(--brain-ops-text-muted)]">
                              {presentation.description}
                            </p>
                          </div>
                        </TableCell>
                        <TableCell className="px-3 py-2 align-top">
                          <div className="flex min-w-0 flex-col gap-1">
                            <span>{providerLabel(process, process.provider)}</span>
                            <span className="font-mono text-xs text-[var(--brain-ops-text-muted)]">
                              {process.model}
                            </span>
                            <span>
                              <Badge variant="outline">{process.source}</Badge>
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="px-3 py-2 align-top">
                          <Select
                            aria-label={`${t('llm.table.provider')} — ${presentation.label}`}
                            value={draft.provider}
                            disabled={locked}
                            onChange={(event) => updateDraftProvider(process, event.target.value)}
                          >
                            {process.providers.map((provider) => (
                              <option
                                key={provider.id}
                                value={provider.id}
                                disabled={!provider.configured}
                              >
                                {provider.label}{provider.configured ? '' : t('llm.provider.keyMissingSuffix')}
                              </option>
                            ))}
                          </Select>
                          {process.lock_reason ? (
                            <p className="mt-2 text-xs text-[var(--brain-ops-text-muted)]">
                              {process.lock_reason}
                            </p>
                          ) : null}
                        </TableCell>
                        <TableCell className="px-3 py-2 align-top">
                          <Select
                            aria-label={`${t('llm.table.model')} — ${presentation.label}`}
                            className="font-mono text-xs"
                            value={draft.model}
                            disabled={locked}
                            onChange={(event) => updateDraftModel(process.process_id, event.target.value)}
                          >
                            {modelOptions.map((model) => (
                              <option key={model} value={model}>{model}</option>
                            ))}
                          </Select>
                        </TableCell>
                        <TableCell className="px-3 py-2 align-top">
                          {renderStatusBadge(configured)}
                        </TableCell>
                        <TableCell className="px-3 py-2 align-top">
                          <div className="flex justify-end">
                            <Button
                              type="button"
                              size="sm"
                              aria-label={`${t('llm.action.save')} — ${presentation.label}`}
                              onClick={() => void saveProcess(process)}
                              disabled={!dirty || !configured || savingProcessId === process.process_id}
                            >
                              <Save data-icon="inline-start" />
                              {t('llm.action.save')}
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>

            <OperationalList ariaLabel={t('llm.table.aria')} className="min-[1360px]:hidden">
              {processes.map((process) => {
                const presentation = processPresentation(process);
                const configured = isConfigured(
                  process,
                  drafts[process.process_id]?.provider ?? process.provider
                );
                return (
                  <OperationalListItem
                    key={process.process_id}
                    leading={
                      <span className="flex size-10 items-center justify-center rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)]">
                        <BrainCircuit className="size-5" />
                      </span>
                    }
                    primary={
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-[var(--brain-ops-text)]">{presentation.label}</span>
                        {renderStatusBadge(configured)}
                      </span>
                    }
                    secondary={
                      <span className="flex min-w-0 flex-col gap-1">
                        <span>{presentation.description}</span>
                        {process.lock_reason ? <span>{process.lock_reason}</span> : null}
                      </span>
                    }
                    metadata={
                      <span>
                        {providerLabel(process, process.provider)} / {process.model} · {process.source}
                      </span>
                    }
                    monospaceMetadata
                    actionsLabel={t('llm.table.actions')}
                    actions={renderProcessControls(process)}
                  />
                );
              })}
            </OperationalList>
          </>
        )}
      </Section>
    </PageFrame>
  );
}
