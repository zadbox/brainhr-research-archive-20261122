import type { Meta, StoryObj } from '@storybook/react-vite';
import { I18nContext } from '../../i18n/I18nContext';
import { messages, type Language, type TranslationKey } from '../../i18n/messages';
import type { MatrixCriterionColumn, QualifiedPoolMatrixRow, ShortlistMatrixRow } from '../../lib/matchingMatrix';
import { MatchingResultsMatrix } from './MatchingResultsMatrix';

type MatrixReferenceProps = {
  language: Language;
  theme: 'light' | 'dark';
  initialColumnView: 'essential' | 'all';
};

const columns: MatrixCriterionColumn[] = [
  { id: 'must:distributed-systems', label: 'Distributed systems architecture', group: 'must' },
  { id: 'must:cloud-platform', label: 'Cloud platform delivery', group: 'must' },
  { id: 'nice:mentoring', label: 'Engineering team mentoring', group: 'nice' },
];

const breakdown = {
  mode: 'sectioned',
  score_base: 0.866,
  final_algorithmic_score_before_rerank_coefficient: 0.866,
  tech_score: 0.91,
  experience_score_effective: 0.84,
  summary_score: 0.86,
  nice_to_have_missing_count: 1,
  nice_to_have_multiplier: 0.96,
};

const statuses = {
  'must:distributed-systems': { status: 'met' as const, reason: 'Multiple production-scale platforms delivered.', evidenceIds: [] },
  'must:cloud-platform': { status: 'met' as const, reason: 'Hands-on AWS platform leadership.', evidenceIds: [] },
  'nice:mentoring': { status: 'partial' as const, reason: 'Mentoring is mentioned without a team size.', evidenceIds: [] },
};

const shortlistRows: ShortlistMatrixRow[] = [
  {
    candidateId: 'candidate-karima',
    candidateLabel: 'Karima Ben Salah — Principal Platform Engineer',
    finalScorePct: 94.6,
    recommendationLevel: 'Strong fit',
    relevantExperienceYears: 7.5,
    totalExperienceYears: 11.2,
    experienceSignal: 1.08,
    summary: 'Strong architecture depth with concrete ownership of resilient cloud platforms and cross-functional delivery.',
    topStrengths: ['Distributed architecture', 'AWS delivery', 'Technical leadership'],
    watchouts: ['Confirm current people-management scope'],
    interviewFocus: ['Architecture trade-offs', 'Operational ownership'],
    riskFlags: [],
    algorithmicBreakdown: breakdown,
    criterionStatuses: statuses,
  },
  {
    candidateId: 'candidate-karim',
    candidateLabel: 'Karim El Mansouri',
    finalScorePct: 88.2,
    recommendationLevel: 'Good fit',
    relevantExperienceYears: 6.1,
    totalExperienceYears: 9.4,
    experienceSignal: 1.04,
    summary: 'Balanced technical profile with strong delivery evidence and a clear progression toward platform ownership.',
    topStrengths: ['Delivery discipline', 'Platform reliability'],
    watchouts: ['Less evidence on multi-region systems'],
    interviewFocus: ['Scale boundaries', 'Mentoring examples'],
    riskFlags: [],
    algorithmicBreakdown: { ...breakdown, score_base: 0.822, final_algorithmic_score_before_rerank_coefficient: 0.822 },
    criterionStatuses: statuses,
  },
];

const qualifiedRows: QualifiedPoolMatrixRow[] = Array.from({ length: 5 }, (_, index) => ({
  candidateId: `qualified-${index}`,
  candidateLabel: index === 0 ? 'Karima Ben Salah — Principal Platform Engineer' : `Qualified candidate ${index + 1}`,
  algorithmicRank: index + 1,
  algorithmicScorePct: 86.6 - index * 2.1,
  scoreBasePct: 86.6 - index * 2.1,
  niceToHaveCoverage: { matched: 1, total: 2 },
  totalExperienceYears: 11.2 - index * 0.7,
  reranked: index < 2,
  algorithmicBreakdown: breakdown,
  criterionStatuses: statuses,
}));

function MatrixReference({ language, theme, initialColumnView }: MatrixReferenceProps) {
  const t = (key: TranslationKey) => messages[language][key];

  return (
    <I18nContext.Provider value={{ language, setLanguage: () => undefined, t }}>
      <main
        data-brain-ops=""
        className={`${theme === 'dark' ? 'dark' : ''} min-h-screen bg-[var(--brain-ops-canvas)] px-4 py-8 text-[var(--brain-ops-text)] sm:px-8`}
      >
        <div className="mx-auto max-w-7xl">
          <MatchingResultsMatrix
            columns={columns}
            shortlistRows={shortlistRows}
            qualifiedRows={qualifiedRows}
            initialColumnView={initialColumnView}
          />
        </div>
      </main>
    </I18nContext.Provider>
  );
}

const meta = {
  title: 'BRAIN Operations/Matching results matrix',
  component: MatrixReference,
  parameters: { layout: 'fullscreen' },
  args: { language: 'en', theme: 'light', initialColumnView: 'essential' },
  argTypes: {
    language: { control: 'inline-radio', options: ['en', 'fr'] },
    theme: { control: 'inline-radio', options: ['light', 'dark'] },
    initialColumnView: { control: 'inline-radio', options: ['essential', 'all'] },
  },
} satisfies Meta<typeof MatrixReference>;

export default meta;
type Story = StoryObj<typeof meta>;

export const DesktopComparison: Story = {};

export const FrenchDarkTheme: Story = {
  args: { language: 'fr', theme: 'dark' },
};

export const MobileComparison: Story = {
  args: { language: 'fr' },
  parameters: { viewport: { defaultViewport: 'mobile1' } },
};

export const MobileAllDetails: Story = {
  args: { language: 'fr', initialColumnView: 'all' },
  parameters: { viewport: { defaultViewport: 'mobile1' } },
};
