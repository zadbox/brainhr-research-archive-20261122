import { Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  OperationsDialog,
  OperationsDialogClose,
  OperationsDialogContent,
  OperationsDialogDescription,
  OperationsDialogHeader,
  OperationsDialogTitle,
} from '../../components/operations';
import { Button } from '../../components/ui/button';
import { useAuth } from '../auth/context/AuthContext';
import { useI18n } from '../../i18n/useI18n';
import { useAppStore } from '../../stores/useAppStore';
import { GlobalSearchView } from './GlobalSearchView';
import { loadSearchIndex, searchIndex } from './searchData';
import type { HeaderSearchKey } from './searchMessages';
import type { SearchIndex, SearchStatus } from './types';

export function GlobalSearch() {
  const { user } = useAuth();
  const { t } = useI18n();
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<SearchStatus>('idle');
  const [index, setIndex] = useState<SearchIndex | null>(null);
  const [retryRevision, setRetryRevision] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const isPlatformAdmin = user?.role === 'platform_admin';
  const scope = isPlatformAdmin ? selectedTenantId : '';
  const shouldLoad = open && query.trim().length >= 2;
  const text = useCallback((key: HeaderSearchKey) => t(key), [t]);

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === 'k') {
        event.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener('keydown', onShortcut);
    return () => window.removeEventListener('keydown', onShortcut);
  }, []);

  useEffect(() => {
    if (!open) {
      setQuery('');
      setIndex(null);
      setStatus('idle');
    }
  }, [open]);

  useEffect(() => {
    if (!shouldLoad || index) return undefined;
    const controller = new AbortController();
    setStatus('loading');
    loadSearchIndex({ tenantId: scope || undefined, signal: controller.signal })
      .then((data) => {
        if (controller.signal.aborted) return;
        setIndex(data);
        setStatus('ready');
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus('error');
      });
    return () => controller.abort();
  }, [index, retryRevision, scope, shouldLoad]);

  useEffect(() => {
    setIndex(null);
    setStatus('idle');
  }, [scope]);

  const search = useMemo(
    () => index ? searchIndex(index, query) : { results: [], total: 0 },
    [index, query]
  );

  const retry = () => {
    setIndex(null);
    setStatus('loading');
    setRetryRevision((revision) => revision + 1);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={text('headerSearch.open')}
        className="hidden h-9 min-w-0 flex-1 items-center gap-2 rounded-[var(--brain-ops-radius-panel)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] px-3 text-sm text-[var(--brain-ops-text-muted)] transition-colors hover:bg-[var(--brain-ops-surface)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)] md:flex motion-reduce:transition-none"
      >
        <Search aria-hidden="true" className="size-4 shrink-0" />
        <span className="truncate">{text('headerSearch.trigger')}</span>
        <kbd className="ml-auto shrink-0 rounded border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] px-1.5 py-0.5 font-mono text-[0.68rem]">⌘K</kbd>
      </button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={() => setOpen(true)}
        aria-label={text('headerSearch.open')}
        className="brain-shell-touch-target brain-shell-square-target shrink-0 md:hidden"
      >
        <Search aria-hidden="true" className="brain-shell-icon" />
      </Button>

      <OperationsDialog open={open} onOpenChange={setOpen}>
        <OperationsDialogContent className="max-w-2xl grid-cols-1 gap-3 p-4 sm:p-5" aria-describedby="global-search-description">
          <OperationsDialogHeader className="pr-10">
            <OperationsDialogTitle>{text('headerSearch.title')}</OperationsDialogTitle>
            <OperationsDialogDescription id="global-search-description">{text('headerSearch.description')}</OperationsDialogDescription>
          </OperationsDialogHeader>
          <GlobalSearchView
            query={query}
            status={status}
            results={search.results}
            total={search.total}
            partial={Boolean(index?.failedCandidateProjects)}
            inputRef={inputRef}
            onQueryChange={setQuery}
            onRetry={retry}
            onNavigate={() => setOpen(false)}
            text={text}
          />
          <OperationsDialogClose />
        </OperationsDialogContent>
      </OperationsDialog>
    </>
  );
}
