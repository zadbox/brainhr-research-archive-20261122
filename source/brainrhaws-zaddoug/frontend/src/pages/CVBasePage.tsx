import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams, useParams } from 'react-router-dom';
import { Upload, FileText, Trash2, ArrowRight, Search, ChevronDown, ChevronUp, UserSearch } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Select } from '../components/ui/select';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import {
  ContextStrip,
  MetricStrip,
  OperationalList,
  OperationalListItem,
  OperationsDialog,
  OperationsDialogClose,
  OperationsDialogContent,
  OperationsDialogDescription,
  OperationsDialogFooter,
  OperationsDialogHeader,
  OperationsDialogTitle,
  OperationsErrorBanner,
  PageBackButton,
  PageFrame,
  PageHeader,
  RowActionMenu,
  Section,
  SystemState,
} from '../components/operations';
import { RealtimeInterviewButton } from '../components/interview/realtime/RealtimeInterviewButton';
import {
  getCandidateDisplayName,
  getCandidateEmail,
} from '../components/interview/realtime/realtimeInterviewHelpers';
import { SchedulerButton } from '../components/interview/scheduler/SchedulerButton';
import { cvsApi } from '../api/cvs';
import { interviewSheetApi, type InterviewSheet } from '../api/interviewSheet';
import type { CV, APIError } from '../api/types';
import { cn } from '../lib/utils';
import { formatMessage } from '../i18n/formatMessage';
import { useI18n } from '../i18n/useI18n';
import { candidateLabel } from '../lib/candidateLabel';
import { DisclosureSection } from '../components/operations/DisclosureSection';
import { CandidateProfileDetails } from '../components/candidates/CandidateProfileDetails';

type UploadErrorState =
  | { kind: 'http'; status: number }
  | { kind: 'processing' | 'invalid' | 'interrupted' };

const INITIAL_CANDIDATE_RENDER_COUNT = 24;
const CANDIDATE_RENDER_BATCH_SIZE = 24;

const isUploadErrorState = (value: unknown): value is UploadErrorState => {
  if (!value || typeof value !== 'object' || !('kind' in value)) return false;

  const kind = value.kind;
  if (kind === 'processing' || kind === 'invalid' || kind === 'interrupted') return true;

  return kind === 'http' && 'status' in value && typeof value.status === 'number';
};

const cancelUploadReader = async (
  reader: ReadableStreamDefaultReader<Uint8Array>
): Promise<void> => {
  try {
    await reader.cancel();
  } catch {
    // A terminal SSE event remains authoritative even if transport cleanup fails.
  }
};

export const CVBasePage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { projectId: urlProjectId } = useParams<{ projectId: string }>();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const candidateImportRef = useRef<HTMLDetailsElement>(null);
  const { t } = useI18n();
  const tRef = useRef(t);

  useEffect(() => {
    tRef.current = t;
  }, [t]);

  // If we arrive from a project (URL), preload that project. Otherwise default to "all"
  const [selectedProjectId, setSelectedProjectId] = useState<string>(urlProjectId || searchParams.get('project') || 'tous');
  const [cvs, setCvs] = useState<CV[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [dragging, setDragging] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedCVs, setExpandedCVs] = useState<Set<string>>(new Set());
  const [filterCompetence, setFilterCompetence] = useState('');
  // Company filter: "all" by default
  const [filterEntreprise, setFilterEntreprise] = useState<string>('tout');
  const [cvPendingDeletion, setCvPendingDeletion] = useState<{ id: string; name: string } | null>(null);
  const [deletingCv, setDeletingCv] = useState(false);
  const [deleteFailed, setDeleteFailed] = useState(false);
  // Parsing progress state
  const [parsing, setParsing] = useState(false);
  const [parsingProgress, setParsingProgress] = useState({ current: 0, total: 0 });
  const [uploadError, setUploadError] = useState<UploadErrorState | null>(null);
  const [sheetsByCandidate, setSheetsByCandidate] = useState<Record<string, InterviewSheet>>({});
  const [renderedCandidateCount, setRenderedCandidateCount] = useState(INITIAL_CANDIDATE_RENDER_COUNT);
  const [candidateImportOpen, setCandidateImportOpen] = useState(false);
  const candidateDeepLink = searchParams.get('candidate') || '';
  const appliedCandidateDeepLinkRef = useRef('');


  const fetchCVs = useCallback(async (projectId: string) => {
    try {
      setLoading(true);
      setError(null);

      // If projectId is "all", fetch every resume
      if (projectId === 'tous') {
        const data = await cvsApi.getAll();
        setCvs(data);
      } else {
        const data = await cvsApi.getByProject(projectId);
        setCvs(data);
      }
      setRenderedCandidateCount(INITIAL_CANDIDATE_RENDER_COUNT);
    } catch (err) {
      console.error('Failed to fetch CVs:', err);
      setError({
        code: 'CV_FETCH_ERROR',
        message: err instanceof Error ? err.message : tRef.current('candidates.error.load'),
        details: err,
      });
      setCvs([]);
    } finally {
      setLoading(false);
    }
  }, []);


  // Update selectedProjectId whenever urlProjectId changes
  useEffect(() => {
    if (urlProjectId && urlProjectId !== selectedProjectId) {
      setSelectedProjectId(urlProjectId);
    }
  }, [urlProjectId, selectedProjectId]);

  useEffect(() => {
    if (selectedProjectId) {
      fetchCVs(selectedProjectId);
    } else {
      setCvs([]);
      setLoading(false);
    }
  }, [selectedProjectId, fetchCVs]);

  useEffect(() => {
    const deepLinkKey = `${selectedProjectId}:${candidateDeepLink}`;
    if (!candidateDeepLink || appliedCandidateDeepLinkRef.current === deepLinkKey) return;
    const intendedCandidate = cvs.find((cv) => cv.cv === candidateDeepLink);
    if (!intendedCandidate) return;
    appliedCandidateDeepLinkRef.current = deepLinkKey;
    setSearchQuery(candidateDeepLink);
    setExpandedCVs((current) => new Set(current).add(candidateDeepLink));
    setRenderedCandidateCount(INITIAL_CANDIDATE_RENDER_COUNT);
  }, [candidateDeepLink, cvs, selectedProjectId]);

  useEffect(() => {
    const fetchSheets = async () => {
      try {
        if (!selectedProjectId || selectedProjectId === 'tous') return;
        const res = await interviewSheetApi.listAll({ job_id: selectedProjectId });
        const map: Record<string, InterviewSheet> = {};
        res.sheets.forEach((s) => { map[s.candidate_id] = s; });
        setSheetsByCandidate(map);
      } catch (err) {
        console.error('Erreur chargement fiches entretien', err);
      }
    };
    fetchSheets();
  }, [selectedProjectId]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setSelectedFiles(Array.from(e.target.files));
      setUploadError(null);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files) {
      setSelectedFiles(Array.from(e.dataTransfer.files));
      setUploadError(null);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  };

  const handleDragLeave = () => {
    setDragging(false);
  };

  const handleUploadAndParse = async () => {
    console.log('🔵 handleUploadAndParse called');
    console.log('📁 selectedFiles:', selectedFiles);
    console.log('📂 selectedProjectId:', selectedProjectId);

    // Prevent double-clicks
    if (parsing) {
      console.log('⚠️ Parsing already in progress, ignoring click');
      return;
    }

    if (selectedFiles.length === 0) {
      console.log('❌ No files selected');
      setError({
        message: t('candidates.error.selectFile'),
        code: 'NO_FILES_SELECTED'
      });
      return;
    }

    if (!selectedProjectId || selectedProjectId === 'tous') {
      console.log('❌ No project selected');
      setError({
        message: t('candidates.error.selectProject'),
        code: 'NO_PROJECT_SELECTED'
      });
      return;
    }

    console.log('✅ Validation passed, starting upload...');

    setParsing(true);
    setParsingProgress({ current: 0, total: selectedFiles.length });
    setError(null);
    setUploadError(null);

    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

    try {
      // Upload files via FormData + SSE parsing
      const formData = new FormData();
      selectedFiles.forEach((file) => {
        formData.append('files', file);
      });
      console.log('📦 FormData created with', selectedFiles.length, 'files');

      const urlParams = new URLSearchParams();
      urlParams.append('project_id', selectedProjectId);
      const url = `${cvsApi.getParseStreamUrl()}?${urlParams.toString()}`;
      console.log('🌐 Fetch URL:', url);

      console.log('⏳ Starting fetch...');
      const response = await fetch(url, {
        method: 'POST',
        body: formData,
      });
      console.log('📨 Response received:', response.status, response.statusText);

      if (!response.ok) {
        throw { kind: 'http', status: response.status } satisfies UploadErrorState;
      }

      console.log('✅ Response OK, starting to read stream...');

      // Read SSE stream and update progress
      reader = response.body?.getReader() ?? null;
      const decoder = new TextDecoder();

      if (!reader) {
        console.log('❌ No response body/reader');
        throw { kind: 'invalid' } satisfies UploadErrorState;
      }

      console.log('📖 Reader created, starting to read chunks...');
      let buffer = '';
      let chunkCount = 0;
      let doneReceived = false;
      let terminalReceived = false;

      while (!terminalReceived) {
        const { done, value } = await reader.read();
        chunkCount++;
        console.log(`📦 Chunk ${chunkCount} received:`, { done, valueLength: value?.length });

        if (done) {
          console.log('✅ Stream reading done');
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || '';

        console.log(`📝 Processing ${frames.length} SSE frames`);
        for (const frame of frames) {
          if (!frame.trim()) continue;

          const eventMatch = frame.match(/^event:\s*(\S+)\s*$/m);
          const dataMatch = frame.match(/^data:\s*(.+)\s*$/m);

          if (!eventMatch || !dataMatch) {
            throw { kind: 'invalid' } satisfies UploadErrorState;
          }

          const eventType = eventMatch[1];
          let data: unknown;
          try {
            data = JSON.parse(dataMatch[1]);
          } catch {
            throw { kind: 'invalid' } satisfies UploadErrorState;
          }

          if (eventType === 'progress') {
            if (
              !data ||
              typeof data !== 'object' ||
              !('current' in data) ||
              !('total' in data) ||
              typeof data.current !== 'number' ||
              typeof data.total !== 'number'
            ) {
              throw { kind: 'invalid' } satisfies UploadErrorState;
            }

            setParsingProgress({ current: data.current, total: data.total });
          } else if (eventType === 'error') {
            terminalReceived = true;
            await cancelUploadReader(reader);
            throw { kind: 'processing' } satisfies UploadErrorState;
          } else if (eventType === 'done') {
            doneReceived = true;
            terminalReceived = true;
            await cancelUploadReader(reader);
            break;
          }
        }
      }

      if (!doneReceived) {
        throw { kind: 'interrupted' } satisfies UploadErrorState;
      }

      console.log('✅ Parsing complete, refreshing resumes...');

      await fetchCVs(selectedProjectId);
      console.log('✅ Resumes reloaded successfully');

      // Clear selected files
      setSelectedFiles([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }

    } catch (err) {
      const nextUploadError = isUploadErrorState(err)
        ? err
        : { kind: 'interrupted' as const };
      setUploadError(nextUploadError);
      console.error('❌ Candidate upload ended without a successful terminal event');
    } finally {
      if (reader) {
        await cancelUploadReader(reader);
      }
      setParsing(false);
      setParsingProgress({ current: 0, total: 0 });
    }
  };

  const requestDeleteCV = (cvId: string, candidateName: string) => {
    setDeleteFailed(false);
    setCvPendingDeletion({ id: cvId, name: candidateName });
  };

  const handleDeleteCV = async () => {
    if (!cvPendingDeletion) return;

    setDeletingCv(true);
    setDeleteFailed(false);
    try {
      await cvsApi.delete(cvPendingDeletion.id);
      if (selectedProjectId) {
        await fetchCVs(selectedProjectId);
      }
      setCvPendingDeletion(null);
    } catch {
      setDeleteFailed(true);
    } finally {
      setDeletingCv(false);
    }
  };

  const toggleCVExpand = (cvId: string) => {
    setExpandedCVs(prev => {
      const next = new Set(prev);
      if (next.has(cvId)) {
        next.delete(cvId);
      } else {
        next.add(cvId);
      }
      return next;
    });
  };

  // Extraire la liste unique des entreprises depuis les projets des CVs
  const uniqueEntreprises = useMemo(() => Array.from(
    new Set(cvs.flatMap((cv) => cv.enterprise_nom ? [cv.enterprise_nom] : []))
  ).sort(), [cvs]);

  // Filter CVs based on search and filters
  // Si on arrive depuis un projet (urlProjectId), pas de filtre entreprise
  const filteredCVs = useMemo(() => {
    const normalizedSearch = searchQuery.toLowerCase();
    const normalizedCompetence = filterCompetence.toLowerCase();

    return cvs.filter((cv) => {
      const matchesSearch =
        !normalizedSearch ||
        cv.identite?.nom?.toLowerCase().includes(normalizedSearch) ||
        cv.identite?.prenom?.toLowerCase().includes(normalizedSearch) ||
        cv.identite?.email?.toLowerCase().includes(normalizedSearch) ||
        cv.titre?.toLowerCase().includes(normalizedSearch) ||
        cv.cv.toLowerCase().includes(normalizedSearch);

      const matchesCompetence =
        !normalizedCompetence ||
        cv.competences_techniques.some((competence) => competence.toLowerCase().includes(normalizedCompetence)) ||
        cv.competences_transversales.some((competence) => competence.toLowerCase().includes(normalizedCompetence));

      const matchesEntreprise = urlProjectId
        ? true
        : (!filterEntreprise || filterEntreprise === 'tout' || cv.enterprise_nom === filterEntreprise);

      return matchesSearch && matchesCompetence && matchesEntreprise;
    });
  }, [cvs, filterCompetence, filterEntreprise, searchQuery, urlProjectId]);

  const { avgSkills, representedCompanies } = useMemo(() => {
    if (cvs.length === 0) {
      return { avgSkills: 0, representedCompanies: 0 };
    }

    const companies = new Set<string>();
    const skillCount = cvs.reduce((total, cv) => {
      if (cv.enterprise_nom) companies.add(cv.enterprise_nom);
      return total + cv.competences_techniques.length + cv.competences_transversales.length;
    }, 0);

    return {
      avgSkills: Math.round(skillCount / cvs.length),
      representedCompanies: companies.size,
    };
  }, [cvs]);

  const visibleCVs = useMemo(
    () => filteredCVs.slice(0, renderedCandidateCount),
    [filteredCVs, renderedCandidateCount]
  );

  const parsePercent = parsingProgress.total > 0
    ? Math.round((parsingProgress.current / parsingProgress.total) * 100)
    : 0;
  const uploadErrorContent = (() => {
    if (!uploadError) return null;

    switch (uploadError.kind) {
      case 'http':
        return {
          title: t('candidates.upload.error.http.title'),
          description: formatMessage(t('candidates.upload.error.http.description'), {
            status: uploadError.status,
          }),
        };
      case 'processing':
        return {
          title: t('candidates.upload.error.processing.title'),
          description: t('candidates.upload.error.processing.description'),
        };
      case 'invalid':
        return {
          title: t('candidates.upload.error.invalid.title'),
          description: t('candidates.upload.error.invalid.description'),
        };
      case 'interrupted':
        return {
          title: t('candidates.upload.error.interrupted.title'),
          description: t('candidates.upload.error.interrupted.description'),
        };
    }
  })();

  const openCandidateImport = () => {
    setCandidateImportOpen(true);
    requestAnimationFrame(() => {
      candidateImportRef.current?.scrollIntoView({ block: 'nearest' });
      candidateImportRef.current?.querySelector<HTMLElement>('summary')?.focus();
    });
  };

  const candidateListActions = cvs.length > 0
    ? {
        actionsLabel: t('candidates.upload.title'),
        actions: (
          <Button type="button" variant="outline" onClick={openCandidateImport}>
            <Upload data-icon="inline-start" />
            {t('candidates.upload.action')}
          </Button>
        ),
      } as const
    : { actions: undefined, actionsLabel: undefined } as const;

  const candidateImportSection = (
    <DisclosureSection
      data-tour="cv-import"
      ref={candidateImportRef}
      open={cvs.length === 0 || candidateImportOpen || parsing || selectedFiles.length > 0 || Boolean(uploadErrorContent)}
      onToggle={(event) => setCandidateImportOpen(event.currentTarget.open)}
      title={t('candidates.upload.title')}
      description={urlProjectId
        ? t('candidates.upload.description')
        : t('candidates.upload.workspaceDescription')}
    >
      <div className="flex flex-col gap-4">
        <div
          role="button"
          tabIndex={0}
          aria-label={t('candidates.upload.dropzone')}
          className={cn(
            'cursor-pointer rounded-[var(--brain-ops-radius-structural)] border-2 border-dashed p-8 text-center transition-colors motion-reduce:transition-none',
            dragging
              ? 'border-[color:var(--brain-ops-accent)] bg-[var(--brain-ops-accent-soft)]'
              : 'border-[color:var(--brain-ops-border)] hover:border-[color:var(--brain-ops-accent)] hover:bg-[var(--brain-ops-accent-soft)]'
          )}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              fileInputRef.current?.click();
            }
          }}
        >
          <Upload aria-hidden="true" className="mx-auto mb-4 size-12 text-[var(--brain-ops-text-muted)]" />
          <p className="mb-2 text-sm font-medium">
            {t('candidates.upload.dropzone')}
          </p>
          <p className="text-xs text-[var(--brain-ops-text-muted)]">
            {t('candidates.upload.formats')}
          </p>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.docx"
            onChange={handleFileSelect}
            className="hidden"
          />
        </div>

        {selectedFiles.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium">{selectedFiles.length} {t('candidates.upload.filesSelected')}</p>
            <ul className="flex flex-col gap-1">
              {selectedFiles.map((file, index) => (
                <li key={index} className="flex items-center gap-2 text-sm">
                  <FileText aria-hidden="true" className="size-4 text-[var(--brain-ops-text-muted)]" />
                  <span className="flex-1 truncate">{file.name}</span>
                  <Badge variant="secondary">{(file.size / 1024).toFixed(1)} KB</Badge>
                </li>
              ))}
            </ul>
          </div>
        )}

        <Button
          onClick={handleUploadAndParse}
          className="w-full"
          size="lg"
          disabled={parsing || selectedFiles.length === 0}
        >
          <Upload data-icon="inline-start" />
          {parsing ? t('candidates.upload.parsing') : t('candidates.upload.action')}
        </Button>

        {uploadErrorContent && (
          <SystemState
            kind="error"
            title={uploadErrorContent.title}
            description={uploadErrorContent.description}
          />
        )}

        {parsing && (
          <div className="flex w-full flex-col gap-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-[var(--brain-ops-text-muted)]">
                {t('candidates.upload.progress')}: {parsingProgress.current} / {parsingProgress.total}
              </span>
              <span className="font-medium">
                {parsePercent}%
              </span>
            </div>
            <div
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={parsePercent}
              aria-label={t('candidates.upload.progress')}
              className="h-2.5 w-full overflow-hidden rounded-full bg-[var(--brain-ops-surface-muted)]"
            >
              <div
                className="h-2.5 rounded-full bg-[var(--brain-ops-accent)] transition-all duration-300 motion-reduce:transition-none"
                style={{ width: `${parsePercent}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </DisclosureSection>
  );

  if (loading && selectedProjectId) {
    return (
      <PageFrame>
        <SystemState
          kind="loading"
          title={t('candidates.loading')}
          indicator={<FileText className="size-5" />}
        />
      </PageFrame>
    );
  }

  return (
    <PageFrame>
      <PageHeader
        eyebrow={urlProjectId ? t('candidates.badge.project') : t('candidates.badge.global')}
        backAction={urlProjectId ? (
          <PageBackButton
            onClick={() => navigate(`/projects/${urlProjectId}`)}
            aria-label={t('common.back')}
          />
        ) : undefined}
        title={urlProjectId ? t('candidates.title.project') : t('candidates.title.global')}
        description={t('candidates.description')}
        actionsLabel={t('candidates.header.actions')}
        actions={
          urlProjectId ? (
            <>
              <Button
                variant="outline"
                onClick={() => navigate(`/projects/${urlProjectId}/candidates/search`)}
              >
                <UserSearch data-icon="inline-start" />
                {t('candidates.action.searchProfiles')}
              </Button>
              {cvs.length > 0 && (
                <Button onClick={() => navigate(`/projects/${urlProjectId}/matching`)}>
                  {t('candidates.action.nextMatching')}
                  <ArrowRight data-icon="inline-end" />
                </Button>
              )}
            </>
          ) : null
        }
      />

      {error && <OperationsErrorBanner error={error} />}

      <MetricStrip
        data-tour="cv-summary"
        ariaLabel={t('candidates.snapshot')}
        items={[
          {
            id: 'candidates',
            label: t('candidates.metric.candidates'),
            value: cvs.length,
            detail: t('candidates.metric.ready'),
          },
          {
            id: 'skills',
            label: t('candidates.metric.skills'),
            value: avgSkills,
            detail: t('candidates.metric.skillsDescription'),
          },
          {
            id: 'coverage',
            label: t('candidates.metric.coverage'),
            value: representedCompanies,
            detail: urlProjectId ? t('candidates.metric.projectScope') : t('candidates.metric.clientsRepresented'),
          },
        ]}
      />

      {cvs.length === 0 && candidateImportSection}

      {/* CVs List */}
      {selectedProjectId && selectedProjectId !== '' && (
        <Section
          data-tour="cv-library"
          title={`${t('candidates.list.title')} (${filteredCVs.length}/${cvs.length})`}
          {...candidateListActions}
        >
          <div className="flex flex-col gap-5">
            {/* Search and Filters */}
            {cvs.length > 0 && (
              <ContextStrip
                data-tour="cv-filters"
                ariaLabel={t('candidates.filters.aria')}
                items={[
                  {
                    id: 'scope',
                    label: t(urlProjectId ? 'common.project' : 'common.companyScope'),
                    value: urlProjectId
                      ? t('candidates.metric.projectScope')
                      : (!filterEntreprise || filterEntreprise === 'tout'
                        ? t('candidates.filter.allClients')
                        : filterEntreprise),
                  },
                ]}
                actionsLabel={t('candidates.filters.aria')}
                actions={
                  <>
                    <div className="flex w-full min-w-0 flex-col gap-1 sm:w-64">
                      <Label htmlFor="cv-search">{t('candidates.searchLabel')}</Label>
                      <Input
                        id="cv-search"
                        value={searchQuery}
                        onChange={(e) => {
                          setSearchQuery(e.target.value);
                          setRenderedCandidateCount(INITIAL_CANDIDATE_RENDER_COUNT);
                        }}
                        placeholder={t('candidates.search.placeholder')}
                      />
                    </div>
                    <div className="flex w-full min-w-0 flex-col gap-1 sm:w-64">
                      <Label htmlFor="cv-skill-filter">{t('candidates.filter.skillLabel')}</Label>
                      <Input
                        id="cv-skill-filter"
                        value={filterCompetence}
                        onChange={(e) => {
                          setFilterCompetence(e.target.value);
                          setRenderedCandidateCount(INITIAL_CANDIDATE_RENDER_COUNT);
                        }}
                        placeholder={t('candidates.filter.skill')}
                      />
                    </div>
                    {/* Company filter only when coming from the sidebar */}
                    {!urlProjectId && (
                      <div className="flex w-full min-w-0 flex-col gap-1 sm:w-64">
                        <Label htmlFor="cv-company-filter">{t('candidates.filter.companyLabel')}</Label>
                        <Select
                          id="cv-company-filter"
                          value={filterEntreprise}
                          onChange={(e) => {
                            setFilterEntreprise(e.target.value);
                            setRenderedCandidateCount(INITIAL_CANDIDATE_RENDER_COUNT);
                          }}
                        >
                          <option value="tout">{t('candidates.filter.allClients')}</option>
                          {uniqueEntreprises.map((entreprise) => (
                            <option key={entreprise} value={entreprise}>
                              {entreprise}
                            </option>
                          ))}
                        </Select>
                      </div>
                    )}
                  </>
                }
              />
            )}

            {cvs.length === 0 ? (
              <SystemState
                kind="empty"
                indicator={<FileText className="size-5" />}
                title={t('candidates.empty.title')}
                description={t('candidates.empty.description')}
              />
            ) : filteredCVs.length === 0 ? (
              <SystemState
                kind="empty"
                indicator={<Search className="size-5" />}
                title={t('candidates.noResults.title')}
                description={t('candidates.noResults.description')}
              />
            ) : (
              <>
                <OperationalList ariaLabel={t('candidates.list.title')}>
                {visibleCVs.map((cv) => {
                  const isExpanded = expandedCVs.has(cv.cv);
                  const displayName = candidateLabel(
                    { candidateId: cv.cv, identity: cv.identite },
                    t('candidates.fallbackLabel')
                  );
                  return (
                    <OperationalListItem
                      key={cv.cv}
                      className="sm:items-start [&>div:first-child]:flex-1 [&>div:first-child>div]:flex-1"
                      primary={displayName}
                      secondary={
                        <div className="flex flex-col gap-0.5">
                          <span>{cv.titre || t('candidates.noTitle')}</span>
                          {cv.identite?.email && (
                            <span>{cv.identite.email}</span>
                          )}
                          {cv.identite?.telephone && (
                            <span>{cv.identite.telephone}</span>
                          )}
                        </div>
                      }
                      metadata={
                        <div className="flex flex-col gap-2">
                          {/* Technical skills */}
                          {cv.competences_techniques.length > 0 && (
                            <div>
                              <p className="mb-1 text-xs font-medium text-[var(--brain-ops-text)]">
                                {t('candidates.technicalSkills')}
                              </p>
                              <div className="flex flex-wrap gap-1">
                                {(isExpanded ? cv.competences_techniques : cv.competences_techniques.slice(0, 5)).map((comp, idx) => (
                                  <Badge key={idx} variant="secondary" className="text-xs">
                                    {comp}
                                  </Badge>
                                ))}
                                {!isExpanded && cv.competences_techniques.length > 5 && (
                                  <Badge variant="outline" className="text-xs">
                                    +{cv.competences_techniques.length - 5}
                                  </Badge>
                                )}
                              </div>
                            </div>
                          )}

                          {/* Expanded candidate profile */}
                          {isExpanded && (
                            <CandidateProfileDetails cv={cv} />
                          )}
                        </div>
                      }
                      actionsLabel={formatMessage(t('candidates.list.itemActions'), { candidate: displayName })}
                      actions={
                        <>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => toggleCVExpand(cv.cv)}
                            aria-expanded={isExpanded}
                            aria-label={isExpanded
                              ? formatMessage(t('candidates.aria.collapse'), { candidate: displayName })
                              : formatMessage(t('candidates.aria.expand'), { candidate: displayName })}
                          >
                            {isExpanded ? (
                              <ChevronUp data-icon="inline-start" />
                            ) : (
                              <ChevronDown data-icon="inline-start" />
                            )}
                          </Button>
                          {selectedProjectId && selectedProjectId !== 'tous' && (
                            <>
                              <SchedulerButton
                                candidateId={cv.cv}
                                jobId={selectedProjectId}
                                matchingId="manual"
                                candidateName={getCandidateDisplayName(cv)}
                                candidateEmail={getCandidateEmail(cv) || sheetsByCandidate[cv.cv]?.data.identite?.email || null}
                                existingSheetId={sheetsByCandidate[cv.cv]?.id}
                                initialData={{
                                  scheduled_at: sheetsByCandidate[cv.cv]?.scheduled_at,
                                  end_at: sheetsByCandidate[cv.cv]?.data.scheduling?.end_at,
                                  location: sheetsByCandidate[cv.cv]?.location,
                                  scheduler_notes: sheetsByCandidate[cv.cv]?.scheduler_notes,
                                  interviewer: sheetsByCandidate[cv.cv]?.interviewer,
                                  appointment_id: sheetsByCandidate[cv.cv]?.data.scheduling?.appointment_id,
                                }}
                                onUpdate={async () => {
                                  try {
                                    const res = await interviewSheetApi.listAll({ job_id: selectedProjectId });
                                    const map: Record<string, InterviewSheet> = {};
                                    res.sheets.forEach((s) => { map[s.candidate_id] = s; });
                                    setSheetsByCandidate(map);
                                  } catch (err) {
                                    console.error(err);
                                  }
                                }}
                                variant="outline"
                                size="sm"
                              />
                              <RealtimeInterviewButton
                                projectId={selectedProjectId}
                                candidateId={cv.cv}
                                matchingId="manual"
                                interviewSheetId={sheetsByCandidate[cv.cv]?.id}
                                source="cv-base"
                              />
                            </>
                          )}
                          <RowActionMenu
                            triggerLabel={t('rowActions.trigger')}
                            menuLabel={formatMessage(t('candidates.list.itemActions'), { candidate: displayName })}
                            items={[{
                              id: 'delete',
                              label: formatMessage(t('candidates.aria.delete'), { candidate: displayName }),
                              icon: <Trash2 className="size-4" />,
                              onSelect: () => requestDeleteCV(cv.cv, displayName),
                              destructive: true,
                            }]}
                          />
                        </>
                      }
                    />
                  );
                })}
                </OperationalList>
                {renderedCandidateCount < filteredCVs.length && (
                  <div className="flex justify-center border-t border-[color:var(--brain-ops-border)] pt-4">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setRenderedCandidateCount((currentCount) => Math.min(
                        currentCount + CANDIDATE_RENDER_BATCH_SIZE,
                        filteredCVs.length
                      ))}
                    >
                      {t('candidates.list.loadMore')}
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        </Section>
      )}

      {cvs.length > 0 && candidateImportSection}

      <OperationsDialog
        open={cvPendingDeletion !== null}
        onOpenChange={(open) => {
          if (!open && !deletingCv) {
            setCvPendingDeletion(null);
            setDeleteFailed(false);
          }
        }}
      >
        <OperationsDialogContent aria-describedby="candidate-delete-description">
          <OperationsDialogClose disabled={deletingCv} />
          <OperationsDialogHeader>
            <OperationsDialogTitle>{t('candidates.delete.title')}</OperationsDialogTitle>
            <OperationsDialogDescription id="candidate-delete-description">
              {formatMessage(t('candidates.delete.description'), {
                candidate: cvPendingDeletion?.name || t('candidates.fallbackLabel'),
              })}
            </OperationsDialogDescription>
          </OperationsDialogHeader>
          {deleteFailed && (
            <SystemState
              kind="error"
              title={t('candidates.delete.error.title')}
              description={t('candidates.delete.error.description')}
            />
          )}
          <OperationsDialogFooter>
            <Button
              variant="outline"
              onClick={() => setCvPendingDeletion(null)}
              disabled={deletingCv}
            >
              {t('common.cancel')}
            </Button>
            <Button variant="destructive" onClick={() => void handleDeleteCV()} disabled={deletingCv}>
              {deletingCv ? t('common.deleting') : t('common.delete')}
            </Button>
          </OperationsDialogFooter>
        </OperationsDialogContent>
      </OperationsDialog>
    </PageFrame>
  );
};
