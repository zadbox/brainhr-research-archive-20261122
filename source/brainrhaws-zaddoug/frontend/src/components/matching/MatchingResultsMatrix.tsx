import { Fragment, useState } from 'react';
import { Columns3, Eye, MoveHorizontal } from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../ui/table';
import { MetricStrip } from '../operations';
import type { MatchingResponse } from '../../api/types';
import { useI18n } from '../../i18n/useI18n';
import type {
  MatrixAssessmentCell,
  MatrixCriterionColumn,
  QualifiedPoolMatrixRow,
  ShortlistMatrixRow,
} from '../../lib/matchingMatrix';

type Props = {
  columns: MatrixCriterionColumn[];
  shortlistRows: ShortlistMatrixRow[];
  qualifiedRows: QualifiedPoolMatrixRow[];
  metadata?: MatchingResponse['metadata'] | null;
  initialColumnView?: 'essential' | 'all';
};

const rankColumnClass = 'sticky left-0 z-20 w-14 min-w-14 max-w-14 bg-[var(--brain-ops-surface)] px-2 text-center';
const rankCellClass = 'sticky left-0 z-10 w-14 min-w-14 max-w-14 bg-[var(--brain-ops-surface)] px-2 text-center font-medium';
const candidateColumnClass = 'min-w-[210px] bg-[var(--brain-ops-surface)] sm:sticky sm:left-14 sm:z-20 sm:w-[240px] sm:min-w-[240px] sm:max-w-[240px]';
const candidateCellClass = 'min-w-[210px] bg-[var(--brain-ops-surface)] sm:sticky sm:left-14 sm:z-10 sm:w-[240px] sm:min-w-[240px] sm:max-w-[240px]';

function renderMetric(value?: number | null, asPercent = true) {
  if (typeof value !== 'number') {
    return '—';
  }
  return asPercent ? `${(value * 100).toFixed(1)}%` : value.toFixed(2);
}

function NarrativeBlock({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold text-[var(--brain-ops-text)]">{label}</h4>
      <p className="text-sm leading-6 text-[var(--brain-ops-text-muted)]">
        {values.length ? values.join(' • ') : '—'}
      </p>
    </div>
  );
}

export function MatchingResultsMatrix({
  columns,
  shortlistRows,
  qualifiedRows,
  metadata,
  initialColumnView = 'all',
}: Props) {
  const { t } = useI18n();
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [columnView, setColumnView] = useState<'essential' | 'all'>(initialColumnView);
  const requiredColumns = columns.filter((column) => column.group === 'must');
  const preferredColumns = columns.filter((column) => column.group === 'nice');
  const shortlistRowByCandidateId = new Map(shortlistRows.map((row) => [row.candidateId, row]));
  const showAllDetails = columnView === 'all';
  const shortlistColumnCount = (showAllDetails ? 17 : 5) + columns.length;
  const qualifiedColumnCount = (showAllDetails ? 19 : 8) + columns.length;
  void metadata;

  const toggleExpanded = (candidateId: string) => {
    setExpandedRows((current) => {
      const next = new Set(current);
      if (next.has(candidateId)) {
        next.delete(candidateId);
      } else {
        next.add(candidateId);
      }
      return next;
    });
  };

  const statusBadge = (cell: MatrixAssessmentCell) => {
    switch (cell.status) {
      case 'met':
        return <Badge variant="success" title={cell.reason}>{t('results.matrix.status.met')}</Badge>;
      case 'partial':
        return (
          <Badge
            variant="outline"
            className="border-[color:var(--brain-ops-warning)] text-[var(--brain-ops-warning)]"
            title={cell.reason}
          >
            {t('results.matrix.status.partial')}
          </Badge>
        );
      case 'missing':
        return <Badge variant="destructive" title={cell.reason}>{t('results.matrix.status.missing')}</Badge>;
      default:
        return <Badge variant="outline" title={cell.reason || t('results.matrix.status.unavailable')}>{t('results.matrix.status.unclear')}</Badge>;
    }
  };

  const recommendationBadge = (level: string) => {
    const normalized = level.toLowerCase();
    const key = normalized.includes('strong')
      ? 'results.matrix.recommendation.strong'
      : normalized.includes('good')
        ? 'results.matrix.recommendation.good'
        : normalized.includes('weak')
          ? 'results.matrix.recommendation.weak'
          : 'results.matrix.recommendation.mixed';
    return <Badge variant={normalized.includes('strong') || normalized.includes('good') ? 'success' : 'outline'}>{t(key)}</Badge>;
  };

  const criterionGrid = (candidateId: string, statuses: Record<string, MatrixAssessmentCell>) => (
    <section className="space-y-3" aria-label={t('results.matrix.criteria.aria')}>
      <h4 className="font-mono text-xs uppercase tracking-[0.12em] text-[var(--brain-ops-text-muted)]">
        {t('results.matrix.criteria.title')}
      </h4>
      {columns.length ? (
        <div className="grid gap-px overflow-hidden border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-border)] sm:grid-cols-2 xl:grid-cols-3">
          {columns.map((column) => (
            <div key={`${candidateId}:${column.id}`} className="flex min-w-0 items-start justify-between gap-3 bg-[var(--brain-ops-surface)] p-3">
              <div className="min-w-0">
                <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--brain-ops-text-muted)]">
                  {column.group === 'must' ? t('results.matrix.criteria.requiredShort') : t('results.matrix.criteria.preferredShort')}
                </div>
                <div className="mt-1 text-sm font-medium text-[var(--brain-ops-text)]">{column.label}</div>
              </div>
              {statusBadge(statuses[column.id] || { status: 'unclear', reason: '', evidenceIds: [] })}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-[var(--brain-ops-text-muted)]">{t('results.matrix.criteria.none')}</p>
      )}
    </section>
  );

  const scrollHint = (
    <p className="flex items-center gap-2 text-xs text-[var(--brain-ops-text-muted)]">
      <MoveHorizontal className="size-4 shrink-0" aria-hidden="true" />
      {t('results.matrix.scrollHint')}
    </p>
  );

  const columnViewControl = (
    <div className="flex flex-col gap-2 border-y border-[color:var(--brain-ops-border)] py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)]">
        <Columns3 className="size-4" aria-hidden="true" />
        <span>{t('results.matrix.columns.label')}</span>
      </div>
      <div
        className="flex w-full gap-1 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-1 sm:w-auto"
        role="group"
        aria-label={t('results.matrix.columns.label')}
      >
        <Button
          type="button"
          variant={columnView === 'essential' ? 'default' : 'ghost'}
          size="sm"
          className="min-h-9 flex-1 px-3 sm:flex-none"
          aria-pressed={columnView === 'essential'}
          onClick={() => setColumnView('essential')}
        >
          {t('results.matrix.columns.essential')}
        </Button>
        <Button
          type="button"
          variant={columnView === 'all' ? 'default' : 'ghost'}
          size="sm"
          className="min-h-9 flex-1 px-3 sm:flex-none"
          aria-pressed={columnView === 'all'}
          onClick={() => setColumnView('all')}
        >
          {t('results.matrix.columns.all')}
        </Button>
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      <MetricStrip
        ariaLabel={t('results.matrix.metricsAria')}
        items={[
          { id: 'must', label: t('results.matrix.metric.mustHave'), value: requiredColumns.length },
          { id: 'nice', label: t('results.matrix.metric.niceToHave'), value: preferredColumns.length },
        ]}
      />

      {columnViewControl}

      <Tabs defaultValue="shortlist" className="space-y-5">
        <TabsList className="h-auto w-full justify-start gap-1 overflow-x-auto rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-1 sm:w-auto">
          <TabsTrigger value="shortlist" className="rounded-[var(--brain-ops-radius-structural)] px-4 py-2 data-[state=active]:bg-[var(--brain-ops-surface)] data-[state=active]:shadow-none">
            {t('results.matrix.tab.shortlist')}
          </TabsTrigger>
          <TabsTrigger value="qualified" className="rounded-[var(--brain-ops-radius-structural)] px-4 py-2 data-[state=active]:bg-[var(--brain-ops-surface)] data-[state=active]:shadow-none">
            {t('results.matrix.tab.qualified')}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="shortlist" className="space-y-4">
          <div className="border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-4 text-sm text-[var(--brain-ops-text-muted)]">
            {t('results.matrix.shortlistDescription')}
          </div>
          {scrollHint}
          <div
            className="max-w-full overflow-x-auto border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]"
            role="region"
            aria-label={t('results.matrix.shortlistTableAria')}
            tabIndex={0}
          >
            <Table className={showAllDetails ? 'min-w-[2400px]' : 'min-w-[980px]'}>
              <TableHeader>
                <TableRow>
                  <TableHead className={rankColumnClass}>{t('results.matrix.column.rank')}</TableHead>
                  <TableHead className={candidateColumnClass}>{t('results.matrix.column.candidate')}</TableHead>
                  <TableHead className="min-w-[120px]">{t('results.matrix.column.finalScore')}</TableHead>
                  {showAllDetails ? <TableHead className="min-w-[140px]">{t('results.matrix.column.algorithmicScore')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[120px]">{t('results.matrix.column.baseScore')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[120px]">{t('results.matrix.column.tech')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[140px]">{t('results.matrix.column.experienceComponent')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[130px]">{t('results.matrix.column.summaryComponent')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[150px]">{t('results.matrix.column.niceMultiplier')}</TableHead> : null}
                  <TableHead className="min-w-[150px]">{t('results.matrix.column.recommendation')}</TableHead>
                  <TableHead className="min-w-[150px]">{t('results.matrix.column.relevantExperience')}</TableHead>
                  {showAllDetails ? <TableHead className="min-w-[140px]">{t('results.matrix.column.totalExperience')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[140px]">{t('results.matrix.column.experienceSignal')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[260px]">{t('results.matrix.column.strengths')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[260px]">{t('results.matrix.column.watchouts')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[260px]">{t('results.matrix.column.interviewFocus')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[280px]">{t('results.matrix.column.summary')}</TableHead> : null}
                  {requiredColumns.map((column) => <TableHead key={column.id} className="min-w-[170px] bg-[var(--brain-ops-surface-muted)]">MH: {column.label}</TableHead>)}
                  {preferredColumns.map((column) => <TableHead key={column.id} className="min-w-[170px] bg-[var(--brain-ops-accent-soft)]">NH: {column.label}</TableHead>)}
                </TableRow>
              </TableHeader>
              <TableBody>
                {shortlistRows.length ? shortlistRows.map((row, index) => {
                  const expanded = expandedRows.has(row.candidateId);
                  return (
                    <Fragment key={row.candidateId}>
                      <TableRow>
                        <TableCell className={rankCellClass}>{index + 1}</TableCell>
                        <TableCell className={candidateCellClass}>
                          <div className="space-y-2">
                            <div className="font-medium">{row.candidateLabel}</div>
                            <Button type="button" variant="outline" size="sm" className="h-8 px-2 text-xs" aria-expanded={expanded} onClick={() => toggleExpanded(row.candidateId)}>
                              <Eye data-icon="inline-start" />
                              {t(expanded ? 'results.matrix.closeDetails' : 'results.matrix.openDetails')}
                            </Button>
                          </div>
                        </TableCell>
                        <TableCell className="font-semibold">{row.finalScorePct.toFixed(1)}%</TableCell>
                        {showAllDetails ? <TableCell>{renderMetric(row.algorithmicBreakdown?.final_algorithmic_score_before_rerank_coefficient)}</TableCell> : null}
                        {showAllDetails ? <TableCell>{renderMetric(row.algorithmicBreakdown?.score_base)}</TableCell> : null}
                        {showAllDetails ? <TableCell>{renderMetric(row.algorithmicBreakdown?.tech_score)}</TableCell> : null}
                        {showAllDetails ? <TableCell>{renderMetric(row.algorithmicBreakdown?.experience_score_effective)}</TableCell> : null}
                        {showAllDetails ? <TableCell>{renderMetric(row.algorithmicBreakdown?.summary_score)}</TableCell> : null}
                        {showAllDetails ? <TableCell>{renderMetric(row.algorithmicBreakdown?.nice_to_have_multiplier, false)}x</TableCell> : null}
                        <TableCell>{recommendationBadge(row.recommendationLevel)}</TableCell>
                        <TableCell>{row.relevantExperienceYears !== null ? `${row.relevantExperienceYears.toFixed(1)} ${t('results.matrix.yearsShort')}` : '—'}</TableCell>
                        {showAllDetails ? <TableCell>{row.totalExperienceYears !== null ? `${row.totalExperienceYears.toFixed(1)} ${t('results.matrix.yearsShort')}` : '—'}</TableCell> : null}
                        {showAllDetails ? <TableCell>{row.experienceSignal.toFixed(2)}x</TableCell> : null}
                        {showAllDetails ? <TableCell className="text-sm text-[var(--brain-ops-text-muted)]">{row.topStrengths.length ? row.topStrengths.join(' • ') : '—'}</TableCell> : null}
                        {showAllDetails ? <TableCell className="text-sm text-[var(--brain-ops-text-muted)]">{row.watchouts.length ? row.watchouts.join(' • ') : '—'}</TableCell> : null}
                        {showAllDetails ? <TableCell className="text-sm text-[var(--brain-ops-text-muted)]">{row.interviewFocus.length ? row.interviewFocus.join(' • ') : '—'}</TableCell> : null}
                        {showAllDetails ? <TableCell className="text-sm text-[var(--brain-ops-text-muted)]">{row.summary || '—'}</TableCell> : null}
                        {columns.map((column) => <TableCell key={`${row.candidateId}:${column.id}`}>{statusBadge(row.criterionStatuses[column.id] || { status: 'unclear', reason: '', evidenceIds: [] })}</TableCell>)}
                      </TableRow>
                      {expanded ? (
                        <TableRow className="hover:bg-transparent">
                          <TableCell colSpan={shortlistColumnCount} className="bg-[var(--brain-ops-surface-muted)] p-0">
                            <div className="sticky left-0 w-[calc(100vw-2rem)] min-w-[280px] max-w-6xl p-4 sm:w-[calc(100vw-4rem)] sm:p-5">
                            <div className="grid gap-5 lg:grid-cols-2">
                              <NarrativeBlock label={t('results.matrix.column.summary')} values={row.summary ? [row.summary] : []} />
                              <NarrativeBlock label={t('results.matrix.column.strengths')} values={row.topStrengths} />
                              <NarrativeBlock label={t('results.matrix.column.watchouts')} values={row.watchouts} />
                              <NarrativeBlock label={t('results.matrix.column.interviewFocus')} values={row.interviewFocus} />
                            </div>
                            <div className="mt-5">{criterionGrid(row.candidateId, row.criterionStatuses)}</div>
                            </div>
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </Fragment>
                  );
                }) : (
                  <TableRow><TableCell colSpan={shortlistColumnCount} className="py-8 text-[var(--brain-ops-text-muted)]">{t('results.matrix.shortlistEmpty')}</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        <TabsContent value="qualified" className="space-y-4">
          <div className="border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-4 text-sm text-[var(--brain-ops-text-muted)]">
            {t('results.matrix.qualifiedDescription')}
          </div>
          {scrollHint}
          <div className="max-w-full overflow-x-auto border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]" role="region" aria-label={t('results.matrix.qualifiedTableAria')} tabIndex={0}>
            <Table className={showAllDetails ? 'min-w-[3200px]' : 'min-w-[1320px]'}>
              <TableHeader>
                <TableRow>
                  <TableHead
                    className={rankColumnClass}
                    aria-label={t('results.matrix.column.algorithmicRank')}
                    title={t('results.matrix.column.algorithmicRank')}
                  >
                    {t('results.matrix.column.rank')}
                  </TableHead>
                  <TableHead className={candidateColumnClass}>{t('results.matrix.column.candidate')}</TableHead>
                  <TableHead className="min-w-[120px]">{t('results.matrix.column.finalScore')}</TableHead>
                  <TableHead className="min-w-[140px]">{t('results.matrix.column.algorithmicScore')}</TableHead>
                  {showAllDetails ? <TableHead className="min-w-[130px]">{t('results.matrix.column.baseScore')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[120px]">{t('results.matrix.column.tech')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[140px]">{t('results.matrix.column.experienceComponent')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[130px]">{t('results.matrix.column.summaryComponent')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[150px]">{t('results.matrix.column.niceMultiplier')}</TableHead> : null}
                  <TableHead className="min-w-[150px]">{t('results.matrix.column.niceCoverage')}</TableHead>
                  <TableHead className="min-w-[150px]">{t('results.matrix.column.recommendation')}</TableHead>
                  {showAllDetails ? <TableHead className="min-w-[150px]">{t('results.matrix.column.relevantExperience')}</TableHead> : null}
                  <TableHead className="min-w-[140px]">{t('results.matrix.column.totalExperience')}</TableHead>
                  {showAllDetails ? <TableHead className="min-w-[140px]">{t('results.matrix.column.experienceSignal')}</TableHead> : null}
                  <TableHead className="min-w-[130px]">{t('results.matrix.column.reranked')}</TableHead>
                  {showAllDetails ? <TableHead className="min-w-[260px]">{t('results.matrix.column.strengths')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[260px]">{t('results.matrix.column.watchouts')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[260px]">{t('results.matrix.column.interviewFocus')}</TableHead> : null}
                  {showAllDetails ? <TableHead className="min-w-[280px]">{t('results.matrix.column.summary')}</TableHead> : null}
                  {requiredColumns.map((column) => <TableHead key={column.id} className="min-w-[170px] bg-[var(--brain-ops-surface-muted)]">MH: {column.label}</TableHead>)}
                  {preferredColumns.map((column) => <TableHead key={column.id} className="min-w-[170px] bg-[var(--brain-ops-accent-soft)]">NH: {column.label}</TableHead>)}
                </TableRow>
              </TableHeader>
              <TableBody>
                {qualifiedRows.length ? qualifiedRows.map((row) => {
                  const expanded = expandedRows.has(row.candidateId);
                  const shortlistRow = shortlistRowByCandidateId.get(row.candidateId);
                  return (
                    <Fragment key={`${row.algorithmicRank}:${row.candidateId}`}>
                      <TableRow>
                        <TableCell className={rankCellClass}>{row.algorithmicRank}</TableCell>
                        <TableCell className={candidateCellClass}>
                          <div className="space-y-2">
                            <div className="font-medium">{row.candidateLabel}</div>
                            <Button type="button" variant="outline" size="sm" className="h-8 px-2 text-xs" aria-expanded={expanded} onClick={() => toggleExpanded(row.candidateId)}>
                              <Eye data-icon="inline-start" />
                              {t(expanded
                                ? 'results.matrix.closeDetails'
                                : shortlistRow
                                  ? 'results.matrix.openDetails'
                                  : 'results.matrix.openAvailableDetails')}
                            </Button>
                          </div>
                        </TableCell>
                        <TableCell className="font-semibold">{shortlistRow ? `${shortlistRow.finalScorePct.toFixed(1)}%` : '—'}</TableCell>
                        <TableCell className="font-semibold">{row.algorithmicScorePct.toFixed(1)}%</TableCell>
                        {showAllDetails ? <TableCell>{row.scoreBasePct.toFixed(1)}%</TableCell> : null}
                        {showAllDetails ? <TableCell>{renderMetric(row.algorithmicBreakdown?.tech_score)}</TableCell> : null}
                        {showAllDetails ? <TableCell>{renderMetric(row.algorithmicBreakdown?.experience_score_effective)}</TableCell> : null}
                        {showAllDetails ? <TableCell>{renderMetric(row.algorithmicBreakdown?.summary_score)}</TableCell> : null}
                        {showAllDetails ? <TableCell>{renderMetric(row.algorithmicBreakdown?.nice_to_have_multiplier, false)}x</TableCell> : null}
                        <TableCell>{row.niceToHaveCoverage.total > 0 ? `${row.niceToHaveCoverage.matched} / ${row.niceToHaveCoverage.total}` : '—'}</TableCell>
                        <TableCell>{shortlistRow ? recommendationBadge(shortlistRow.recommendationLevel) : '—'}</TableCell>
                        {showAllDetails ? <TableCell>{typeof shortlistRow?.relevantExperienceYears === 'number' ? `${shortlistRow.relevantExperienceYears.toFixed(1)} ${t('results.matrix.yearsShort')}` : '—'}</TableCell> : null}
                        <TableCell>{row.totalExperienceYears !== null ? `${row.totalExperienceYears.toFixed(1)} ${t('results.matrix.yearsShort')}` : '—'}</TableCell>
                        {showAllDetails ? <TableCell>{shortlistRow ? `${shortlistRow.experienceSignal.toFixed(2)}x` : '—'}</TableCell> : null}
                        <TableCell>{row.reranked ? <Badge variant="success">{t('results.matrix.reranked.top')}</Badge> : <Badge variant="outline">{t('results.matrix.reranked.algorithmic')}</Badge>}</TableCell>
                        {showAllDetails ? <TableCell className="text-sm text-[var(--brain-ops-text-muted)]">{shortlistRow?.topStrengths.length ? shortlistRow.topStrengths.join(' • ') : '—'}</TableCell> : null}
                        {showAllDetails ? <TableCell className="text-sm text-[var(--brain-ops-text-muted)]">{shortlistRow?.watchouts.length ? shortlistRow.watchouts.join(' • ') : '—'}</TableCell> : null}
                        {showAllDetails ? <TableCell className="text-sm text-[var(--brain-ops-text-muted)]">{shortlistRow?.interviewFocus.length ? shortlistRow.interviewFocus.join(' • ') : '—'}</TableCell> : null}
                        {showAllDetails ? <TableCell className="text-sm text-[var(--brain-ops-text-muted)]">{shortlistRow?.summary || '—'}</TableCell> : null}
                        {columns.map((column) => <TableCell key={`${row.candidateId}:${column.id}`}>{statusBadge(row.criterionStatuses[column.id] || { status: 'unclear', reason: '', evidenceIds: [] })}</TableCell>)}
                      </TableRow>
                      {expanded ? (
                        <TableRow className="hover:bg-transparent">
                          <TableCell colSpan={qualifiedColumnCount} className="bg-[var(--brain-ops-surface-muted)] p-0">
                            <div className="sticky left-0 w-[calc(100vw-2rem)] min-w-[280px] max-w-6xl p-4 sm:w-[calc(100vw-4rem)] sm:p-5">
                            {shortlistRow ? (
                              <div className="grid gap-5 lg:grid-cols-2">
                                <NarrativeBlock label={t('results.matrix.column.summary')} values={shortlistRow.summary ? [shortlistRow.summary] : []} />
                                <NarrativeBlock label={t('results.matrix.column.strengths')} values={shortlistRow.topStrengths} />
                                <NarrativeBlock label={t('results.matrix.column.watchouts')} values={shortlistRow.watchouts} />
                                <NarrativeBlock label={t('results.matrix.column.interviewFocus')} values={shortlistRow.interviewFocus} />
                              </div>
                            ) : (
                              <div className="max-w-3xl border-l-2 border-[color:var(--brain-ops-accent)] bg-[var(--brain-ops-surface)] p-4">
                                <h4 className="font-semibold text-[var(--brain-ops-text)]">{t('results.matrix.algorithmicDetail.title')}</h4>
                                <p className="mt-2 text-sm leading-6 text-[var(--brain-ops-text-muted)]">{t('results.matrix.algorithmicDetail.description')}</p>
                              </div>
                            )}
                            <div className="mt-5">{criterionGrid(row.candidateId, row.criterionStatuses)}</div>
                            </div>
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </Fragment>
                  );
                }) : (
                  <TableRow><TableCell colSpan={qualifiedColumnCount} className="py-8 text-[var(--brain-ops-text-muted)]">{t('results.matrix.qualifiedEmpty')}</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
