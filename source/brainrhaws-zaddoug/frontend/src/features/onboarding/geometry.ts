export interface GuideRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** One rounded cutout for both the scrim and blur: rectangular mask panels leave
 * sharp, unblurred corners even when the outline itself has a border radius. */
export function guideMaskPath(target: GuideRect, viewport: { width: number; height: number }, radius: number): string {
  const { left: x, top: y, width, height } = target;
  const right = x + width;
  const bottom = y + height;
  const r = Math.max(0, Math.min(radius, width / 2, height / 2));
  return `path(evenodd, "M0 0 H${viewport.width} V${viewport.height} H0 Z ` +
    `M${x + r} ${y} H${right - r} A${r} ${r} 0 0 1 ${right} ${y + r} ` +
    `V${bottom - r} A${r} ${r} 0 0 1 ${right - r} ${bottom} ` +
    `H${x + r} A${r} ${r} 0 0 1 ${x} ${bottom - r} ` +
    `V${y + r} A${r} ${r} 0 0 1 ${x + r} ${y} Z")`;
}

/** Breathing room belongs to the spotlight, never to the underlying business layout. */
export function frameGuideTarget(target: GuideRect, viewport: { width: number; height: number }, topInset = 12): GuideRect | null {
  const padding = viewport.width < 640 ? 12 : 20;
  const left = Math.max(8, target.left - padding);
  const top = Math.max(topInset, target.top - padding);
  const right = Math.min(viewport.width - 8, target.left + target.width + padding);
  const bottom = Math.min(viewport.height - 8, target.top + target.height + padding);
  return right > left && bottom > top ? { left, top, width: right - left, height: bottom - top } : null;
}

/** Keep the explanation inside the viewport and never cover the highlighted area. */
export function placeGuide(
  target: GuideRect | null,
  card: { width: number; height: number },
  viewport: { width: number; height: number },
) {
  const margin = 12;
  const gap = 16;
  const width = Math.min(card.width, viewport.width - margin * 2);
  const height = Math.min(card.height, viewport.height - margin * 2);
  const clampX = (x: number) => Math.max(margin, Math.min(x, viewport.width - width - margin));
  const clampY = (y: number) => Math.max(margin, Math.min(y, viewport.height - height - margin));
  if (target) {
    const right = target.left + target.width;
    const bottom = target.top + target.height;
    const candidates = [
      { left: clampX(target.left), top: bottom + gap },
      { left: clampX(target.left), top: target.top - height - gap },
      { left: right + gap, top: clampY(target.top) },
      { left: target.left - width - gap, top: clampY(target.top) },
    ];
    const position = candidates.find(({ left, top }) =>
      left >= margin && top >= margin && left + width <= viewport.width - margin &&
      top + height <= viewport.height - margin);
    if (position) return { ...position, highlight: target };
    // A tall transcript/workspace can exceed the available space. Keep its leading
    // content in focus while reserving a separate, readable area for the guide.
    const leadingHeight = viewport.height - margin - height - gap - target.top;
    if (target.height > 180 && leadingHeight >= 140) {
      const highlight = { ...target, height: Math.min(target.height, leadingHeight) };
      return { left: clampX(target.left), top: highlight.top + highlight.height + gap, highlight };
    }
  }
  // Large sections / zoomed mobile screens use a readable modal, without a misleading spotlight.
  return {
    left: clampX((viewport.width - width) / 2),
    top: clampY((viewport.height - height) / 2),
    highlight: null,
  };
}
