import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/utils';

type NamedActionGroup =
  | { ariaLabel: string; actions: ReactNode }
  | { ariaLabel?: undefined; actions?: undefined };

export type ActionGroupProps = Omit<HTMLAttributes<HTMLDivElement>, 'children'> &
  NamedActionGroup;

export function ActionGroup({ ariaLabel, actions, className, ...props }: ActionGroupProps) {
  if (!actions) {
    return null;
  }

  return (
    <div
      {...props}
      role="group"
      aria-label={ariaLabel}
      className={cn('brain-ops-action-group flex shrink-0 flex-wrap items-center gap-2', className)}
    >
      {actions}
    </div>
  );
}
