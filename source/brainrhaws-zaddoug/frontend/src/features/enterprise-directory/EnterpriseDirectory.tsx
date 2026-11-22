import './enterprise-directory.css';
import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, X } from 'lucide-react';
import type { Enterprise } from '../../api/types';
import { Button } from '../../components/ui/button';
import { useI18n } from '../../i18n/useI18n';
import { formatMessage } from '../../i18n/formatMessage';

interface EnterpriseDirectoryProps {
  enterprises: Enterprise[];
  canDelete: boolean;
  onEdit: (enterprise: Enterprise) => void;
  onDelete: (id: string) => void;
}

export function EnterpriseDirectory({ enterprises, canDelete, onEdit, onDelete }: EnterpriseDirectoryProps) {
  const { t, language } = useI18n();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const panel = useRef<HTMLElement | null>(null);
  const selected = enterprises.find((enterprise) => enterprise.id === selectedId);
  const close = () => {
    setSelectedId(null);
    opener.current?.focus();
  };
  const clientName = (enterprise: Enterprise) => enterprise.tenant_name?.trim().toLocaleLowerCase() !== enterprise.nom.trim().toLocaleLowerCase()
    ? enterprise.tenant_name : null;
  const date = selected?.created_at ? new Date(selected.created_at) : null;
  const formattedDate = date && !Number.isNaN(date.getTime())
    ? new Intl.DateTimeFormat(language === 'fr' ? 'fr-FR' : 'en-GB', { dateStyle: 'medium' }).format(date) : '—';

  return (
    <div data-detail-open={Boolean(selected)} className={`enterprise-directory grid min-w-0 overflow-hidden rounded-[var(--brain-ops-radius-structural)] border border-[var(--brain-ops-border)] bg-[var(--brain-ops-surface)] ${selected ? 'xl:grid-cols-[minmax(0,1fr)_20rem]' : ''}`}>
      <div className="min-w-0 px-3 sm:px-5">
        <div className="flex justify-between gap-4 px-3 py-4 text-xs text-[var(--brain-ops-text-muted)]">
          <span>{t('clients.directory.companySector')}</span><span>{t('clients.directory.access')}</span>
        </div>
        <ul aria-label={t('clients.title')} className="m-0 list-none p-0">
          {enterprises.map((enterprise) => (
            <li key={enterprise.id} className="border-t border-[color:color-mix(in_srgb,var(--brain-ops-border)_55%,transparent)]">
              <button
                type="button"
                aria-label={formatMessage(t('clients.directory.openFor'), { company: enterprise.nom })}
                aria-expanded={selected?.id === enterprise.id}
                aria-controls={selected?.id === enterprise.id ? 'enterprise-directory-detail' : undefined}
                className={`enterprise-directory-row flex w-full min-w-0 items-center justify-between gap-4 px-3 py-5 text-left transition-colors hover:bg-[var(--brain-ops-surface-muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] ${selected?.id === enterprise.id ? 'bg-[var(--brain-ops-surface-muted)]' : ''}`}
                onClick={(event) => {
                  opener.current = event.currentTarget;
                  setSelectedId(enterprise.id);
                  requestAnimationFrame(() => {
                    panel.current?.focus({ preventScroll: true });
                    if (window.innerWidth < 1024) panel.current?.scrollIntoView({ block: 'nearest', behavior: 'instant' });
                  });
                }}
              >
                <span className="min-w-0">
                  <span className="block break-words font-medium text-[var(--brain-ops-text)]">{enterprise.nom}</span>
                  {clientName(enterprise) && <span className="mt-1 block break-words text-xs text-[var(--brain-ops-text-muted)]">{t('clients.creation.companyCabinet')} : {clientName(enterprise)}</span>}
                  <span className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-[var(--brain-ops-text-muted)]">
                    <span>{enterprise.secteur || t('clients.industryMissing')}</span><span aria-hidden="true">·</span>
                    <span>{formatMessage(t(enterprise.projects_count === 1 ? 'clients.directory.project' : 'clients.directory.projects'), { count: enterprise.projects_count || 0 })}</span>
                  </span>
                </span>
                <span className="inline-flex shrink-0 items-center gap-2 text-sm text-[var(--brain-ops-text-muted)]">{t('clients.directory.open')}<ArrowRight className="size-4" aria-hidden="true" /></span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      {selected && (
        <aside
          id="enterprise-directory-detail" ref={panel} tabIndex={-1} aria-labelledby="enterprise-directory-title"
          onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); close(); } }}
          className="enterprise-directory-panel min-w-0 border-t border-[var(--brain-ops-border)] bg-[var(--brain-ops-canvas)] p-5 xl:border-l xl:border-t-0"
        >
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-[var(--brain-ops-text-muted)]">{t('clients.directory.details')}</span>
            <Button variant="ghost" size="icon" onClick={close} aria-label={t('clients.directory.close')}><X className="size-4" /></Button>
          </div>
          <h2 id="enterprise-directory-title" className="mt-4 break-words text-xl font-medium tracking-tight">{selected.nom}</h2>
          <p className="mt-1 break-words text-sm text-[var(--brain-ops-text-muted)]">{selected.secteur || t('clients.industryMissing')}</p>
          <dl className="my-6 divide-y divide-[var(--brain-ops-border)] border-y border-[var(--brain-ops-border)] text-sm">
            {clientName(selected) && <div className="py-3"><dt className="text-xs text-[var(--brain-ops-text-muted)]">{t('clients.creation.companyCabinet')}</dt><dd className="mt-1 break-words">{clientName(selected)}</dd></div>}
            <div className="py-3"><dt className="text-xs text-[var(--brain-ops-text-muted)]">{t('common.projects')}</dt><dd className="mt-1">{selected.projects_count || 0}</dd></div>
            <div className="py-3"><dt className="text-xs text-[var(--brain-ops-text-muted)]">{t('clients.createdOn')}</dt><dd className="mt-1">{formattedDate}</dd></div>
            {selected.site_web && <div className="py-3"><dt className="text-xs text-[var(--brain-ops-text-muted)]">{t('clients.dialog.website')}</dt><dd className="mt-1 break-words">{selected.site_web}</dd></div>}
          </dl>
          <div className="flex flex-col gap-3">
            <Link className="inline-flex min-h-11 items-center justify-between gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/80" to={`/enterprises/${selected.id}`}>{t('clients.directory.viewProjects')}<ArrowRight className="size-4" aria-hidden="true" /></Link>
            <Button variant="outline" onClick={() => onEdit(selected)}>{t('clients.directory.edit')}</Button>
            {canDelete && <Button variant="ghost" className="mt-3 text-[var(--brain-ops-danger)]" onClick={() => onDelete(selected.id)}>{t('clients.delete.title')}</Button>}
          </div>
        </aside>
      )}
    </div>
  );
}
