import type { TranslationKey } from '../../i18n/messages';
import type { GuideRect } from './geometry';
import type { TourStep } from './tours';

type Translate = (key: TranslationKey) => string;
const normalize = (text: string) => text.replace(/\s+/g, ' ').trim();
const matchesText = (node: HTMLElement, key: TranslationKey | undefined, t: Translate) =>
  !key || normalize(node.textContent ?? '').startsWith(normalize(t(key)));
const isRendered = (node: HTMLElement) => {
  const box = node.getBoundingClientRect();
  return box.width > 0 && box.height > 0 && box.right > 0 && box.left < document.documentElement.clientWidth &&
    getComputedStyle(node).visibility !== 'hidden';
};

export function findGuideTarget(step: TourStep, t: Translate): HTMLElement | undefined {
  const anchored = Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${CSS.escape(step.target)}"]`)).find(isRendered);
  if (anchored) return anchored;
  if (!step.selector) return undefined;
  const node = Array.from(document.querySelectorAll<HTMLElement>(step.selector)).find((item) => isRendered(item) && matchesText(item, step.textKey, t));
  return node && (step.closest ? node.closest<HTMLElement>(step.closest) ?? node : node);
}

/** Grid and flex layouts can stretch an anchor far beyond its rendered content.
 * Trim only substantial trailing empty space so the spotlight describes what the
 * user can actually see while preserving the target's full width and padding. */
export function measureGuideTarget(target: HTMLElement): GuideRect {
  const targetRect = target.getBoundingClientRect();
  const contentBottom = Array.from(target.children)
    .filter((child): child is HTMLElement => child instanceof HTMLElement)
    .map((child) => child.getBoundingClientRect())
    .filter((rect) => rect.width > 0 && rect.height > 0)
    .reduce((bottom, rect) => Math.max(bottom, Math.min(rect.bottom, targetRect.bottom)), targetRect.top);
  const measuredHeight = contentBottom - targetRect.top;
  const height = measuredHeight > 0 && targetRect.height - measuredHeight >= 48
    ? measuredHeight
    : targetRect.height;
  return { left: targetRect.left, top: targetRect.top, width: targetRect.width, height };
}

/** Only presentation changes are allowed: existing interview tabs and native disclosures. */
export class GuidePresentation {
  private originalTab: HTMLElement | null = null;
  private requestedPanel: string | undefined;
  private disclosures = new Map<HTMLDetailsElement, boolean>();

  private openDisclosure(details: HTMLDetailsElement) {
    if (!this.disclosures.has(details)) this.disclosures.set(details, details.open);
    if (!details.open) details.open = true;
  }

  reveal(step: TourStep, t: Translate) {
    const anchored = findGuideTarget({ ...step, selector: undefined }, t);
    if (anchored instanceof HTMLDetailsElement) this.openDisclosure(anchored);
    if (!step.reveal || anchored) return;
    const { panel, disclosureKey } = step.reveal;
    if (!['profile', 'matching', 'human', 'ai', 'decision'].includes(panel)) return;
    const tab = document.querySelector<HTMLElement>(`[role="tab"][aria-controls="interview-panel-${panel}"]`);
    if (!tab || tab.matches(':disabled, [aria-disabled="true"]')) return;
    if (tab.getAttribute('aria-selected') !== 'true') {
      if (this.requestedPanel === panel) return;
      this.originalTab ??= tab.closest('[role="tablist"]')?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]') ?? null;
      this.requestedPanel = panel;
      tab.click();
      return;
    }
    this.requestedPanel = undefined;
    if (!disclosureKey) return;
    const summary = Array.from(document.querySelectorAll<HTMLElement>(`#interview-panel-${panel} details > summary`))
      .find((node) => matchesText(node, disclosureKey, t));
    const details = summary?.parentElement;
    if (!(details instanceof HTMLDetailsElement)) return;
    this.openDisclosure(details);
  }

  restore() {
    for (const [node, open] of this.disclosures) if (node.isConnected) node.open = open;
    if (this.originalTab?.isConnected) this.originalTab.click();
    this.disclosures.clear();
    this.originalTab = null;
    this.requestedPanel = undefined;
  }
}
