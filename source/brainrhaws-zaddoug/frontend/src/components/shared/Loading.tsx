import { Loader2 } from 'lucide-react';
import { cn } from '../../lib/utils';

interface LoadingProps {
  className?: string;
  size?: 'sm' | 'md' | 'lg';
  text?: string;
}

export const Loading: React.FC<LoadingProps> = ({ className, size = 'md', text }) => {
  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-8 w-8',
    lg: 'h-12 w-12',
  };

  return (
    <div className={cn('flex flex-col items-center justify-center gap-2', className)}>
      <Loader2 className={cn('animate-spin text-primary motion-reduce:animate-none', sizeClasses[size])} />
      {text && <p className="text-sm text-muted-foreground">{text}</p>}
    </div>
  );
};

export const LoadingPage: React.FC<{ text: string }> = ({ text }) => {
  return (
    <div data-brain-ops="" className="min-h-32 py-4">
      <div
        role="status"
        aria-live="polite"
        aria-busy="true"
        className="inline-flex max-w-full rounded-[var(--brain-ops-radius-structural)] border border-l-4 border-[color:var(--brain-ops-border)] border-l-[color:var(--brain-ops-accent)] bg-[var(--brain-ops-surface)] p-3"
      >
        <Loading className="flex-row justify-start" size="sm" text={text} />
      </div>
    </div>
  );
};
