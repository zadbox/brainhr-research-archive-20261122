import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Coins, LoaderCircle, RefreshCw, Save } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import type { APIError } from '../api/types';
import {
  crustdataApi,
  type CrustdataAdminWallet,
  type CrustdataCreditOperation,
} from '../api/crustdata';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
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
import { useAuth } from '../features/auth/context/AuthContext';
import { formatMessage } from '../i18n/formatMessage';
import { useI18n } from '../i18n/useI18n';

export function AdminCrustdataPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { language, t } = useI18n();
  const [wallets, setWallets] = useState<CrustdataAdminWallet[]>([]);
  const [operations, setOperations] = useState<CrustdataCreditOperation[]>([]);
  const [totalOperations, setTotalOperations] = useState(0);
  const [tenantId, setTenantId] = useState('');
  const [tenantBalance, setTenantBalance] = useState('');
  const [reconciliationCredits, setReconciliationCredits] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [ledgerRefreshing, setLedgerRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<APIError | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const locale = language === 'fr' ? 'fr-FR' : 'en-US';

  const load = useCallback(async () => {
    if (user?.role !== 'platform_admin') return;
    setLoading(true);
    setError(null);
    try {
      const [creditResponse, operationResponse] = await Promise.all([
        crustdataApi.getAdminCredits(),
        crustdataApi.getAdminOperations(),
      ]);
      setWallets(creditResponse);
      setOperations(operationResponse);
      setTotalOperations(operationResponse.length);
    } catch (caught) {
      setError(caught as APIError);
    } finally {
      setLoading(false);
    }
  }, [user?.role]);

  useEffect(() => {
    void load();
  }, [load]);

  const refreshLedger = async () => {
    setLedgerRefreshing(true);
    setError(null);
    try {
      const operationResponse = await crustdataApi.getAdminOperations();
      setOperations(operationResponse);
      setTotalOperations(operationResponse.length);
    } catch (caught) {
      setError(caught as APIError);
    } finally {
      setLedgerRefreshing(false);
    }
  };

  const globalWallet = wallets.find((wallet) => wallet.scope_kind === 'platform');

  const lastSync = useMemo(() => {
    const latest = globalWallet?.provider_last_synced_at;
    if (!latest) return t('crustdataAdmin.sync.never');
    const date = new Date(latest);
    return Number.isNaN(date.getTime()) ? t('crustdataAdmin.sync.never') : new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }, [globalWallet?.provider_last_synced_at, locale, t]);

  const handleSync = async () => {
    setBusy('sync');
    setError(null);
    setSuccess(null);
    try {
      await crustdataApi.syncAdminCredits();
      setWallets(await crustdataApi.getAdminCredits());
      setSuccess(t('crustdataAdmin.sync.success'));
    } catch (caught) {
      setError(caught as APIError);
    } finally {
      setBusy(null);
    }
  };

  const handleWalletUpdate = async () => {
    if (!tenantId.trim() || !tenantBalance.trim()) return;
    setBusy('wallet');
    setError(null);
    setSuccess(null);
    try {
      await crustdataApi.updateTenantWallet(tenantId.trim(), tenantBalance.trim());
      setSuccess(t('crustdataAdmin.wallet.success'));
      setTenantBalance('');
      const [walletResponse, operationResponse] = await Promise.all([
        crustdataApi.getAdminCredits(),
        crustdataApi.getAdminOperations(),
      ]);
      setWallets(walletResponse);
      setOperations(operationResponse);
      setTotalOperations(operationResponse.length);
    } catch (caught) {
      setError(caught as APIError);
    } finally {
      setBusy(null);
    }
  };

  const handleReconcile = async (operationId: string) => {
    const actualCredits = reconciliationCredits[operationId]?.trim();
    if (!actualCredits || !/^\d+(?:\.\d+)?$/.test(actualCredits)) return;
    setBusy(`reconcile:${operationId}`);
    setError(null);
    setSuccess(null);
    try {
      await crustdataApi.reconcileOperation(operationId, actualCredits);
      const [walletResponse, operationResponse] = await Promise.all([
        crustdataApi.getAdminCredits(),
        crustdataApi.getAdminOperations(),
      ]);
      setWallets(walletResponse);
      setOperations(operationResponse);
      setTotalOperations(operationResponse.length);
      setReconciliationCredits((current) => {
        const next = { ...current };
        delete next[operationId];
        return next;
      });
      setSuccess(t('crustdataAdmin.reconcile.success'));
    } catch (caught) {
      setError(caught as APIError);
    } finally {
      setBusy(null);
    }
  };

  if (user?.role !== 'platform_admin') {
    return <PageFrame><SystemState kind="warning" title={t('crustdataAdmin.access.title')} description={t('crustdataAdmin.access.description')} /></PageFrame>;
  }

  if (loading) {
    return <PageFrame><SystemState kind="loading" title={t('crustdataAdmin.loading')} indicator={<LoaderCircle className="size-5 animate-spin" />} /></PageFrame>;
  }

  return (
    <PageFrame width="wide">
      <PageHeader
        eyebrow={t('crustdataAdmin.badge')}
        title={t('crustdataAdmin.title')}
        description={t('crustdataAdmin.description')}
        actionsLabel={t('crustdataAdmin.header.actions')}
        actions={<Button variant="outline" onClick={() => navigate('/settings')}><ArrowLeft />{t('settings.back')}</Button>}
      />

      <ContextStrip
        ariaLabel={t('crustdataAdmin.context.aria')}
        items={[
          { id: 'provider', label: t('crustdataAdmin.context.provider'), value: 'Crustdata' },
          { id: 'scope', label: t('crustdataAdmin.context.scope'), value: t('crustdataAdmin.context.platform') },
          { id: 'sync', label: t('crustdataAdmin.context.lastSync'), value: lastSync },
        ]}
      />

      <MetricStrip
        ariaLabel={t('crustdataAdmin.metrics.aria')}
        items={[
          { id: 'balance', label: t('crustdataAdmin.metric.balance'), value: globalWallet?.balance ?? '—', detail: t('crustdataAdmin.metric.creditUnit'), tone: globalWallet ? 'neutral' : 'warning' },
          { id: 'operations', label: t('crustdataAdmin.metric.operations'), value: totalOperations, detail: t('crustdataAdmin.metric.ledger') },
          { id: 'provider', label: t('crustdataAdmin.metric.provider'), value: globalWallet ? t('crustdataAdmin.provider.available') : t('crustdataAdmin.provider.unavailable'), tone: globalWallet ? 'success' : 'danger' },
        ]}
      />

      {error ? <SystemState kind="error" title={t('crustdataAdmin.error')} description={typeof error.message === 'string' ? error.message : undefined} /> : null}
      {success ? <SystemState kind="success" title={success} /> : null}

      <Section
        title={t('crustdataAdmin.sync.title')}
        description={t('crustdataAdmin.sync.description')}
        actionsLabel={t('crustdataAdmin.sync.actions')}
        actions={<Button disabled={busy !== null || ledgerRefreshing} onClick={() => void handleSync()}>{busy === 'sync' ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}{t('crustdataAdmin.sync.action')}</Button>}
      >
        <p className="text-sm text-[var(--brain-ops-text-muted)]">{t('crustdataAdmin.sync.note')}</p>
      </Section>

      <Section data-tour="admin-crustdata-workspace" title={t('crustdataAdmin.wallet.title')} description={t('crustdataAdmin.wallet.description')}>
        <div className="grid gap-4 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4 sm:grid-cols-[minmax(0,1fr)_minmax(10rem,0.5fr)_auto] sm:items-end">
          <div className="flex flex-col gap-2"><Label htmlFor="crustdata-tenant-id">{t('crustdataAdmin.wallet.tenant')}</Label><Input id="crustdata-tenant-id" value={tenantId} onChange={(event) => setTenantId(event.target.value)} placeholder={t('crustdataAdmin.wallet.tenantPlaceholder')} /></div>
          <div className="flex flex-col gap-2"><Label htmlFor="crustdata-tenant-balance">{t('crustdataAdmin.wallet.balance')}</Label><Input id="crustdata-tenant-balance" inputMode="decimal" value={tenantBalance} onChange={(event) => setTenantBalance(event.target.value)} placeholder="0.00" /></div>
          <Button disabled={busy !== null || ledgerRefreshing || !tenantId.trim() || !/^\d+(?:\.\d+)?$/.test(tenantBalance.trim())} onClick={() => void handleWalletUpdate()}>{busy === 'wallet' ? <LoaderCircle className="animate-spin" /> : <Save />}{t('crustdataAdmin.wallet.save')}</Button>
        </div>
      </Section>

      <Section
        title={t('crustdataAdmin.ledger.title')}
        description={t('crustdataAdmin.ledger.description')}
        actionsLabel={t('crustdataAdmin.ledger.actions')}
        actions={(
          <Button
            variant="ghost"
            size="sm"
            disabled={busy !== null || ledgerRefreshing}
            onClick={() => void refreshLedger()}
          >
            {ledgerRefreshing ? (
              <LoaderCircle className="animate-spin motion-reduce:animate-none" />
            ) : (
              <RefreshCw />
            )}
            {t('crustdataAdmin.ledger.refresh')}
          </Button>
        )}
      >
        {operations.length === 0 ? <SystemState kind="empty" title={t('crustdataAdmin.ledger.empty')} /> : (
          <OperationalList ariaLabel={t('crustdataAdmin.ledger.aria')}>
            {operations.map((operation) => {
              const commonProps = {
                leading: <span className="flex size-10 items-center justify-center border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)]"><Coins className="size-5" /></span>,
                primary: `${operation.operation_type.toUpperCase()} · ${operation.tenant_id}`,
                secondary: formatMessage(t('crustdataAdmin.ledger.credits'), { estimated: operation.estimated_credits, settled: operation.settled_credits ?? '—' }),
                metadata: `${operation.status} · ${new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(operation.created_at))}`,
              };
              if (operation.status !== 'pending_reconciliation') {
                return <OperationalListItem key={operation.operation_id} {...commonProps} monospaceMetadata />;
              }
              const draft = reconciliationCredits[operation.operation_id] ?? '';
              return (
                <OperationalListItem
                  key={operation.operation_id}
                  {...commonProps}
                  monospaceMetadata
                  actionsLabel={formatMessage(t('crustdataAdmin.reconcile.actions'), { operation: operation.operation_id })}
                  actions={
                    <div className="flex flex-wrap items-center gap-2">
                      <Label className="sr-only" htmlFor={`reconcile-${operation.operation_id}`}>{t('crustdataAdmin.reconcile.actualCredits')}</Label>
                      <Input
                        id={`reconcile-${operation.operation_id}`}
                        className="w-32"
                        inputMode="decimal"
                        value={draft}
                        onChange={(event) => setReconciliationCredits((current) => ({ ...current, [operation.operation_id]: event.target.value }))}
                        placeholder={t('crustdataAdmin.reconcile.placeholder')}
                      />
                      <Button
                        size="sm"
                        disabled={busy !== null || ledgerRefreshing || !/^\d+(?:\.\d+)?$/.test(draft.trim())}
                        onClick={() => void handleReconcile(operation.operation_id)}
                      >
                        {busy === `reconcile:${operation.operation_id}` ? <LoaderCircle className="animate-spin" /> : <Save />}
                        {t('crustdataAdmin.reconcile.action')}
                      </Button>
                    </div>
                  }
                />
              );
            })}
          </OperationalList>
        )}
      </Section>
    </PageFrame>
  );
}
