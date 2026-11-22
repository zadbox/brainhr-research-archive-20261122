import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, ArrowRight, CircleHelp, X } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { useI18n } from '../../i18n/useI18n';
import { frameGuideTarget, placeGuide } from './geometry';
import { findGuideTarget, GuidePresentation, measureGuideTarget } from './targets';
import type { TourDefinition } from './tours';

interface GuideOverlayProps {
  tour: TourDefinition;
  step: number;
  onStep: (step: number) => void;
  onClose: (restoreFocus?: boolean) => void;
  onFinish: () => void;
}

/** Non-modal contextual help: the active target stays visible and the application remains interactive. */
export function GuideOverlay({ tour, step, onStep, onClose, onFinish }: GuideOverlayProps) {
  const { t } = useI18n();
  const titleId = useId();
  const descriptionId = useId();
  const layerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const [geometry, setGeometry] = useState<ReturnType<typeof placeGuide> | null>(null);
  const [targetAvailable, setTargetAvailable] = useState(true);
  const [presentation] = useState(() => new GuidePresentation());
  const current = tour.steps[step];
  const isLastStep = step === tour.steps.length - 1;
  const progress = t('guide.step')
    .replace('{{current}}', String(step + 1))
    .replace('{{total}}', String(tour.steps.length));

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      closeRef.current(true);
    };
    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      presentation.restore();
    };
  }, [presentation]);

  useEffect(() => {
    const focusFrame = requestAnimationFrame(() => panelRef.current?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(focusFrame);
  }, [step]);

  useLayoutEffect(() => {
    let frame = 0;
    let scrolledTarget: HTMLElement | undefined;
    let observedTarget: HTMLElement | undefined;
    const findTarget = () => findGuideTarget(current, t);

    const measure = () => {
      const panel = panelRef.current;
      if (!panel) return;
      presentation.reveal(current, t);
      const target = findTarget();
      if (target !== observedTarget) {
        if (observedTarget) resize.unobserve(observedTarget);
        if (target) resize.observe(target);
        observedTarget = target;
      }
      const rect = target?.getBoundingClientRect();
      const visible = Boolean(target && rect && rect.width > 0 && rect.height > 0 && getComputedStyle(target).visibility !== 'hidden');
      if (visible && target && scrolledTarget !== target && current.target !== 'sidebar-navigation') {
        scrolledTarget = target;
        target.scrollIntoView({ block: 'start', behavior: 'instant' });
        window.scrollBy({ top: target.getBoundingClientRect().top - 104, behavior: 'instant' });
      }
      const viewport = { width: document.documentElement.clientWidth, height: window.innerHeight };
      const targetBox = visible ? measureGuideTarget(target!) : null;
      const highlight = targetBox
        ? frameGuideTarget(targetBox, viewport, current.target === 'sidebar-navigation' ? 8 : 76)
        : null;
      setTargetAvailable(visible);
      setGeometry(placeGuide(highlight, { width: panel.offsetWidth, height: panel.offsetHeight }, viewport));
    };

    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    const resize = new ResizeObserver(schedule);
    if (panelRef.current) resize.observe(panelRef.current);
    const target = findTarget();
    if (target) resize.observe(target);
    const mutations = new MutationObserver((records) => {
      if (records.some((record) => !layerRef.current?.contains(record.target))) schedule();
    });
    const root = document.getElementById('root');
    if (root) mutations.observe(root, { childList: true, subtree: true, attributes: true });
    window.addEventListener('resize', schedule);
    window.addEventListener('scroll', schedule, true);
    window.visualViewport?.addEventListener('resize', schedule);
    measure();
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      mutations.disconnect();
      window.removeEventListener('resize', schedule);
      window.removeEventListener('scroll', schedule, true);
      window.visualViewport?.removeEventListener('resize', schedule);
    };
  }, [current, presentation, t]);

  return createPortal(
    <>
    <div data-guide-scroll-space="" aria-hidden="true" inert className="pointer-events-none h-[100dvh]" />
    <div
      ref={layerRef}
      data-page-guide-layer=""
      data-brain-ops=""
      className="pointer-events-none fixed inset-0 z-[100] text-[var(--brain-ops-text)] [font-family:var(--brain-ops-font-body)]"
    >
      {geometry?.highlight ? (
        <div
          key={`${tour.id}-${step}`}
          data-guide-spotlight=""
          aria-hidden="true"
          className="absolute rounded-2xl border-2 border-[color:var(--brain-ops-text)] opacity-70 shadow-[0_0_0_4px_color-mix(in_srgb,var(--brain-ops-surface)_72%,transparent)]"
          style={geometry.highlight}
        />
      ) : null}
      <aside
        ref={panelRef}
        id="page-help-panel"
        role="dialog"
        aria-modal="false"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        data-page-guide=""
        tabIndex={-1}
        className="brain-guide-panel pointer-events-auto absolute flex w-[min(28rem,calc(100vw-1.5rem))] max-h-[calc(100dvh-1.5rem)] flex-col overflow-hidden border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--brain-ops-canvas)]"
        style={{ left: geometry?.left ?? 12, top: geometry?.top ?? 12, visibility: geometry ? 'visible' : 'hidden' }}
      >
        <div className="flex min-h-0 flex-1 flex-col p-5 sm:p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 items-center gap-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-[var(--brain-ops-surface-muted)] text-[var(--brain-ops-text)]">
                <CircleHelp className="size-4" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <p className="truncate text-xs font-medium uppercase tracking-[0.12em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                  {t(tour.titleKey)}
                </p>
                <p className="mt-1 text-xs text-[var(--brain-ops-text-muted)]">{progress}</p>
              </div>
            </div>
            <Button type="button" variant="ghost" size="icon" className="min-h-11 min-w-11 shrink-0" onClick={() => onClose(true)} aria-label={t('guide.close')}>
              <X className="size-4" aria-hidden="true" />
            </Button>
          </div>

          <div key={step} aria-live="polite" aria-atomic="true" className="mt-5 min-h-0 overflow-y-auto overscroll-contain">
            <h2 id={titleId} className="text-lg font-semibold leading-snug tracking-[-0.01em]">
              {t(current.titleKey)}
            </h2>
            <p id={descriptionId} className="mt-2 text-sm leading-6 text-[var(--brain-ops-text-muted)]">
              {t(current.bodyKey)}
            </p>
            {!targetAvailable ? (
              <p className="mt-4 rounded-md bg-[var(--brain-ops-surface-muted)] p-3 text-sm leading-5">
                {t('guide.targetUnavailable')}
              </p>
            ) : null}
          </div>

          <div className="mt-5 flex items-center gap-2 border-t border-[color:var(--brain-ops-border)] pt-4">
            <div className="mr-auto flex items-center gap-1.5" aria-hidden="true">
              {tour.steps.map((item, index) => (
                <span
                  key={`${item.target}-${index}`}
                  className={`h-1.5 rounded-full transition-[width,background-color] motion-reduce:transition-none ${index === step ? 'w-5 bg-[var(--brain-ops-text)]' : 'w-1.5 bg-[var(--brain-ops-border)]'}`}
                />
              ))}
            </div>
            {step > 0 ? (
              <Button type="button" variant="ghost" size="icon" className="min-h-11 min-w-11" onClick={() => onStep(step - 1)} aria-label={t('guide.back')}>
                <ArrowLeft className="size-4" aria-hidden="true" />
              </Button>
            ) : null}
            <Button type="button" variant="secondary" className="min-h-11" onClick={() => isLastStep ? onFinish() : onStep(step + 1)}>
              {t(isLastStep ? 'guide.finish' : 'guide.next')}
              {!isLastStep ? <ArrowRight className="size-4" aria-hidden="true" /> : null}
            </Button>
          </div>
        </div>
      </aside>
    </div>
    </>,
    document.body,
  );
}
