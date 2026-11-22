import { useId, type HTMLAttributes, type ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { ActionGroup } from './ActionGroup';

export type SystemStateKind = 'loading' | 'empty' | 'info' | 'success' | 'warning' | 'error';

type SystemStateAction =
  | { action: ReactNode; actionLabel: string }
  | { action?: undefined; actionLabel?: undefined };

export type SystemStateProps = Omit<HTMLAttributes<HTMLElement>, 'title'> & SystemStateAction & {
  kind: SystemStateKind;
  title: ReactNode;
  description?: ReactNode;
  indicator?: ReactNode;
};

const stateClasses: Record<SystemStateKind, string> = {
  loading: 'border-l-[color:var(--brain-ops-accent)]',
  empty: '',
  info: '',
  success: 'border-l-[color:var(--brain-ops-success)]',
  warning: 'border-l-[color:var(--brain-ops-warning)]',
  error: 'border-l-[color:var(--brain-ops-danger)]',
};

export function SystemState({
  kind,
  title,
  description,
  indicator,
  action,
  actionLabel,
  className,
  ...props
}: SystemStateProps) {
  const titleId = useId();
  const isError = kind === 'error';
  const isLoading = kind === 'loading';
  const isCompactTransientState = (kind === 'success' || kind === 'loading') && !description && !action;

  return (
    <section
      {...props}
      role={isError ? 'alert' : 'status'}
      aria-live={isError ? 'assertive' : 'polite'}
      aria-atomic="true"
      aria-busy={isLoading || undefined}
      aria-labelledby={titleId}
      className={cn(
        'flex min-w-0 flex-col rounded-[var(--brain-ops-radius-structural)]',
        'border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]',
        kind !== 'empty' && kind !== 'info' && 'border-l-4',
        'sm:flex-row sm:items-start sm:justify-between',
        isCompactTransientState ? 'gap-2 p-3' : 'gap-4 p-5 sm:p-6',
        stateClasses[kind],
        className
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        {indicator && (
          <div aria-hidden="true" className="shrink-0 text-[var(--brain-ops-text-muted)]">
            {indicator}
          </div>
        )}
        <div className="flex min-w-0 flex-col gap-1">
          <p id={titleId} className="font-semibold leading-6 text-[var(--brain-ops-text)]">
            {title}
          </p>
          {description && (
            <div className="text-sm leading-6 text-[var(--brain-ops-text-muted)]">
              {description}
            </div>
          )}
        </div>
      </div>

      {action && actionLabel ? (
        <ActionGroup ariaLabel={actionLabel} actions={action} className="sm:justify-end" />
      ) : null}
    </section>
  );
}
