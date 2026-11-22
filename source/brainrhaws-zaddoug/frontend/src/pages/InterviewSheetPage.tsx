import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  AlertCircle,
  ArrowLeft,
  Bot,
  CalendarDays,
  ClipboardCheck,
  Download,
  ExternalLink,
  Save,
  UserRound,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '../components/ui/card';
import { Tabs, TabsContent } from '../components/ui/tabs';
import { LoadingPage } from '../components/shared/Loading';
import {
  premiumCardClass,
  premiumFieldClass,
  premiumHeroPrimaryButtonClass,
  premiumPanelClass,
  premiumSubPanelClass,
} from '../components/shared/PremiumPage';
import {
  interviewSheetApi,
  type InterviewQuestionItem,
  type InterviewScorecardItem,
  type InterviewSheet,
} from '../api/interviewSheet';
import { matchingApi } from '../api/matching';
import { cvsApi } from '../api/cvs';
import { projectsApi } from '../api/projects';
import type { APIError, CV, Project, ResultatMatching, CompanyCvTemplate } from '../api/types';
import { useToast } from '../hooks/useToast';
import { realtimeInterviewApi, type InterviewPlan } from '../api/realtimeInterview';
import { companyCvApi } from '../api/companyCv';
import { cvTemplatesApi } from '../api/cvTemplates';
import { SchedulerButton } from '../components/interview/scheduler/SchedulerButton';
import type { InterviewMode } from '../api/interviewAppointments';
import { RecordingLinks } from '../components/interview/recordings/RecordingLinks';
import { EvidencePanel } from '../components/matching/EvidencePanel';
import { renderTextWithEvidences } from '../components/matching/renderTextWithEvidences';
import { API_BASE_URL } from '../api/client';
import { PageFrame } from '../components/operations/PageFrame';
import { PageHeader } from '../components/operations/PageHeader';
import { ContextStrip } from '../components/operations/ContextStrip';
import { SystemState } from '../components/operations/SystemState';
import { MetricStrip } from '../components/operations/MetricStrip';
import { Section } from '../components/operations/Section';
import { useI18n } from '../i18n/useI18n';
import { formatMessage } from '../i18n/formatMessage';
import { buildOpenCvHref } from '../lib/cvSourceUrl';

type CandidatePassage = {
  matchingId: string;
  timestamp: string;
  rank: number;
  totalCandidates: number;
  result: ResultatMatching;
  isCurrent: boolean;
};

type GeneratedCompanyCvInfo = {
  filename: string;
  objectUrl: string;
  generatedAt: string;
  renderFingerprint: string | null;
  templateId: string | null;
  templateName: string | null;
  templateVersion: number | null;
  renderer: string | null;
  rendererVersion: string | null;
};

function normalizeToken(value: unknown): string[] {
  if (value === null || value === undefined) {
    return [];
  }

  const raw = String(value).trim().toLowerCase();
  if (!raw) {
    return [];
  }

  const tokens = new Set<string>([raw]);
  const parts = raw.split('/');
  const lastPart = parts[parts.length - 1];
  if (lastPart) {
    tokens.add(lastPart);
    const lastDot = lastPart.lastIndexOf('.');
    if (lastDot > 0) {
      tokens.add(lastPart.slice(0, lastDot));
    }
  }
  return Array.from(tokens);
}

function buildCandidateTokens(sheet: InterviewSheet, profile: CV | null): Set<string> {
  const tokens = new Set<string>();

  [
    sheet.candidate_id,
    sheet.data.identite?.nom_complet,
    sheet.data.identite?.nom,
    sheet.data.identite?.email,
    profile?.cv,
    profile?.identite?.email,
    profile?.identite?.nom,
    profile?.identite?.prenom ? `${profile.identite.prenom} ${profile.identite.nom || ''}` : '',
  ].forEach((value) => {
    normalizeToken(value).forEach((token) => tokens.add(token));
  });

  return tokens;
}

function resultMatchesCandidate(result: ResultatMatching, tokens: Set<string>): boolean {
  const resultTokens = new Set<string>();
  normalizeToken(result.cv).forEach((token) => resultTokens.add(token));
  normalizeToken(result.candidate_name).forEach((token) => resultTokens.add(token));

  for (const token of resultTokens) {
    if (tokens.has(token)) {
      return true;
    }
  }

  return false;
}

function formatTimestampLabel(
  timestamp: string,
  locale = 'en-GB',
  undatedLabel = 'Undated run'
): string {
  if (!timestamp) {
    return undatedLabel;
  }

  const [datePart, timePart] = timestamp.split('_');
  if (!datePart || !timePart) {
    return timestamp;
  }

  const date = new Date(`${datePart}T${timePart.replace(/-/g, ':')}`);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }

  return date.toLocaleString(locale, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function clampText(value: string | undefined, maxLength = 180, fallback = 'Not available'): string {
  if (!value) {
    return fallback;
  }

  const normalized = value.trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }

  return `${normalized.slice(0, maxLength).trim()}...`;
}

function formatRank(rank: number | null, total: number | null, fallback = 'Not available'): string {
  if (!rank || !total) {
    return fallback;
  }

  return `#${rank}/${total}`;
}

function formatDateTimeLabel(
  value?: string | null,
  fallback = 'Not scheduled',
  locale = 'en-GB'
): string {
  if (!value) {
    return fallback;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return fallback;
  }

  return date.toLocaleString(locale, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatStatusLabel(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function getCandidateName(sheet: InterviewSheet, profile: CV | null): string {
  const sheetName = sheet.data.identite?.nom_complet || sheet.data.identite?.nom;
  if (sheetName) {
    return sheetName;
  }

  const profileName = [profile?.identite?.prenom, profile?.identite?.nom]
    .filter(Boolean)
    .join(' ')
    .trim();
  if (profileName) {
    return profileName;
  }

  return sheet.candidate_id;
}

function parseInitialQuestions(
  rawQuestions: InterviewSheet['data']['questions'],
  evaluationGrid: InterviewSheet['data']['evaluation_grid']
): InterviewQuestionItem[] {
  if (!Array.isArray(rawQuestions)) {
    return [];
  }

  const firstQuestion = rawQuestions[0];
  if (firstQuestion && 'question' in firstQuestion) {
    return rawQuestions.map((question) => ({
      theme: typeof question.theme === 'string' ? question.theme : '',
      question: typeof question.question === 'string' ? question.question : '',
      criteria: typeof question.criteria === 'string' ? question.criteria : '',
      notes: typeof question.notes === 'string' ? question.notes : '',
      score: typeof question.score === 'number' ? question.score : Number(question.score ?? 0),
      asked: Boolean(question.asked),
      satisfactory: Boolean(question.satisfactory),
    }));
  }

  const convertedQuestions: InterviewQuestionItem[] = [];
  const fallbackCriteria = Array.isArray(evaluationGrid)
    ? evaluationGrid.map((item) => item.description || item.criterion).filter(Boolean)
    : [];
  let convertedIndex = 0;
  rawQuestions.forEach((question) => {
    if (!Array.isArray(question.items)) {
      return;
    }

    question.items.forEach((item) => {
      convertedQuestions.push({
        theme: typeof question.theme === 'string' ? question.theme : '',
        question: item,
        criteria: fallbackCriteria[convertedIndex % Math.max(fallbackCriteria.length, 1)] || '',
        notes: '',
        score: 0,
        asked: false,
        satisfactory: false,
      });
      convertedIndex += 1;
    });
  });

  return convertedQuestions;
}

function hydrateQuestionsFromAiRubric(
  current: InterviewQuestionItem[],
  plan: InterviewPlan
): InterviewQuestionItem[] {
  const criteria = plan.scoringRubric.flatMap((item) => item.criteria).filter(Boolean);
  const isUnevaluated = current.every((question) => (
    Number(question.score ?? 0) === 0
    && !question.notes?.trim()
    && !question.asked
    && !question.satisfactory
  ));
  if (!criteria.length || !current.length || !isUnevaluated) {
    return current;
  }

  return current.map((question, index) => (
    question.criteria?.trim()
      ? question
      : { ...question, criteria: criteria[index % criteria.length] }
  ));
}

function hydrateScorecardFromAiRubric(
  current: InterviewScorecardItem[],
  plan: InterviewPlan
): InterviewScorecardItem[] {
  const rubric = plan.scoringRubric.filter((item) => item.category.trim() || item.criteria.length > 0);
  if (!rubric.length || current.length > 0) {
    return current;
  }

  const weight = 1 / rubric.length;
  return rubric.map((item) => ({
    criterion: item.category,
    description: item.criteria.join(' · '),
    weight,
    score: 0,
    justification: '',
  }));
}

function parseInitialScorecard(
  scorecard: InterviewSheet['data']['scorecard'],
  evaluationGrid: InterviewSheet['data']['evaluation_grid']
): InterviewScorecardItem[] {
  const source = Array.isArray(scorecard) && scorecard.length > 0 ? scorecard : evaluationGrid;
  if (!Array.isArray(source)) {
    return [];
  }

  return source.map((item) => ({
    criterion: typeof item.criterion === 'string' ? item.criterion : '',
    weight: typeof item.weight === 'number' ? item.weight : Number(item.weight ?? 0),
    description: typeof item.description === 'string' ? item.description : '',
    score: typeof item.score === 'number' ? item.score : Number(item.score ?? 0),
    justification: typeof item.justification === 'string' ? item.justification : '',
  }));
}

function linesToArray(value: string): string[] {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);
}

function arrayToLines(values: string[] | undefined): string {
  return Array.isArray(values) ? values.join('\n') : '';
}

function buildCandidateCvUrl(projectId: string, candidate: CV | null, fallbackId: string): string | null {
  const cvId = candidate?.cv || fallbackId;
  if (!projectId || !cvId) {
    return null;
  }
  return `/api/v1/cvs/projects/${encodeURIComponent(projectId)}/cvs/${encodeURIComponent(cvId)}/download?proxy=true&download=0`;
}

function getApiErrorStatus(error: APIError): number | null {
  if (!error.details || typeof error.details !== 'object') {
    return null;
  }
  const details = error.details as { status?: unknown; details?: unknown };
  if (typeof details.status === 'number') {
    return details.status;
  }
  if (details.details && typeof details.details === 'object' && 'status' in details.details) {
    const nestedStatus = (details.details as { status?: unknown }).status;
    return typeof nestedStatus === 'number' ? nestedStatus : null;
  }
  return null;
}

export const InterviewSheetPage: React.FC = () => {
  const { sheetId } = useParams<{ sheetId: string }>();
  const navigate = useNavigate();
  const { success, error: showError } = useToast();
  const { language, t } = useI18n();
  const tRef = useRef(t);
  tRef.current = t;
  const locale = language === 'fr' ? 'fr-FR' : 'en-GB';

  const [sheet, setSheet] = useState<InterviewSheet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [saving, setSaving] = useState(false);

  const [project, setProject] = useState<Project | null>(null);
  const [candidateProfile, setCandidateProfile] = useState<CV | null>(null);
  const [passages, setPassages] = useState<CandidatePassage[]>([]);
  const [contextLoading, setContextLoading] = useState(false);

  const [scorecard, setScorecard] = useState<InterviewScorecardItem[]>([]);
  const [questions, setQuestions] = useState<InterviewQuestionItem[]>([]);
  const [freeNotes, setFreeNotes] = useState('');
  const [verdict, setVerdict] = useState('');
  const [verdictDetail, setVerdictDetail] = useState('');
  const [additionalTests, setAdditionalTests] = useState(false);
  const [residualRisks, setResidualRisks] = useState('');
  const [aiPlanInstructions, setAiPlanInstructions] = useState('');
  const [aiPlan, setAiPlan] = useState<InterviewPlan | null>(null);
  const [aiPlanLoading, setAiPlanLoading] = useState(false);
  const [aiPlanSaving, setAiPlanSaving] = useState(false);
  const [aiPlanPreparing, setAiPlanPreparing] = useState(false);
  const [aiPlanDirty, setAiPlanDirty] = useState(false);
  const [activeView, setActiveView] = useState<'profile' | 'matching' | 'ai' | 'human' | 'decision'>('profile');
  const [generatingCompanyCv, setGeneratingCompanyCv] = useState(false);
  const [companyCvGenerationGuidance, setCompanyCvGenerationGuidance] = useState('');
  const [companyCvTemplateReady, setCompanyCvTemplateReady] = useState(false);
  const [companyCvTemplateLoading, setCompanyCvTemplateLoading] = useState(false);
  const [activeCompanyCvTemplate, setActiveCompanyCvTemplate] = useState<CompanyCvTemplate | null>(null);
  const [generatedCompanyCv, setGeneratedCompanyCv] = useState<GeneratedCompanyCvInfo | null>(null);

  useEffect(() => {
    return () => {
      if (generatedCompanyCv?.objectUrl) {
        URL.revokeObjectURL(generatedCompanyCv.objectUrl);
      }
    };
  }, [generatedCompanyCv]);

  useEffect(() => {
    setGeneratedCompanyCv((current) => {
      if (current?.objectUrl) {
        URL.revokeObjectURL(current.objectUrl);
      }
      return null;
    });
  }, [sheetId]);

  useEffect(() => {
    if (!sheetId) {
      return;
    }

    let cancelled = false;

    const loadSheet = async () => {
      try {
        setLoading(true);
        setError(null);

        const data = await interviewSheetApi.getById(sheetId);
        if (cancelled) {
          return;
        }

        setSheet(data);
        setScorecard(parseInitialScorecard(data.data.scorecard, data.data.evaluation_grid));
        setQuestions(parseInitialQuestions(data.data.questions, data.data.evaluation_grid));
        setFreeNotes(data.data.free_notes || '');
        setVerdict(data.data.verdict || '');
        setVerdictDetail(data.data.verdict_detail || '');
        setAdditionalTests(data.data.additional_tests || false);
        setResidualRisks(data.data.residual_risks || '');
        setAiPlanInstructions(data.data.ai_plan_instructions || '');
      } catch (sheetError: unknown) {
        if (cancelled) {
          return;
        }

        setError({
          code: 'INTERVIEW_LOAD_ERROR',
          message: sheetError instanceof Error ? sheetError.message : tRef.current('interviewSheet.error.load'),
          details: sheetError,
        });
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadSheet();

    return () => {
      cancelled = true;
    };
  }, [sheetId]);

  useEffect(() => {
    if (!sheet) {
      return;
    }

    let cancelled = false;

    const loadContext = async () => {
      setContextLoading(true);
      try {
        const [projectData, projectHistory, projectCandidates] = await Promise.all([
          projectsApi.getById(sheet.job_id),
          projectsApi.getHistory(sheet.job_id),
          cvsApi.getByProject(sheet.job_id),
        ]);

        if (cancelled) {
          return;
        }

        setProject(projectData);

        const fallbackProfile =
          projectCandidates.find((candidate) => normalizeToken(candidate.cv).includes(sheet.candidate_id.toLowerCase())) ||
          null;
        setCandidateProfile(fallbackProfile);

        const candidateTokens = buildCandidateTokens(sheet, fallbackProfile);
        const historyItems = [...(projectHistory.items || [])];
        if (
          sheet.matching_id &&
          !historyItems.some((item) => item.matching_id === sheet.matching_id)
        ) {
          historyItems.unshift({
            matching_id: sheet.matching_id,
            timestamp: sheet.matching_id,
            candidats_count: 0,
          });
        }

        const runPayloads = await Promise.all(
          historyItems.map(async (item) => {
            try {
              const results = await matchingApi.getResults(sheet.job_id, item.matching_id);
              return { item, results };
            } catch {
              return null;
            }
          })
        );

        if (cancelled) {
          return;
        }

        const nextPassages: CandidatePassage[] = [];
        runPayloads.forEach((payload) => {
          if (!payload) {
            return;
          }

          const resultIndex = payload.results.findIndex((result) => resultMatchesCandidate(result, candidateTokens));
          if (resultIndex === -1) {
            return;
          }

          nextPassages.push({
            matchingId: payload.item.matching_id,
            timestamp: payload.item.timestamp,
            rank: resultIndex + 1,
            totalCandidates: payload.results.length,
            result: payload.results[resultIndex],
            isCurrent: payload.item.matching_id === sheet.matching_id,
          });
        });

        nextPassages.sort((left, right) => right.timestamp.localeCompare(left.timestamp));
        setPassages(nextPassages);
      } catch (contextError) {
        if (!cancelled) {
          console.error('Unable to load candidate dashboard context:', contextError);
          setProject(null);
          setCandidateProfile(null);
          setPassages([]);
        }
      } finally {
        if (!cancelled) {
          setContextLoading(false);
        }
      }
    };

    void loadContext();

    return () => {
      cancelled = true;
    };
  }, [sheet]);

  useEffect(() => {
    const enterpriseId = project?.enterprise_id;
    if (!enterpriseId) {
      setCompanyCvTemplateReady(false);
      setCompanyCvTemplateLoading(false);
      setActiveCompanyCvTemplate(null);
      return;
    }

    let cancelled = false;
    const loadTemplates = async () => {
      try {
        setCompanyCvTemplateLoading(true);
        const templates = await cvTemplatesApi.list(enterpriseId);
        if (!cancelled) {
          const activeTemplate = templates.find((template) => template.is_active) || null;
          setActiveCompanyCvTemplate(activeTemplate);
          setCompanyCvTemplateReady(Boolean(activeTemplate && activeTemplate.is_valid));
        }
      } catch (templateError) {
        if (!cancelled) {
          console.error('Unable to load company CV templates:', templateError);
          setCompanyCvTemplateReady(false);
          setActiveCompanyCvTemplate(null);
        }
      } finally {
        if (!cancelled) {
          setCompanyCvTemplateLoading(false);
        }
      }
    };

    void loadTemplates();
    return () => {
      cancelled = true;
    };
  }, [project?.enterprise_id]);

  const activePreparation = sheet?.data.realtime_preparation;
  const editableRealtimeInterviewId = activePreparation?.interview_id || (
    sheet?.data.realtime_interview?.status !== 'completed'
      ? sheet?.data.realtime_interview?.interview_id
      : undefined
  );

  useEffect(() => {
    const interviewId = editableRealtimeInterviewId;
    if (!interviewId) {
      setAiPlan(null);
      setAiPlanDirty(false);
      setAiPlanLoading(false);
      return;
    }

    let cancelled = false;

    const loadAiContext = async () => {
      try {
        setAiPlanLoading(true);
        const context = await realtimeInterviewApi.getContext(interviewId);
        if (!cancelled) {
          setAiPlan(context.plan || null);
          if (context.plan) {
            setQuestions((current) => hydrateQuestionsFromAiRubric(current, context.plan as InterviewPlan));
            setScorecard((current) => hydrateScorecardFromAiRubric(current, context.plan as InterviewPlan));
          }
          setAiPlanDirty(false);
        }
      } catch (aiError) {
        if (!cancelled) {
          console.error('Unable to load AI interview context:', aiError);
          setAiPlan(null);
        }
      } finally {
        if (!cancelled) {
          setAiPlanLoading(false);
        }
      }
    };

    void loadAiContext();

    return () => {
      cancelled = true;
    };
  }, [editableRealtimeInterviewId]);

  const updateAiPlan = (updater: (current: InterviewPlan) => InterviewPlan) => {
    setAiPlan((current) => {
      if (!current) {
        return current;
      }
      const next = updater(current);
      setAiPlanDirty(true);
      return next;
    });
  };

  const saveAiPlan = async () => {
    const interviewId = editableRealtimeInterviewId;
    if (!interviewId || !aiPlan || !aiPlanDirty) {
      return;
    }

    try {
      setAiPlanSaving(true);
      const response = await realtimeInterviewApi.updatePlan(interviewId, aiPlan);
      setAiPlan(response.plan);
      const nextQuestions = hydrateQuestionsFromAiRubric(questions, response.plan);
      const nextScorecard = hydrateScorecardFromAiRubric(scorecard, response.plan);
      setQuestions(nextQuestions);
      setScorecard(nextScorecard);
      if (sheetId) {
        await interviewSheetApi.patch(sheetId, {
          questions: nextQuestions,
          scorecard: nextScorecard,
        });
      }
      setAiPlanDirty(false);
      success(t('interviewSheet.toast.aiPlanSaved'));
    } catch (saveError) {
      const message = saveError instanceof Error ? saveError.message : t('interviewSheet.error.aiPlanSave');
      showError(message);
    } finally {
      setAiPlanSaving(false);
    }
  };

  const prepareAiPlan = async () => {
    if (!sheet) {
      return;
    }

    try {
      setAiPlanPreparing(true);
      await interviewSheetApi.patch(sheet.id, {
        ai_plan_instructions: aiPlanInstructions,
      });
      const response = await realtimeInterviewApi.setup({
        mode: 'registry',
        projectId: sheet.job_id,
        jobId: sheet.job_id,
        candidateId: sheet.candidate_id,
        matchingId: sheet.matching_id,
        interviewSheetId: sheet.id,
        candidateName: getCandidateName(sheet, candidateProfile),
        aiPlanInstructions,
        languageHint: language,
      });

      if (response.plan) {
        setAiPlan(response.plan);
        const nextQuestions = hydrateQuestionsFromAiRubric(questions, response.plan);
        const nextScorecard = hydrateScorecardFromAiRubric(scorecard, response.plan);
        setQuestions(nextQuestions);
        setScorecard(nextScorecard);
        await interviewSheetApi.patch(sheet.id, {
          ai_plan_instructions: aiPlanInstructions,
          questions: nextQuestions,
          scorecard: nextScorecard,
        });
        setAiPlanDirty(false);
      }

      const refreshed = await interviewSheetApi.getById(sheet.id);
      setSheet(refreshed);

      if (response.preparationState === 'failed') {
        showError(response.message || t('interviewSheet.error.aiPlanPrepare'));
      } else if (response.preparationState === 'pending' && !response.plan) {
        showError(response.message || t('interviewSheet.ai.preparationPending'));
      } else {
        success(t('interviewSheet.toast.aiPlanPrepared'));
      }
    } catch (prepareError) {
      const message = prepareError instanceof Error
        ? prepareError.message
        : t('interviewSheet.error.aiPlanPrepare');
      showError(message);
    } finally {
      setAiPlanPreparing(false);
    }
  };

  const handleGenerateCompanyCv = async () => {
    if (!sheetId) {
      return;
    }

    try {
      setGeneratingCompanyCv(true);
      const {
        blob,
        filename,
        renderFingerprint,
        templateId,
        templateName,
        templateVersion,
        renderer,
        rendererVersion,
      } = await companyCvApi.generateFromInterviewSheet(
        sheetId,
        undefined,
        companyCvGenerationGuidance
      );
      const url = URL.createObjectURL(blob);
      const resolvedFilename = filename || 'company-cv.docx';
      setGeneratedCompanyCv((current) => {
        if (current?.objectUrl) {
          URL.revokeObjectURL(current.objectUrl);
        }
        return {
          filename: resolvedFilename,
          objectUrl: url,
          generatedAt: new Date().toISOString(),
          renderFingerprint,
          templateId,
          templateName,
          templateVersion,
          renderer,
          rendererVersion,
        };
      });
      window.setTimeout(() => {
        const link = document.createElement('a');
        link.href = url;
        link.download = resolvedFilename;
        document.body.appendChild(link);
        link.click();
        link.remove();
      }, 0);
      success(
        t('interviewSheet.toast.clientCvGenerated'),
        t('interviewSheet.toast.downloadedFile').replace('{{filename}}', resolvedFilename)
      );
    } catch (generationError) {
      const message = generationError instanceof Error ? generationError.message : t('interviewSheet.error.clientCvGenerate');
      showError(message);
    } finally {
      setGeneratingCompanyCv(false);
    }
  };

  const handleSave = async () => {
    if (!sheetId) {
      return;
    }

    try {
      setSaving(true);
      await interviewSheetApi.patch(sheetId, {
        scorecard,
        questions,
        free_notes: freeNotes,
        verdict,
        verdict_detail: verdictDetail,
        additional_tests: additionalTests,
        residual_risks: residualRisks,
        ai_plan_instructions: aiPlanInstructions,
        status: 'in_progress',
      });
      success(t('interviewSheet.toast.saved'));

      const refreshed = await interviewSheetApi.getById(sheetId);
      setSheet(refreshed);
    } catch (saveError: unknown) {
      const message = saveError instanceof Error ? saveError.message : t('interviewSheet.error.save');
      showError(message);
    } finally {
      setSaving(false);
    }
  };

  const addQuestion = () => {
    setQuestions((current) => [
      ...current,
      {
        theme: '',
        question: '',
        criteria: t('interviewSheet.human.defaultCriterion'),
        notes: '',
        score: 0,
        asked: false,
        satisfactory: false,
      },
    ]);
  };

  const removeQuestion = (index: number) => {
    setQuestions((current) => current.filter((_, currentIndex) => currentIndex !== index));
  };

  const calculateTotalScore = () => {
    if (scorecard.length === 0) {
      return 0;
    }

    const total = scorecard.reduce((sum, item) => (
      sum + Number(item.score ?? 0) * Number(item.weight ?? 0)
    ), 0);

    return Number(total.toFixed(2));
  };

  if (loading) {
    return <LoadingPage text={t('interviewSheet.loading')} />;
  }

  if (error) {
    const isNotFound = getApiErrorStatus(error) === 404;
    return (
      <PageFrame>
        <SystemState
          kind="error"
          title={isNotFound ? t('interviewSheet.notFound') : t('interviewSheet.error.load')}
          description={isNotFound
            ? t('interviewSheet.notFoundDescription')
            : t('interviewSheet.error.loadDescription')}
          indicator={<AlertCircle className="size-5" />}
          actionLabel={t('interviewSheet.back')}
          action={(
            <Button onClick={() => navigate('/interviews')}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              {t('interviewSheet.back')}
            </Button>
          )}
        />
      </PageFrame>
    );
  }

  if (!sheet) {
    return (
      <PageFrame>
        <SystemState
          kind="error"
          title={t('interviewSheet.notFound')}
          description={t('interviewSheet.notFoundDescription')}
          indicator={<AlertCircle className="size-5" />}
          actionLabel={t('interviewSheet.back')}
          action={(
            <Button onClick={() => navigate('/interviews')}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              {t('interviewSheet.back')}
            </Button>
          )}
        />
      </PageFrame>
    );
  }

  const sheetWorkflowStatus = sheet.status;
  const isCompleted = sheet.status === 'completed';
  const candidateName = getCandidateName(sheet, candidateProfile);
  const realtimeInterview = sheet.data.realtime_interview;
  const recordingArtifacts = sheet.data.scheduling?.provider_artifacts?.recordings || [];
  const realtimeTranscript = Array.isArray(realtimeInterview?.transcript_turns)
    ? realtimeInterview.transcript_turns
    : [];
  const realtimeSummaryData = realtimeInterview?.summary_data;
  const realtimeOverallAppreciation =
    realtimeInterview?.overall_appreciation ||
    realtimeInterview?.appreciation_globale ||
    (typeof realtimeSummaryData?.overallAppreciation === 'string'
      ? realtimeSummaryData.overallAppreciation
      : '') ||
    (typeof realtimeSummaryData?.overall_appreciation === 'string'
      ? realtimeSummaryData.overall_appreciation
      : '');
  const currentPassage = passages.find((passage) => passage.isCurrent) || passages[0] || null;
  const historicalPassages = passages.filter((passage) => !passage.isCurrent);
  const schedulingSummary = sheet.data.scheduling;
  // Un entretien recruteur planifié ne doit pas apparaître comme une session IA.
  const isHumanScheduling = schedulingSummary?.interview_mode === 'human';
  const aiScheduledAt = isHumanScheduling ? null : schedulingSummary?.scheduled_at;
  const humanScheduledAt = isHumanScheduling ? schedulingSummary?.scheduled_at : null;
  const humanOutcomeLabel = !isHumanScheduling
    ? ''
    : schedulingSummary?.status === 'completed'
      ? t('scheduler.status.completed')
      : schedulingSummary?.status === 'no_show'
        ? t('scheduler.status.noShow')
        : '';
  const weightedScore = calculateTotalScore().toFixed(2);
  const hasRhScoring = scorecard.some((item) => (
    Number(item.score ?? 0) > 0 || Boolean(item.justification?.trim())
  ));
  const weightedScoreLabel = hasRhScoring ? `${weightedScore} / 5` : t('interviewSheet.common.notEvaluated');
  const verdictLabel = verdict
    ? verdict === 'retained'
      ? t('interviewSheet.decision.retained')
      : verdict === 'reserved'
        ? t('interviewSheet.decision.reserved')
        : t('interviewSheet.decision.rejected')
    : t('interviewSheet.decision.pending');
  const humanInterviewState = formatDateTimeLabel(
    schedulingSummary?.scheduled_at,
    t('interviewSheet.common.notScheduled'),
    locale
  );
  const interviewLocationLabel = isHumanScheduling
    ? t('interviewSheet.human.locationUndefined')
    : schedulingSummary?.location?.startsWith('http')
      ? t('interviewSheet.human.videoAvailable')
      : schedulingSummary?.location || t('interviewSheet.human.locationUndefined');
  const aiInterviewDateValue = realtimeInterview?.completed_at || aiScheduledAt;
  const aiInterviewDate = formatDateTimeLabel(
    aiInterviewDateValue,
    t('interviewSheet.ai.noInterview'),
    locale
  );
  const aiInterviewDateLabel = realtimeInterview?.completed_at
    ? t('interviewSheet.ai.completedDate')
    : aiScheduledAt
      ? t('interviewSheet.ai.scheduledDate')
      : t('interviewSheet.ai.interviewDate');
  const candidateSummary = sheet.data.resume || candidateProfile?.resume_professionnel || '';
  const candidateStrength = sheet.data.strengths?.[0]?.point || '';
  const candidateConcern = sheet.data.concerns?.[0]?.point || sheet.data.concerns?.[0]?.question || '';
  const fallbackCvUrl = buildCandidateCvUrl(sheet.job_id, candidateProfile, sheet.candidate_id);
  const originalCvUrl =
    currentPassage?.result.original_cv_url ||
    passages.find((passage) => Boolean(passage.result.original_cv_url))?.result.original_cv_url ||
    null;
  const candidateCvHref = buildOpenCvHref(API_BASE_URL, originalCvUrl, fallbackCvUrl);
  const projectLabel = project?.nom || sheet.job_id;
  const matchingLabel = sheet.matching_id
    ? t('interviewSheet.header.currentMatching').replace('{{id}}', sheet.matching_id)
    : t('interviewSheet.header.noCurrentMatching');
  const aiInterviewStatusLabel = activePreparation?.status === 'pending'
    ? t('interviewSheet.status.preparing')
    : activePreparation?.status === 'failed'
      ? t('interviewSheet.status.preparationFailed')
      : activePreparation?.status === 'ready'
        ? t('interviewSheet.status.planReady')
        : realtimeInterview?.status
    ? realtimeInterview.status === 'completed'
      ? t('interviewSheet.status.completed')
      : realtimeInterview.status === 'in_progress'
        ? t('interviewSheet.status.inProgress')
        : realtimeInterview.status === 'scheduled'
          ? t('interviewSheet.status.scheduled')
          : formatStatusLabel(realtimeInterview.status)
    : aiScheduledAt
      ? t('interviewSheet.status.scheduled')
      : aiPlan
        ? t('interviewSheet.status.planReady')
        : t('interviewSheet.status.toPrepare');
  const renderSchedulerButton = (mode: InterviewMode, label: string) => (
    <SchedulerButton
      candidateId={sheet.candidate_id}
      jobId={sheet.job_id}
      matchingId={sheet.matching_id}
      candidateName={candidateName}
      candidateEmail={sheet.data.identite?.email || candidateProfile?.identite?.email || null}
      existingSheetId={sheet.id}
      initialData={{
        scheduled_at: sheet.scheduled_at,
        end_at: sheet.data.scheduling?.end_at,
        location: sheet.location,
        scheduler_notes: sheet.scheduler_notes,
        interviewer: sheet.interviewer,
        appointment_id: sheet.data.scheduling?.appointment_id,
      }}
      label={label}
      defaultMode={mode}
      onUpdate={async () => {
        const refreshed = await interviewSheetApi.getById(sheet.id);
        setSheet(refreshed);
      }}
    />
  );
  const aiSessionDetail = aiScheduledAt
    ? humanInterviewState
    : realtimeInterview?.status === 'scheduled'
      ? t('interviewSheet.ai.sessionDatePending')
      : t('interviewSheet.ai.sessionNotScheduled');
  const stageItems = [
    {
      key: 'profile',
      value: 'profile',
      label: t('interviewSheet.stage.profile'),
      status: candidateSummary ? 'complete' : 'pending',
      detail: candidateSummary ? t('interviewSheet.status.ready') : t('interviewSheet.status.missing'),
    },
    {
      key: 'matching',
      value: 'matching',
      label: t('interviewSheet.stage.matchRuns'),
      status: contextLoading ? 'loading' : passages.length > 0 ? 'complete' : 'pending',
      detail: contextLoading
        ? t('interviewSheet.status.loading')
        : passages.length
          ? t('interviewSheet.stage.runCount').replace('{{count}}', String(passages.length))
          : t('interviewSheet.stage.noRuns'),
      meta: currentPassage
        ? formatTimestampLabel(currentPassage.timestamp, locale, t('interviewSheet.common.undatedRun'))
        : '',
    },
    {
      key: 'human',
      value: 'human',
      label: t('interviewSheet.stage.humanPreparation'),
      status: questions.length > 0 ? 'complete' : 'pending',
      detail: questions.length > 0
        ? t('interviewSheet.stage.questionCount').replace('{{count}}', String(questions.length))
        : t('interviewSheet.status.toPrepare'),
      meta: humanScheduledAt ? humanInterviewState : '',
    },
    {
      key: 'ai',
      value: 'ai',
      label: t('interviewSheet.stage.aiInterview'),
      status: realtimeInterview?.status === 'completed'
        ? 'complete'
        : realtimeInterview || aiPlan || Boolean(aiScheduledAt)
          ? 'current'
          : aiPlanLoading
            ? 'loading'
            : 'pending',
      detail: realtimeInterview?.completed_at ? aiInterviewDate : aiInterviewStatusLabel,
      meta: aiScheduledAt ? humanInterviewState : '',
    },
    {
      key: 'decision',
      value: 'decision',
      label: t('interviewSheet.stage.decision'),
      status: verdict ? 'complete' : hasRhScoring ? 'current' : 'pending',
      detail: verdictLabel,
    },
  ] as const;
  const matchingSummary = currentPassage
    ? t('interviewSheet.matching.summary')
      .replace(
        '{{date}}',
        formatTimestampLabel(currentPassage.timestamp, locale, t('interviewSheet.common.undatedRun'))
      )
      .replace(
        '{{rank}}',
        formatRank(currentPassage.rank, currentPassage.totalCandidates, t('interviewSheet.common.notAvailable'))
      )
    : t('interviewSheet.matching.noRun');
  const canEditAiPlan = Boolean(aiPlan && realtimeInterview?.status !== 'completed');
  const generatedCompanyCvLabel = generatedCompanyCv
    ? formatDateTimeLabel(generatedCompanyCv.generatedAt, t('interviewSheet.common.justNow'), locale)
    : '';

  return (
    <PageFrame width="wide">
      <div className={premiumPanelClass}>
        <PageHeader
          eyebrow={
            <div className="flex flex-wrap items-center gap-3">
              <button
                className="brain-shell-touch-target flex h-9 w-9 items-center justify-center rounded-md border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text)] transition-colors hover:bg-[var(--brain-ops-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => navigate(-1)}
                aria-label={t('interviewSheet.back')}
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
              <span>{t('interviewSheet.eyebrow')}</span>
              <Badge variant={sheetWorkflowStatus === 'completed' ? 'success' : sheetWorkflowStatus === 'in_progress' ? 'default' : 'secondary'}>
                {sheetWorkflowStatus === 'completed'
                  ? t('interviewSheet.status.completed')
                  : sheetWorkflowStatus === 'in_progress'
                    ? t('interviewSheet.status.inProgress')
                    : t('interviewSheet.status.draft')}
              </Badge>
            </div>
          }
          title={<span className="block min-w-0 break-words [overflow-wrap:anywhere]">{candidateName}</span>}
          description={
            <span>
              {t('interviewSheet.header.project')} · {projectLabel} · {matchingLabel}
            </span>
          }
          context={
            <ContextStrip
              ariaLabel={t('interviewSheet.header.contextAria')}
              items={[
                {
                  id: 'project',
                  label: t('interviewSheet.header.project'),
                  value: projectLabel,
                },
                {
                  id: 'matching',
                  label: t('interviewSheet.stage.matchRuns'),
                  value: matchingLabel,
                },
                {
                  id: 'decision',
                  label: t('interviewSheet.stage.decision'),
                  value: verdictLabel,
                },
              ]}
            />
          }
          actionsLabel={t('interviewSheet.header.actions')}
          actions={
            <>
              {candidateCvHref ? (
                <a
                  href={candidateCvHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center justify-center gap-2 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] px-4 py-2 text-sm font-medium text-[var(--brain-ops-text)] transition-colors hover:bg-[var(--brain-ops-surface-muted)]"
                >
                  {t('interviewSheet.actions.viewCv')}
                </a>
              ) : null}
              {!isCompleted ? (
                <Button onClick={handleSave} disabled={saving} className={premiumHeroPrimaryButtonClass}>
                  <Save className="mr-2 h-4 w-4" />
                  {saving ? t('interviewSheet.actions.saving') : t('interviewSheet.actions.save')}
                </Button>
              ) : null}
            </>
          }
          className="p-5 sm:p-6"
        />

        <div className="border-t border-[color:var(--brain-ops-border)] px-5 py-4 sm:px-6">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <div className="max-w-3xl space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Label htmlFor="company-cv-generation-guidance">{t('interviewSheet.companyCv.guidance')}</Label>
                {activeCompanyCvTemplate ? (
                  <Badge variant="outline">
                    {activeCompanyCvTemplate.name} v{activeCompanyCvTemplate.version}
                  </Badge>
                ) : null}
              </div>
              <Textarea
                id="company-cv-generation-guidance"
                value={companyCvGenerationGuidance}
                onChange={(event) => setCompanyCvGenerationGuidance(event.target.value)}
                rows={3}
                maxLength={4000}
                placeholder={t('interviewSheet.companyCv.guidancePlaceholder')}
                className={premiumFieldClass}
              />
              <p className="text-xs leading-5 text-[var(--brain-ops-text-muted)]">
                {t('interviewSheet.companyCv.guidanceDescription')}
              </p>
            </div>
            <div className="flex flex-wrap gap-2 lg:justify-end">
              <Button
                type="button"
                onClick={() => void handleGenerateCompanyCv()}
                disabled={generatingCompanyCv || companyCvTemplateLoading || !companyCvTemplateReady}
                title={!companyCvTemplateReady ? t('interviewSheet.companyCv.noTemplate') : undefined}
              >
                <Download className="mr-2 h-4 w-4" />
                {generatingCompanyCv
                  ? t('interviewSheet.companyCv.generating')
                  : companyCvTemplateLoading
                    ? t('interviewSheet.companyCv.loadingTemplate')
                    : t('interviewSheet.companyCv.generate')}
              </Button>
            </div>
          </div>
          <p className="mt-3 text-xs text-[var(--brain-ops-text-muted)]">
            {t('interviewSheet.companyCv.downloadDescription')}
            {activeCompanyCvTemplate ? `: ${activeCompanyCvTemplate.name} (v${activeCompanyCvTemplate.version})` : ''}.
          </p>
        </div>

        {generatedCompanyCv ? (
          <div className="border-t border-[color:var(--brain-ops-border)] px-5 py-4 sm:px-6">
            <div className="flex flex-wrap items-start justify-between gap-3 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-accent)] bg-[var(--brain-ops-surface-muted)] px-4 py-3 text-sm text-[var(--brain-ops-text)]">
              <div className="min-w-0 space-y-1">
                <p className="font-semibold">{t('interviewSheet.companyCv.lastGenerated')}</p>
                <p className="break-all">
                  {generatedCompanyCv.filename}
                  {generatedCompanyCvLabel ? ` · ${generatedCompanyCvLabel}` : ''}
                </p>
                {generatedCompanyCv.templateName ? (
                  <p className="text-[var(--brain-ops-text-muted)]">
                    {t('interviewSheet.companyCv.generatedWith')} {generatedCompanyCv.templateName}
                    {generatedCompanyCv.templateVersion ? ` v${generatedCompanyCv.templateVersion}` : ''}
                  </p>
                ) : null}
                <p className="text-[var(--brain-ops-text-muted)]">
                  {t('interviewSheet.companyCv.renderer')}: {generatedCompanyCv.renderer || 'html_docx'}
                  {generatedCompanyCv.rendererVersion ? ` · ${generatedCompanyCv.rendererVersion}` : ''}
                </p>
                {generatedCompanyCv.renderFingerprint ? (
                  <p className="font-mono text-xs text-[var(--brain-ops-text-muted)]">
                    {t('interviewSheet.companyCv.fingerprint')}: {generatedCompanyCv.renderFingerprint}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => window.open(generatedCompanyCv.objectUrl, '_blank', 'noopener,noreferrer')}
                >
                  <ExternalLink className="mr-2 h-4 w-4" />
                  {t('interviewSheet.companyCv.openGenerated')}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    const link = document.createElement('a');
                    link.href = generatedCompanyCv.objectUrl;
                    link.download = generatedCompanyCv.filename;
                    document.body.appendChild(link);
                    link.click();
                    link.remove();
                  }}
                >
                  <Download className="mr-2 h-4 w-4" />
                  {t('interviewSheet.companyCv.downloadAgain')}
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <div className={`${premiumPanelClass} p-4`}>
        <div
          role="tablist"
          aria-label={t('interviewSheet.stage.navigation')}
          className="mb-4 grid gap-px overflow-hidden border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-border)] sm:grid-cols-2 xl:grid-cols-5"
        >
          {stageItems.map((item) => (
            <button
              type="button"
              role="tab"
              key={item.key}
              onClick={() => setActiveView(item.value)}
              aria-selected={activeView === item.value}
              aria-controls={`interview-panel-${item.value}`}
              className={`min-h-24 min-w-0 px-4 py-3 text-left text-sm focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--brain-ops-focus-ring)] ${
                item.status === 'complete'
                  ? 'bg-[var(--brain-ops-surface-muted)] text-[var(--brain-ops-success)]'
                  : item.status === 'current'
                    ? 'bg-[var(--brain-ops-accent-soft)] text-[var(--brain-ops-text)]'
                    : item.status === 'loading'
                      ? 'bg-[var(--brain-ops-surface-muted)] text-[var(--brain-ops-warning)]'
                      : 'bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text-muted)]'
              } ${
                activeView === item.value
                  ? 'shadow-[inset_0_-2px_0_var(--brain-ops-accent)]'
                  : 'hover:bg-[var(--brain-ops-surface-muted)]'
              } transition-colors motion-reduce:transition-none`}
            >
              <div className="text-xs uppercase tracking-[0.2em] opacity-70">{item.label}</div>
              <div className="mt-2 font-semibold">{item.detail}</div>
              {'meta' in item && item.meta ? (
                <div className="mt-1 text-xs opacity-70">{item.meta}</div>
              ) : null}
            </button>
          ))}
        </div>

        <Tabs value={activeView} onValueChange={(value) => setActiveView(value as typeof activeView)} className="space-y-4">
          <TabsContent id="interview-panel-profile" value="profile">
            <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
              <Card className={premiumCardClass}>
                <CardHeader>
                  <CardTitle>{t('interviewSheet.profile.title')}</CardTitle>
                  <CardDescription>
                    {t('interviewSheet.profile.description')}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className={`${premiumSubPanelClass} p-4`}>
                    <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t('interviewSheet.profile.summary')}</p>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      {clampText(candidateSummary, 220, t('interviewSheet.common.notAvailable'))}
                    </p>
                  </div>
                  <div className={`${premiumSubPanelClass} p-4`}>
                    <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t('interviewSheet.profile.keyPoints')}</p>
                    <ul className="mt-2 space-y-2 text-sm text-muted-foreground">
                      <li>{t('interviewSheet.profile.profile')}: {clampText(candidateSummary, 110, t('interviewSheet.common.notAvailable'))}</li>
                      <li>{t('interviewSheet.profile.strength')}: {candidateStrength || t('interviewSheet.profile.noStrength')} <span className="opacity-70">· {t('interviewSheet.profile.source')}</span></li>
                      <li>{t('interviewSheet.profile.watchItem')}: {candidateConcern || t('interviewSheet.profile.noConcern')} <span className="opacity-70">· {t('interviewSheet.profile.source')}</span></li>
                    </ul>
                  </div>
                </CardContent>
              </Card>

              <Card className={premiumCardClass}>
                <CardHeader>
                  <CardTitle>{t('interviewSheet.profile.recruitmentContext')}</CardTitle>
                  <CardDescription>
                    {t('interviewSheet.profile.recruitmentDescription')}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <Link
                    to={`/projects/${encodeURIComponent(project?.id || sheet.job_id)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={formatMessage(t('interviewSheet.profile.openProject'), { project: project?.nom || sheet.job_id })}
                    className={`${premiumSubPanelClass} group block p-4 transition-colors hover:border-[color:var(--brain-ops-accent)] hover:bg-[var(--brain-ops-accent-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brain-ops-focus-ring)] motion-reduce:transition-none`}
                  >
                    <span className="flex items-center justify-between gap-3 text-xs uppercase tracking-[0.2em] text-muted-foreground">
                      {t('interviewSheet.profile.recruitmentProject')}
                      <ExternalLink className="size-4 shrink-0 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 motion-reduce:transition-none" aria-hidden="true" />
                    </span>
                    <span className="mt-2 block text-base font-semibold text-[var(--brain-ops-text)]">{project?.nom || sheet.job_id}</span>
                    <span className="mt-2 block text-sm text-muted-foreground">
                      {project?.service_demandeur || project?.responsable_offre || t('interviewSheet.profile.activeProject')}
                    </span>
                  </Link>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent id="interview-panel-matching" value="matching">
            <Card className={premiumCardClass}>
              <CardHeader>
                <CardTitle>{t('interviewSheet.matching.title')}</CardTitle>
                <CardDescription>
                  {t('interviewSheet.matching.description')}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {contextLoading ? (
                  <div className={`${premiumSubPanelClass} p-5 text-sm text-muted-foreground`}>
                    {t('interviewSheet.matching.loading')}
                  </div>
                ) : !currentPassage ? (
                  <div className={`${premiumSubPanelClass} p-5 text-sm text-muted-foreground`}>
                    {t('interviewSheet.matching.empty')}
                  </div>
                ) : (
                  <>
                    <div className={`${premiumSubPanelClass} space-y-4 p-4`}>
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="success">{t('interviewSheet.matching.currentRun')}</Badge>
                          <span className="text-sm font-medium">{matchingSummary}</span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Badge variant="outline">{formatRank(currentPassage.rank, currentPassage.totalCandidates, t('interviewSheet.common.notAvailable'))}</Badge>
                          <Badge variant="outline">{t('interviewSheet.common.score')} {currentPassage.result.score_final.toFixed(3)}</Badge>
                        </div>
                      </div>
                      <div className="grid gap-3 md:grid-cols-3">
                        <div className="rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-3">
                          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t('interviewSheet.matching.baseScore')}</p>
                          <p className="mt-2 text-lg font-semibold">{currentPassage.result.score_base.toFixed(3)}</p>
                        </div>
                        <div className="rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-3">
                          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t('interviewSheet.matching.niceBonus')}</p>
                          <p className="mt-2 text-lg font-semibold">{currentPassage.result.bonus_nice_have_multiplicateur.toFixed(2)}x</p>
                        </div>
                        <div className="rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-3">
                          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t('interviewSheet.matching.experienceQuality')}</p>
                          <p className="mt-2 text-lg font-semibold">{currentPassage.result.coefficient_qualite_experience.toFixed(2)}x</p>
                        </div>
                      </div>
                      {currentPassage.result.nice_have_manquants?.length ? (
                        <div>
                          <p className="mb-2 text-sm font-semibold">{t('interviewSheet.matching.missingNice')}</p>
                          <div className="flex flex-wrap gap-2">
                            {currentPassage.result.nice_have_manquants.map((item) => (
                              <Badge key={`current-${item}`} variant="outline">{item}</Badge>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {currentPassage.result.commentaire_scoring ? (
                        <div>
                          <p className="mb-2 text-sm font-semibold">{t('interviewSheet.matching.scoringCommentary')}</p>
                          <div className="text-sm text-muted-foreground whitespace-pre-wrap">
                            {renderTextWithEvidences(currentPassage.result.commentaire_scoring, currentPassage.result.evidences)}
                          </div>
                        </div>
                      ) : null}
                      {currentPassage.result.appreciation_globale ? (
                        <div>
                          <p className="mb-2 text-sm font-semibold">{t('interviewSheet.common.hrAppreciation')}</p>
                          <div className="text-sm text-muted-foreground whitespace-pre-wrap">
                            {renderTextWithEvidences(currentPassage.result.appreciation_globale, currentPassage.result.evidences)}
                          </div>
                        </div>
                      ) : null}
                      <EvidencePanel evidences={currentPassage.result.evidences} flags={currentPassage.result.flags} />
                    </div>

                    {historicalPassages.length > 0 ? (
                      <details className={`${premiumSubPanelClass} p-4`}>
                        <summary className="cursor-pointer text-sm font-semibold">
                          {t('interviewSheet.matching.history')
                            .replace('{{count}}', String(historicalPassages.length))}
                        </summary>
                        <div className="mt-4 space-y-4">
                          {historicalPassages.map((passage) => (
                            <div key={passage.matchingId} className="space-y-3 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4">
                              <div className="flex flex-wrap items-center justify-between gap-3">
                                <div className="flex flex-wrap items-center gap-2">
                                  <Badge variant="outline">{t('interviewSheet.matching.historicalRun')}</Badge>
                                  <span className="text-sm font-medium">
                                    {t('interviewSheet.matching.summary')
                                      .replace(
                                        '{{date}}',
                                        formatTimestampLabel(passage.timestamp, locale, t('interviewSheet.common.undatedRun'))
                                      )
                                      .replace(
                                        '{{rank}}',
                                        formatRank(passage.rank, passage.totalCandidates, t('interviewSheet.common.notAvailable'))
                                      )}
                                  </span>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                  <Badge variant="outline">{formatRank(passage.rank, passage.totalCandidates, t('interviewSheet.common.notAvailable'))}</Badge>
                                  <Badge variant="outline">{t('interviewSheet.common.score')} {passage.result.score_final.toFixed(3)}</Badge>
                                </div>
                              </div>
                              {passage.result.nice_have_manquants?.length ? (
                                <div>
                                  <p className="mb-2 text-sm font-semibold">{t('interviewSheet.matching.missingNice')}</p>
                                  <div className="flex flex-wrap gap-2">
                                    {passage.result.nice_have_manquants.map((item) => (
                                      <Badge key={`${passage.matchingId}-${item}`} variant="outline">{item}</Badge>
                                    ))}
                                  </div>
                                </div>
                              ) : null}
                              {passage.result.commentaire_scoring ? (
                                <div>
                                  <p className="mb-2 text-sm font-semibold">{t('interviewSheet.matching.scoringCommentary')}</p>
                                  <div className="text-sm text-muted-foreground whitespace-pre-wrap">
                                    {renderTextWithEvidences(passage.result.commentaire_scoring, passage.result.evidences)}
                                  </div>
                                </div>
                              ) : null}
                              {passage.result.appreciation_globale ? (
                                <div>
                                  <p className="mb-2 text-sm font-semibold">{t('interviewSheet.common.hrAppreciation')}</p>
                                  <div className="text-sm text-muted-foreground whitespace-pre-wrap">
                                    {renderTextWithEvidences(passage.result.appreciation_globale, passage.result.evidences)}
                                  </div>
                                </div>
                              ) : null}
                              <EvidencePanel evidences={passage.result.evidences} flags={passage.result.flags} />
                            </div>
                          ))}
                        </div>
                      </details>
                    ) : null}
                  </>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent id="interview-panel-human" value="human">
            <Card className={premiumCardClass}>
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      <UserRound className="h-5 w-5" />
                      {t('interviewSheet.human.title')}
                    </CardTitle>
                    <CardDescription>
                      {t('interviewSheet.human.description')}
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {renderSchedulerButton('human', t('interviewSheet.actions.scheduleHuman'))}
                    {!isCompleted ? (
                      <Button onClick={addQuestion} size="sm" variant="outline">
                        {t('interviewSheet.human.addQuestion')}
                      </Button>
                    ) : null}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <MetricStrip
                  ariaLabel={t('interviewSheet.human.overview')}
                  items={[
                    {
                      id: 'human-questions',
                      label: t('interviewSheet.human.questions'),
                      value: questions.length,
                      detail: t('interviewSheet.human.questionsDescription'),
                    },
                    {
                      id: 'human-grid',
                      label: t('interviewSheet.human.evaluationGrid'),
                      value: scorecard.length,
                      detail: t('interviewSheet.human.evaluationGridDescription'),
                    },
                    {
                      id: 'human-scheduling',
                      label: t('interviewSheet.human.scheduling'),
                      value: humanScheduledAt ? humanInterviewState : t('interviewSheet.common.notScheduled'),
                      detail: humanScheduledAt
                        ? [schedulingSummary?.interviewer, humanOutcomeLabel].filter(Boolean).join(' · ')
                        : t('interviewSheet.actions.scheduleHuman'),
                    },
                  ]}
                />
                {questions.length === 0 ? (
                  <SystemState
                    kind="empty"
                    title={t('interviewSheet.human.noQuestions')}
                    description={t('interviewSheet.human.noQuestionsDescription')}
                    indicator={<ClipboardCheck className="h-5 w-5" />}
                  />
                ) : (
                  <div className="space-y-4">
                    {questions.map((question, index) => (
                      <div key={`${question.question}-${index}-full`} className={`${premiumSubPanelClass} space-y-3 p-4`}>
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0 flex-1 space-y-2">
                            <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{question.theme || `${t('interviewSheet.human.question')} ${index + 1}`}</p>
                            <Label htmlFor={`question-text-${index}`}>{t('interviewSheet.human.question')}</Label>
                            <Textarea
                              id={`question-text-${index}`}
                              value={question.question}
                              onChange={(event) => {
                                const nextQuestions = [...questions];
                                nextQuestions[index].question = event.target.value;
                                setQuestions(nextQuestions);
                              }}
                              disabled={isCompleted}
                              rows={2}
                              className={premiumFieldClass}
                            />
                          </div>
                          {!isCompleted ? (
                            <Button variant="ghost" size="sm" onClick={() => removeQuestion(index)}>
                              {t('interviewSheet.common.remove')}
                            </Button>
                          ) : null}
                        </div>
                        <div className="grid gap-4 xl:grid-cols-2">
                          <div className="space-y-2">
                            <Label htmlFor={`question-criteria-${index}`}>{t('interviewSheet.human.criteriaPlaceholder')}</Label>
                            <Textarea
                              id={`question-criteria-${index}`}
                              value={question.criteria}
                              onChange={(event) => {
                                const nextQuestions = [...questions];
                                nextQuestions[index].criteria = event.target.value;
                                setQuestions(nextQuestions);
                              }}
                              disabled={isCompleted}
                              rows={3}
                              className={premiumFieldClass}
                              placeholder={t('interviewSheet.human.criteriaPlaceholder')}
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor={`question-notes-${index}`}>{t('interviewSheet.human.notesPlaceholder')}</Label>
                            <Textarea
                              id={`question-notes-${index}`}
                              value={question.notes}
                              onChange={(event) => {
                                const nextQuestions = [...questions];
                                nextQuestions[index].notes = event.target.value;
                                setQuestions(nextQuestions);
                              }}
                              disabled={isCompleted}
                              rows={3}
                              className={premiumFieldClass}
                              placeholder={t('interviewSheet.human.notesPlaceholder')}
                            />
                          </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-4">
                          <Label htmlFor={`score-q-${index}`} className="min-w-[120px]">
                            {t('interviewSheet.common.score')}: {question.score}
                          </Label>
                          <input
                            id={`score-q-${index}`}
                            type="range"
                            min="0"
                            max="5"
                            step="0.5"
                            value={question.score}
                            onChange={(event) => {
                              const nextQuestions = [...questions];
                              nextQuestions[index].score = parseFloat(event.target.value);
                              setQuestions(nextQuestions);
                            }}
                            disabled={isCompleted}
                            className="flex-1"
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                <section className={`${premiumSubPanelClass} p-4`} aria-labelledby="human-scorecard-title">
                  <h3 id="human-scorecard-title" className="font-mono text-sm font-semibold uppercase tracking-[0.12em]">
                    {t('interviewSheet.human.viewHrGrid')}
                  </h3>
                  <div className="mt-4 space-y-4">
                        {scorecard.length === 0 ? (
                          <p className="text-sm text-muted-foreground">{t('interviewSheet.human.noHrGrid')}</p>
                        ) : (
                          scorecard.map((item, index) => (
                            <div key={`${item.criterion}-${index}`} className="space-y-3 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div>
                                  <h3 className="font-semibold">{item.criterion}</h3>
                                  <p className="mt-1 text-sm text-muted-foreground">{item.description}</p>
                                </div>
                                <Badge variant="outline">{t('interviewSheet.human.weight')} {(item.weight * 100).toFixed(0)}%</Badge>
                              </div>
                              <div className="flex items-center gap-4">
                                <Label htmlFor={`score-${index}`} className="min-w-[84px]">
                                  {t('interviewSheet.common.score')}: {item.score}
                                </Label>
                                <input
                                  id={`score-${index}`}
                                  type="range"
                                  min="0"
                                  max="5"
                                  step="0.5"
                                  value={item.score}
                                  onChange={(event) => {
                                    const nextScorecard = [...scorecard];
                                    nextScorecard[index].score = parseFloat(event.target.value);
                                    setScorecard(nextScorecard);
                                  }}
                                  disabled={isCompleted}
                                  className="flex-1"
                                />
                                <span className="min-w-[60px] text-center font-medium">{item.score} / 5</span>
                              </div>
                              <div className="space-y-2">
                                <Label htmlFor={`score-justification-${index}`}>{t('interviewSheet.human.justification')}</Label>
                                <Textarea
                                  id={`score-justification-${index}`}
                                  value={item.justification}
                                  onChange={(event) => {
                                    const nextScorecard = [...scorecard];
                                    nextScorecard[index].justification = event.target.value;
                                    setScorecard(nextScorecard);
                                  }}
                                  disabled={isCompleted}
                                  rows={3}
                                  className={premiumFieldClass}
                                />
                              </div>
                            </div>
                          ))
                        )}
                  </div>
                </section>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent id="interview-panel-ai" value="ai">
            <Card className={premiumCardClass}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Bot className="h-5 w-5" />
                  {t('interviewSheet.ai.workspaceTitle')}
                </CardTitle>
                <CardDescription>
                  {t('interviewSheet.ai.workspaceDescription')}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-8">
                <MetricStrip
                  ariaLabel={t('interviewSheet.ai.progressOverview')}
                  items={[
                    {
                      id: 'ai-plan',
                      label: t('interviewSheet.ai.plan'),
                      value: aiPlan ? t('interviewSheet.status.planReady') : t('interviewSheet.status.toPrepare'),
                      detail: t('interviewSheet.ai.planMetricDescription'),
                      tone: aiPlan ? 'success' : 'neutral',
                    },
                    {
                      id: 'ai-session',
                      label: t('interviewSheet.ai.sessionTitle'),
                      value: aiInterviewStatusLabel,
                      detail: aiSessionDetail,
                      tone: realtimeInterview?.status === 'completed' ? 'success' : 'neutral',
                    },
                  ]}
                />

                <Section
                  title={t('interviewSheet.ai.plan')}
                  description={t('interviewSheet.ai.planDescription')}
                  headingAs="h3"
                  divided={false}
                >
                <div className={`${premiumSubPanelClass} mb-4 space-y-3 p-4`}>
                  <div className="space-y-2">
                    <Label htmlFor="ai-plan-instructions">{t('interviewSheet.ai.planInstructions')}</Label>
                    <p id="ai-plan-instructions-help" className="text-sm leading-6 text-muted-foreground">
                      {t('interviewSheet.ai.planInstructionsDescription')}
                    </p>
                    <Textarea
                      id="ai-plan-instructions"
                      aria-describedby="ai-plan-instructions-help"
                      value={aiPlanInstructions}
                      onChange={(event) => setAiPlanInstructions(event.target.value)}
                      disabled={Boolean(aiPlan) || aiPlanPreparing || activePreparation?.status === 'pending' || isCompleted}
                      rows={4}
                      maxLength={4000}
                      className={premiumFieldClass}
                    />
                  </div>
                  <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="max-w-full whitespace-normal text-left"
                      disabled={Boolean(aiPlan) || aiPlanPreparing || activePreparation?.status === 'pending'}
                      onClick={() => void prepareAiPlan()}
                    >
                      <Bot className="mr-2 h-4 w-4 shrink-0" />
                      {aiPlanPreparing || activePreparation?.status === 'pending'
                        ? t('interviewSheet.ai.preparingAction')
                        : aiPlan
                          ? t('interviewSheet.ai.refreshPlanAction')
                          : t('interviewSheet.ai.prepareAction')}
                  </Button>
                </div>
                <details className={`${premiumSubPanelClass} p-4`} open>
                  <summary className="cursor-pointer text-sm font-semibold">
                    {t('interviewSheet.ai.planDetails')}
                  </summary>
                  <div className="mt-4 space-y-4">
                    {aiPlanLoading ? (
                      <p className="text-sm text-muted-foreground">{t('interviewSheet.ai.planLoading')}</p>
                    ) : !aiPlan ? (
                      <p className="text-sm text-muted-foreground">
                        {t('interviewSheet.ai.noPlan')}
                      </p>
                    ) : (
                      <>
                        <div className="grid gap-4 md:grid-cols-2">
                          <div className="space-y-2">
                            <Label htmlFor="ai-role-title">{t('interviewSheet.ai.roleTitle')}</Label>
                            <Textarea
                              id="ai-role-title"
                              value={aiPlan.roleTitle}
                              onChange={(event) => updateAiPlan((current) => ({
                                ...current,
                                roleTitle: event.target.value,
                              }))}
                              disabled={!canEditAiPlan}
                              rows={2}
                              className={premiumFieldClass}
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="ai-language">{t('interviewSheet.ai.language')}</Label>
                            <Textarea
                              id="ai-language"
                              value={aiPlan.languageHint || 'auto'}
                              disabled
                              rows={2}
                              className={premiumFieldClass}
                            />
                          </div>
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="ai-candidate-summary">{t('interviewSheet.ai.candidateContext')}</Label>
                          <Textarea
                            id="ai-candidate-summary"
                            value={aiPlan.candidateSummary}
                            onChange={(event) => updateAiPlan((current) => ({
                              ...current,
                              candidateSummary: event.target.value,
                            }))}
                            disabled={!canEditAiPlan}
                            rows={4}
                            className={premiumFieldClass}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="ai-job-summary">{t('interviewSheet.ai.jobContext')}</Label>
                          <Textarea
                            id="ai-job-summary"
                            value={aiPlan.jobSummary}
                            onChange={(event) => updateAiPlan((current) => ({
                              ...current,
                              jobSummary: event.target.value,
                            }))}
                            disabled={!canEditAiPlan}
                            rows={4}
                            className={premiumFieldClass}
                          />
                        </div>
                        <div className="space-y-4">
                          {aiPlan.stages.map((stage, index) => (
                            <div key={stage.id} className="space-y-3 rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4">
                              <div className="flex items-center gap-3">
                                <p className="text-sm font-semibold">{t('interviewSheet.ai.stage')} {index + 1}</p>
                              </div>
                              <div className="space-y-2">
                                <Label htmlFor={`ai-stage-label-${index}`}>{t('interviewSheet.ai.label')}</Label>
                                <Textarea
                                  id={`ai-stage-label-${index}`}
                                  value={stage.label}
                                  onChange={(event) => updateAiPlan((current) => ({
                                    ...current,
                                    stages: current.stages.map((currentStage, stageIndex) => (
                                      stageIndex === index
                                        ? { ...currentStage, label: event.target.value }
                                        : currentStage
                                    )),
                                  }))}
                                  disabled={!canEditAiPlan}
                                  rows={2}
                                  className={premiumFieldClass}
                                />
                              </div>
                              <Textarea
                                value={stage.objective}
                                onChange={(event) => updateAiPlan((current) => ({
                                  ...current,
                                  stages: current.stages.map((currentStage, stageIndex) => (
                                    stageIndex === index
                                      ? { ...currentStage, objective: event.target.value }
                                      : currentStage
                                  )),
                                }))}
                                disabled={!canEditAiPlan}
                                rows={3}
                                className={premiumFieldClass}
                                placeholder={t('interviewSheet.ai.objectivePlaceholder')}
                              />
                              <Textarea
                                value={arrayToLines(stage.sampleQuestions)}
                                onChange={(event) => updateAiPlan((current) => ({
                                  ...current,
                                  stages: current.stages.map((currentStage, stageIndex) => (
                                    stageIndex === index
                                      ? { ...currentStage, sampleQuestions: linesToArray(event.target.value) }
                                      : currentStage
                                  )),
                                }))}
                                disabled={!canEditAiPlan}
                                rows={4}
                                className={premiumFieldClass}
                                placeholder={t('interviewSheet.ai.questionsPlaceholder')}
                              />
                            </div>
                          ))}
                        </div>
                        <section className="space-y-4 border-t border-[color:var(--brain-ops-border)] pt-5" aria-labelledby="ai-scoring-rubric-title">
                          <div>
                            <h4 id="ai-scoring-rubric-title" className="font-mono text-sm font-semibold uppercase tracking-[0.12em]">
                              {t('interviewSheet.ai.scoringRubric')}
                            </h4>
                            <p className="mt-1 text-sm leading-6 text-muted-foreground">
                              {t('interviewSheet.ai.scoringRubricDescription')}
                            </p>
                          </div>
                          {aiPlan.scoringRubric.map((rubric, index) => (
                            <div key={`${rubric.category}-${index}`} className="grid gap-4 border-l-2 border-[color:var(--brain-ops-border-strong)] pl-4 lg:grid-cols-[0.75fr_1.25fr]">
                              <div className="space-y-2">
                                <Label htmlFor={`ai-rubric-category-${index}`}>{t('interviewSheet.ai.rubricCategory')}</Label>
                                <Textarea
                                  id={`ai-rubric-category-${index}`}
                                  value={rubric.category}
                                  onChange={(event) => updateAiPlan((current) => ({
                                    ...current,
                                    scoringRubric: current.scoringRubric.map((item, rubricIndex) => (
                                      rubricIndex === index ? { ...item, category: event.target.value } : item
                                    )),
                                  }))}
                                  disabled={!canEditAiPlan}
                                  rows={2}
                                  className={premiumFieldClass}
                                />
                              </div>
                              <div className="space-y-2">
                                <Label htmlFor={`ai-rubric-criteria-${index}`}>{t('interviewSheet.ai.rubricCriteria')}</Label>
                                <Textarea
                                  id={`ai-rubric-criteria-${index}`}
                                  value={arrayToLines(rubric.criteria)}
                                  onChange={(event) => updateAiPlan((current) => ({
                                    ...current,
                                    scoringRubric: current.scoringRubric.map((item, rubricIndex) => (
                                      rubricIndex === index ? { ...item, criteria: linesToArray(event.target.value) } : item
                                    )),
                                  }))}
                                  disabled={!canEditAiPlan}
                                  rows={4}
                                  className={premiumFieldClass}
                                />
                              </div>
                            </div>
                          ))}
                        </section>
                        {canEditAiPlan ? (
                          <Button
                            onClick={() => void saveAiPlan()}
                            disabled={!aiPlanDirty || aiPlanSaving}
                            className={premiumHeroPrimaryButtonClass}
                          >
                            {aiPlanSaving ? t('interviewSheet.ai.planSaving') : t('interviewSheet.ai.savePlan')}
                          </Button>
                        ) : null}
                      </>
                    )}
                  </div>
                </details>
                </Section>

                <Section
                  title={
                    <span className="flex items-center gap-2">
                      <CalendarDays className="h-5 w-5" />
                      {t('interviewSheet.ai.sessionTitle')}
                    </span>
                  }
                  description={t('interviewSheet.ai.sessionDescription')}
                  headingAs="h3"
                  actionsLabel={t('interviewSheet.ai.sessionActions')}
                  actions={renderSchedulerButton('ai', t('interviewSheet.actions.scheduleAi'))}
                >
                <p className="mb-5 text-sm leading-6 text-muted-foreground">
                  {aiPlan
                    ? t('interviewSheet.ai.sessionPlanReadyHelp')
                    : t('interviewSheet.ai.sessionBeforePlanHelp')}
                </p>
                <div className="grid gap-px overflow-hidden border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-border)] lg:grid-cols-[0.9fr_1.1fr]">
                  <div className="bg-[var(--brain-ops-surface-muted)] p-4 sm:p-5">
                    <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t('interviewSheet.ai.summary')}</p>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      {realtimeOverallAppreciation || t('interviewSheet.ai.noSummary')}
                    </p>
                  </div>
                  <div className="bg-[var(--brain-ops-surface-muted)] p-4 sm:p-5">
                    <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t('interviewSheet.ai.activity')}</p>
                    <p className="mt-2 text-sm text-muted-foreground">
                      {aiInterviewDateLabel}: {aiInterviewDate}
                    </p>
                    <p className="mt-1 text-sm text-muted-foreground">{interviewLocationLabel}</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Badge variant="outline">{realtimeTranscript.length} {t('interviewSheet.ai.transcriptTurns')}</Badge>
                      <Badge variant="outline">{recordingArtifacts.length} {t('interviewSheet.ai.recordingsCount')}</Badge>
                      <Badge variant="outline">{aiInterviewStatusLabel}</Badge>
                    </div>
                  </div>
                </div>

                <details className={`${premiumSubPanelClass} p-4`}>
                  <summary className="cursor-pointer text-sm font-semibold">
                    {t('interviewSheet.ai.recordings')}
                  </summary>
                  <div className="mt-4">
                    <RecordingLinks recordings={recordingArtifacts} title={t('interviewSheet.ai.videoRecordings')} />
                  </div>
                </details>

                <details className={`${premiumSubPanelClass} p-4`}>
                  <summary className="cursor-pointer text-sm font-semibold">
                    {t('interviewSheet.ai.fullTranscript')} ({realtimeTranscript.length} {t('interviewSheet.ai.turns')})
                  </summary>
                  <div className="mt-4 max-h-[26rem] space-y-3 overflow-y-auto pr-2">
                    {realtimeTranscript.length === 0 ? (
                      <p className="text-sm text-muted-foreground">{t('interviewSheet.ai.noTranscript')}</p>
                    ) : (
                      realtimeTranscript.map((turn, index) => (
                        <div
                          key={turn.id ?? `${turn.speaker}-${turn.ts}-${index}`}
                          className={`rounded-[var(--brain-ops-radius-structural)] border p-4 ${
                            turn.speaker === 'assistant'
                              ? 'border-[color:var(--brain-ops-accent)] bg-[var(--brain-ops-accent-soft)]'
                              : 'border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]'
                          }`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <Badge variant={turn.speaker === 'assistant' ? 'default' : 'outline'}>
                              {turn.speaker === 'assistant' ? 'BrainRH AI' : t('interviewSheet.common.candidate')}
                            </Badge>
                            <span className="text-xs text-muted-foreground">
                              {turn.ts
                                ? new Date(turn.ts).toLocaleTimeString(locale, {
                                    hour: '2-digit',
                                    minute: '2-digit',
                                    second: '2-digit',
                                  })
                                : ''}
                            </span>
                          </div>
                          <p className="mt-3 whitespace-pre-wrap text-sm leading-6">{turn.text}</p>
                        </div>
                      ))
                    )}
                  </div>
                </details>
                </Section>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent id="interview-panel-decision" value="decision">
            <Card className={premiumCardClass}>
              <CardHeader className="space-y-3">
                <div>
                  <CardTitle>{t('interviewSheet.decision.title')}</CardTitle>
                  <CardDescription>
                    {t('interviewSheet.decision.description')}
                  </CardDescription>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4">
                    <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t('interviewSheet.decision.verdict')}</p>
                    <select
                      id="verdict"
                      value={verdict}
                      onChange={(event) => setVerdict(event.target.value)}
                      disabled={isCompleted}
                      className={`mt-2 w-full rounded-md px-3 py-2 ${premiumFieldClass}`}
                    >
                      <option value="">{t('interviewSheet.decision.select')}</option>
                      <option value="retained">{t('interviewSheet.decision.retained')}</option>
                      <option value="reserved">{t('interviewSheet.decision.reserved')}</option>
                      <option value="rejected">{t('interviewSheet.decision.rejected')}</option>
                    </select>
                  </div>
                  <div className="rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4">
                    <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{t('interviewSheet.decision.weightedScore')}</p>
                    <p className="mt-2 text-3xl font-semibold">{weightedScoreLabel}</p>
                    <p className="mt-2 text-sm text-muted-foreground">
                      {additionalTests ? t('interviewSheet.decision.testsRequired') : t('interviewSheet.decision.noTests')}
                    </p>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="space-y-2">
                  <Label htmlFor="verdict-detail">{t('interviewSheet.common.hrAppreciation')}</Label>
                  <Textarea
                    id="verdict-detail"
                    value={verdictDetail}
                    onChange={(event) => setVerdictDetail(event.target.value)}
                    disabled={isCompleted}
                    rows={4}
                    className={premiumFieldClass}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="free-notes">{t('interviewSheet.decision.freeNotes')}</Label>
                  <Textarea
                    id="free-notes"
                    value={freeNotes}
                    onChange={(event) => setFreeNotes(event.target.value)}
                    disabled={isCompleted}
                    rows={5}
                    className={premiumFieldClass}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="residual-risks">{t('interviewSheet.decision.residualRisks')}</Label>
                  <Textarea
                    id="residual-risks"
                    value={residualRisks}
                    onChange={(event) => setResidualRisks(event.target.value)}
                    disabled={isCompleted}
                    rows={3}
                    className={premiumFieldClass}
                  />
                </div>

                <label className="flex items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    checked={additionalTests}
                    onChange={(event) => setAdditionalTests(event.target.checked)}
                    disabled={isCompleted}
                  />
                  {t('interviewSheet.decision.testsRequired')}
                </label>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </PageFrame>
  );
};
