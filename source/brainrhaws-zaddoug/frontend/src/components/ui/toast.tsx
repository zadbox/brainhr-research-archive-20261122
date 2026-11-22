import * as React from 'react';
import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from 'lucide-react';
import { cn } from '../../lib/utils';

export interface Toast {
  id: string;
  title?: string;
  description?: string;
  type?: 'success' | 'error' | 'warning' | 'info';
  duration?: number;
}

interface ToastProps extends Toast {
  onClose: (id: string) => void;
  closeLabel: string;
}

const typeStyles = {
  success: {
    edge: 'border-l-[color:var(--brain-ops-success)]',
    icon: 'text-[var(--brain-ops-success)]',
    Icon: CircleCheck,
  },
  error: {
    edge: 'border-l-[color:var(--brain-ops-danger)]',
    icon: 'text-[var(--brain-ops-danger)]',
    Icon: CircleAlert,
  },
  warning: {
    edge: 'border-l-[color:var(--brain-ops-warning)]',
    icon: 'text-[var(--brain-ops-warning)]',
    Icon: TriangleAlert,
  },
  info: {
    edge: 'border-l-[color:var(--brain-ops-accent)]',
    icon: 'text-[var(--brain-ops-accent)]',
    Icon: Info,
  },
} as const;

const Toast: React.FC<ToastProps> = ({ id, title, description, type = 'info', onClose, closeLabel }) => {
  const style = typeStyles[type];
  const Icon = style.Icon;
  const compact = type === 'success';

  return (
    <div
      data-brain-ops=""
      role={type === 'error' ? 'alert' : 'status'}
      aria-live={type === 'error' ? 'assertive' : 'polite'}
      aria-atomic="true"
      className={cn(
        'pointer-events-auto overflow-hidden rounded-[var(--brain-ops-radius-structural)]',
        compact ? 'w-fit max-w-full self-end' : 'w-full',
        'border border-l-[3px] border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]',
        'shadow-[0_4px_16px_color-mix(in_srgb,var(--brain-ops-text)_8%,transparent)]',
        'motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-reduce:transition-none',
        style.edge
      )}
    >
      <div className={cn('flex gap-2.5 px-3', compact ? 'items-center py-2' : 'items-start py-2.5')}>
        <Icon aria-hidden="true" className={cn(compact ? 'size-3.5' : 'mt-0.5 size-4', 'shrink-0', style.icon)} />
        <div className={cn('min-w-0 flex-1', compact && 'flex flex-wrap items-baseline gap-x-1.5')}>
          {title && <p className="text-sm font-medium leading-5 text-[var(--brain-ops-text)]">{title}</p>}
          {description && (
            <p className={cn('text-xs leading-5 text-[var(--brain-ops-text-muted)]', !compact && 'mt-0.5')}>
              {description}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => onClose(id)}
          className={cn(
            'inline-flex shrink-0 items-center justify-center rounded-[var(--brain-ops-radius-structural)] text-[var(--brain-ops-text-muted)] transition-colors hover:bg-[var(--brain-ops-surface-muted)] hover:text-[var(--brain-ops-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)] motion-reduce:transition-none',
            compact ? 'size-7' : 'size-8'
          )}
          aria-label={closeLabel}
        >
          <X className={compact ? 'size-3.5' : 'size-4'} />
        </button>
      </div>
    </div>
  );
};

export { Toast };
