import { apiClient } from '../../api/client';
import { candidateLabel } from '../../lib/candidateLabel';
import type { HeaderInterviewReminder } from './types';
import { UPCOMING_WINDOW_MS } from './types';

type UnknownRecord = Record<string, unknown>;
const CALENDAR_REQUEST_TIMEOUT_MS = 20_000;

interface LoadReminderInput {
  role: string;
  tenantId?: string;
  signal: AbortSignal;
  now?: number;
}

function isRecord(value: unknown): value is UnknownRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function requiredString(record: UnknownRecord, key: string): string {
  const value = record[key];
  if (typeof value !== 'string' || !value.trim()) throw new Error(`Invalid ${key}`);
  return value;
}

function optionalString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function parseProjects(value: unknown): string[] {
  if (!Array.isArray(value)) throw new Error('Invalid project summaries');
  return value.map((project) => {
    if (!isRecord(project)) throw new Error('Invalid project summary');
    return requiredString(project, 'id');
  });
}

function parseSheets(value: unknown): UnknownRecord[] {
  if (!isRecord(value) || !Array.isArray(value.sheets)) throw new Error('Invalid interview sheet response');
  return value.sheets.map((sheet) => {
    if (!isRecord(sheet)) throw new Error('Invalid interview sheet');
    requiredString(sheet, 'id');
    requiredString(sheet, 'job_id');
    return sheet;
  });
}

async function mapWithConcurrency<T, R>(
  values: readonly T[],
  concurrency: number,
  mapper: (value: T) => Promise<R>,
  signal?: AbortSignal,
): Promise<R[]> {
  const results = new Array<R>(values.length);
  let cursor = 0;
  async function worker() {
    while (cursor < values.length) {
      signal?.throwIfAborted();
      const index = cursor++;
      results[index] = await mapper(values[index]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, values.length) }, worker));
  return results;
}

async function loadSheets(input: LoadReminderInput): Promise<UnknownRecord[]> {
  if (input.role !== 'platform_admin') {
    const response = await apiClient.get<unknown>('/interview-sheet/', {
      signal: input.signal,
      timeout: CALENDAR_REQUEST_TIMEOUT_MS,
    });
    return parseSheets(response.data);
  }
  if (!input.tenantId) return [];

  const projectResponse = await apiClient.get<unknown>('/projects', {
    params: { tenant_id: input.tenantId },
    signal: input.signal,
    timeout: CALENDAR_REQUEST_TIMEOUT_MS,
  });
  const projectIds = parseProjects(projectResponse.data);
  const projectIdSet = new Set(projectIds);
  const responses = await mapWithConcurrency(projectIds, 4, async (projectId) => {
    input.signal.throwIfAborted();
    const response = await apiClient.get<unknown>('/interview-sheet/', {
      params: { job_id: projectId },
      signal: input.signal,
      timeout: CALENDAR_REQUEST_TIMEOUT_MS,
    });
    return parseSheets(response.data).filter((sheet) => sheet.job_id === projectId);
  }, input.signal);
  return [...new Map(
    responses.flat().filter((sheet) => projectIdSet.has(String(sheet.job_id))).map((sheet) => [String(sheet.id), sheet]),
  ).values()];
}

function getScheduling(sheet: UnknownRecord): UnknownRecord | null {
  const data = isRecord(sheet.data) ? sheet.data : null;
  return data && isRecord(data.scheduling) ? data.scheduling : null;
}

function getCandidateName(sheet: UnknownRecord, fallback: string, includeIdentifier = true): string {
  const data = isRecord(sheet.data) ? sheet.data : null;
  const identity = data && isRecord(data.identite) ? data.identite : null;
  return candidateLabel({
    candidateId: includeIdentifier ? requiredString(sheet, 'candidate_id') : '',
    identity: identity ? {
      nom_complet: optionalString(identity.nom_complet),
      prenom: optionalString(identity.prenom),
      nom: optionalString(identity.nom),
    } : undefined,
  }, fallback);
}

function errorStatus(error: unknown): number | null {
  if (!isRecord(error) || !isRecord(error.details)) return null;
  return typeof error.details.status === 'number' ? error.details.status : null;
}

export interface CockpitInterview extends HeaderInterviewReminder {
  projectId: string;
  status: string;
}

const activeStatuses = new Set(['in_progress', 'paused', 'wrapping_up']);
const scheduledStatuses = new Set(['scheduled', 'waiting_candidate']);

function fileKey(value: string): string {
  return value.split(/[\\/]/).pop()?.replace(/\.(json|pdf|docx?)$/i, '').trim() || '';
}

/** Reads canonical appointments; a sheet's cached schedule is only a lookup hint. */
async function resolveInterviews(
  sheets: readonly UnknownRecord[], signal: AbortSignal, fallback: string, now: number, cockpit: boolean,
): Promise<CockpitInterview[]> {
  const startOfToday = new Date(now);
  startOfToday.setHours(0, 0, 0, 0);
  const endOfTomorrow = new Date(startOfToday);
  endOfTomorrow.setDate(endOfTomorrow.getDate() + 2);
  const from = cockpit ? startOfToday.getTime() : now;
  const until = cockpit ? endOfTomorrow.getTime() - 1 : now + UPCOMING_WINDOW_MS;
  const candidates = sheets.filter((sheet) => {
    // A provider can reschedule an appointment before the sheet cache catches up.
    // Only the canonical response may exclude it by status or date.
    if (optionalString(getScheduling(sheet)?.appointment_id)) return true;
    if (!cockpit || sheet.status === 'completed') return false;
    const timestamp = new Date(optionalString(sheet.scheduled_at) || optionalString(getScheduling(sheet)?.scheduled_at) || '').getTime();
    return Number.isFinite(timestamp) && timestamp >= from && timestamp <= until;
  });
  // Only fetch CV identities when the sheet has no name. One lookup per project,
  // exact filename match, and no identity is retained across client changes.
  const cvRequests = new Map<string, Promise<UnknownRecord[]>>();
  const resolveName = async (sheet: UnknownRecord, appointment: UnknownRecord): Promise<string> => {
    const identityName = getCandidateName(sheet, '', false);
    if (identityName && candidateLabel({ candidateId: identityName }, '')) return identityName;
    const candidateId = requiredString(sheet, 'candidate_id');
    const appointmentName = optionalString(appointment.candidate_name);
    if (appointmentName && fileKey(appointmentName) !== fileKey(candidateId)) {
      const name = candidateLabel({ candidateId: appointmentName }, '');
      if (name) return appointmentName;
    }
    const projectId = requiredString(sheet, 'job_id');
    let request = cvRequests.get(projectId);
    if (!request) {
      request = apiClient.get<unknown>(`/cvs/projects/${encodeURIComponent(projectId)}/cvs`, { signal, timeout: CALENDAR_REQUEST_TIMEOUT_MS })
        .then(({ data }) => Array.isArray(data) ? data.filter(isRecord) : [])
        .catch(() => { signal.throwIfAborted(); return []; });
      cvRequests.set(projectId, request);
    }
    const cvs = await request;
    const matches = cvs.filter((cv) => typeof cv.cv === 'string' && fileKey(cv.cv) === fileKey(candidateId));
    const identity = matches.length === 1 && isRecord(matches[0].identite) ? matches[0].identite : null;
    return candidateLabel({ candidateId, identity: identity ? {
      nom_complet: optionalString(identity.nom_complet), prenom: optionalString(identity.prenom), nom: optionalString(identity.nom),
    } : undefined }, fallback);
  };
  const appointments = await mapWithConcurrency(candidates, 4, async (sheet) => {
    signal.throwIfAborted();
    const scheduling = getScheduling(sheet);
    const appointmentId = optionalString(scheduling?.appointment_id);
    if (!appointmentId) {
      const startsAt = optionalString(sheet.scheduled_at) || requiredString(scheduling || {}, 'scheduled_at');
      const sheetId = requiredString(sheet, 'id');
      return {
        id: `${sheetId}:${startsAt}`, appointmentId: sheetId, sheetId,
        candidateName: await resolveName(sheet, {}), startsAt,
        endsAt: optionalString(scheduling?.end_at),
        location: optionalString(sheet.location) || optionalString(scheduling?.location),
        projectId: requiredString(sheet, 'job_id'), status: 'scheduled',
      } satisfies CockpitInterview;
    }
    let response;
    try {
      response = await apiClient.get<unknown>(`/interview-appointments/${encodeURIComponent(appointmentId)}`, {
        signal, timeout: CALENDAR_REQUEST_TIMEOUT_MS,
      });
    } catch (error) {
      if (errorStatus(error) === 404) return null;
      throw error;
    }
    if (!isRecord(response.data)) throw new Error('Invalid interview appointment response');
    const appointment = response.data;
    const id = requiredString(appointment, 'id');
    const sheetId = requiredString(sheet, 'id');
    if (requiredString(appointment, 'interview_sheet_id') !== sheetId) return null;
    const status = requiredString(appointment, 'status');
    const active = cockpit && activeStatuses.has(status);
    if (!active && !scheduledStatuses.has(status)) return null;
    const startsAt = requiredString(appointment, 'start_at');
    const timestamp = new Date(startsAt).getTime();
    if (!Number.isFinite(timestamp) || (!active && (timestamp < from || timestamp > until))) return null;
    return {
      id: `${id}:${startsAt}`, appointmentId: id, sheetId,
      candidateName: await resolveName(sheet, appointment),
      startsAt, endsAt: optionalString(appointment.end_at),
      location: optionalString(sheet.location) || optionalString(scheduling?.location),
      projectId: requiredString(sheet, 'job_id'), status,
    } satisfies CockpitInterview;
  }, signal);
  return [...new Map(appointments.filter((item): item is CockpitInterview => item !== null).map((item) => [item.appointmentId, item])).values()]
    .sort((left, right) => Date.parse(left.startsAt) - Date.parse(right.startsAt));
}

export async function loadHeaderInterviewReminders(input: LoadReminderInput, candidateFallback: string): Promise<HeaderInterviewReminder[]> {
  return resolveInterviews(await loadSheets(input), input.signal, candidateFallback, input.now ?? Date.now(), false);
}

export async function loadCockpitInterviews(
  sheets: readonly unknown[], signal: AbortSignal, candidateFallback: string, now = Date.now(),
): Promise<CockpitInterview[]> {
  return resolveInterviews(sheets.filter(isRecord), signal, candidateFallback, now, true);
}
