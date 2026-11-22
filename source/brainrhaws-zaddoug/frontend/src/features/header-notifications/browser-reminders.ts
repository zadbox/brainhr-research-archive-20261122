import type { HeaderInterviewReminder } from './types';
import { isDueReminder } from './types';

const CLAIM_TTL_MS = 60_000;
const CLAIM_ARBITRATION_MS = 25;
const SEEN_TTL_MS = 30 * 24 * 60 * 60 * 1000;

function safeInternalPath(reminder: HeaderInterviewReminder): string {
  return `/interviews/${encodeURIComponent(reminder.sheetId)}`;
}

function seenKey(userId: string, tenantId: string | undefined, reminderId: string): string {
  return `brainrh:header-notifications:shown:${userId}:${tenantId || 'own-tenant'}:${reminderId}`;
}

function isRecentlySeen(key: string, now: number): boolean {
  try {
    const timestamp = Number(window.localStorage.getItem(key));
    return Number.isFinite(timestamp) && timestamp >= now - SEEN_TTL_MS;
  } catch {
    return false;
  }
}

function rememberSeen(key: string, now: number): boolean {
  try {
    window.localStorage.setItem(key, String(now));
    return true;
  } catch {
    return false;
  }
}

async function withCrossTabClaim(id: string, callback: () => void): Promise<void> {
  if (navigator.locks?.request) {
    try {
      await navigator.locks.request(`brainrh-reminder:${id}`, { ifAvailable: true }, (lock) => {
        if (lock) callback();
      });
      return;
    } catch {
      // Fall back to the expiring local storage claim.
    }
  }
  const key = `brainrh:header-notifications:claim:${id}`;
  const now = Date.now();
  const token = crypto.randomUUID?.() ?? `${now}:${Math.random().toString(36).slice(2)}`;
  try {
    const currentValue = window.localStorage.getItem(key);
    if (currentValue) {
      try {
        const current = JSON.parse(currentValue) as unknown;
        if (
          current
          && typeof current === 'object'
          && 'expiresAt' in current
          && typeof current.expiresAt === 'number'
          && current.expiresAt > now
        ) return;
      } catch {
        window.localStorage.removeItem(key);
      }
    }
    const claim = JSON.stringify({ token, expiresAt: now + CLAIM_TTL_MS });
    window.localStorage.setItem(key, claim);
    await new Promise((resolve) => window.setTimeout(resolve, CLAIM_ARBITRATION_MS));
    if (window.localStorage.getItem(key) !== claim) return;
    callback();
  } catch {
    return;
  }
}

export async function dispatchBrowserInterviewReminders({
  userId,
  tenantId,
  reminders,
  title,
  formatTime,
  navigate,
  onOpenReminder,
  isCurrent,
  now = Date.now(),
}: {
  userId: string;
  tenantId?: string;
  reminders: readonly HeaderInterviewReminder[];
  title: string;
  formatTime: (startsAt: string) => string;
  navigate: (path: string) => void;
  onOpenReminder?: (reminder: HeaderInterviewReminder) => void;
  isCurrent: () => boolean;
  now?: number;
}): Promise<void> {
  if (!('Notification' in window) || Notification.permission !== 'granted' || !isCurrent()) return;
  await Promise.all(reminders.filter((reminder) => isDueReminder(reminder, now)).map(async (reminder) => {
    const key = seenKey(userId, tenantId, reminder.id);
    await withCrossTabClaim(`${userId}:${tenantId || 'own-tenant'}:${reminder.id}`, () => {
      if (!isCurrent() || isRecentlySeen(key, now)) return;
      let notification: Notification;
      try {
        notification = new Notification(title, {
          tag: reminder.id,
          body: formatTime(reminder.startsAt),
        });
      } catch {
        return;
      }
      if (!rememberSeen(key, now)) {
        notification.close();
        return;
      }
      notification.onclick = () => {
        if (!isCurrent()) {
          notification.close();
          return;
        }
        window.focus();
        if (onOpenReminder) onOpenReminder(reminder);
        else navigate(safeInternalPath(reminder));
        notification.close();
      };
    });
  }));
}
