import { useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';

import {
  configureTurnover,
  getTurnoverConfiguration,
  testTurnoverConnection,
} from '../../api/integrations';
import type { TurnoverConfiguration } from '../../api/types';
import { useI18n } from '../../i18n/useI18n';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import { OperationsErrorBanner, Section, SystemState } from '../operations';

interface TurnoverConfigurationPanelProps {
  tenantId?: string;
  requiresSelectedTenant: boolean;
  onConfigured: () => void | Promise<void>;
}

export function TurnoverConfigurationPanel({
  tenantId,
  requiresSelectedTenant,
  onConfigured,
}: TurnoverConfigurationPanelProps) {
  const { t } = useI18n();
  const [configuration, setConfiguration] = useState<TurnoverConfiguration | null>(null);
  const [token, setToken] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (requiresSelectedTenant) {
      setConfiguration(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTurnoverConfiguration(tenantId)
      .then((data) => {
        if (!cancelled) setConfiguration(data);
      })
      .catch(() => {
        if (!cancelled) setConfiguration(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [requiresSelectedTenant, tenantId]);

  const handleConfigure = async () => {
    if (!token.trim()) return;
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const data = await configureTurnover(token.trim(), tenantId);
      setConfiguration(data);
      setToken('');
      await onConfigured();
      setSuccess(t('integrations.turnover.success.configured'));
    } catch {
      setError(t('integrations.turnover.error.configure'));
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await testTurnoverConnection(tenantId);
      if (!result.connected) throw new Error(result.message);
      setSuccess(t('integrations.turnover.success.connected'));
    } catch {
      setError(t('integrations.turnover.error.test'));
    } finally {
      setTesting(false);
    }
  };

  return (
    <Section
      title={t('integrations.turnover.title')}
      description={t('integrations.turnover.description')}
      divided={false}
    >
      {error ? <OperationsErrorBanner error={error} /> : null}
      {success ? <SystemState kind="success" title={success} /> : null}
      <div className="grid gap-5 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-5 lg:grid-cols-[1fr_auto] lg:items-end">
        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <ShieldCheck className="size-5 text-[var(--brain-ops-text-muted)]" aria-hidden="true" />
            <span className="font-medium text-[var(--brain-ops-text)]">
              {t('integrations.turnover.connectorName')}
            </span>
            <Badge variant={configuration?.configured ? 'success' : 'secondary'}>
              {requiresSelectedTenant
                ? t('integrations.error.selectClient')
                : loading
                  ? t('integrations.loading')
                  : configuration?.configured
                    ? t('integrations.turnover.configured')
                    : t('integrations.turnover.notConfigured')}
            </Badge>
          </div>
          <p className="text-sm leading-6 text-[var(--brain-ops-text-muted)]">
            {t('integrations.turnover.help')}
          </p>
          <div className="flex min-w-0 flex-col gap-1">
            <Label htmlFor="turnover-token">{t('integrations.turnover.token')}</Label>
            <Input
              id="turnover-token"
              type="password"
              autoComplete="new-password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder={t('integrations.turnover.tokenPlaceholder')}
              disabled={requiresSelectedTenant}
            />
            <p className="text-xs text-[var(--brain-ops-text-muted)]">
              {t('integrations.turnover.secretNotice')}
            </p>
          </div>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row lg:flex-col">
          <Button type="button" onClick={() => void handleConfigure()} disabled={!token.trim() || saving || requiresSelectedTenant}>
            {saving ? t('integrations.turnover.saving') : t('integrations.turnover.save')}
          </Button>
          <Button type="button" variant="outline" onClick={() => void handleTest()} disabled={!configuration?.configured || testing}>
            {testing ? t('integrations.turnover.testing') : t('integrations.turnover.test')}
          </Button>
        </div>
      </div>
    </Section>
  );
}
