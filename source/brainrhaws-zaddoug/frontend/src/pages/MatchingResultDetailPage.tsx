import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { AlertCircle, AlertTriangle, ChevronDown, ChevronRight, Clock, FileJson, FileSpreadsheet, FileText, SearchCheck } from 'lucide-react';
import { cvsApi } from '../api/cvs';
import { interviewSheetApi, type InterviewSheet } from '../api/interviewSheet';
import { matchingApi } from '../api/matching';
import { offresApi } from '../api/offres';
import type { APIError, CV, MatchingResponse, Offre, ResultatMatching } from '../api/types';
import { InterviewSheetButton } from '../components/interview/InterviewSheetButton';
import { RealtimeInterviewButton } from '../components/interview/realtime/RealtimeInterviewButton';
import { SchedulerButton } from '../components/interview/scheduler/SchedulerButton';
import { MatchingResultsMatrix } from '../components/matching/MatchingResultsMatrix';
import { renderTextWithEvidences } from '../components/matching/renderTextWithEvidences';
import { ContextStrip, MetricStrip, OperationsErrorBanner, PageBackButton, PageFrame, PageHeader, Section, SystemState } from '../components/operations';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { useToast } from '../hooks/useToast';
import { formatMessage } from '../i18n/formatMessage';
import { useI18n } from '../i18n/useI18n';
import { downloadOriginalCv } from '../lib/downloadOriginalCv';
import {
  buildMatchingMatrixColumns,
  buildQualifiedPoolMatrixRows,
  buildShortlistMatrixRows,
} from '../lib/matchingMatrix';

export const MatchingResultDetailPage: React.FC = () => {
  const { projectId, timestamp } = useParams<{ projectId: string; timestamp: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const toast = useToast();
  const { language, t } = useI18n();

  const [results, setResults] = useState<ResultatMatching[]>([]);
  const [matchingResponse, setMatchingResponse] = useState<MatchingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [exporting, setExporting] = useState(false);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [sheetsByCandidate, setSheetsByCandidate] = useState<Record<string, InterviewSheet>>({});
  const viewMode = searchParams.get('view') === 'matrix' ? 'matrix' : 'detail';
  const [offer, setOffer] = useState<Offre | null>(null);
  const [projectCvs, setProjectCvs] = useState<CV[]>([]);
  const resultsRequestKeyRef = useRef<string | null>(null);
  const sheetsRequestKeyRef = useRef<string | null>(null);

  useEffect(() => {
    const requestKey = projectId && timestamp ? `${projectId}:${timestamp}` : null;
    if (!requestKey || resultsRequestKeyRef.current === requestKey) {
      return;
    }
    resultsRequestKeyRef.current = requestKey;

    const fetchResults = async () => {
      if (!projectId || !timestamp) return;

      try {
        setLoading(true);
        setError(null);
        const offerRequest = offresApi.getByProject(projectId).catch(() => null);
        const cvsRequest = cvsApi.getByProject(projectId).catch(() => [] as CV[]);
        const matchingData = await matchingApi.getResultsResponse(projectId, timestamp);

        setMatchingResponse(matchingData);
        setResults(matchingData.results || []);
        setLoading(false);

        const [offerResult, cvsResult] = await Promise.all([offerRequest, cvsRequest]);
        setOffer(offerResult);
        setProjectCvs(cvsResult);
      } catch (err) {
        setError(err as APIError);
      } finally {
        setLoading(false);
      }
    };

    fetchResults();
  }, [projectId, timestamp]);

  useEffect(() => {
    if (!projectId || sheetsRequestKeyRef.current === projectId) {
      return;
    }
    sheetsRequestKeyRef.current = projectId;

    const fetchSheets = async () => {
      try {
        if (!projectId) return;
        const res = await interviewSheetApi.listAll({ job_id: projectId });
        const map: Record<string, InterviewSheet> = {};
        res.sheets.forEach((sheet) => { map[sheet.candidate_id] = sheet; });
        setSheetsByCandidate(map);
      } catch (err) {
        console.error('Erreur chargement fiches entretien', err);
      }
    };
    fetchSheets();
  }, [projectId]);

  const toggleRowExpansion = (cv: string) => {
    setExpandedRows((previous) => {
      const next = new Set(previous);
      if (next.has(cv)) {
        next.delete(cv);
      } else {
        next.add(cv);
      }
      return next;
    });
  };

  const handleDownloadOriginalCv = async (result: ResultatMatching) => {
    if (!result.original_cv_url) {
      return;
    }

    try {
      const filename = await downloadOriginalCv(result.original_cv_url, result.cv);
      toast.success(t('results.detail.downloadSuccess'), filename);
    } catch (err) {
      const message = err instanceof Error ? err.message : t('results.detail.unknownError');
      toast.error(t('results.detail.downloadError'), message);
    }
  };

  const handleExportExcel = async () => {
    if (!projectId || !timestamp) return;
    setExporting(true);
    try {
      const blob = await matchingApi.exportExcel(projectId, timestamp);
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `matching_${projectId}_${timestamp}.xlsx`;
      document.body.appendChild(anchor);
      anchor.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(anchor);
    } catch (err) {
      setError(err as APIError);
    } finally {
      setExporting(false);
    }
  };

  const handleExportJSON = async () => {
    if (!projectId || !timestamp) return;
    setExporting(true);
    try {
      const data = await matchingApi.exportJSON(projectId, timestamp);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `matching_${projectId}_${timestamp}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(anchor);
    } catch (err) {
      setError(err as APIError);
    } finally {
      setExporting(false);
    }
  };

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'font-semibold text-[var(--brain-ops-success)]';
    if (score >= 60) return 'font-semibold text-[var(--brain-ops-accent)]';
    if (score >= 40) return 'text-[var(--brain-ops-warning)]';
    return 'text-[var(--brain-ops-text-muted)]';
  };

  const qualifiedPoolResults = useMemo(
    () => matchingResponse?.qualified_results?.length
      ? matchingResponse.qualified_results
      : results,
    [matchingResponse?.qualified_results, results]
  );
  const matrixColumns = useMemo(
    () => viewMode === 'matrix' ? buildMatchingMatrixColumns(offer) : [],
    [offer, viewMode]
  );
  const shortlistMatrixRows = useMemo(
    () => viewMode === 'matrix' ? buildShortlistMatrixRows(results, offer, projectCvs) : [],
    [offer, projectCvs, results, viewMode]
  );
  const qualifiedPoolRows = useMemo(
    () => viewMode === 'matrix'
      ? buildQualifiedPoolMatrixRows(qualifiedPoolResults, offer, projectCvs)
      : [],
    [offer, projectCvs, qualifiedPoolResults, viewMode]
  );
  const averageScore = results.length
    ? results.reduce((total, result) => total + result.score_final, 0) / results.length
    : 0;
  const evidenceCount = results.filter((result) => result.evidences?.length).length;

  const formatRunLabel = (runTimestamp?: string) => {
    if (!runTimestamp) return '—';
    const [datePart, timePart] = runTimestamp.split('_');
    if (!datePart || !timePart) return runTimestamp.replace('_', ' · ');
    const date = new Date(`${datePart}T${timePart.replace(/-/g, ':')}`);
    if (Number.isNaN(date.getTime())) return `${datePart} · ${timePart.replace(/-/g, ':')}`;
    return date.toLocaleString(language === 'fr' ? 'fr-FR' : 'en-US', {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  };

  if (loading) {
    return (
      <PageFrame>
        <SystemState kind="loading" title={t('results.detail.loading')} />
      </PageFrame>
    );
  }

  return (
    <PageFrame width="full">
      <PageHeader
        eyebrow={t('results.detail.eyebrow')}
        backAction={<PageBackButton onClick={() => navigate(-1)} aria-label={t('common.back')} />}
        title={t('results.detail.title')}
        description={t('results.detail.description')}
        actions={(
          <>
            <Button
              type="button"
              onClick={handleExportExcel}
              disabled={exporting}
            >
              <FileSpreadsheet className="size-4" />
              {exporting ? t('results.detail.exporting') : t('results.detail.exportExcel')}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={handleExportJSON}
              disabled={exporting}
            >
              <FileJson className="size-4" />
              {exporting ? t('results.detail.exporting') : t('results.detail.exportJson')}
            </Button>
          </>
        )}
        actionsLabel={t('results.detail.actionsLabel')}
        context={(
          <ContextStrip
            ariaLabel={t('results.detail.contextLabel')}
            items={[
              {
                id: 'run',
                label: t('results.detail.context.run'),
                value: formatRunLabel(timestamp),
                detail: timestamp ?? '—',
              },
              {
                id: 'project',
                label: t('results.detail.context.project'),
                value: projectId ?? '—',
              },
            ]}
          />
        )}
      />

      {error ? <OperationsErrorBanner error={error} /> : null}

      <MetricStrip
        ariaLabel={t('results.detail.metricsLabel')}
        items={[
          {
            id: 'shortlist',
            label: t('results.detail.metric.shortlist'),
            value: results.length,
            detail: t('results.detail.metric.candidates'),
          },
          {
            id: 'qualified',
            label: t('results.detail.metric.qualified'),
            value: qualifiedPoolResults.length,
            detail: t('results.detail.metric.candidates'),
          },
          {
            id: 'average',
            label: t('results.detail.metric.averageScore'),
            value: `${(averageScore * 100).toFixed(1)}%`,
          },
          {
            id: 'evidence',
            label: t('results.detail.metric.evidenceCoverage'),
            value: `${evidenceCount}/${results.length}`,
            detail: t('results.detail.metric.withEvidence'),
          },
        ]}
      />

      <Tabs
        value={viewMode}
        activationMode="manual"
        onValueChange={(value) => setSearchParams((current) => {
          const next = new URLSearchParams(current);
          if (value === 'matrix') next.set('view', 'matrix');
          else next.delete('view');
          return next;
        })}
        className="min-w-0 space-y-6"
      >
        <div className="max-w-full overflow-x-auto pb-1">
          <TabsList
            aria-label={t('results.detail.tabsLabel')}
            className="grid h-auto w-full grid-cols-2 gap-px rounded-none border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-border)] p-0 sm:w-[32rem]"
          >
            <TabsTrigger
              value="detail"
              className="min-h-12 rounded-none bg-[var(--brain-ops-surface)] px-4 py-3 text-left data-[state=active]:bg-[var(--brain-ops-accent-soft)] data-[state=active]:shadow-[inset_0_-2px_0_var(--brain-ops-accent)]"
            >
              {t('results.detail.tab.detail')}
            </TabsTrigger>
            <TabsTrigger
              value="matrix"
              className="min-h-12 rounded-none bg-[var(--brain-ops-surface)] px-4 py-3 text-left data-[state=active]:bg-[var(--brain-ops-accent-soft)] data-[state=active]:shadow-[inset_0_-2px_0_var(--brain-ops-accent)]"
            >
              {t('results.detail.tab.matrix')}
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="detail" className="min-w-0">
          <Section
            title={t('results.detail.shortlist.title')}
            description={t('results.detail.shortlist.description')}
            divided={false}
          >
            {results.length === 0 ? (
              <SystemState
                kind={error ? 'error' : 'empty'}
                title={t('results.detail.empty.title')}
                description={t('results.detail.empty.description')}
                indicator={<SearchCheck className="size-5" />}
              />
            ) : (
              <div className="min-w-0 border-y border-[color:var(--brain-ops-border)]">
                <p className="border-b border-[color:var(--brain-ops-border)] px-4 py-2 text-xs text-[var(--brain-ops-text-muted)] lg:hidden">
                  {t('common.horizontalScrollHint')}
                </p>
                <div className="overflow-x-auto">
                  <Table className="min-w-[58rem]">
                    <TableHeader>
                      <TableRow className="border-[color:var(--brain-ops-border)] hover:bg-transparent">
                        <TableHead className="w-12"><span className="sr-only">{t('results.detail.table.expand')}</span></TableHead>
                        <TableHead>{t('results.detail.table.rank')}</TableHead>
                        <TableHead>{t('results.detail.table.resume')}</TableHead>
                        <TableHead className="w-20">{t('results.detail.table.original')}</TableHead>
                        <TableHead>{t('results.detail.table.finalScore')}</TableHead>
                        <TableHead>{t('results.detail.table.baseScore')}</TableHead>
                        <TableHead>{t('results.detail.table.niceHaveBonus')}</TableHead>
                        <TableHead>{t('results.detail.table.quality')}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {results.map((result, index) => {
                        const isRerankFallback = result.commentaire_scoring?.includes('⚠️ Re-ranking LLM indisponible');
                        const displayName = result.candidate_name || result.cv;
                        const isExpanded = expandedRows.has(result.cv);
                        const hasProof = Boolean(
                          result.evidences?.length
                          || result.flags?.gappes?.length
                          || result.flags?.overlaps?.length
                        );

                        return (
                          <Fragment key={result.cv}>
                            <TableRow
                              className="cursor-pointer border-[color:var(--brain-ops-border)] hover:bg-[var(--brain-ops-surface-muted)]"
                              onClick={() => toggleRowExpansion(result.cv)}
                            >
                              <TableCell>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon"
                                  className="size-8"
                                  aria-expanded={isExpanded}
                                  aria-label={formatMessage(
                                    t(isExpanded
                                      ? 'results.detail.collapseCandidate'
                                      : 'results.detail.expandCandidate'),
                                    { candidate: displayName }
                                  )}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    toggleRowExpansion(result.cv);
                                  }}
                                >
                                  {isExpanded
                                    ? <ChevronDown className="size-4" />
                                    : <ChevronRight className="size-4" />}
                                </Button>
                              </TableCell>
                              <TableCell className="font-semibold tabular-nums">{index + 1}</TableCell>
                              <TableCell>
                                <div className="flex items-center gap-2">
                                  <span className="font-medium">{displayName}</span>
                                  {isRerankFallback ? (
                                    <Badge
                                      variant="outline"
                                      className="border-[color:var(--brain-ops-warning)] text-[var(--brain-ops-warning)]"
                                    >
                                      {t('results.detail.fallback')}
                                    </Badge>
                                  ) : null}
                                </div>
                                <span className="mt-1 block text-xs text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                                  {result.cv}
                                </span>
                              </TableCell>
                              <TableCell onClick={(event) => event.stopPropagation()}>
                                {result.original_cv_url ? (
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    className="size-8"
                                    title={formatMessage(t('results.detail.downloadOriginal'), { candidate: displayName })}
                                    aria-label={formatMessage(t('results.detail.downloadOriginal'), { candidate: displayName })}
                                    onClick={() => handleDownloadOriginalCv(result)}
                                  >
                                    <FileText className="size-4" />
                                  </Button>
                                ) : <span className="text-[var(--brain-ops-text-muted)]">—</span>}
                              </TableCell>
                              <TableCell className="tabular-nums">
                                <span className={getScoreColor(result.score_final * 100)}>
                                  {(result.score_final * 100).toFixed(1)}%
                                </span>
                              </TableCell>
                              <TableCell className="tabular-nums">{(result.score_base * 100).toFixed(1)}%</TableCell>
                              <TableCell className="tabular-nums">{result.bonus_nice_have_multiplicateur.toFixed(2)}×</TableCell>
                              <TableCell className="tabular-nums">{result.coefficient_qualite_experience.toFixed(2)}×</TableCell>
                            </TableRow>

                            {isExpanded ? (
                              <TableRow className="border-[color:var(--brain-ops-border)] hover:bg-transparent">
                                <TableCell colSpan={8} className="bg-[var(--brain-ops-surface-muted)] p-0">
                                  <div className="grid gap-px bg-[var(--brain-ops-border)] lg:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)]">
                                    <section className="min-w-0 bg-[var(--brain-ops-surface)] p-5 sm:p-6" aria-labelledby={`decision-${index}`}>
                                      <h3 id={`decision-${index}`} className="text-lg font-semibold">
                                        {t('results.detail.decisionDossier')}
                                      </h3>

                                      <div className="mt-5 border-y border-[color:var(--brain-ops-border)] py-4">
                                        <p className="text-xs font-medium uppercase tracking-[0.1em] text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
                                          {t('results.detail.calculationFormula')}
                                        </p>
                                        <p className="mt-2 overflow-x-auto text-sm tabular-nums [font-family:var(--brain-ops-font-command)]">
                                          {t('results.detail.finalScore')} = {result.score_base.toFixed(3)} × {result.bonus_nice_have_multiplicateur.toFixed(2)} × {result.coefficient_qualite_experience.toFixed(2)} = {result.score_final.toFixed(3)}
                                        </p>
                                      </div>

                                      {result.nice_have_manquants?.length ? (
                                        <div className="mt-5">
                                          <h4 className="text-sm font-semibold">{t('results.detail.missingNiceHave')}</h4>
                                          <div className="mt-2 flex flex-wrap gap-2">
                                            {result.nice_have_manquants.map((niceToHave) => (
                                              <Badge key={niceToHave} variant="outline">{niceToHave}</Badge>
                                            ))}
                                          </div>
                                        </div>
                                      ) : null}

                                      {result.commentaire_scoring ? (
                                        <div className="mt-5">
                                          <h4 className="text-sm font-semibold">{t('results.detail.scoringCommentary')}</h4>
                                          <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[var(--brain-ops-text-muted)]">
                                            {renderTextWithEvidences(result.commentaire_scoring, result.evidences)}
                                          </div>
                                        </div>
                                      ) : null}

                                      {result.appreciation_globale ? (
                                        <div className="mt-5">
                                          <h4 className="text-sm font-semibold">{t('results.detail.hrAppreciation')}</h4>
                                          <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[var(--brain-ops-text-muted)]">
                                            {renderTextWithEvidences(
                                              result.appreciation_globale.startsWith(displayName)
                                                ? result.appreciation_globale
                                                : `${displayName} — ${result.appreciation_globale}`,
                                              result.evidences
                                            )}
                                          </div>
                                        </div>
                                      ) : null}

                                      {projectId && timestamp ? (
                                        <div
                                          role="group"
                                          aria-label={t('results.detail.interviewActions')}
                                          className="mt-6 flex flex-wrap gap-2 border-t border-[color:var(--brain-ops-border)] pt-5"
                                        >
                                          <SchedulerButton
                                            candidateId={result.cv}
                                            jobId={projectId}
                                            matchingId={timestamp}
                                            candidateName={displayName}
                                            candidateEmail={sheetsByCandidate[result.cv]?.data.identite?.email || null}
                                            existingSheetId={sheetsByCandidate[result.cv]?.id}
                                            initialData={{
                                              scheduled_at: sheetsByCandidate[result.cv]?.scheduled_at,
                                              end_at: sheetsByCandidate[result.cv]?.data.scheduling?.end_at,
                                              location: sheetsByCandidate[result.cv]?.location,
                                              scheduler_notes: sheetsByCandidate[result.cv]?.scheduler_notes,
                                              interviewer: sheetsByCandidate[result.cv]?.interviewer,
                                              appointment_id: sheetsByCandidate[result.cv]?.data.scheduling?.appointment_id,
                                            }}
                                            onUpdate={async () => {
                                              try {
                                                const res = await interviewSheetApi.listAll({ job_id: projectId });
                                                const map: Record<string, InterviewSheet> = {};
                                                res.sheets.forEach((sheet) => { map[sheet.candidate_id] = sheet; });
                                                setSheetsByCandidate(map);
                                              } catch (err) {
                                                console.error(err);
                                              }
                                            }}
                                            variant="outline"
                                            size="sm"
                                          />
                                          <InterviewSheetButton
                                            candidateId={result.cv}
                                            jobId={projectId}
                                            matchingId={timestamp}
                                            variant="default"
                                            size="sm"
                                          />
                                          <RealtimeInterviewButton
                                            projectId={projectId}
                                            candidateId={result.cv}
                                            matchingId={timestamp}
                                            interviewSheetId={sheetsByCandidate[result.cv]?.id}
                                            source="matching-detail"
                                            candidateName={displayName}
                                            candidateEmail={sheetsByCandidate[result.cv]?.data.identite?.email || null}
                                          />
                                        </div>
                                      ) : null}

                                      {isRerankFallback ? (
                                        <SystemState
                                          kind="warning"
                                          className="mt-5"
                                          title={t('results.detail.fallbackNoteTitle')}
                                          description={t('results.detail.fallbackNote')}
                                        />
                                      ) : null}
                                    </section>

                                    <aside className="min-w-0 bg-[var(--brain-ops-surface)] p-5 sm:p-6" aria-labelledby={`proof-${index}`}>
                                      <h3 id={`proof-${index}`} className="text-lg font-semibold">
                                        {t('results.detail.missionSplit')}
                                      </h3>
                                      <p className="mt-2 text-sm leading-6 text-[var(--brain-ops-text-muted)]">
                                        {t('results.detail.missionSplitDescription')}
                                      </p>
                                      {hasProof ? (
                                        <div className="mt-5 space-y-6">
                                          {result.flags?.gappes?.length || result.flags?.overlaps?.length ? (
                                            <div>
                                              <h4 className="flex items-center gap-2 text-sm font-semibold">
                                                <AlertCircle className="size-4 text-[var(--brain-ops-warning)]" />
                                                {t('results.detail.vigilanceFlags')}
                                              </h4>

                                              {result.flags?.gappes?.length ? (
                                                <div className="mt-3 border-l-2 border-[color:var(--brain-ops-danger)] pl-4">
                                                  <p className="flex items-center gap-2 text-sm font-semibold">
                                                    <Clock className="size-4 text-[var(--brain-ops-danger)]" />
                                                    {formatMessage(t('results.detail.gapsDetected'), {
                                                      count: result.flags.gappes.length,
                                                    })}
                                                  </p>
                                                  <ul className="mt-3 space-y-3">
                                                    {result.flags.gappes.map((gap, gapIndex) => (
                                                      <li key={`${gap.period}-${gapIndex}`} className="text-sm leading-5">
                                                        <Badge variant="outline">
                                                          {gap.duration_months} {t('results.detail.months')}
                                                        </Badge>
                                                        <p className="mt-2">{gap.period}</p>
                                                        <p className="text-xs text-[var(--brain-ops-text-muted)]">
                                                          {t('results.detail.between')} {gap.between}
                                                        </p>
                                                      </li>
                                                    ))}
                                                  </ul>
                                                </div>
                                              ) : null}

                                              {result.flags?.overlaps?.length ? (
                                                <div className="mt-4 border-l-2 border-[color:var(--brain-ops-warning)] pl-4">
                                                  <p className="flex items-center gap-2 text-sm font-semibold">
                                                    <AlertTriangle className="size-4 text-[var(--brain-ops-warning)]" />
                                                    {formatMessage(t('results.detail.overlapsDetected'), {
                                                      count: result.flags.overlaps.length,
                                                    })}
                                                  </p>
                                                  <ul className="mt-3 space-y-3">
                                                    {result.flags.overlaps.map((overlap, overlapIndex) => (
                                                      <li key={`${overlap.overlap_period}-${overlapIndex}`} className="text-sm leading-5">
                                                        <div className="flex flex-wrap items-center gap-2">
                                                          <Badge variant="outline">
                                                            {overlap.overlap_days} {t('results.detail.days')}
                                                          </Badge>
                                                          {overlap.same_company ? (
                                                            <span className="text-xs text-[var(--brain-ops-text-muted)]">
                                                              {t('results.detail.sameCompany')}
                                                            </span>
                                                          ) : null}
                                                        </div>
                                                        <p className="mt-2">{overlap.overlap_period}</p>
                                                        <p className="text-xs text-[var(--brain-ops-text-muted)]">
                                                          {overlap.experiences}
                                                        </p>
                                                      </li>
                                                    ))}
                                                  </ul>
                                                </div>
                                              ) : null}
                                            </div>
                                          ) : null}

                                          {result.evidences?.length ? (
                                            <div>
                                              <h4 className="text-sm font-semibold">
                                                {t('results.detail.supportingEvidence')}
                                              </h4>
                                              <ol className="mt-3 border-y border-[color:var(--brain-ops-border)]">
                                                {result.evidences.map((evidence) => (
                                                  <li
                                                    key={evidence.id}
                                                    className="grid gap-1 border-b border-[color:var(--brain-ops-border)] py-3 last:border-b-0"
                                                  >
                                                    <div className="flex flex-wrap items-center gap-2 text-xs [font-family:var(--brain-ops-font-command)]">
                                                      <span>[{evidence.id}]</span>
                                                      <span className="uppercase text-[var(--brain-ops-text-muted)]">
                                                        {evidence.type}
                                                      </span>
                                                    </div>
                                                    <p className="break-words text-sm leading-5">{evidence.ref}</p>
                                                  </li>
                                                ))}
                                              </ol>
                                            </div>
                                          ) : null}
                                        </div>
                                      ) : (
                                        <SystemState
                                          kind="empty"
                                          className="mt-5"
                                          title={t('results.detail.proofUnavailableTitle')}
                                          description={t('results.detail.proofUnavailableDescription')}
                                        />
                                      )}
                                    </aside>
                                  </div>
                                </TableCell>
                              </TableRow>
                            ) : null}
                          </Fragment>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}
          </Section>
        </TabsContent>

        <TabsContent value="matrix" className="min-w-0">
          <Section
            title={t('results.detail.matrix.title')}
            description={t('results.detail.matrix.description')}
            divided={false}
          >
            <MatchingResultsMatrix
              columns={matrixColumns}
              shortlistRows={shortlistMatrixRows}
              qualifiedRows={qualifiedPoolRows}
              metadata={matchingResponse?.metadata ?? null}
            />
          </Section>
        </TabsContent>
      </Tabs>
    </PageFrame>
  );
};
