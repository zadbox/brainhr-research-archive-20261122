import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowRight, Save, Sparkles, Loader2, CheckCircle, Plus, X } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Select } from '../components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import {
  ChoiceTarget,
  ContextStrip,
  MetricStrip,
  OperationsErrorBanner,
  PageBackButton,
  PageFrame,
  PageHeader,
  Section,
  SystemState,
} from '../components/operations';
import { offresApi } from '../api/offres';
import { projectsApi } from '../api/projects';
import type {
  Offre,
  APIError,
  Project,
  EnrichmentResult,
  EnrichmentSelections,
  QuestionResponses,
} from '../api/types';
import { useToast } from '../hooks/useToast';
import { useI18n } from '../i18n/useI18n';
import { DisclosureSection } from '../components/operations/DisclosureSection';

type CriteriaClassification = 'N/A' | 'Must-have' | 'Nice-to-have';

interface CriteriaItem {
  text: string;
  source: 'ia' | 'manual';
  classification: CriteriaClassification;
}

type OfferTextOrigin = 'empty' | 'explicit' | 'derived' | 'manual';

const flexibleButtonClassName = 'h-auto min-h-9 max-w-full whitespace-normal text-center';
const flexibleSmallButtonClassName = 'h-auto min-h-8 max-w-full whitespace-normal text-center';
const flexibleLargeButtonClassName = 'h-auto min-h-10 max-w-full whitespace-normal text-center';

function collectOfferTextFragments(value: unknown): string[] {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed ? [trimmed] : [];
  }

  if (Array.isArray(value)) {
    return value.flatMap((item) => collectOfferTextFragments(item));
  }

  if (value && typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).flatMap((item) => collectOfferTextFragments(item));
  }

  return [];
}

function getExplicitOfferSourceText(
  offreData: Offre | null,
  draftText: string,
  draftOrigin: OfferTextOrigin
): string {
  const draft = draftText.trim();
  if (draft && draftOrigin !== 'derived') {
    return draftText;
  }

  const stored = offreData?.source_text?.trim();
  if (stored) {
    return offreData?.source_text || '';
  }

  return '';
}

function getOfferAnalysisText(
  offreData: Offre | null,
  draftText: string,
  draftOrigin: OfferTextOrigin
): string {
  const explicit = getExplicitOfferSourceText(offreData, draftText, draftOrigin);
  if (explicit) {
    return explicit;
  }

  const draft = draftText.trim();
  if (draft) {
    return draftText;
  }

  const sectionText = offreData ? collectOfferTextFragments(offreData.sections).join('\n') : '';
  return sectionText;
}

function buildOfferPayload(
  offreData: Offre,
  criteriaList: CriteriaItem[],
  sourceText: string,
  sourceFileName?: string | null
): Offre {
  const mustHave = criteriaList
    .filter((c) => c.classification === 'Must-have')
    .map((c) => c.text);
  const niceHave = criteriaList
    .filter((c) => c.classification === 'Nice-to-have')
    .map((c) => c.text);

  return {
    ...offreData,
    must_have: mustHave,
    nice_have: niceHave,
    source_text: sourceText || offreData.source_text || undefined,
    source_file_name: sourceFileName ?? offreData.source_file_name ?? null,
  };
}

export const OffrePage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { success, error: showError } = useToast();
  const { t } = useI18n();
  const showErrorRef = useRef(showError);
  const tRef = useRef(t);
  const offerOperationInFlightRef = useRef(false);

  useEffect(() => {
    showErrorRef.current = showError;
  }, [showError]);

  useEffect(() => {
    tRef.current = t;
  }, [t]);

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<APIError | null>(null);

  // === SECTION 1: Préparer l'offre ===
  const [inputMethod, setInputMethod] = useState<'text' | 'file'>('text');
  const [offreText, setOffreText] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [parsing, setParsing] = useState(false);
  const [offerTextOrigin, setOfferTextOrigin] = useState<OfferTextOrigin>('empty');

  // Offre parsée
  const [offreData, setOffreData] = useState<Offre | null>(null);

  // === SECTION 2: Enrichissement ===
  const [enriching, setEnriching] = useState(false);
  const [enrichmentResult, setEnrichmentResult] = useState<EnrichmentResult | null>(null);
  const [selections, setSelections] = useState<EnrichmentSelections>({
    competences: [],
    outils: [],
    langages: [],
    certifications: [],
    missions: [],
  });
  const [questionResponses, setQuestionResponses] = useState<QuestionResponses>({});

  // === SECTION 3: Critères Must-have/Nice-have ===
  const [extractingCriteria, setExtractingCriteria] = useState(false);
  const [criteriaList, setCriteriaList] = useState<CriteriaItem[]>([]);
  const [criteriaInitialized, setCriteriaInitialized] = useState(false);
  const [manualCriteriaText, setManualCriteriaText] = useState('');

  const fetchData = useCallback(async () => {
    if (!projectId) return;

    try {
      setLoading(true);
      setError(null);

      const projectData = await projectsApi.getById(projectId);
      setProject(projectData);

      // Charger offre existante si disponible
      try {
        const existingOffre = await offresApi.getByProject(projectId);
        setOffreData(existingOffre);
        const existingSourceText = getExplicitOfferSourceText(existingOffre, '', 'empty');
        if (existingSourceText) {
          setOffreText(existingSourceText);
          setOfferTextOrigin('explicit');
          setInputMethod('text');
        } else {
          const derivedSourceText = getOfferAnalysisText(existingOffre, '', 'empty');
          if (derivedSourceText) {
            setOffreText(derivedSourceText);
            setOfferTextOrigin('derived');
            setInputMethod('text');
          }
        }
      } catch {
        // Pas d'offre existante
      }
    } catch (err) {
      setError(err as APIError);
      showErrorRef.current(tRef.current('common.error'), tRef.current('offer.error.loadProject'));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;
    fetchData();
  }, [projectId, fetchData]);

  // Hydrater criteriaList depuis l'offre chargée (must_have / nice_have)
  useEffect(() => {
    if (!offreData || criteriaInitialized) return;

    const fromMust = (offreData.must_have || []).map((text) => ({
      text,
      source: 'manual' as const,
      classification: 'Must-have' as CriteriaClassification,
    }));

    const fromNice = (offreData.nice_have || []).map((text) => ({
      text,
      source: 'manual' as const,
      classification: 'Nice-to-have' as CriteriaClassification,
    }));

    setCriteriaList([...fromMust, ...fromNice]);
    setCriteriaInitialized(true);
  }, [offreData, criteriaInitialized]);

  // === HANDLERS SECTION 1 ===
  const handleParseOffre = async () => {
    if (!projectId || offerOperationInFlightRef.current) return;

    if (inputMethod === 'text' && !offreText.trim()) {
      showError(t('common.error'), t('offer.error.enterText'));
      return;
    }

    if (inputMethod === 'file' && !selectedFile) {
      showError(t('common.error'), t('offer.error.selectFile'));
      return;
    }

    offerOperationInFlightRef.current = true;
    setParsing(true);
    try {
      let parsed;

      if (inputMethod === 'text') {
        parsed = await offresApi.parseText(projectId, offreText);
      } else {
        parsed = await offresApi.parseFile(projectId, selectedFile!);
      }

      setOffreData(parsed);
      const parsedSourceText = getExplicitOfferSourceText(parsed, '', 'empty');
      if (parsedSourceText) {
        setOffreText(parsedSourceText);
        setOfferTextOrigin('explicit');
        setInputMethod('text');
      }
      setEnrichmentResult(null);
      setSelections({
        competences: [],
        outils: [],
        langages: [],
        certifications: [],
        missions: [],
      });
      setQuestionResponses({});
      setCriteriaInitialized(false);
      success(t('offer.success.parsedTitle'));
    } catch (err) {
      setError(err as APIError);
      showError(t('common.error'), t('offer.error.parse'));
    } finally {
      offerOperationInFlightRef.current = false;
      setParsing(false);
    }
  };

  // === HANDLERS SECTION 2 ===
  const handleEnrichWithAI = async () => {
    if (!projectId) {
      showError(t('common.error'), t('projectDetail.notFound'));
      return;
    }
    if (offerOperationInFlightRef.current) return;

    // Utiliser description existante OU le texte saisi
    const descriptionToEnrich = getOfferAnalysisText(offreData, offreText, offerTextOrigin) || offreData?.sections?.description || '';

    if (!descriptionToEnrich) {
      showError(t('common.error'), t('offer.error.prepareFirst'));
      return;
    }

    offerOperationInFlightRef.current = true;
    setEnriching(true);
    try {
      const result = await offresApi.enrich(projectId, descriptionToEnrich);
      setEnrichmentResult(result);
      setSelections({
        competences: [],
        outils: [],
        langages: [],
        certifications: [],
        missions: [],
      });
      setQuestionResponses({});
      success(t('offer.success.enrichedTitle'), `${t('offer.coverageScore')}: ${result.coverage_score}%`);
    } catch (err) {
      setError(err as APIError);
      showError(t('common.error'), t('offer.error.enrich'));
    } finally {
      offerOperationInFlightRef.current = false;
      setEnriching(false);
    }
  };

  const toggleSelection = (category: keyof EnrichmentSelections, index: number) => {
    setSelections((prev) => {
      const current = prev[category];
      const next = current.includes(index)
        ? current.filter((i) => i !== index)
        : [...current, index];
      return {
        ...prev,
        [category]: next,
      };
    });
  };

  const handleApplyEnrichment = async () => {
    if (!projectId || !offreData || !enrichmentResult) return;

    try {
      // Calculer le nombre total d'éléments sélectionnés
      const totalSelected =
        selections.competences.length +
        selections.outils.length +
        selections.langages.length +
        selections.certifications.length +
        selections.missions.length +
        Object.keys(questionResponses).filter((k) => questionResponses[k]?.trim()).length;

      const payload = {
        offre: buildOfferPayload(
          offreData,
          criteriaList,
          getExplicitOfferSourceText(offreData, offreText, offerTextOrigin),
          offreData.source_file_name
        ),
        enrichment: enrichmentResult,
        selections,
        question_responses: questionResponses,
      };

      const enriched = await offresApi.applyEnrichment(projectId, payload as Record<string, unknown>);

      setOffreData(enriched);
      setCriteriaInitialized(false);
      setEnrichmentResult(null);
      success(
        t('offer.success.appliedTitle'),
        `${totalSelected} ${totalSelected > 1 ? t('offer.success.itemsAdded') : t('offer.success.itemAdded')}`
      );
    } catch (err) {
      setError(err as APIError);
      showError(t('common.error'), t('offer.error.apply'));
    }
  };

  // === HANDLERS SECTION 3 ===
  const handleExtractCriteria = async () => {
    const sourceText = getOfferAnalysisText(offreData, offreText, offerTextOrigin);
    if (!projectId || !sourceText) {
      showError(t('common.error'), t('offer.error.enterFirst'));
      return;
    }

    setExtractingCriteria(true);
    try {
      const result = await offresApi.extractCriteria(projectId, sourceText);

      const newCriteria: CriteriaItem[] = result.criteria.map((text: string) => ({
        text,
        source: 'ia' as const,
        classification: 'N/A' as CriteriaClassification,
      }));

      setCriteriaList((prev) => [...prev, ...newCriteria]);
      success(t('offer.success.criteriaExtractedTitle'), `${result.count} ${t('offer.success.criteriaFound')}`);
    } catch (err) {
      setError(err as APIError);
      showError(t('common.error'), t('offer.error.extract'));
    } finally {
      setExtractingCriteria(false);
    }
  };

  const handleAddManualCriteria = () => {
    if (!manualCriteriaText.trim()) return;

    const lines = manualCriteriaText.split('\n').filter((line) => line.trim());
    const newCriteria: CriteriaItem[] = lines.map((text) => ({
      text: text.trim(),
      source: 'manual' as const,
      classification: 'Must-have' as CriteriaClassification,
    }));

    setCriteriaList((prev) => [...prev, ...newCriteria]);
    setManualCriteriaText('');
    success(t('offer.success.criteriaAddedTitle'), `${lines.length} ${t('offer.success.criteriaAdded')}`);
  };

  const updateCriteriaClassification = (index: number, classification: CriteriaClassification) => {
    setCriteriaList((prev) => {
      const newList = [...prev];
      newList[index] = { ...newList[index], classification };
      return newList;
    });
  };

  const removeCriteria = (index: number) => {
    setCriteriaList((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSave = async () => {
    if (!projectId || !offreData) return;

    const finalOffre = buildOfferPayload(
      offreData,
      criteriaList,
      getExplicitOfferSourceText(offreData, offreText, offerTextOrigin),
      offreData.source_file_name
    );

    setSaving(true);
    try {
      await offresApi.upsert(projectId, finalOffre);
      success(t('offer.success.savedTitle'));
      return true;
    } catch (err) {
      setError(err as APIError);
      showError(t('common.error'), t('offer.error.save'));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handleSaveAndNext = async () => {
    const saved = await handleSave();
    if (saved) {
      navigate(`/projects/${projectId}/cvs`);
    }
  };

  if (loading) {
    return (
      <PageFrame width="content">
        <SystemState
          kind="loading"
          title={t('offer.loading')}
          indicator={<Loader2 className="h-5 w-5 animate-spin motion-reduce:animate-none" />}
        />
      </PageFrame>
    );
  }

  const mustHaveCount = criteriaList.filter((c) => c.classification === 'Must-have').length;
  const niceHaveCount = criteriaList.filter((c) => c.classification === 'Nice-to-have').length;
  const offerReadyForEnrichment = Boolean(offreData);
  const selectedEnrichmentCount =
    selections.competences.length +
    selections.outils.length +
    selections.langages.length +
    selections.certifications.length +
    selections.missions.length +
    Object.values(questionResponses).filter((response) => response?.trim()).length;
  const enrichmentProposalCount = enrichmentResult
    ? enrichmentResult.propositions.competences.length
      + enrichmentResult.propositions.outils.length
      + enrichmentResult.propositions.langages.length
      + enrichmentResult.propositions.certifications.length
      + enrichmentResult.propositions.missions.length
      + enrichmentResult.propositions.questions_clarification.length
    : 0;

  const coverageDetail = enrichmentResult
    ? enrichmentResult.coverage_score >= 90
      ? t('offer.coverage.veryComplete')
      : enrichmentResult.coverage_score >= 70
        ? t('offer.coverage.correct')
        : enrichmentResult.coverage_score >= 50
          ? t('offer.coverage.incomplete')
          : t('offer.coverage.veryIncomplete')
    : null;

  return (
    <PageFrame width="content" contentClassName="max-w-[60rem] pb-8">
      <PageHeader
        eyebrow={t('offer.breadcrumb')}
        backAction={(
          <PageBackButton
            onClick={() => navigate(`/projects/${projectId}`)}
            aria-label={t('common.back')}
          />
        )}
        title={offreData?.sections.titre || t('offer.newOffer')}
        actionsLabel={t('offer.breadcrumb')}
        actions={
          <Button
            type="button"
            onClick={handleSave}
            disabled={saving || !offreData}
            className={flexibleButtonClassName}
          >
            <Save data-icon="inline-start" className="h-4 w-4" />
            {saving ? t('common.saving') : t('common.save')}
          </Button>
        }
        context={
          <ContextStrip
            ariaLabel={t('offer.breadcrumb')}
            items={[
              {
                id: 'project',
                label: t('common.project'),
                value: project?.nom || t('common.notSpecified'),
              },
              {
                id: 'offer-state',
                label: t('offer.breadcrumb'),
                value: error
                  ? t('common.error')
                  : offreData
                    ? t('common.ready')
                    : t('common.draft'),
              },
            ]}
          />
        }
      />

      {error && <OperationsErrorBanner error={error} />}

      <Section data-tour="offer-source" title={t('offer.section.prepare')} divided={false}>
        <Tabs
          value={inputMethod}
          onValueChange={(value) => setInputMethod(value as 'text' | 'file')}
          className="space-y-5"
        >
          <TabsList className="h-auto w-full justify-start gap-1 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)] p-1 sm:w-auto">
            <TabsTrigger
              value="text"
              className="min-h-9 flex-1 rounded-[var(--brain-ops-radius-structural)] px-4 py-2 data-[state=active]:bg-[var(--brain-ops-surface)] data-[state=active]:shadow-none sm:flex-none"
            >
              {t('offer.input.textTab')}
            </TabsTrigger>
            <TabsTrigger
              value="file"
              className="min-h-9 flex-1 rounded-[var(--brain-ops-radius-structural)] px-4 py-2 data-[state=active]:bg-[var(--brain-ops-surface)] data-[state=active]:shadow-none sm:flex-none"
            >
              {t('offer.input.fileTab')}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="text" className="mt-0 space-y-2">
            <div className="space-y-2">
              <Label htmlFor="offer-source-text">{t('offer.input.text')}</Label>
              {offreData?.source_file_name ? (
                <p className="break-all text-sm text-[var(--brain-ops-text-muted)]">
                  {t('offer.sourceFile')}: {offreData.source_file_name}
                </p>
              ) : null}
              <Textarea
                id="offer-source-text"
                value={offreText}
                onChange={(e) => {
                  setOffreText(e.target.value);
                  setOfferTextOrigin('manual');
                }}
                placeholder={t('offer.input.textPlaceholder')}
                rows={12}
                className="min-h-64 resize-y"
              />
            </div>
          </TabsContent>

          <TabsContent value="file" className="mt-0 space-y-2">
            <div className="space-y-2">
              <Label htmlFor="offer-source-file">{t('offer.input.file')}</Label>
              <Input
                id="offer-source-file"
                type="file"
                accept=".pdf,.docx"
                onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
              />
              {selectedFile && (
                <p className="break-all text-sm text-[var(--brain-ops-text-muted)]">
                  {t('offer.selectedFile')}: {selectedFile.name}
                </p>
              )}
            </div>
          </TabsContent>

          <Button
            type="button"
            onClick={handleParseOffre}
            disabled={parsing || enriching}
            className={`${flexibleButtonClassName} w-full sm:w-auto`}
          >
            {parsing ? (
              <>
                <Loader2 data-icon="inline-start" className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                {t('offer.analyzing')}
              </>
            ) : (
              t(inputMethod === 'text' ? 'offer.action.analyzeText' : 'offer.action.analyzeFile')
            )}
          </Button>
        </Tabs>
      </Section>

      <DisclosureSection
        data-tour="offer-enrichment"
        title={t('offer.section.enrich')}
        titleClassName="text-xl leading-tight tracking-[-0.01em] sm:text-2xl"
        description={t('offer.section.enrichDescription')}
        metadata={enrichmentResult
          ? `${t('offer.ai.proposals')}: ${enrichmentProposalCount}`
          : undefined}
      >
          <div className="space-y-6">
            <div className="border-l-2 border-[color:var(--brain-ops-border)] pl-4">
              <div className="flex max-w-2xl flex-col items-start gap-3">
                <h3 className="text-sm font-semibold leading-5">{t('offer.ai.title')}</h3>
                <p
                  id="offer-ai-enrichment-help"
                  className="text-xs leading-5 text-[var(--brain-ops-text-muted)]"
                >
                  {offerReadyForEnrichment
                    ? t('offer.ai.readyDescription')
                    : t('offer.ai.lockedDescription')}
                </p>
                <Button
                  type="button"
                  onClick={handleEnrichWithAI}
                  disabled={enriching || parsing || !offerReadyForEnrichment}
                  aria-describedby="offer-ai-enrichment-help"
                  className={`${flexibleButtonClassName} w-full sm:w-auto`}
                >
                  {enriching ? (
                    <>
                      <Loader2 data-icon="inline-start" className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                      {t('offer.analyzing')}
                    </>
                  ) : (
                    <>
                      <Sparkles data-icon="inline-start" className="h-4 w-4" />
                      {t('offer.ai.action')}
                    </>
                  )}
                </Button>
              </div>
            </div>

            {enrichmentResult && coverageDetail && (
              <div className="space-y-5 border-t border-[color:var(--brain-ops-border)] pt-6">
                <MetricStrip
                  ariaLabel={t('offer.ai.proposals')}
                  items={[
                    {
                      id: 'coverage',
                      label: t('offer.coverageCurrent'),
                      value: `${enrichmentResult.coverage_score}%`,
                      detail: coverageDetail,
                      tone: 'accent',
                    },
                  ]}
                />

                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <h3 className="text-lg font-semibold">{t('offer.ai.proposals')}</h3>
                  <Button
                    type="button"
                    onClick={handleApplyEnrichment}
                    disabled={selectedEnrichmentCount === 0}
                    aria-describedby="offer-ai-apply-help"
                    className={flexibleButtonClassName}
                  >
                    <CheckCircle data-icon="inline-start" className="h-4 w-4" />
                    {t('offer.ai.applyAction')} ({selectedEnrichmentCount})
                  </Button>
                </div>

                <p
                  id="offer-ai-apply-help"
                  className="text-xs leading-5 text-[var(--brain-ops-text-muted)]"
                >
                  {t('offer.ai.applyDescription')}
                </p>

                <div className="grid max-h-[32rem] gap-6 overflow-y-auto pr-1 sm:pr-2">
                  {enrichmentResult.propositions.competences.length > 0 && (
                    <div className="space-y-2">
                      <h4 className="text-sm font-semibold">{t('offer.category.skills')}</h4>
                      {enrichmentResult.propositions.competences.map((comp, idx) => (
                        <ChoiceTarget
                          key={idx}
                          className="flex w-full cursor-pointer items-start border-t border-[color:var(--brain-ops-border)] px-1 py-3 transition-colors hover:bg-[var(--brain-ops-surface-muted)] motion-reduce:transition-none"
                        >
                          <input
                            type="checkbox"
                            checked={selections.competences.includes(idx)}
                            onChange={() => toggleSelection('competences', idx)}
                            className="mt-1"
                          />
                          <span className="min-w-0 flex-1 text-sm">
                            <span className="font-medium">{comp.name}</span>
                            <span className="ml-2 text-xs text-[var(--brain-ops-text-muted)]">({comp.type})</span>
                            <span className="mt-1 block text-xs leading-5 text-[var(--brain-ops-text-muted)]">{comp.rationale}</span>
                          </span>
                        </ChoiceTarget>
                      ))}
                    </div>
                  )}

                  {enrichmentResult.propositions.outils.length > 0 && (
                    <div className="space-y-2">
                      <h4 className="text-sm font-semibold">{t('offer.category.tools')}</h4>
                      {enrichmentResult.propositions.outils.map((outil, idx) => (
                        <ChoiceTarget
                          key={idx}
                          className="flex w-full cursor-pointer items-start border-t border-[color:var(--brain-ops-border)] px-1 py-3 transition-colors hover:bg-[var(--brain-ops-surface-muted)] motion-reduce:transition-none"
                        >
                          <input
                            type="checkbox"
                            checked={selections.outils.includes(idx)}
                            onChange={() => toggleSelection('outils', idx)}
                            className="mt-1"
                          />
                          <span className="min-w-0 flex-1 text-sm">
                            <span className="font-medium">{outil.name}</span>
                            <span className="mt-1 block text-xs leading-5 text-[var(--brain-ops-text-muted)]">{outil.rationale}</span>
                          </span>
                        </ChoiceTarget>
                      ))}
                    </div>
                  )}

                  {enrichmentResult.propositions.langages.length > 0 && (
                    <div className="space-y-2">
                      <h4 className="text-sm font-semibold">{t('offer.category.languages')}</h4>
                      {enrichmentResult.propositions.langages.map((lang, idx) => (
                        <ChoiceTarget
                          key={idx}
                          className="flex w-full cursor-pointer items-start border-t border-[color:var(--brain-ops-border)] px-1 py-3 transition-colors hover:bg-[var(--brain-ops-surface-muted)] motion-reduce:transition-none"
                        >
                          <input
                            type="checkbox"
                            checked={selections.langages.includes(idx)}
                            onChange={() => toggleSelection('langages', idx)}
                            className="mt-1"
                          />
                          <span className="min-w-0 flex-1 text-sm">
                            <span className="font-medium">{lang.name}</span>
                            <span className="mt-1 block text-xs leading-5 text-[var(--brain-ops-text-muted)]">{lang.rationale}</span>
                          </span>
                        </ChoiceTarget>
                      ))}
                    </div>
                  )}

                  {enrichmentResult.propositions.certifications.length > 0 && (
                    <div className="space-y-2">
                      <h4 className="text-sm font-semibold">{t('offer.category.certifications')}</h4>
                      {enrichmentResult.propositions.certifications.map((cert, idx) => (
                        <ChoiceTarget
                          key={idx}
                          className="flex w-full cursor-pointer items-start border-t border-[color:var(--brain-ops-border)] px-1 py-3 transition-colors hover:bg-[var(--brain-ops-surface-muted)] motion-reduce:transition-none"
                        >
                          <input
                            type="checkbox"
                            checked={selections.certifications.includes(idx)}
                            onChange={() => toggleSelection('certifications', idx)}
                            className="mt-1"
                          />
                          <span className="min-w-0 flex-1 text-sm">
                            <span className="font-medium">{cert.name}</span>
                            <span className="mt-1 block text-xs leading-5 text-[var(--brain-ops-text-muted)]">{cert.rationale}</span>
                          </span>
                        </ChoiceTarget>
                      ))}
                    </div>
                  )}

                  {enrichmentResult.propositions.missions.length > 0 && (
                    <div className="space-y-2">
                      <h4 className="text-sm font-semibold">{t('offer.category.missions')}</h4>
                      {enrichmentResult.propositions.missions.map((mission, idx) => (
                        <ChoiceTarget
                          key={idx}
                          className="flex w-full cursor-pointer items-start border-t border-[color:var(--brain-ops-border)] px-1 py-3 transition-colors hover:bg-[var(--brain-ops-surface-muted)] motion-reduce:transition-none"
                        >
                          <input
                            type="checkbox"
                            checked={selections.missions.includes(idx)}
                            onChange={() => toggleSelection('missions', idx)}
                            className="mt-1"
                          />
                          <span className="min-w-0 flex-1 text-sm">
                            <span className="font-medium">{mission.text}</span>
                            <span className="mt-1 block text-xs leading-5 text-[var(--brain-ops-text-muted)]">{mission.rationale}</span>
                          </span>
                        </ChoiceTarget>
                      ))}
                    </div>
                  )}

                  {enrichmentResult.propositions.questions_clarification.length > 0 && (
                    <div className="space-y-4">
                      <h4 className="text-sm font-semibold">{t('offer.category.questions')}</h4>
                      {enrichmentResult.propositions.questions_clarification.map((q, idx) => {
                        const questionId = `offer-question-${idx}`;

                        return (
                          <div key={idx} className="space-y-2 border-t border-[color:var(--brain-ops-border)] pt-3">
                            <Label htmlFor={questionId}>{q}</Label>
                            <Input
                              id={questionId}
                              value={questionResponses[q] || ''}
                              onChange={(e) =>
                                setQuestionResponses({ ...questionResponses, [q]: e.target.value })
                              }
                              placeholder={t('offer.answerPlaceholder')}
                            />
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </DisclosureSection>

      {offreData && (
        <Section data-tour="offer-criteria" title={t('offer.section.criteria')}>
          <div className="space-y-6">
            <div className="grid gap-6 md:grid-cols-2">
              <div className="flex flex-col items-start gap-3 border-l-2 border-[color:var(--brain-ops-border)] pl-4">
                <h3 className="text-sm font-semibold leading-5">{t('offer.criteria.aiExtraction')}</h3>
                <Button
                  type="button"
                  onClick={handleExtractCriteria}
                  disabled={extractingCriteria}
                  variant="outline"
                  className={`${flexibleButtonClassName} w-full sm:w-auto`}
                >
                  {extractingCriteria ? (
                    <>
                      <Loader2 data-icon="inline-start" className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                      {t('offer.criteria.extracting')}
                    </>
                  ) : (
                    t('offer.criteria.extract')
                  )}
                </Button>
              </div>

              <div className="flex flex-col items-start gap-3 border-l-2 border-[color:var(--brain-ops-border)] pl-4">
                <Label htmlFor="manual-criteria">{t('offer.criteria.manualEntry')}</Label>
                <Textarea
                  id="manual-criteria"
                  value={manualCriteriaText}
                  onChange={(e) => setManualCriteriaText(e.target.value)}
                  placeholder={t('offer.criteria.placeholder')}
                  rows={3}
                  className="resize-y"
                />
                <Button
                  type="button"
                  onClick={handleAddManualCriteria}
                  variant="outline"
                  className={`${flexibleSmallButtonClassName} w-full sm:w-auto`}
                  size="sm"
                >
                  <Plus data-icon="inline-start" className="h-3 w-3" />
                  {t('common.add')}
                </Button>
              </div>
            </div>

            {criteriaList.length > 0 && (
              <div className="space-y-5 border-t border-[color:var(--brain-ops-border)] pt-6">
                <MetricStrip
                  ariaLabel={t('offer.criteria.classify')}
                  items={[
                    { id: 'must-have', label: 'Must-have', value: mustHaveCount },
                    { id: 'nice-to-have', label: 'Nice-to-have', value: niceHaveCount },
                  ]}
                />

                <div className="space-y-2">
                  <h3 className="text-lg font-semibold">
                    {t('offer.criteria.classify')} ({criteriaList.length})
                  </h3>
                  <p className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">
                    {t('offer.criteria.help')}
                  </p>
                </div>

                <div className="max-h-[32rem] overflow-y-auto border-y border-[color:var(--brain-ops-border)]">
                  {criteriaList.map((criteria, idx) => (
                    <div
                      key={idx}
                      className="grid gap-3 border-b border-[color:var(--brain-ops-border)] px-3 py-3 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_11rem_auto] sm:items-center"
                    >
                      <span className="min-w-0 break-words text-sm">
                        {criteria.text}
                        <span className="ml-2 text-xs text-[var(--brain-ops-text-muted)]">
                          ({criteria.source === 'ia' ? t('common.ai') : t('common.manual')})
                        </span>
                      </span>
                      <Select
                        value={criteria.classification}
                        aria-label={`${t('offer.criteria.classify')}: ${criteria.text}`}
                        onChange={(e) =>
                          updateCriteriaClassification(
                            idx,
                            e.target.value as CriteriaClassification
                          )
                        }
                        className="w-full"
                      >
                        <option value="N/A">N/A</option>
                        <option value="Must-have">Must-have</option>
                        <option value="Nice-to-have">Nice-to-have</option>
                      </Select>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`${t('common.delete')}: ${criteria.text}`}
                        onClick={() => removeCriteria(idx)}
                        className="justify-self-end"
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Section>
      )}

      {offreData && (
        <div data-tour="offer-save-next" className="flex justify-end border-t border-[color:var(--brain-ops-border)] pt-6">
          <Button
            type="button"
            onClick={handleSaveAndNext}
            size="lg"
            disabled={saving}
            className={flexibleLargeButtonClassName}
          >
            {saving ? (
              <>
                <Loader2 data-icon="inline-start" className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                {t('common.saving')}
              </>
            ) : (
              <>
                {t('offer.action.next')}
                <ArrowRight data-icon="inline-end" className="h-5 w-5" />
              </>
            )}
          </Button>
        </div>
      )}
    </PageFrame>
  );
};
