import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, ChevronDown, ChevronsUpDown, RefreshCw } from 'lucide-react';
import { useI18n } from '../../i18n/useI18n';
import { cn } from '../../lib/utils';
import { Button } from '../ui/button';
import { Label } from '../ui/label';
import { Input } from '../ui/input';
import {
  OperationsDialog, OperationsDialogClose, OperationsDialogContent,
  OperationsDialogDescription, OperationsDialogFooter, OperationsDialogHeader, OperationsDialogTitle,
} from '../operations';

interface ClientWorkspacePickerProps {
  clients: readonly { id: string; name: string }[];
  selectedTenantId: string;
  status: 'ready' | 'loading' | 'error';
  collapsed?: boolean;
  compact?: boolean;
  onSelect: (tenantId: string) => void;
  onRetry: () => void;
  onNavigate?: () => void;
}

/** Platform view preference only. Client accounts never mount this control. */
export function ClientWorkspacePicker({ clients, selectedTenantId, status, collapsed = false, compact = false, onSelect, onRetry, onNavigate }: ClientWorkspacePickerProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const selectorId = useId();
  const descriptionId = useId();
  const selectedClient = clients.find((client) => client.id === selectedTenantId);
  const currentLabel = selectedTenantId ? selectedClient?.name ?? t('tenant.currentClient') : t('tenant.allClients');
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleClients = clients.filter((client) => client.name.toLocaleLowerCase().includes(normalizedQuery));
  const choices = [
    { id: '', name: t('tenant.allClients') },
    ...(selectedTenantId && !selectedClient ? [{ id: selectedTenantId, name: t('tenant.selectedClient') }] : []),
    ...visibleClients,
  ];

  return <>
    <button type="button" onClick={() => { setQuery(''); setOpen(true); }} aria-haspopup="dialog" aria-expanded={open}
      aria-label={t('tenant.switchClient')} title={`${t('tenant.switchClient')} · ${currentLabel}`}
      className={cn('brain-shell-touch-target flex w-full min-w-0 items-center gap-2 rounded-md px-4 py-2 text-left text-[var(--brain-ops-text-muted)] transition-colors hover:bg-[var(--brain-sidebar-active)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-text)]', collapsed && 'justify-center px-0', compact && 'w-auto max-w-44 rounded-[var(--brain-ops-radius-panel)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] px-3')}>
      {!collapsed && <span className="min-w-0 flex-1">
        {!compact && <span className="block text-[0.65rem] font-medium uppercase tracking-wider">{t('tenant.workspace')}</span>}
        <span className={cn('block truncate font-medium text-[var(--brain-ops-text)]', compact ? 'text-sm' : 'text-xs')}>{currentLabel}</span>
      </span>}
      {compact ? <ChevronDown className="size-4 shrink-0" aria-hidden="true" /> : <ChevronsUpDown className="size-4 shrink-0" aria-hidden="true" />}
    </button>
    <OperationsDialog open={open} onOpenChange={setOpen}>
      <OperationsDialogContent aria-describedby={descriptionId} className="max-w-lg">
        <OperationsDialogHeader className="pr-8 text-left">
          <OperationsDialogTitle>{t('tenant.switchClient')}</OperationsDialogTitle>
          <OperationsDialogDescription id={descriptionId}>{t('tenant.workspaceHelp')}</OperationsDialogDescription>
        </OperationsDialogHeader>
        <OperationsDialogClose className="flex size-11 items-center justify-center" />
        <div className="space-y-2">
          <Label htmlFor={selectorId}>{t('tenant.searchClients')}</Label>
          <Input id={selectorId} type="search" value={query} disabled={status !== 'ready'}
            onChange={(event) => setQuery(event.target.value)} className="min-h-11" />
          <p className="text-xs text-[var(--brain-ops-text-muted)]">{t('tenant.currentSelection')}: {currentLabel}</p>
          <fieldset disabled={status === 'loading'} aria-label={t('tenant.selectorLabel')} className="min-w-0">
            <div className="max-h-56 space-y-1 overflow-y-auto overscroll-contain p-1">
              {choices.map((client) => <label key={client.id} className={cn(
                'brain-client-choice flex min-h-11 cursor-pointer items-center gap-3 px-3 py-2.5 text-sm transition-colors',
                'hover:bg-[var(--brain-ops-surface-muted)] has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-[-2px]',
                selectedTenantId === client.id && 'bg-[var(--brain-ops-surface-muted)] font-medium',
                status === 'loading' && 'cursor-wait opacity-60',
              )}>
                <input type="radio" name={selectorId} value={client.id} checked={selectedTenantId === client.id}
                  onChange={() => onSelect(client.id)} className="size-4 shrink-0 accent-[var(--brain-ops-text)]" />
                <span className="min-w-0 break-words [overflow-wrap:anywhere]">{client.name}</span>
              </label>)}
            </div>
          </fieldset>
          {status === 'ready' && normalizedQuery && !visibleClients.length && <p role="status" className="text-sm text-[var(--brain-ops-text-muted)]">{t('tenant.noSearchResults')}</p>}
          {status === 'loading' && <p role="status" className="text-sm text-[var(--brain-ops-text-muted)]">{t('tenant.loadingCatalog')}</p>}
          {status === 'error' && <div role="status" className="space-y-2 text-sm text-[var(--brain-ops-text-muted)]">
            <p>{t('tenant.catalogError')}</p>
            <Button type="button" variant="outline" onClick={onRetry} className="min-h-11 whitespace-normal">
              <RefreshCw className="size-4 shrink-0" aria-hidden="true" />{t('tenant.retryCatalog')}
            </Button>
          </div>}
          {status === 'ready' && !clients.length && <p className="text-sm text-[var(--brain-ops-text-muted)]">{t('tenant.noClients')}</p>}
        </div>
        <OperationsDialogFooter className="mt-2 sm:items-center sm:justify-between">
          <Link to="/enterprises" onClick={() => { setOpen(false); onNavigate?.(); }}
            className="inline-flex min-h-11 items-center gap-2 text-sm font-medium underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-2">
            {t('tenant.openCompanies')}<ArrowRight className="size-4" aria-hidden="true" />
          </Link>
          <Button type="button" onClick={() => setOpen(false)} className="min-h-11">{t('common.close')}</Button>
        </OperationsDialogFooter>
      </OperationsDialogContent>
    </OperationsDialog>
  </>;
}
