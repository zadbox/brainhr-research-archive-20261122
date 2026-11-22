import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/utils';

export type MetricTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

export interface MetricStripItem {
  id: string;
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
  tone?: MetricTone;
}

export interface MetricStripProps extends Omit<HTMLAttributes<HTMLElement>, 'children'> {
  ariaLabel: string;
  items: readonly MetricStripItem[];
}

const toneClasses: Record<MetricTone, string> = {
  neutral: 'text-[var(--brain-ops-text)]',
  accent: 'text-[var(--brain-ops-accent)]',
  success: 'text-[var(--brain-ops-success)]',
  warning: 'text-[var(--brain-ops-warning)]',
  danger: 'text-[var(--brain-ops-danger)]',
};

export function MetricStrip({ ariaLabel, items, className, ...props }: MetricStripProps) {
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
      <dl className="grid grid-cols-2 gap-px sm:grid-cols-[repeat(auto-fit,minmax(11rem,1fr))]">
        {items.map((item, index) => {
          const tone = item.tone ?? 'neutral';
          const spansMobileRow = items.length === 1
            || (items.length % 2 === 1 && index === items.length - 1);

          return (
            <div
              key={item.id}
              className={cn(
                'flex min-w-0 flex-col gap-2 bg-[var(--brain-ops-surface)] px-4 py-4 sm:px-5',
                spansMobileRow && 'col-span-2 sm:col-span-1'
              )}
            >
              <dt className="text-[0.6875rem] font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                {item.label}
              </dt>
              <dd className="flex min-w-0 flex-col gap-1">
                <span
                  className={cn(
                    'break-words text-xl font-semibold leading-none tracking-[-0.02em] [font-family:var(--brain-ops-font-command)] [overflow-wrap:anywhere] sm:text-2xl',
                    toneClasses[tone]
                  )}
                >
                  {item.value}
                </span>
                {item.detail && (
                  <span className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">
                    {item.detail}
                  </span>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
