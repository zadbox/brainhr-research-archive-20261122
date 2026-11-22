import { useId, type ComponentPropsWithoutRef, type ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { ActionGroup } from './ActionGroup';

type SectionNaming =
  | { title: ReactNode; ariaLabel?: string }
  | { title?: undefined; ariaLabel: string };

type SectionActions =
  | { actions: ReactNode; actionsLabel: string }
  | { actions?: undefined; actionsLabel?: undefined };

type SectionBaseProps = Omit<ComponentPropsWithoutRef<'section'>, 'title'> & {
  description?: ReactNode;
  children: ReactNode;
  contentClassName?: string;
  headingAs?: 'h2' | 'h3';
  divided?: boolean;
};

export type SectionProps = SectionBaseProps & SectionNaming & SectionActions;

export function Section({
  title,
  description,
  ariaLabel,
  actions,
  actionsLabel,
  children,
  className,
  contentClassName,
  headingAs = 'h2',
  divided = true,
  ...props
}: SectionProps) {
  const titleId = useId();
  const Heading = headingAs;

  return (
    <section
      {...props}
      aria-label={title ? undefined : ariaLabel}
      aria-labelledby={title ? titleId : undefined}
      className={cn(
        'flex min-w-0 flex-col gap-5',
        divided && 'border-t border-[color:var(--brain-ops-border)] pt-6 sm:pt-8',
        className
      )}
    >
      {(title || description || actions) && (
        <div className="flex min-w-0 flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 max-w-3xl flex-col gap-2">
            {title && (
              <Heading id={titleId} className="text-xl font-semibold leading-tight tracking-[-0.01em] sm:text-2xl">
                {title}
              </Heading>
            )}
            {description && (
              <div className="text-sm leading-6 text-[var(--brain-ops-text-muted)]">
                {description}
              </div>
            )}
          </div>

          {actions && actionsLabel ? (
            <ActionGroup ariaLabel={actionsLabel} actions={actions} className="sm:justify-end" />
          ) : null}
        </div>
      )}

      <div className={cn('min-w-0', contentClassName)}>{children}</div>
    </section>
  );
}
