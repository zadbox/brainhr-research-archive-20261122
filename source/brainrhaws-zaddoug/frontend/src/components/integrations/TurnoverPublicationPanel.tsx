import { useCallback, useEffect, useMemo, useState } from 'react';
import { ExternalLink, RefreshCw, Send } from 'lucide-react';

import {
  createTurnoverPublication,
  getTurnoverProjectPublications,
} from '../../api/integrations';
import type {
  TurnoverContract,
  TurnoverPublication,
  TurnoverRemote,
} from '../../api/types';
import { useI18n } from '../../i18n/useI18n';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { Select } from '../ui/select';
import { OperationsErrorBanner, SystemState } from '../operations';

interface TurnoverPublicationPanelProps {
  projectId: string;
  offerReady: boolean;
  onOpenCandidates: () => void;
}

const terminalStatuses = new Set(['published', 'failed']);

export function TurnoverPublicationPanel({
  projectId,
  offerReady,
  onOpenCandidates,
}: TurnoverPublicationPanelProps) {
  const { t } = useI18n();
  const [publications, setPublications] = useState<TurnoverPublication[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [contract, setContract] = useState<TurnoverContract>('PERMANENT');
  const [remote, setRemote] = useState<TurnoverRemote>('PARTIAL');
  const [country, setCountry] = useState('FR');
  const [region, setRegion] = useState('Ile-de-France');
  const [postalCode, setPostalCode] = useState('');
  const [requestedStatus, setRequestedStatus] = useState<'Draft' | 'Published'>('Draft');

  const latestPublication = useMemo(() => publications[0] ?? null, [publications]);

  const loadPublications = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const data = await getTurnoverProjectPublications(projectId);
      setPublications(data);
      if (!quiet) setError(null);
    } catch {
      if (!quiet) setError(t('turnover.publication.error.load'));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [projectId, t]);

  useEffect(() => {
    void loadPublications();
  }, [loadPublications]);

  useEffect(() => {
    if (!latestPublication || terminalStatuses.has(latestPublication.status)) return;
    const interval = window.setInterval(() => void loadPublications(true), 3000);
    return () => window.clearInterval(interval);
  }, [latestPublication, loadPublications]);

  const handlePublish = async () => {
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const publication = await createTurnoverPublication({
        project_id: projectId,
        contract,
        remote,
        country: country.trim().toUpperCase(),
        region: region.trim() || undefined,
        postal_code: postalCode.trim() || undefined,
        requested_status: requestedStatus,
      });
      setPublications((current) => [publication, ...current]);
      setSuccess(t('turnover.publication.success.queued'));
    } catch {
      setError(t('turnover.publication.error.publish'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {error ? <OperationsErrorBanner error={error} /> : null}
      {success ? <SystemState kind="success" title={success} /> : null}

      {loading ? (
        <SystemState kind="loading" title={t('turnover.publication.loading')} />
      ) : (
        <div className="grid min-w-0 gap-6 xl:grid-cols-[1fr_1fr]">
          <div className="flex min-w-0 flex-col gap-5 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-5">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-[var(--brain-ops-text)]">
                  {t('turnover.publication.form.title')}
                </h3>
                <p className="mt-1 text-sm leading-6 text-[var(--brain-ops-text-muted)]">
                  {t('turnover.publication.form.help')}
                </p>
              </div>
              {latestPublication ? (
                <Badge variant={latestPublication.status === 'failed' ? 'destructive' : 'secondary'}>
                  {t(`turnover.publication.status.${latestPublication.status}` as const)}
                </Badge>
              ) : null}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex min-w-0 flex-col gap-1">
                <Label htmlFor="turnover-contract">{t('turnover.publication.field.contract')}</Label>
                <Select id="turnover-contract" value={contract} onChange={(event) => setContract(event.target.value as TurnoverContract)}>
                  <option value="PERMANENT">{t('turnover.contract.permanent')}</option>
                  <option value="TEMPORARY">{t('turnover.contract.temporary')}</option>
                  <option value="FREELANCE">{t('turnover.contract.freelance')}</option>
                  <option value="INTERNSHIP">{t('turnover.contract.internship')}</option>
                  <option value="APPRENTICESHIP">{t('turnover.contract.apprenticeship')}</option>
                  <option value="INTERCONTRACT">{t('turnover.contract.intercontract')}</option>
                </Select>
              </div>
              <div className="flex min-w-0 flex-col gap-1">
                <Label htmlFor="turnover-remote">{t('turnover.publication.field.remote')}</Label>
                <Select id="turnover-remote" value={remote} onChange={(event) => setRemote(event.target.value as TurnoverRemote)}>
                  <option value="NONE">{t('turnover.remote.none')}</option>
                  <option value="PARTIAL">{t('turnover.remote.partial')}</option>
                  <option value="FULL">{t('turnover.remote.full')}</option>
                </Select>
              </div>
              <div className="flex min-w-0 flex-col gap-1">
                <Label htmlFor="turnover-country">{t('turnover.publication.field.country')}</Label>
                <Input id="turnover-country" maxLength={2} value={country} onChange={(event) => setCountry(event.target.value)} />
              </div>
              <div className="flex min-w-0 flex-col gap-1">
                <Label htmlFor="turnover-region">{t('turnover.publication.field.region')}</Label>
                <Input id="turnover-region" value={region} onChange={(event) => setRegion(event.target.value)} />
              </div>
              <div className="flex min-w-0 flex-col gap-1">
                <Label htmlFor="turnover-postal-code">{t('turnover.publication.field.postalCode')}</Label>
                <Input id="turnover-postal-code" value={postalCode} onChange={(event) => setPostalCode(event.target.value)} />
              </div>
              <div className="flex min-w-0 flex-col gap-1">
                <Label htmlFor="turnover-requested-status">{t('turnover.publication.field.requestedStatus')}</Label>
                <Select id="turnover-requested-status" value={requestedStatus} onChange={(event) => setRequestedStatus(event.target.value as 'Draft' | 'Published')}>
                  <option value="Draft">{t('common.draft')}</option>
                  <option value="Published">{t('turnover.publication.status.requestedPublished')}</option>
                </Select>
              </div>
            </div>
            <Button type="button" onClick={() => void handlePublish()} disabled={!offerReady || submitting || !country.trim() || (!region.trim() && !postalCode.trim())}>
              <Send data-icon="inline-start" />
              {submitting ? t('turnover.publication.action.sending') : t('turnover.publication.action.send')}
            </Button>
            {!offerReady ? (
              <p className="text-sm text-[var(--brain-ops-warning)]">{t('turnover.publication.offerRequired')}</p>
            ) : null}
          </div>

          <div className="flex min-w-0 flex-col gap-5 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold text-[var(--brain-ops-text)]">
                  {t('turnover.application.title')}
                </h3>
                <p className="mt-1 text-sm text-[var(--brain-ops-text-muted)]">
                  {latestPublication
                    ? `${latestPublication.application_count} ${t('turnover.application.received')}`
                    : t('turnover.application.noPublication')}
                </p>
              </div>
              <Button type="button" variant="outline" size="icon" onClick={() => void loadPublications()} aria-label={t('turnover.publication.action.refresh')}>
                <RefreshCw />
              </Button>
            </div>

            {latestPublication ? (
              <div className="flex min-w-0 flex-col gap-4">
                {latestPublication.remote_public_url ? (
                  <a href={latestPublication.remote_public_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 font-medium text-[var(--brain-ops-accent)] hover:underline">
                    {t('turnover.publication.openRemote')} <ExternalLink className="size-4" />
                  </a>
                ) : null}
                <details className="rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-3 text-sm">
                  <summary className="cursor-pointer font-medium text-[var(--brain-ops-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)]">
                    {t('turnover.publication.technicalDetails')}
                  </summary>
                  <div className="mt-3 min-w-0">
                    <span className="text-[var(--brain-ops-text-muted)]">{t('turnover.publication.callback')}</span>
                    <p className="mt-1 break-all font-mono text-xs text-[var(--brain-ops-text-muted)]">{latestPublication.callback_url}</p>
                    {latestPublication.last_error ? (
                      <p className="mt-3 text-[var(--brain-ops-danger)]">{latestPublication.last_error}</p>
                    ) : null}
                  </div>
                </details>
              </div>
            ) : (
              <p className="text-sm text-[var(--brain-ops-text-muted)]">{t('turnover.application.noPublication')}</p>
            )}

            <Button type="button" variant="outline" className="mt-auto w-full" onClick={onOpenCandidates} disabled={!latestPublication?.application_count}>
              {t('turnover.application.action.openCandidates')}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
