import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Search, UserRound } from 'lucide-react';
import { talentPoolApi, type CatalogCandidate, type CatalogScope } from '../api/talentPool';
import { Button } from '../components/ui/button';
import { ContextStrip, OperationalList, OperationalListItem, PageFrame, PageHeader, SystemState } from '../components/operations';
import { useAuth } from '../features/auth/context/AuthContext';
import { useI18n } from '../i18n/useI18n';
import { useAppStore } from '../stores/useAppStore';

const PAGE_SIZE = 40;

export function TalentPoolPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);
  const enterpriseCatalogRevision = useAppStore((state) => state.enterpriseCatalogRevision);
  const isPlatformAdmin = user?.role === 'platform_admin';
  const [scopes, setScopes] = useState<CatalogScope[]>([]);
  const [profiles, setProfiles] = useState<CatalogCandidate[]>([]);
  const [total, setTotal] = useState(0);
  const [loadingEnterprises, setLoadingEnterprises] = useState(false);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [loadedScope, setLoadedScope] = useState('');
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const [localTenantId, setLocalTenantId] = useState('');
  const [enterpriseId, setEnterpriseId] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const requiresClient = isPlatformAdmin && !selectedTenantId;
  const scopeKey = `${user?.id || ''}:${isPlatformAdmin ? selectedTenantId : 'grants'}:${enterpriseCatalogRevision}:${retry}`;

  useEffect(() => {
    setScopes([]);
    setProfiles([]);
    setLoadedScope('');
    setFailed(false);
    if (!user?.id || requiresClient) return;
    let active = true;
    setLoadingEnterprises(true);
    talentPoolApi.scopes().then((nextScopes) => {
      if (!active) return;
      setScopes(nextScopes);
      setLoadedScope(scopeKey);
    }).catch(() => {
      if (active) setFailed(true);
    }).finally(() => {
      if (active) setLoadingEnterprises(false);
    });
    return () => { active = false; };
  }, [user?.id, requiresClient, isPlatformAdmin, selectedTenantId, enterpriseCatalogRevision, retry, scopeKey]);

  const tenantIds = useMemo(() => [...new Set(scopes.map((scope) => scope.tenant_id))], [scopes]);
  const tenantId = isPlatformAdmin ? selectedTenantId : user?.tenant_id || (tenantIds.length === 1 ? tenantIds[0] : localTenantId);
  const scopedEnterprises = useMemo(() => scopes.filter((scope) => scope.tenant_id === tenantId), [scopes, tenantId]);
  useEffect(() => { setEnterpriseId(''); setSearch(''); setOffset(0); }, [tenantId]);
  useEffect(() => { setOffset(0); }, [enterpriseId, search]);
  useEffect(() => {
    if (offset === 0) { setProfiles([]); setTotal(0); }
    if (!tenantId || loadedScope !== scopeKey || failed) return;
    let active = true;
    setLoadingCatalog(true);
    const timer = window.setTimeout(() => {
      talentPoolApi.list({
        tenant_id: tenantId,
        enterprise_id: enterpriseId || undefined,
        search: search.trim() || undefined,
        offset,
        limit: PAGE_SIZE,
      }).then((page) => {
        if (!active) return;
        setProfiles((current) => offset === 0 ? page.items : [...current, ...page.items]);
        setTotal(page.total);
      }).catch(() => {
        if (active) setFailed(true);
      }).finally(() => {
        if (active) setLoadingCatalog(false);
      });
    }, search ? 250 : 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [tenantId, enterpriseId, search, offset, loadedScope, scopeKey, failed]);

  const loading = !failed && (
    (loadedScope !== scopeKey && !requiresClient)
    || loadingEnterprises
    || (loadingCatalog && offset === 0)
  );

  return <PageFrame width="full" contentClassName="gap-5 lg:gap-6">
    <PageHeader title={t('pool.title')} description={t('catalog.description')} />
    {requiresClient ? <SystemState kind="info" title={t('catalog.chooseClient')} description={t('catalog.chooseClientHelp')} />
      : loading ? <SystemState kind="loading" title={t('catalog.loading')} />
        : failed ? <SystemState kind="error" title={t('catalog.error')} description={t('catalog.errorHelp')} actionLabel={t('catalog.retry')} action={<Button variant="outline" onClick={() => setRetry((value) => value + 1)}>{t('catalog.retry')}</Button>} />
          : <>
            {!isPlatformAdmin && !user?.tenant_id && tenantIds.length > 1 && <label className="flex max-w-sm flex-col gap-2 text-sm">
              <span>{t('catalog.client')}</span>
              <select className="min-h-11 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] px-3 text-[var(--brain-ops-text)]" value={localTenantId} onChange={(event) => setLocalTenantId(event.target.value)}>
                <option value="">{t('catalog.chooseClient')}</option>
                {tenantIds.map((id) => <option key={id} value={id}>{scopes.find((scope) => scope.tenant_id === id)?.tenant_name || id}</option>)}
              </select>
            </label>}
            {tenantId ? <>
              <ContextStrip ariaLabel={t('catalog.scope')} items={[
                { id: 'client', label: t('catalog.client'), value: scopedEnterprises[0]?.tenant_name || user?.tenant_name || tenantId },
                { id: 'enterprise', label: t('catalog.enterprises'), value: scopedEnterprises.length },
                { id: 'profiles', label: t('catalog.profiles'), value: total },
              ]} />
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                <label className="flex min-w-0 flex-1 flex-col gap-2 text-sm"><span>{t('catalog.search')}</span><span className="flex min-h-11 items-center gap-2 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] px-3 focus-within:ring-1 focus-within:ring-[var(--brain-ops-text-muted)]"><Search className="size-4 shrink-0" aria-hidden="true" /><input type="search" className="min-w-0 flex-1 appearance-none !border-0 bg-transparent p-0 text-[var(--brain-ops-text)] shadow-none !outline-none placeholder:text-[var(--brain-ops-text-muted)] focus:ring-0 focus-visible:ring-0" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('catalog.searchPlaceholder')} /></span></label>
                <label className="flex min-w-0 flex-col gap-2 text-sm"><span>{t('catalog.enterprise')}</span><select className="min-h-11 min-w-52 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] px-3 text-[var(--brain-ops-text)]" value={enterpriseId} onChange={(event) => setEnterpriseId(event.target.value)}><option value="">{t('catalog.allEnterprises')}</option>{scopedEnterprises.map((enterprise) => <option key={enterprise.enterprise_id} value={enterprise.enterprise_id}>{enterprise.enterprise_name}</option>)}</select></label>
              </div>
              {profiles.length ? <><OperationalList ariaLabel={t('catalog.profiles')}>
                {profiles.map((cv) => {
                  const name = cv.name || t('catalog.unnamed');
                  const candidateQuery = cv.source_filename ? `?candidate=${encodeURIComponent(cv.source_filename)}` : '';
                  return <OperationalListItem key={`${cv.project_id}:${cv.filename}`} leading={<span className="flex size-10 items-center justify-center rounded-full border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]"><UserRound className="size-5" aria-hidden="true" /></span>} primary={name} secondary={[cv.title, cv.enterprise_name, cv.project_name].filter(Boolean).join(' · ')} metadata={cv.source_filename || cv.filename} monospaceMetadata actionsLabel={name} actions={<Link className="inline-flex min-h-11 items-center rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] px-3 text-sm font-medium transition-colors hover:bg-[var(--brain-ops-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)]" to={`/projects/${encodeURIComponent(cv.project_id)}/cvs${candidateQuery}`}>{t('catalog.openProfile')}</Link>} />;
                })}
              </OperationalList>{profiles.length < total && <Button variant="outline" className="self-center" disabled={loadingCatalog} onClick={() => setOffset((current) => current + PAGE_SIZE)}>{t('catalog.showMore')}</Button>}</>
                : <SystemState kind="empty" title={search || enterpriseId ? t('catalog.noResults') : t('catalog.empty')} description={search || enterpriseId ? t('catalog.clearFilters') : t('catalog.emptyHelp')} actionLabel={t('catalog.clearFilters')} action={search || enterpriseId ? <Button variant="outline" onClick={() => { setSearch(''); setEnterpriseId(''); }}>{t('catalog.clearFilters')}</Button> : undefined} />}
            </> : <SystemState kind="info" title={t('catalog.chooseClient')} description={t('catalog.chooseClientHelp')} />}
          </>}
  </PageFrame>;
}
