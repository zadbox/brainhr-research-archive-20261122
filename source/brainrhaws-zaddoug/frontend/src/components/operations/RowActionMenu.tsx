import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { MoreHorizontal } from 'lucide-react';
import { cn } from '../../lib/utils';
import { Button } from '../ui/button';

export interface RowActionMenuItem {
  id: string;
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  destructive?: boolean;
  disabled?: boolean;
}

export interface RowActionMenuProps {
  triggerLabel: string;
  menuLabel: string;
  items: RowActionMenuItem[];
  className?: string;
}

interface MenuPosition {
  left: number;
  top: number;
}

export function RowActionMenu({
  triggerLabel,
  menuLabel,
  items,
  className,
}: RowActionMenuProps) {
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<MenuPosition>({ left: 8, top: 8 });

  const updatePosition = () => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const menuWidth = menuRef.current?.offsetWidth ?? 224;
    const menuHeight = menuRef.current?.offsetHeight ?? 176;
    const gap = 6;
    const viewportPadding = 8;
    const left = Math.max(
      viewportPadding,
      Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - viewportPadding),
    );
    const hasRoomBelow = rect.bottom + gap + menuHeight <= window.innerHeight - viewportPadding;
    const top = hasRoomBelow
      ? rect.bottom + gap
      : Math.max(viewportPadding, rect.top - menuHeight - gap);
    setPosition({ left, top });
  };

  const closeMenu = (restoreFocus = false) => {
    setOpen(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => triggerRef.current?.focus());
    }
  };

  const openMenu = (focus: 'first' | 'last' = 'first') => {
    if (items.every((item) => item.disabled)) return;
    setOpen(true);
    window.requestAnimationFrame(() => {
      const enabledItems = itemRefs.current.filter((item) => item && !item.disabled);
      const target = focus === 'last' ? enabledItems.at(-1) : enabledItems[0];
      target?.focus();
    });
  };

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      closeMenu();
    };
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      closeMenu(true);
    };
    const handleViewportChange = () => updatePosition();

    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    window.addEventListener('resize', handleViewportChange);
    window.addEventListener('scroll', handleViewportChange, true);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('resize', handleViewportChange);
      window.removeEventListener('scroll', handleViewportChange, true);
    };
  }, [open]);

  const handleMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const enabledItems = itemRefs.current.filter(
      (item): item is HTMLButtonElement => Boolean(item && !item.disabled),
    );
    if (enabledItems.length === 0) return;
    const currentIndex = enabledItems.indexOf(document.activeElement as HTMLButtonElement);
    let nextIndex: number | null = null;
    if (event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % enabledItems.length;
    if (event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + enabledItems.length) % enabledItems.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = enabledItems.length - 1;
    if (event.key === 'Tab') closeMenu();
    if (nextIndex === null) return;
    event.preventDefault();
    enabledItems[nextIndex]?.focus();
  };

  const menu = open ? (
    <div
      id={menuId}
      ref={menuRef}
      data-brain-ops=""
      role="menu"
      aria-label={menuLabel}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={handleMenuKeyDown}
      className={cn(
        'fixed z-[100] min-w-52 overflow-hidden rounded-[var(--brain-ops-radius-structural)]',
        'border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-1',
        'text-[var(--brain-ops-text)] shadow-lg shadow-black/10 dark:shadow-black/40',
      )}
      style={{ left: position.left, top: position.top }}
    >
      {items.map((item, index) => (
        <button
          key={item.id}
          ref={(node) => { itemRefs.current[index] = node; }}
          type="button"
          role="menuitem"
          disabled={item.disabled}
          onClick={() => {
            triggerRef.current?.focus();
            closeMenu();
            item.onSelect();
          }}
          className={cn(
            'flex min-h-11 w-full items-center gap-3 px-3 py-2 text-left text-sm',
            'rounded-[var(--brain-ops-radius-structural)] transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)]',
            'disabled:pointer-events-none disabled:opacity-50',
            item.destructive
              ? 'text-[var(--brain-ops-danger)] hover:bg-[color-mix(in_srgb,var(--brain-ops-danger)_10%,transparent)]'
              : 'hover:bg-[var(--brain-ops-surface-muted)]',
          )}
        >
          <span aria-hidden="true" className="flex size-4 shrink-0 items-center justify-center">
            {item.icon}
          </span>
          <span>{item.label}</span>
        </button>
      ))}
    </div>
  ) : null;

  return (
    <div className={cn('relative inline-flex', className)} onClick={(event) => event.stopPropagation()}>
      <Button
        ref={triggerRef}
        type="button"
        variant="ghost"
        size="sm"
        aria-label={menuLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => {
          if (open) closeMenu(true);
          else openMenu();
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown') {
            event.preventDefault();
            openMenu('first');
          }
          if (event.key === 'ArrowUp') {
            event.preventDefault();
            openMenu('last');
          }
        }}
      >
        <MoreHorizontal data-icon="inline-start" aria-hidden="true" />
        {triggerLabel}
      </Button>
      {menu && typeof document !== 'undefined' ? createPortal(menu, document.body) : null}
    </div>
  );
}
