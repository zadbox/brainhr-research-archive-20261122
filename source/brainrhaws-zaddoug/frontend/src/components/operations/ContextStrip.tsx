import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { ActionGroup } from './ActionGroup';

export interface ContextStripItem {
  id: string;
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
}

type ContextStripActions =
  | { actions: ReactNode; actionsLabel: string }
  | { actions?: undefined; actionsLabel?: undefined };

export type ContextStripProps = Omit<HTMLAttributes<HTMLElement>, 'children'> & ContextStripActions & {
  ariaLabel: string;
  items: readonly ContextStripItem[];
};

export function ContextStrip({
  ariaLabel,
  items,
  actions,
  actionsLabel,
  className,
  ...props
}: ContextStripProps) {
  return (
    <section
      {...props}
      aria-label={ariaLabel}
      className={cn(
        'overflow-hidden rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)]',
        'bg-[var(--brain-ops-border)]',
        className
      )}
    >
      {items.length > 0 ? <dl className="grid gap-px sm:grid-cols-[repeat(auto-fit,minmax(12rem,1fr))]">
        {items.map((item) => (
          <div key={item.id} className="flex min-w-0 flex-col gap-1 bg-[var(--brain-ops-surface)] px-4 py-3">
            <dt className="text-[0.6875rem] font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
              {item.label}
            </dt>
            <dd className="min-w-0 text-sm font-medium text-[var(--brain-ops-text)]">
              <span className="block break-words">{item.value}</span>
              {item.detail && (
                <span className="mt-1 block text-xs font-normal leading-5 text-[var(--brain-ops-text-muted)]">
                  {item.detail}
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl> : null}

      {actions && actionsLabel ? (
        <ActionGroup
          ariaLabel={actionsLabel}
          actions={actions}
          className="bg-[var(--brain-ops-surface)] px-4 py-2"
        />
      ) : null}
    </section>
  );
}
