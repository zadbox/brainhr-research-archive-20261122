import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { ActionGroup } from './ActionGroup';

export interface OperationalListProps extends Omit<HTMLAttributes<HTMLUListElement>, 'children'> {
  ariaLabel: string;
  children: ReactNode;
}

type OperationalListItemActions =
  | { actions: ReactNode; actionsLabel: string }
  | { actions?: undefined; actionsLabel?: undefined };

export type OperationalListItemProps = Omit<HTMLAttributes<HTMLLIElement>, 'title'> &
  OperationalListItemActions & {
  primary: ReactNode;
  secondary?: ReactNode;
  metadata?: ReactNode;
  leading?: ReactNode;
  monospaceMetadata?: boolean;
};

export function OperationalList({
  ariaLabel,
  children,
  className,
  ...props
}: OperationalListProps) {
  return (
    <ul
      {...props}
      aria-label={ariaLabel}
      className={cn(
        'min-w-0 border-y border-[color:var(--brain-ops-border)]',
        '[&>li+li]:border-t [&>li+li]:border-[color:var(--brain-ops-border)]',
        className
      )}
    >
      {children}
    </ul>
  );
}

export function OperationalListItem({
  primary,
  secondary,
  metadata,
  leading,
  actions,
  actionsLabel,
  monospaceMetadata = false,
  className,
  ...props
}: OperationalListItemProps) {
  return (
    <li
      {...props}
      className={cn(
        'flex min-w-0 flex-col gap-4 bg-[var(--brain-ops-surface)] px-4 py-4',
        'transition-colors duration-[var(--brain-ops-duration-fast)] ease-[var(--brain-ops-ease-ui)]',
        'sm:flex-row sm:items-center sm:justify-between sm:px-5',
        'motion-reduce:transition-none',
        className
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        {leading && <div className="shrink-0 text-[var(--brain-ops-text-muted)]">{leading}</div>}
        <div className="flex min-w-0 flex-col gap-1">
          <div className="min-w-0 font-medium leading-6 text-[var(--brain-ops-text)]">{primary}</div>
          {secondary && (
            <div className="min-w-0 text-sm leading-5 text-[var(--brain-ops-text-muted)]">
              {secondary}
            </div>
          )}
          {metadata && (
            <div
              className={cn(
                'min-w-0 text-xs leading-5 text-[var(--brain-ops-text-muted)]',
                monospaceMetadata && '[font-family:var(--brain-ops-font-command)]'
              )}
            >
              {metadata}
            </div>
          )}
        </div>
      </div>

      {actions && actionsLabel ? (
        <ActionGroup ariaLabel={actionsLabel} actions={actions} className="sm:justify-end" />
      ) : null}
    </li>
  );
}
