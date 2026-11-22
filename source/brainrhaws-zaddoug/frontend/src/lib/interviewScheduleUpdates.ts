const UPDATE_EVENT = 'brainrh:interview-schedule-updated';
const UPDATE_KEY = 'brainrh:interview-schedule-revision';

/** Invalidate views after a successful mutation. Cross-tab messages contain no candidate data. */
export function publishInterviewScheduleUpdate(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new Event(UPDATE_EVENT));
  try {
    window.localStorage.setItem(UPDATE_KEY, `${Date.now()}:${Math.random()}`);
  } catch {
    // The current tab still refreshes when browser storage is unavailable.
  }
}

export function subscribeInterviewScheduleUpdates(refresh: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === UPDATE_KEY) refresh();
  };
  window.addEventListener(UPDATE_EVENT, refresh);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener(UPDATE_EVENT, refresh);
    window.removeEventListener('storage', onStorage);
  };
}

/** Refresh changes made by another session/provider, and catch up on focus or reconnect. */
export function watchInterviewSchedule(refresh: () => void): () => void {
  const refreshVisible = () => {
    if (document.visibilityState === 'visible') refresh();
  };
  const unsubscribe = subscribeInterviewScheduleUpdates(refresh);
  const interval = window.setInterval(refreshVisible, 60_000);
  document.addEventListener('visibilitychange', refreshVisible);
  window.addEventListener('focus', refreshVisible);
  window.addEventListener('online', refreshVisible);
  return () => {
    unsubscribe();
    window.clearInterval(interval);
    document.removeEventListener('visibilitychange', refreshVisible);
    window.removeEventListener('focus', refreshVisible);
    window.removeEventListener('online', refreshVisible);
  };
}
