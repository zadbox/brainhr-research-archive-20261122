import type { AlgorithmicBreakdown, CriterionAssessment, CV, Offre, ResultatMatching } from '../api/types';

export type MatrixCriterionGroup = 'must' | 'nice';
export type MatrixCriterionStatus = 'met' | 'partial' | 'missing' | 'unclear';

export interface MatrixCriterionColumn {
  id: string;
  label: string;
  group: MatrixCriterionGroup;
}

export interface MatrixAssessmentCell {
  status: MatrixCriterionStatus;
  reason: string;
  evidenceIds: string[];
}

export interface ShortlistMatrixRow {
  candidateId: string;
  candidateLabel: string;
  finalScorePct: number;
  recommendationLevel: string;
  relevantExperienceYears: number | null;
  totalExperienceYears: number | null;
  experienceSignal: number;
  summary: string;
  topStrengths: string[];
  watchouts: string[];
  interviewFocus: string[];
  riskFlags: string[];
  algorithmicBreakdown: AlgorithmicBreakdown | null;
  criterionStatuses: Record<string, MatrixAssessmentCell>;
}

export interface QualifiedPoolMatrixRow {
  candidateId: string;
  candidateLabel: string;
  algorithmicRank: number;
  algorithmicScorePct: number;
  scoreBasePct: number;
  niceToHaveCoverage: {
    matched: number;
    total: number;
  };
  totalExperienceYears: number | null;
  reranked: boolean;
  algorithmicBreakdown: AlgorithmicBreakdown | null;
  criterionStatuses: Record<string, MatrixAssessmentCell>;
}

type DateLike = string | undefined | null;

const NOW = new Date();

function normalizeText(value: string): string {
  return value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9+.#/\s-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function normalizeCriterionId(group: MatrixCriterionGroup, label: string) {
  return `${group}:${normalizeText(label)}`;
}

function parseDate(value: DateLike): Date | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed;
}

function yearsBetween(start: DateLike, end: DateLike): number {
  const startDate = parseDate(start);
  const endDate = parseDate(end) ?? NOW;
  if (!startDate || !endDate || endDate < startDate) {
    return 0;
  }

  const months =
    (endDate.getUTCFullYear() - startDate.getUTCFullYear()) * 12 +
    (endDate.getUTCMonth() - startDate.getUTCMonth());
  return Math.max(0, months) / 12;
}

function collectExperienceBlocks(cv: CV): Array<Record<string, unknown>> {
  const modernExperiences = Array.isArray(cv.experiences_professionnelles)
    ? cv.experiences_professionnelles
    : [];
  if (modernExperiences.length > 0) {
    return modernExperiences as Array<Record<string, unknown>>;
  }
  if (Array.isArray(cv.experience)) {
    return cv.experience as Array<Record<string, unknown>>;
  }
  return [];
}

function totalExperienceYears(cv?: CV): number | null {
  if (!cv) {
    return null;
  }
  const blocks = collectExperienceBlocks(cv);
  if (blocks.length === 0) {
    return null;
  }

  const total = blocks.reduce((sum, block) => {
    return (
      sum +
      yearsBetween(
        (block.date_debut as DateLike) || (block.start_date as DateLike),
        (block.date_fin as DateLike) || (block.end_date as DateLike)
      )
    );
  }, 0);

  return Number(total.toFixed(1));
}

function summarizeRiskFlags(result: ResultatMatching): string[] {
  const flags: string[] = [];
  if (result.flags?.gappes?.length) {
    flags.push(`Gap ×${result.flags.gappes.length}`);
  }
  if (result.flags?.overlaps?.length) {
    flags.push(`Overlap ×${result.flags.overlaps.length}`);
  }
  return flags;
}

function buildSummary(result: ResultatMatching): string {
  const raw = result.matrix_summary || result.appreciation_globale || result.commentaire_scoring || '';
  if (!raw.trim()) {
    return '—';
  }
  const normalized = raw.replace(/\s+/g, ' ').trim();
  if (normalized.length <= 160) {
    return normalized;
  }
  return `${normalized.slice(0, 157)}...`;
}

function formatRecommendationLevel(value?: string | null): string {
  switch ((value || '').trim()) {
    case 'strong_fit':
      return 'Strong fit';
    case 'good_fit':
      return 'Good fit';
    case 'mixed':
      return 'Mixed';
    case 'weak_fit':
      return 'Weak fit';
    default:
      return '—';
  }
}

function candidateLabel(result: ResultatMatching, cv?: CV): string {
  return (
    result.candidate_name ||
    `${cv?.identite?.prenom || ''} ${cv?.identite?.nom || ''}`.trim() ||
    result.cv
  );
}

function addAssessment(
  map: Record<string, MatrixAssessmentCell>,
  group: MatrixCriterionGroup,
  assessment?: CriterionAssessment | null,
) {
  if (!assessment?.criterion) {
    return;
  }
  const id = normalizeCriterionId(group, assessment.criterion);
  map[id] = {
    status: (assessment.status as MatrixCriterionStatus) || 'unclear',
    reason: assessment.reason || '',
    evidenceIds: assessment.evidence_ids || [],
  };
}

function fallbackAssessmentMap(
  result: ResultatMatching,
  offer: Offre | null | undefined,
): Record<string, MatrixAssessmentCell> {
  const map: Record<string, MatrixAssessmentCell> = {};
  const missingNiceToHave = new Set((result.nice_have_manquants || []).map((item) => normalizeText(item)));

  for (const criterion of offer?.must_have || []) {
    map[normalizeCriterionId('must', criterion)] = {
      status: 'met',
      reason: 'This profile is part of the pool that passed the must-have filter for this matching run.',
      evidenceIds: [],
    };
  }

  for (const criterion of offer?.nice_have || []) {
    const normalizedCriterion = normalizeText(criterion);
    const missing = missingNiceToHave.has(normalizedCriterion);
    map[normalizeCriterionId('nice', criterion)] = {
      status: missing ? 'missing' : 'met',
      reason: missing
        ? 'Listed among the missing nice-to-have criteria in the matching result.'
        : 'Not listed among the missing nice-to-have criteria in the matching result.',
      evidenceIds: [],
    };
  }

  return map;
}

function buildAssessmentMap(
  result: ResultatMatching,
  offer: Offre | null | undefined,
): Record<string, MatrixAssessmentCell> {
  const map = fallbackAssessmentMap(result, offer);

  for (const assessment of result.must_have_assessment || []) {
    addAssessment(map, 'must', assessment);
  }
  for (const assessment of result.nice_have_assessment || []) {
    addAssessment(map, 'nice', assessment);
  }

  return map;
}

export function buildMatchingMatrixColumns(offer?: Offre | null): MatrixCriterionColumn[] {
  if (!offer) {
    return [];
  }

  const required = offer.must_have.map((criterion) => ({
    id: normalizeCriterionId('must', criterion),
    label: criterion,
    group: 'must' as const,
  }));

  const preferred = offer.nice_have.map((criterion) => ({
    id: normalizeCriterionId('nice', criterion),
    label: criterion,
    group: 'nice' as const,
  }));

  return [...required, ...preferred];
}

export function buildShortlistMatrixRows(
  results: ResultatMatching[],
  offer: Offre | null | undefined,
  cvs: CV[] = [],
): ShortlistMatrixRow[] {
  const cvMap = new Map<string, CV>();
  for (const cv of cvs) {
    cvMap.set(normalizeText(cv.cv), cv);
  }

  return results.map((result) => {
    const cv = cvMap.get(normalizeText(result.cv));
    return {
      candidateId: result.cv,
      candidateLabel: candidateLabel(result, cv),
      finalScorePct: Number((result.score_final * 100).toFixed(1)),
      recommendationLevel: formatRecommendationLevel(result.recommendation_level),
      relevantExperienceYears:
        typeof result.relevant_experience_years === 'number'
          ? Number(result.relevant_experience_years.toFixed(1))
          : null,
      totalExperienceYears: totalExperienceYears(cv),
      experienceSignal: result.coefficient_qualite_experience,
      summary: buildSummary(result),
      topStrengths: result.top_strengths || [],
      watchouts: result.watchouts || [],
      interviewFocus: result.interview_focus || [],
      riskFlags: summarizeRiskFlags(result),
      algorithmicBreakdown: result.algorithmic_breakdown || null,
      criterionStatuses: buildAssessmentMap(result, offer),
    };
  });
}

export function buildQualifiedPoolMatrixRows(
  qualifiedResults: ResultatMatching[],
  offer: Offre | null | undefined,
  cvs: CV[] = [],
): QualifiedPoolMatrixRow[] {
  const cvMap = new Map<string, CV>();
  for (const cv of cvs) {
    cvMap.set(normalizeText(cv.cv), cv);
  }

  const niceToHaveCount = offer?.nice_have.length ?? 0;

  return qualifiedResults.map((result, index) => {
    const cv = cvMap.get(normalizeText(result.cv));
    const missingNiceToHave = new Set((result.nice_have_manquants || []).map((item) => normalizeText(item)));
    const matchedNiceToHave = Math.max(0, niceToHaveCount - missingNiceToHave.size);

    return {
      candidateId: result.cv,
      candidateLabel: candidateLabel(result, cv),
      algorithmicRank: result.algorithmic_rank || index + 1,
      algorithmicScorePct: Number((result.score_final * 100).toFixed(1)),
      scoreBasePct: Number((result.score_base * 100).toFixed(1)),
      niceToHaveCoverage: {
        matched: matchedNiceToHave,
        total: niceToHaveCount,
      },
      totalExperienceYears: totalExperienceYears(cv),
      reranked: !!result.reranked,
      algorithmicBreakdown: result.algorithmic_breakdown || null,
      criterionStatuses: buildAssessmentMap(result, offer),
    };
  });
}
