import { ArrowLeft } from 'lucide-react';
import { cn } from '../../lib/utils';
import { Button, type ButtonProps } from '../ui/button';

export interface PageBackButtonProps extends Omit<ButtonProps, 'children' | 'size' | 'variant'> {
  'aria-label': string;
}

export function PageBackButton({ className, ...props }: PageBackButtonProps) {
  return (
    <Button
      type="button"
      variant="outline"
      size="icon"
      className={cn(
        'brain-shell-square-target shrink-0 bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text)]',
        'hover:bg-[var(--brain-ops-surface-muted)]',
        className
      )}
      {...props}
      data-page-back-button=""
    >
      <ArrowLeft className="size-4" aria-hidden="true" />
    </Button>
  );
}
