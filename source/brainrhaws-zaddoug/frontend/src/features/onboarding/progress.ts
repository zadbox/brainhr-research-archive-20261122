export interface GuideProgress {
  status: 'paused' | 'skipped' | 'completed';
  step: number;
  revision?: number;
}

export const GUIDE_VERSION = 1;
const CONTENT_REVISION = 2;
// Denied browser storage still remembers dismissed guides during SPA navigation.
const sessionProgress = new Map<string, GuideProgress>();

export function guideStorageKey(userId: string, role: string, scope: string, tourId: string) {
  return `brainrh-guide:v${GUIDE_VERSION}:${JSON.stringify([userId, role, scope, tourId])}`;
}

export function readGuideProgress(key: string, stepCount: number): {
  progress: GuideProgress | null;
  available: boolean;
} {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return { progress: sessionProgress.get(key) ?? null, available: !sessionProgress.has(key) };
    const value: unknown = JSON.parse(raw);
    if (typeof value !== 'object' || !value) return { progress: null, available: true };
    const { status, step, revision } = value as Record<string, unknown>;
    if ((status !== 'paused' && status !== 'skipped' && status !== 'completed') ||
      typeof step !== 'number' || !Number.isInteger(step) || step < 0 || step >= stepCount) {
      return { progress: null, available: true };
    }
    // Preserve dismissals from the original shorter tours; old paused indices no longer match.
    return { progress: { status, step: revision === CONTENT_REVISION ? step : 0 }, available: true };
  } catch (error) {
    // Corrupt progress should restart the tour; denied storage must not break the app.
    return { progress: sessionProgress.get(key) ?? null, available: error instanceof SyntaxError };
  }
}

export function saveGuideProgress(key: string, progress: GuideProgress): boolean {
  const value = { ...progress, revision: CONTENT_REVISION };
  try {
    localStorage.setItem(key, JSON.stringify(value));
    sessionProgress.delete(key);
    return true;
  } catch {
    sessionProgress.set(key, value);
    if (sessionProgress.size > 200) sessionProgress.delete(sessionProgress.keys().next().value!);
    return false;
  }
}
