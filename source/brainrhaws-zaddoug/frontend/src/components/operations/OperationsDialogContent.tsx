import * as React from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { useI18n } from '../../i18n/useI18n';
import { cn } from '../../lib/utils';

interface OperationsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}

interface OperationsDialogContextValue {
  close: () => void;
  titleId: string;
}

const OperationsDialogContext = React.createContext<OperationsDialogContextValue | null>(null);

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export function OperationsDialog({
  open,
  onOpenChange,
  children,
}: OperationsDialogProps) {
  const titleId = React.useId();
  const onOpenChangeRef = React.useRef(onOpenChange);
  onOpenChangeRef.current = onOpenChange;

  const close = React.useCallback(() => onOpenChangeRef.current(false), []);

  React.useEffect(() => {
    if (!open) return undefined;

    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const getDialog = () =>
      document.getElementById(titleId)?.closest<HTMLElement>('[role="dialog"]') ?? null;

    const animationFrame = window.requestAnimationFrame(() => {
      const dialog = getDialog();
      if (!dialog) return;
      const firstFocusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
      ).find((element) => element.getClientRects().length > 0);
      (firstFocusable ?? dialog).focus();
    });

    const handleKeyDown = (event: KeyboardEvent) => {
      const dialog = getDialog();
      if (!dialog) return;

      if (event.key === 'Escape') {
        event.preventDefault();
        close();
        return;
      }

      if (event.key !== 'Tab') return;

      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
      ).filter((element) => element.getClientRects().length > 0);

      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
    };
  }, [close, open, titleId]);

  if (!open) return null;

  return createPortal(
    <OperationsDialogContext.Provider value={{ close, titleId }}>
      {children}
    </OperationsDialogContext.Provider>,
    document.body
  );
}

export const OperationsDialogContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, children, ...props }, ref) => {
  const context = React.useContext(OperationsDialogContext);

  if (!context) {
    throw new Error('OperationsDialogContent must be rendered inside OperationsDialog.');
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-x-hidden overflow-y-auto p-4"
    >
      <div
        aria-hidden="true"
        className="fixed inset-0 cursor-default bg-black/50 backdrop-blur-sm"
        onClick={context.close}
      />
      <div
        {...props}
        ref={ref}
        data-brain-ops=""
        role="dialog"
        aria-modal="true"
        aria-labelledby={context.titleId}
        tabIndex={-1}
        className={cn(
          'relative z-[60] my-auto grid max-h-[calc(100vh-2rem)] w-full',
          'max-w-[min(42rem,calc(100vw-2rem))] gap-4 overflow-x-hidden overflow-y-auto',
          'rounded-[var(--brain-ops-radius-panel)] border bg-background p-6 shadow-lg',
          className
        )}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
});
OperationsDialogContent.displayName = 'OperationsDialogContent';

export const OperationsDialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn('flex flex-col space-y-1.5 text-center sm:text-left', className)} {...props} />
);

export const OperationsDialogFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn('flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)}
    {...props}
  />
);

export const OperationsDialogTitle = React.forwardRef<
  HTMLHeadingElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => {
  const context = React.useContext(OperationsDialogContext);

  return (
    <h2
      {...props}
      ref={ref}
      id={context?.titleId}
      className={cn('text-lg font-semibold leading-none tracking-tight', className)}
    />
  );
});
OperationsDialogTitle.displayName = 'OperationsDialogTitle';

export const OperationsDialogDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p
    {...props}
    ref={ref}
    className={cn('text-sm text-[var(--brain-ops-text-muted)]', className)}
  />
));
OperationsDialogDescription.displayName = 'OperationsDialogDescription';

export const OperationsDialogClose = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement>
>(({ className, onClick, ...props }, ref) => {
  const context = React.useContext(OperationsDialogContext);
  const { t } = useI18n();

  return (
    <button
      {...props}
      ref={ref}
      type="button"
      className={cn(
        'absolute right-4 top-4 opacity-70 transition-opacity hover:opacity-100',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        'disabled:pointer-events-none',
        className
      )}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) context?.close();
      }}
    >
      <X className="size-4" />
      <span className="sr-only">{t('common.close')}</span>
    </button>
  );
});
OperationsDialogClose.displayName = 'OperationsDialogClose';

export type OperationsDialogContentProps = React.ComponentPropsWithoutRef<
  typeof OperationsDialogContent
>;
