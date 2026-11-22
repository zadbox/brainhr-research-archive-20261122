import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/utils';

export type PageFrameWidth = 'content' | 'wide' | 'full';

export interface PageFrameProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  contentClassName?: string;
  width?: PageFrameWidth;
}

const widthClasses: Record<PageFrameWidth, string> = {
  content: 'max-w-5xl',
  wide: 'max-w-7xl',
  full: 'max-w-none',
};

/**
 * Owns the normal DOM Operations scope. Portaled dialog content must use
 * OperationsDialogContent so tokens cross the document.body portal boundary
 * without styling unrelated pages.
 */
export function PageFrame({
  children,
  className,
  contentClassName,
  width = 'wide',
  ...props
}: PageFrameProps) {
  return (
    <div
      data-tour="page-content"
      {...props}
      data-brain-ops=""
      className={cn(
        'min-w-0 text-[var(--brain-ops-text)]',
        '[font-family:var(--brain-ops-font-body)]',
        className
      )}
    >
      <div
        className={cn(
          'mx-auto flex w-full min-w-0 flex-col gap-8',
          'lg:gap-10',
          widthClasses[width],
          contentClassName
        )}
      >
        {children}
      </div>
    </div>
  );
}
