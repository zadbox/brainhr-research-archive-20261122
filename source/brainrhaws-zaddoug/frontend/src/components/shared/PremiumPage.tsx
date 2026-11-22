import type { LucideIcon } from 'lucide-react';
import { cn } from '../../lib/utils';

export const premiumPageShellClass =
  'space-y-8 overflow-hidden rounded-[var(--brain-ops-radius-panel)] bg-[var(--brain-ops-canvas)] p-5 text-[var(--brain-ops-text)] sm:p-8';

export const premiumHeroClass =
  'relative overflow-hidden rounded-[var(--brain-ops-radius-panel)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-6 text-[var(--brain-ops-text)] sm:p-8';

export const premiumHeroBackdropClass =
  'pointer-events-none absolute inset-x-0 top-0 h-px bg-[var(--brain-ops-accent)]';

export const premiumHeroGridClass =
  'pointer-events-none absolute inset-y-0 left-0 w-px bg-[var(--brain-ops-border)]';

export const premiumHeroBadgeClass =
  'inline-flex min-h-8 items-center gap-2 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] px-3 py-1 text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]';

export const premiumHeroIconButtonClass =
  'flex h-9 w-9 items-center justify-center rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text)] transition-colors hover:bg-[var(--brain-ops-surface-muted)]';

export const premiumHeroPrimaryButtonClass =
  'gap-2 rounded-[var(--brain-ops-radius-structural)] px-5';

export const premiumHeroSecondaryButtonClass =
  'rounded-[var(--brain-ops-radius-structural)] border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text)] hover:bg-[var(--brain-ops-surface-muted)]';

export const premiumDarkSecondaryButtonClass =
  'rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] px-5 py-2 text-sm font-medium text-[var(--brain-ops-text)] transition-colors hover:bg-[var(--brain-ops-surface-muted)] disabled:opacity-50';

export const premiumDialogContentClass =
  'border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text)] sm:rounded-[var(--brain-ops-radius-panel)]';

export const premiumPanelClass =
  'rounded-[var(--brain-ops-radius-panel)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text)]';

export const premiumCardClass =
  'rounded-[var(--brain-ops-radius-panel)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text)] shadow-none';

export const premiumSubPanelClass =
  'rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] text-[var(--brain-ops-text)]';

export const premiumListItemClass =
  'group relative overflow-hidden rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-5 text-[var(--brain-ops-text)] transition-colors hover:bg-[var(--brain-ops-surface-muted)]';

export const premiumFieldClass =
  'border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text)] shadow-none placeholder:text-[var(--brain-ops-text-muted)] focus:border-[var(--brain-ops-focus-ring)] focus:ring-2 focus:ring-[var(--brain-ops-accent-soft)] focus-visible:border-[var(--brain-ops-focus-ring)] focus-visible:ring-[var(--brain-ops-accent-soft)] [&>option]:bg-[var(--brain-ops-surface)] [&>option]:text-[var(--brain-ops-text)]';

export const premiumTabsListClass =
  'h-auto flex-wrap justify-start gap-1 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-1 text-[var(--brain-ops-text-muted)]';

export const premiumTabsTriggerClass =
  'rounded-[var(--brain-ops-radius-structural)] px-4 py-2.5 data-[state=active]:bg-[var(--brain-ops-surface)] data-[state=active]:text-[var(--brain-ops-text)] data-[state=active]:shadow-none';

export const premiumHeroMetricClass =
  'rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-5';

type PremiumMetricCardProps = {
  icon: LucideIcon;
  label: string;
  value: string | number;
  description?: string;
  className?: string;
};

export function PremiumMetricCard({
  icon: Icon,
  label,
  value,
  description,
  className,
}: PremiumMetricCardProps) {
  return (
    <div className={cn(premiumHeroMetricClass, 'min-w-0 overflow-hidden', className)}>
      <div className="flex min-w-0 items-center gap-2 text-sm text-[var(--brain-ops-text-muted)]">
        <Icon className="h-4 w-4 shrink-0" />
        <span className="truncate uppercase tracking-widest">{label}</span>
      </div>
      <p
        className="mt-3 max-w-full break-words text-2xl font-semibold leading-tight tracking-tight text-[var(--brain-ops-text)] [overflow-wrap:anywhere] sm:text-3xl"
        title={String(value)}
      >
        {value}
      </p>
      {description ? (
        <p
          className="mt-2 max-w-full break-words text-sm leading-5 text-[var(--brain-ops-text-muted)] [overflow-wrap:anywhere]"
          title={description}
        >
          {description}
        </p>
      ) : null}
    </div>
  );
}
