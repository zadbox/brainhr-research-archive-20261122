import { ChevronDown } from 'lucide-react';
import { forwardRef } from 'react';
import type { ComponentPropsWithoutRef, ReactNode } from 'react';
import { cn } from '../../lib/utils';

export interface DisclosureSectionProps extends Omit<ComponentPropsWithoutRef<'details'>, 'title'> {
  title: ReactNode;
  description?: ReactNode;
  metadata?: ReactNode;
  children: ReactNode;
  contentClassName?: string;
  titleClassName?: string;
}

export const DisclosureSection = forwardRef<HTMLDetailsElement, DisclosureSectionProps>(
  function DisclosureSection({
    title,
    description,
    metadata,
    children,
    className,
    contentClassName,
    titleClassName,
    ...props
  }, ref) {
    return (
      <details
        ref={ref}
        {...props}
        className={cn(
          'group min-w-0 border-y border-[color:var(--brain-ops-border)]',
          className
        )}
      >
        <summary className="flex min-h-14 cursor-pointer list-none items-center gap-3 py-3 text-[var(--brain-ops-text)] marker:content-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--brain-ops-canvas)] [&::-webkit-details-marker]:hidden">
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className={cn('text-sm font-semibold leading-5', titleClassName)}>{title}</span>
            {description ? (
              <span className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">
                {description}
              </span>
            ) : null}
          </span>
          {metadata ? (
            <span className="shrink-0 font-mono text-[0.6875rem] uppercase tracking-[0.08em] text-[var(--brain-ops-text-muted)]">
              {metadata}
            </span>
          ) : null}
          <ChevronDown
            aria-hidden="true"
            className="size-4 shrink-0 text-[var(--brain-ops-text-muted)] transition-transform duration-200 group-open:rotate-180 motion-reduce:transition-none"
          />
        </summary>
        <div className={cn('border-t border-[color:var(--brain-ops-border)] py-5', contentClassName)}>
          {children}
        </div>
      </details>
    );
  }
);
