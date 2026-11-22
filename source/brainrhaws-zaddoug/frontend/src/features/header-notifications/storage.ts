const READ_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const ALERT_OPT_IN_TTL_MS = 180 * 24 * 60 * 60 * 1000;
const MAX_ENTRIES = 300;

function scopeKey(userId: string, tenantId: string | undefined): string {
  return `${userId}:${tenantId || 'own-tenant'}`;
}

function readPrefix(userId: string, tenantId: string | undefined): string {
  return `brainrh:header-notifications:read:${scopeKey(userId, tenantId)}:`;
}

function storedReadEntries(prefix: string): Array<{ key: string; id: string; at: number }> {
  const entries: Array<{ key: string; id: string; at: number }> = [];
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const key = window.localStorage.key(index);
    if (!key?.startsWith(prefix)) continue;
    const at = Number(window.localStorage.getItem(key));
    try {
      entries.push({ key, id: decodeURIComponent(key.slice(prefix.length)), at });
    } catch {
      entries.push({ key, id: '', at: Number.NaN });
    }
  }
  return entries;
}

export function readReminderIds(userId: string, tenantId: string | undefined, now = Date.now()): Set<string> {
  try {
    return new Set(storedReadEntries(readPrefix(userId, tenantId))
      .filter((entry) => entry.id && Number.isFinite(entry.at) && entry.at >= now - READ_TTL_MS)
      .map((entry) => entry.id));
  } catch {
    return new Set();
  }
}

export function rememberReminderIds(
  userId: string,
  tenantId: string | undefined,
  reminderIds: readonly string[],
  now = Date.now(),
): Set<string> {
  const prefix = readPrefix(userId, tenantId);
  try {
    reminderIds.forEach((id) => window.localStorage.setItem(`${prefix}${encodeURIComponent(id)}`, String(now)));
    const entries = storedReadEntries(prefix).sort((left, right) => right.at - left.at);
    entries.forEach((entry, index) => {
      if (!Number.isFinite(entry.at) || entry.at < now - READ_TTL_MS || index >= MAX_ENTRIES) {
        window.localStorage.removeItem(entry.key);
      }
    });
  } catch {
    // Reminders still work in memory when device storage is unavailable.
  }
  return readReminderIds(userId, tenantId, now);
}

export function browserAlertsOptedIn(userId: string, tenantId: string | undefined, now = Date.now()): boolean {
  try {
    const value = Number(window.localStorage.getItem(`brainrh:header-notifications:alerts:${scopeKey(userId, tenantId)}`));
    return Number.isFinite(value) && value >= now - ALERT_OPT_IN_TTL_MS;
  } catch {
    return false;
  }
}

export function rememberBrowserAlertsOptIn(userId: string, tenantId: string | undefined, now = Date.now()): void {
  try {
    window.localStorage.setItem(
      `brainrh:header-notifications:alerts:${scopeKey(userId, tenantId)}`,
      String(now),
    );
  } catch {
    // Permission remains effective for this page even without local persistence.
  }
}
