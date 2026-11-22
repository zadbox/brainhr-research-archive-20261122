import type { CV, Offre, Project } from '../../../api/types';

export type RealtimeInterviewLaunchSource =
  | 'matching'
  | 'matching-detail'
  | 'cv-base'
  | 'interview-sheet'
  | 'direct';

export interface RealtimeInterviewLaunchContext {
  source?: RealtimeInterviewLaunchSource;
  projectId?: string | null;
  projectName?: string | null;
  candidateId?: string | null;
  candidateName?: string | null;
  candidateEmail?: string | null;
  candidateCvText?: string | null;
  matchingId?: string | null;
  sheetId?: string | null;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'string') {
    return value.trim();
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function appendSection(lines: string[], title: string, values: Array<unknown>) {
  const cleanValues = values.map(formatValue).filter(Boolean);
  if (cleanValues.length === 0) {
    return;
  }
  lines.push(`${title}:`);
  cleanValues.forEach((value) => lines.push(`- ${value}`));
  lines.push('');
}

export function getCandidateDisplayName(
  candidate?: Partial<CV> | null,
  fallback?: string | null
): string {
  const firstName = candidate?.identite?.prenom?.trim();
  const lastName = candidate?.identite?.nom?.trim();
  const fullName = [firstName, lastName].filter(Boolean).join(' ').trim();
  const legacyIdentity = (candidate as Record<string, unknown> | null)?.informations_personnelles as
    | Record<string, unknown>
    | undefined;
  const legacyFullName =
    typeof legacyIdentity?.nom_complet === 'string' ? legacyIdentity.nom_complet.trim() : '';

  return fullName || legacyFullName || fallback?.trim() || candidate?.cv?.trim() || 'Candidat';
}

export function getCandidateEmail(candidate?: Partial<CV> | null): string | null {
  const legacyIdentity = (candidate as Record<string, unknown> | null)?.informations_personnelles as
    | Record<string, unknown>
    | undefined;
  return (
    candidate?.identite?.email?.trim() ||
    (typeof legacyIdentity?.email === 'string' ? legacyIdentity.email.trim() : null)
  );
}

export function buildRealtimeInterviewSearch(context: RealtimeInterviewLaunchContext): string {
  const params = new URLSearchParams();
  if (context.source) params.set('source', context.source);
  if (context.projectId) params.set('projectId', context.projectId);
  if (context.candidateId) params.set('candidateId', context.candidateId);
  if (context.matchingId) params.set('matchingId', context.matchingId);
  if (context.sheetId) params.set('sheetId', context.sheetId);
  const serialized = params.toString();
  return serialized ? `?${serialized}` : '';
}

export function buildRealtimeInterviewCvText(candidate?: CV | null): string {
  if (!candidate) {
    return '';
  }

  const candidateRecord = candidate as unknown as Record<string, unknown>;
  const legacyIdentity = candidateRecord.informations_personnelles as
    | Record<string, unknown>
    | undefined;
  const legacySkills = candidateRecord.competences as Record<string, unknown> | undefined;
  const legacySummary = [
    candidate.resume_professionnel,
    typeof candidateRecord.resume === 'string' ? candidateRecord.resume : '',
    typeof candidateRecord.summary === 'string' ? candidateRecord.summary : '',
    typeof candidateRecord.profil === 'string' ? candidateRecord.profil : '',
  ]
    .map((value) => value?.trim())
    .find(Boolean);

  const lines: string[] = [];
  const displayName = getCandidateDisplayName(candidate);
  const headline = candidate.titre?.trim() || legacySummary;
  const phone =
    candidate.identite?.telephone?.trim() ||
    (typeof legacyIdentity?.telephone === 'string' ? legacyIdentity.telephone.trim() : '') ||
    (typeof legacyIdentity?.phone === 'string' ? legacyIdentity.phone.trim() : '');

  lines.push(`Candidat: ${displayName}`);
  if (headline) lines.push(`Titre / accroche: ${headline}`);
  if (getCandidateEmail(candidate)) lines.push(`Email: ${getCandidateEmail(candidate)}`);
  if (phone) lines.push(`Téléphone: ${phone}`);
  if (legacySummary) {
    lines.push('', 'Résumé professionnel:', legacySummary, '');
  }

  const technicalSkills = [
    ...(candidate.competences_techniques || []),
    ...((Array.isArray(legacySkills?.techniques) ? legacySkills.techniques : []) as unknown[]),
    ...((Array.isArray(legacySkills?.outils) ? legacySkills.outils : []) as unknown[]),
  ];

  appendSection(lines, 'Compétences techniques', technicalSkills);
  appendSection(lines, 'Compétences transversales', candidate.competences_transversales || []);
  appendSection(lines, 'Langues', candidate.langues || []);

  if (Array.isArray(candidate.experience) && candidate.experience.length > 0) {
    const experiences = candidate.experience.map((item) => {
      const company = item.entreprise?.trim() || 'Entreprise';
      const role = item.poste?.trim() || 'Poste';
      const period = [item.date_debut, item.date_fin].filter(Boolean).join(' -> ');
      const description = item.description?.trim();
      return [company, role, period, description].filter(Boolean).join(' | ');
    });
    appendSection(lines, 'Expériences récentes', experiences);
  } else if (
    Array.isArray(candidate.experiences_professionnelles) &&
    candidate.experiences_professionnelles.length > 0
  ) {
    appendSection(lines, 'Expériences professionnelles', candidate.experiences_professionnelles.slice(0, 8));
  } else if (Array.isArray(candidateRecord.experiences) && candidateRecord.experiences.length > 0) {
    appendSection(lines, 'Expériences professionnelles', candidateRecord.experiences.slice(0, 8));
  }

  appendSection(
    lines,
    'Formations',
    candidate.formations?.length
      ? candidate.formations
      : Array.isArray(candidateRecord.education)
        ? candidateRecord.education
        : []
  );
  appendSection(lines, 'Certifications', candidate.certifications || []);
  appendSection(lines, 'Projets', candidate.projets || []);

  const rendered = lines.join('\n').trim();
  if (rendered) {
    return rendered;
  }
  try {
    return JSON.stringify(candidateRecord, null, 2);
  } catch {
    return '';
  }
}

export function buildRealtimeInterviewOfferText(
  project?: Project | null,
  offer?: Offre | null
): string {
  const lines: string[] = [];
  if (project?.nom?.trim()) {
    lines.push(`Projet: ${project.nom.trim()}`);
  }
  if (offer?.sections?.titre?.trim()) {
    lines.push(`Intitulé du poste: ${offer.sections.titre.trim()}`);
  } else if (project?.nom?.trim()) {
    lines.push(`Intitulé du poste: ${project.nom.trim()}`);
  }
  if (project?.description?.trim()) {
    lines.push('', 'Contexte projet:', project.description.trim(), '');
  }
  if (offer?.sections?.description?.trim()) {
    lines.push('Description du poste:', offer.sections.description.trim(), '');
  }

  appendSection(lines, 'Must-have', offer?.must_have || []);
  appendSection(lines, 'Nice-to-have', offer?.nice_have || []);
  appendSection(lines, 'Compétences techniques', offer?.sections?.competences_techniques || []);
  appendSection(lines, 'Compétences transversales', offer?.sections?.competences_transversales || []);
  appendSection(lines, 'Langues', offer?.sections?.langues || []);
  appendSection(lines, 'Expériences attendues', offer?.sections?.experiences_professionnelles || []);
  appendSection(lines, 'Formations attendues', offer?.sections?.formations || []);
  appendSection(lines, 'Certifications attendues', offer?.sections?.certifications || []);
  appendSection(lines, 'Projets / missions', offer?.sections?.projets || []);

  return lines.join('\n').trim();
}
