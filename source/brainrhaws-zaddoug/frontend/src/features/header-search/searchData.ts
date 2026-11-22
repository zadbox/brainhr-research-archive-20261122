import { apiClient } from '../../api/client';
import { candidateLabel } from '../../lib/candidateLabel';
import type { Enterprise, Project } from '../../api/types';
import type { SearchCandidate, SearchIndex, SearchResult } from './types';

const SEARCH_TIMEOUT_MS = 20_000;
const CANDIDATE_CONCURRENCY = 4;
export const MAX_VISIBLE_RESULTS = 18;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

const isEnterprise = (value: unknown): value is Enterprise =>
  isRecord(value)
  && typeof value.id === 'string'
  && typeof value.nom === 'string'
  && (value.tenant_id === undefined || value.tenant_id === null || typeof value.tenant_id === 'string')
  && (value.secteur === undefined || typeof value.secteur === 'string');

const isProject = (value: unknown): value is Project =>
  isRecord(value)
  && typeof value.id === 'string'
  && typeof value.nom === 'string'
  && (value.enterprise_id === undefined || typeof value.enterprise_id === 'string')
  && (value.description === undefined || typeof value.description === 'string');

interface SearchCVPayload {
  cv: string;
  titre: string;
  enterpriseNom: string;
  identity?: { nom?: string; prenom?: string };
}

function parseSearchCVs(value: unknown): SearchCVPayload[] {
  if (!Array.isArray(value)) throw new Error('INVALID_SEARCH_RESPONSE');
  return value.map((item) => {
    if (!isRecord(item) || typeof item.cv !== 'string') throw new Error('INVALID_SEARCH_RESPONSE');
    const rawIdentity = isRecord(item.identite) ? item.identite : null;
    const identity = rawIdentity ? {
      ...(typeof rawIdentity.nom === 'string' ? { nom: rawIdentity.nom } : {}),
      ...(typeof rawIdentity.prenom === 'string' ? { prenom: rawIdentity.prenom } : {}),
    } : undefined;
    return {
      cv: item.cv,
      titre: typeof item.titre === 'string' ? item.titre : '',
      enterpriseNom: typeof item.enterprise_nom === 'string' ? item.enterprise_nom : '',
      identity,
    };
  });
}

function requireArray<T>(value: unknown, predicate: (item: unknown) => item is T): T[] {
  if (!Array.isArray(value) || !value.every(predicate)) {
    throw new Error('INVALID_SEARCH_RESPONSE');
  }
  return value;
}

async function mapConcurrent<T, R>(
  values: T[],
  concurrency: number,
  mapper: (value: T) => Promise<R>
): Promise<PromiseSettledResult<R>[]> {
  const results: PromiseSettledResult<R>[] = new Array(values.length);
  let cursor = 0;
  const worker = async () => {
    while (cursor < values.length) {
      const index = cursor++;
      try {
        results[index] = { status: 'fulfilled', value: await mapper(values[index]) };
      } catch (reason) {
        results[index] = { status: 'rejected', reason };
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, values.length) }, worker));
  return results;
}

export async function loadSearchIndex(options: {
  tenantId?: string;
  signal: AbortSignal;
}): Promise<SearchIndex> {
  const params = options.tenantId ? { tenant_id: options.tenantId } : undefined;
  const request = { params, signal: options.signal, timeout: SEARCH_TIMEOUT_MS };
  const [enterpriseResponse, projectResponse] = await Promise.all([
    apiClient.get<unknown>('/enterprises', request),
    apiClient.get<unknown>('/projects', request),
  ]);

  let enterprises = requireArray(enterpriseResponse.data, isEnterprise);
  const returnedProjects = requireArray(projectResponse.data, isProject);
  if (options.tenantId) {
    enterprises = enterprises.filter((enterprise) =>
      (enterprise.tenant_id || enterprise.id) === options.tenantId
    );
  }
  const authorizedEnterpriseIds = new Set(enterprises.map((enterprise) => enterprise.id));
  const projects = options.tenantId
    ? returnedProjects.filter((project) =>
        Boolean(project.enterprise_id && authorizedEnterpriseIds.has(project.enterprise_id))
      )
    : returnedProjects;

  const enterpriseById = new Map(enterprises.map((enterprise) => [enterprise.id, enterprise]));
  // The current backend has no authorized, paginated search summary and these
  // routes return full parsed CV payloads. Limit the temporary per-project
  // fan-out, retain only searchable fields in memory, and replace this with an
  // authorized paginated summary endpoint when one becomes available.
  const candidateResponses = await mapConcurrent(projects, CANDIDATE_CONCURRENCY, async (project) => {
    const response = await apiClient.get<unknown>(
      `/cvs/projects/${encodeURIComponent(project.id)}/cvs`,
      { signal: options.signal, timeout: SEARCH_TIMEOUT_MS }
    );
    return parseSearchCVs(response.data).map((cv): SearchCandidate => ({
      id: cv.cv,
      name: candidateLabel({ candidateId: cv.cv, identity: cv.identity }),
      title: cv.titre,
      filename: cv.cv,
      projectId: project.id,
      projectName: project.nom,
      companyName: enterpriseById.get(project.enterprise_id || '')?.nom || cv.enterpriseNom,
    }));
  });

  const candidates = candidateResponses.flatMap((result) =>
    result.status === 'fulfilled' ? result.value : []
  );
  return {
    enterprises,
    projects,
    candidates,
    failedCandidateProjects: candidateResponses.filter((result) => result.status === 'rejected').length,
  };
}

export const normalizeSearchText = (value: string): string =>
  value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase().trim();

export function searchIndex(index: SearchIndex, rawQuery: string): {
  results: SearchResult[];
  total: number;
} {
  const query = normalizeSearchText(rawQuery);
  if (query.length < 2) return { results: [], total: 0 };
  const contains = (...values: Array<string | undefined>) =>
    values.some((value) => normalizeSearchText(value || '').includes(query));

  const candidateResults: SearchResult[] = index.candidates
    .filter((candidate) => contains(
      candidate.name,
      candidate.title,
      candidate.filename,
      candidate.projectName,
      candidate.companyName
    ))
    .map((candidate) => ({
      kind: 'candidate',
      id: `${candidate.projectId}:${candidate.id}`,
      primary: candidate.name,
      secondary: [candidate.title, candidate.projectName, candidate.companyName].filter(Boolean).join(' · '),
      href: `/projects/${encodeURIComponent(candidate.projectId)}/cvs?candidate=${encodeURIComponent(candidate.id)}`,
    }));
  const projectResults: SearchResult[] = index.projects
    .filter((project) => contains(project.nom, project.description))
    .map((project) => ({
      kind: 'project',
      id: project.id,
      primary: project.nom,
      secondary: index.enterprises.find((enterprise) => enterprise.id === project.enterprise_id)?.nom || '',
      href: `/projects/${encodeURIComponent(project.id)}`,
    }));
  const companyResults: SearchResult[] = index.enterprises
    .filter((enterprise) => contains(enterprise.nom, enterprise.secteur))
    .map((enterprise) => ({
      kind: 'company',
      id: enterprise.id,
      primary: enterprise.nom,
      secondary: enterprise.secteur || '',
      href: `/enterprises/${encodeURIComponent(enterprise.id)}`,
    }));
  const allResults = [...candidateResults, ...projectResults, ...companyResults];
  return { results: allResults.slice(0, MAX_VISIBLE_RESULTS), total: allResults.length };
}
