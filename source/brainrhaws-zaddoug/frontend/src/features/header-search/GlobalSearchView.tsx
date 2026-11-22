import { Building2, FileUser, FolderClosed, LoaderCircle, Search } from 'lucide-react';
import type { KeyboardEvent, RefObject } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '../../components/ui/button';
import { cn } from '../../lib/utils';
import type { HeaderSearchKey } from './searchMessages';
import type { SearchResult, SearchStatus } from './types';

interface GlobalSearchViewProps {
  query: string;
  status: SearchStatus;
  results: SearchResult[];
  total: number;
  partial: boolean;
  inputRef?: RefObject<HTMLInputElement | null>;
  onQueryChange: (query: string) => void;
  onRetry: () => void;
  onNavigate: () => void;
  text: (key: HeaderSearchKey) => string;
}

const resultIcons = {
  candidate: FileUser,
  project: FolderClosed,
  company: Building2,
};

const resultGroupKeys = {
  candidate: 'headerSearch.group.candidates',
  project: 'headerSearch.group.projects',
  company: 'headerSearch.group.companies',
} as const;

export function GlobalSearchView({
  query,
  status,
  results,
  total,
  partial,
  inputRef,
  onQueryChange,
  onRetry,
  onNavigate,
  text,
}: GlobalSearchViewProps) {
  const normalizedLength = query.trim().length;
  const grouped = (['candidate', 'project', 'company'] as const).map((kind) => ({
    kind,
    results: results.filter((result) => result.kind === kind),
  })).filter((group) => group.results.length > 0);

  const focusFirstResult = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'ArrowDown' || results.length === 0) return;
    event.preventDefault();
    event.currentTarget.closest('[role="dialog"]')
      ?.querySelector<HTMLElement>('[data-search-result]')?.focus();
  };

  return (
    <div className="flex min-h-64 flex-col gap-4">
      <label className="sr-only" htmlFor="global-search-input">
        {text('headerSearch.inputLabel')}
      </label>
      <div className="relative">
        <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-[var(--brain-ops-text-muted)]" />
        <input
          ref={inputRef}
          id="global-search-input"
          type="search"
          role="searchbox"
          autoComplete="off"
          value={query}
          placeholder={text('headerSearch.placeholder')}
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={focusFirstResult}
          className="h-12 w-full rounded-[var(--brain-ops-radius-panel)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] pl-10 pr-4 text-base text-[var(--brain-ops-text)] outline-none transition-shadow placeholder:text-[var(--brain-ops-text-muted)] focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)] motion-reduce:transition-none"
        />
      </div>

      <div aria-live="polite" className="min-h-40">
        {status === 'ready' && partial && (
          <div role="status" className="mb-3 flex flex-col items-start gap-2 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] px-3 py-2 text-xs text-[var(--brain-ops-text-muted)] sm:flex-row sm:items-center sm:justify-between">
            <span>{text('headerSearch.partial')}</span>
            <Button type="button" variant="outline" size="sm" onClick={onRetry}>{text('headerSearch.retry')}</Button>
          </div>
        )}
        {normalizedLength < 2 ? (
          <p className="py-8 text-center text-sm text-[var(--brain-ops-text-muted)]">{text('headerSearch.minimum')}</p>
        ) : status === 'loading' ? (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-[var(--brain-ops-text-muted)]">
            <LoaderCircle aria-hidden="true" className="size-5 animate-spin motion-reduce:animate-none" />
            {text('headerSearch.loading')}
          </div>
        ) : status === 'error' ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <div>
              <p className="font-medium">{text('headerSearch.errorTitle')}</p>
              <p className="mt-1 text-sm text-[var(--brain-ops-text-muted)]">{text('headerSearch.errorDescription')}</p>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={onRetry}>{text('headerSearch.retry')}</Button>
          </div>
        ) : status === 'ready' && results.length === 0 ? (
          <div className="py-8 text-center">
            <p className="font-medium">{text('headerSearch.emptyTitle')}</p>
            <p className="mt-1 text-sm text-[var(--brain-ops-text-muted)]">{text('headerSearch.emptyDescription')}</p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {grouped.map((group) => (
              <section key={group.kind} aria-labelledby={`search-group-${group.kind}`}>
                <h3 id={`search-group-${group.kind}`} className="mb-1 px-2 font-mono text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-[var(--brain-ops-text-muted)]">
                  {text(resultGroupKeys[group.kind])}
                </h3>
                <ul className="flex flex-col" role="list">
                  {group.results.map((result) => {
                    const Icon = resultIcons[result.kind];
                    return (
                      <li key={`${result.kind}:${result.id}`}>
                        <Link
                          data-search-result=""
                          to={result.href}
                          onClick={onNavigate}
                          className={cn(
                            'flex min-h-14 items-center gap-3 rounded-[var(--brain-ops-radius-structural)] px-2 py-2',
                            'transition-colors hover:bg-[var(--brain-ops-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)] motion-reduce:transition-none'
                          )}
                        >
                          <span className="flex size-9 shrink-0 items-center justify-center rounded-[var(--brain-ops-radius-structural)] bg-[var(--brain-ops-surface-muted)] text-[var(--brain-ops-text-muted)]">
                            <Icon aria-hidden="true" className="size-4" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium">{result.primary}</span>
                            {result.secondary && <span className="block truncate text-xs text-[var(--brain-ops-text-muted)]">{result.secondary}</span>}
                          </span>
                          <span className="hidden font-mono text-[0.68rem] uppercase tracking-wide text-[var(--brain-ops-text-muted)] sm:block">
                            {text(`headerSearch.type.${result.kind}`)}
                          </span>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
            {total > results.length && (
              <p className="border-t border-[color:var(--brain-ops-border)] pt-3 text-center text-xs text-[var(--brain-ops-text-muted)]">
                {text('headerSearch.refine')}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
