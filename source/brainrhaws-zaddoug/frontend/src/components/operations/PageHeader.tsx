import { useId, type HTMLAttributes, type ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { ActionGroup } from './ActionGroup';

type PageHeaderActions =
  | { actions: ReactNode; actionsLabel: string }
  | { actions?: undefined; actionsLabel?: undefined };

export type PageHeaderProps = Omit<HTMLAttributes<HTMLElement>, 'title'> & PageHeaderActions & {
  title: ReactNode;
  description?: ReactNode;
  eyebrow?: ReactNode;
  backAction?: ReactNode;
  context?: ReactNode;
};

export function PageHeader({
  title,
  description,
  eyebrow,
  backAction,
  context,
  actions,
  actionsLabel,
  className,
  ...props
}: PageHeaderProps) {
  const titleId = useId();

  return (
    <header
      data-tour="page-header"
      {...props}
      aria-labelledby={titleId}
      className={cn(
        'flex min-w-0 flex-col gap-5 border-b border-[color:var(--brain-ops-border)] pb-6',
        'sm:pb-8',
        className
      )}
    >
      <div className="flex min-w-0 flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 max-w-3xl flex-col gap-3">
          {(backAction || eyebrow) && (
            <div className="flex min-w-0 items-center gap-3">
              {backAction}
              {eyebrow && (
                <div
                  data-page-header-eyebrow=""
                  className="min-w-0 text-xs font-medium uppercase tracking-[0.12em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]"
                >
                  {eyebrow}
                </div>
              )}
            </div>
          )}
          <h1 id={titleId} className="text-3xl font-semibold leading-tight tracking-[-0.02em] sm:text-4xl">
            {title}
          </h1>
          {description && (
            <div className="max-w-2xl text-sm leading-6 text-[var(--brain-ops-text-muted)] sm:text-base sm:leading-7">
              {description}
            </div>
          )}
        </div>

        {actions && actionsLabel ? (
          <ActionGroup data-tour="page-actions" ariaLabel={actionsLabel} actions={actions} className="sm:justify-end" />
        ) : null}
      </div>

      {context && <div className="min-w-0">{context}</div>}
    </header>
  );
}
