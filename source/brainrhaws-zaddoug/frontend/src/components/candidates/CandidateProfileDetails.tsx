import type { CV } from '../../api/types';
import { useI18n } from '../../i18n/useI18n';

type UnknownRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is UnknownRecord =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value);

const unique = (values: string[]) => Array.from(new Set(values.filter(Boolean)));

const arrayValues = (value: unknown): unknown[] => Array.isArray(value) ? value : [];

const textValues = (value: unknown): string[] => {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed ? [trimmed] : [];
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return [String(value)];
  }
  if (Array.isArray(value)) {
    return unique(value.flatMap(textValues));
  }
  if (isRecord(value)) {
    return unique(Object.values(value).flatMap(textValues));
  }
  return [];
};

const pickText = (record: UnknownRecord, keys: string[]) => {
  for (const key of keys) {
    const value = textValues(record[key]);
    if (value.length > 0) return value[0];
  }
  return '';
};

const pickTexts = (record: UnknownRecord, keys: string[]) =>
  unique(keys.flatMap((key) => textValues(record[key])));

const joinDates = (record: UnknownRecord) => {
  const start = pickText(record, ['date_debut', 'debut', 'start_date', 'start']);
  const end = pickText(record, ['date_fin', 'fin', 'end_date', 'end']);
  if (start && end) return `${start} — ${end}`;
  return start || end;
};

const fallbackRecordLines = (record: UnknownRecord, excludedKeys: string[]) =>
  unique(
    Object.entries(record)
      .filter(([key]) => !excludedKeys.includes(key))
      .flatMap(([, value]) => textValues(value))
  );

const EXPERIENCE_KEYS = [
  'poste', 'titre', 'fonction', 'role', 'job_title',
  'entreprise', 'employeur', 'company', 'organisation', 'organization',
  'lieu', 'location', 'date_debut', 'debut', 'start_date', 'start',
  'date_fin', 'fin', 'end_date', 'end', 'duree', 'duration',
  'description', 'missions', 'mission', 'realisations', 'réalisations',
  'responsabilites', 'responsabilités', 'achievements', 'tasks',
];

const FORMATION_KEYS = [
  'diplome', 'diplôme', 'titre', 'formation', 'degree',
  'ecole', 'école', 'etablissement', 'établissement', 'institution', 'school',
  'annee', 'année', 'date', 'date_debut', 'date_fin', 'lieu', 'location',
  'description', 'details', 'détails',
];

const PROJECT_KEYS = [
  'nom', 'titre', 'name', 'project', 'projet',
  'role', 'rôle', 'client', 'date', 'duree', 'durée',
  'description', 'details', 'détails', 'missions', 'technologies', 'competences',
];

function ProfileSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-[color:var(--brain-ops-border)] pt-4" aria-label={title}>
      <h4 className="mb-3 text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
        {title}
      </h4>
      {children}
    </section>
  );
}

function TextList({ items }: { items: string[] }) {
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-2 text-sm leading-6 text-[var(--brain-ops-text)]">
      {items.map((item) => (
        <li key={item} className="min-w-0 max-w-full break-words [overflow-wrap:anywhere] before:mr-2 before:text-[var(--brain-ops-text-muted)] before:content-['—']">
          {item}
        </li>
      ))}
    </ul>
  );
}

function RecordEntry({
  record,
  kind,
  fallbackTitle,
}: {
  record: UnknownRecord;
  kind: 'experience' | 'formation' | 'project';
  fallbackTitle: string;
}) {
  const configuration = kind === 'experience'
    ? {
        titleKeys: ['poste', 'titre', 'fonction', 'role', 'job_title'],
        metaKeys: ['entreprise', 'employeur', 'company', 'organisation', 'organization', 'lieu', 'location', 'duree', 'duration'],
        bodyKeys: ['description', 'missions', 'mission', 'realisations', 'réalisations', 'responsabilites', 'responsabilités', 'achievements', 'tasks'],
        excludedKeys: EXPERIENCE_KEYS,
      }
    : kind === 'formation'
      ? {
          titleKeys: ['diplome', 'diplôme', 'titre', 'formation', 'degree'],
          metaKeys: ['ecole', 'école', 'etablissement', 'établissement', 'institution', 'school', 'annee', 'année', 'date', 'lieu', 'location'],
          bodyKeys: ['description', 'details', 'détails'],
          excludedKeys: FORMATION_KEYS,
        }
      : {
          titleKeys: ['nom', 'titre', 'name', 'project', 'projet'],
          metaKeys: ['role', 'rôle', 'client', 'date', 'duree', 'durée'],
          bodyKeys: ['description', 'details', 'détails', 'missions', 'technologies', 'competences'],
          excludedKeys: PROJECT_KEYS,
        };

  const title = pickText(record, configuration.titleKeys) || textValues(record)[0] || fallbackTitle;
  const dates = kind === 'experience' ? joinDates(record) : '';
  const metadata = unique([...pickTexts(record, configuration.metaKeys), dates]);
  const body = unique([
    ...pickTexts(record, configuration.bodyKeys),
    ...fallbackRecordLines(record, configuration.excludedKeys),
  ]).filter((value) => value !== title && !metadata.includes(value));

  return (
    <li className="min-w-0 py-3 first:pt-0 last:pb-0">
      <p className="min-w-0 max-w-full break-words font-medium leading-6 text-[var(--brain-ops-text)] [overflow-wrap:anywhere]">{title}</p>
      {metadata.length > 0 && (
        <p className="mt-0.5 min-w-0 max-w-full break-words text-xs leading-5 text-[var(--brain-ops-text-muted)] [overflow-wrap:anywhere]">
          {metadata.join(' · ')}
        </p>
      )}
      {body.length > 0 && <div className="mt-2"><TextList items={body} /></div>}
    </li>
  );
}

export function CandidateProfileDetails({ cv }: { cv: CV }) {
  const { t } = useI18n();
  const professionalExperiences = arrayValues(cv.experiences_professionnelles).filter(isRecord);
  const experiences = professionalExperiences.length > 0
    ? professionalExperiences
    : arrayValues(cv.experience).filter(isRecord);
  const formations = arrayValues(cv.formations).filter(isRecord);
  const transversalSkills = textValues(cv.competences_transversales);
  const languages = textValues(cv.langues);
  const certifications = textValues(cv.certifications);
  const projects = arrayValues(cv.projets).filter(
    (item): item is string | UnknownRecord => typeof item === 'string' || isRecord(item)
  );
  const hasBusinessContent = Boolean(cv.resume_professionnel)
    || experiences.length > 0
    || formations.length > 0
    || transversalSkills.length > 0
    || languages.length > 0
    || certifications.length > 0
    || projects.length > 0;

  return (
    <div className="mt-3 w-full min-w-0 border-t border-[color:var(--brain-ops-border)] pt-4">
      <div className="flex min-w-0 flex-col gap-4">
        {cv.resume_professionnel && (
          <ProfileSection title={t('candidates.profile.summary')}>
            <p className="max-w-4xl whitespace-pre-wrap break-words text-sm leading-6 text-[var(--brain-ops-text)] [overflow-wrap:anywhere]">
              {cv.resume_professionnel}
            </p>
          </ProfileSection>
        )}

        {experiences.length > 0 && (
          <ProfileSection title={t('candidates.profile.experience')}>
            <ul className="divide-y divide-[color:var(--brain-ops-border)]">
              {experiences.map((item, index) => (
                <RecordEntry
                  key={index}
                  record={item}
                  kind="experience"
                  fallbackTitle={t('candidates.profile.experienceItem')}
                />
              ))}
            </ul>
          </ProfileSection>
        )}

        {formations.length > 0 && (
          <ProfileSection title={t('candidates.profile.education')}>
            <ul className="divide-y divide-[color:var(--brain-ops-border)]">
              {formations.map((item, index) => (
                <RecordEntry
                  key={index}
                  record={item}
                  kind="formation"
                  fallbackTitle={t('candidates.profile.educationItem')}
                />
              ))}
            </ul>
          </ProfileSection>
        )}

        {transversalSkills.length > 0 && (
          <ProfileSection title={t('candidates.profile.transversalSkills')}>
            <TextList items={transversalSkills} />
          </ProfileSection>
        )}

        {languages.length > 0 && (
          <ProfileSection title={t('candidates.profile.languages')}>
            <TextList items={languages} />
          </ProfileSection>
        )}

        {certifications.length > 0 && (
          <ProfileSection title={t('candidates.profile.certifications')}>
            <TextList items={certifications} />
          </ProfileSection>
        )}

        {projects.length > 0 && (
          <ProfileSection title={t('candidates.profile.projects')}>
            <ul className="divide-y divide-[color:var(--brain-ops-border)]">
              {projects.map((item, index) => typeof item === 'string'
                ? <li key={index} className="min-w-0 max-w-full break-words py-3 text-sm leading-6 [overflow-wrap:anywhere] first:pt-0 last:pb-0">{item}</li>
                : (
                  <RecordEntry
                    key={index}
                    record={item}
                    kind="project"
                    fallbackTitle={t('candidates.profile.projectItem')}
                  />
                ))}
            </ul>
          </ProfileSection>
        )}

        {!hasBusinessContent && (
          <p className="border-t border-[color:var(--brain-ops-border)] py-4 text-sm leading-6 text-[var(--brain-ops-text-muted)]">
            {t('candidates.profile.empty')}
          </p>
        )}

        <details className="group border-t border-[color:var(--brain-ops-border)]">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)] marker:content-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)] [&::-webkit-details-marker]:hidden">
            <span>{t('candidates.profile.technicalData')}</span>
            <span aria-hidden="true" className="transition-transform duration-[var(--brain-ops-duration-fast)] group-open:rotate-45 motion-reduce:transition-none">+</span>
          </summary>
          <pre className="whitespace-pre-wrap break-words border-t border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-3 text-xs leading-5 text-[var(--brain-ops-text)]">
            {JSON.stringify(cv, null, 2)}
          </pre>
        </details>
      </div>
    </div>
  );
}
