import { useState, useCallback, useEffect } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { Upload, FileText, CheckCircle2, XCircle, Clock, ChevronDown, ChevronUp, ArrowRight } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Progress } from '../components/ui/progress';
import { Badge } from '../components/ui/badge';
import {
  ContextStrip,
  MetricStrip,
  OperationalList,
  OperationalListItem,
  OperationsErrorBanner,
  PageBackButton,
  PageFrame,
  PageHeader,
  Section,
  SystemState,
} from '../components/operations';
import { cvsApi } from '../api/cvs';
import type { APIError, SSEProgressEvent, CVParseResult, CV } from '../api/types';
import { formatMessage } from '../i18n/formatMessage';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/utils';

interface ParseResult {
  filename: string;
  success: boolean;
  cv?: string;
  error?: string;
  data?: CV;
}

interface StreamEvent {
  type: string;
  data: unknown;
}

export const CVParsingPage: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const { t } = useI18n();

  const [selectedFiles, setSelectedFiles] = useState<File[]>(
    location.state?.files || []
  );
  const projectId = location.state?.projectId || null;
  const contextProjectId = projectId || routeProjectId || null;
  const [parsing, setParsing] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0, message: '' });
  const [results, setResults] = useState<ParseResult[]>([]);
  const [error, setError] = useState<APIError | null>(null);
  const [dragging, setDragging] = useState(false);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [endTime, setEndTime] = useState<number | null>(null);
  const [, setTick] = useState(0);
  const [expandedResults, setExpandedResults] = useState<Set<number>>(new Set());

  // Force timer updates every 100ms during parsing
  useEffect(() => {
    let intervalId: number | null = null;

    if (parsing && startTime) {
      intervalId = setInterval(() => {
        setTick(t => t + 1);
      }, 100) as unknown as number;
    }

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [parsing, startTime]);

  const handleMessage = useCallback((event: StreamEvent) => {
    if (event.type === 'progress') {
      const progressData = event.data as SSEProgressEvent;
      setProgress({
        current: progressData.current ?? 0,
        total: progressData.total ?? 0,
        message: progressData.message ?? '',
      });
    } else if (event.type === 'result') {
      const resultData = event.data as CVParseResult;
      setResults((prev) => [
        ...prev,
        {
          filename: resultData.cv || resultData.filename || 'unknown',
          success: resultData.success,
          cv: resultData.data?.cv || resultData.filename,
          error: resultData.error,
          data: resultData.data,
        },
      ]);
    } else if (event.type === 'done') {
      setParsing(false);
      setEndTime(Date.now());
    } else if (event.type === 'error') {
      setError(event.data as APIError);
      setParsing(false);
      setEndTime(Date.now());
    }
  }, []);

  // useSSE hook removed - now using manual fetch with POST

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setSelectedFiles(Array.from(e.target.files));
      setResults([]);
      setError(null);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files) {
      setSelectedFiles(Array.from(e.dataTransfer.files));
      setResults([]);
      setError(null);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  };

  const handleDragLeave = () => {
    setDragging(false);
  };

  const handleStartParsing = async () => {
    if (selectedFiles.length === 0) return;

    setResults([]);
    setError(null);
    setProgress({ current: 0, total: selectedFiles.length, message: t('parsing.progress.uploading') });
    setStartTime(Date.now());
    setEndTime(null);
    setParsing(true);

    try {
      // Upload files via FormData
      const formData = new FormData();
      selectedFiles.forEach((file) => {
        formData.append('files', file);
      });

      // Construire l'URL avec project_id si disponible
      const urlParams = new URLSearchParams();
      if (projectId) {
        urlParams.append('project_id', projectId);
      }
      const url = `${cvsApi.getParseStreamUrl()}?${urlParams.toString()}`;

      console.log(`📤 Uploading ${selectedFiles.length} files to ${url}`);

      // Start parsing with POST + SSE
      const response = await fetch(url, {
        method: 'POST',
        body: formData,
      });

      console.log(`📥 Response status: ${response.status}`);

      if (!response.ok) {
        const errorText = await response.text();
        console.error('❌ Error response:', errorText);
        throw new Error(`HTTP ${response.status}: ${errorText}`);
      }

      // Read SSE stream
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error('No response body');
      }

      console.log('📡 Reading SSE stream...');
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          console.log('✅ Stream finished');
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.trim()) continue;

          const eventMatch = line.match(/^event: (.+)$/m);
          const dataMatch = line.match(/^data: (.+)$/m);

          if (eventMatch && dataMatch) {
            const eventType = eventMatch[1];
            const eventData = JSON.parse(dataMatch[1]);

            console.log(`📨 Event: ${eventType}`, eventData);
            handleMessage({ type: eventType, data: eventData });
          }
        }
      }
    } catch (error: unknown) {
      console.error('❌ Parsing error:', error);
      setError({
        code: 'PARSE_ERROR',
        message: error instanceof Error ? error.message : t('parsing.error.unexpected'),
        details: error,
      });
      setParsing(false);
      setEndTime(Date.now());
    }
  };

  const handleStop = () => {
    // TODO: Implement stream cancellation
    setParsing(false);
    setEndTime(Date.now());
  };

  const toggleResultExpand = (index: number) => {
    setExpandedResults(prev => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const successCount = results.filter((r) => r.success).length;
  const failedCount = results.filter((r) => !r.success).length;
  const duration = startTime && endTime ? ((endTime - startTime) / 1000).toFixed(1) : null;

  return (
    <PageFrame>
      <PageHeader
        eyebrow={t('parsing.eyebrow')}
        backAction={contextProjectId ? (
          <PageBackButton
            onClick={() => navigate(`/projects/${contextProjectId}`)}
            aria-label={t('parsing.backToProject')}
          />
        ) : undefined}
        title={t('parsing.title')}
        description={t('parsing.description')}
      />

      <ContextStrip
        ariaLabel={t('parsing.context.aria')}
        items={[
          {
            id: 'scope',
            label: t('parsing.context.scope'),
            value: contextProjectId || t('parsing.context.workspace'),
            detail: contextProjectId ? t('parsing.context.project') : undefined,
          },
          {
            id: 'formats',
            label: t('parsing.context.formats'),
            value: 'PDF · DOCX',
            detail: t('parsing.context.maxSize'),
          },
          {
            id: 'status',
            label: t('parsing.context.status'),
            value: parsing
              ? t('parsing.status.running')
              : results.length > 0
                ? t('parsing.status.completed')
                : t('parsing.status.ready'),
          },
        ]}
      />

      {error && <OperationsErrorBanner error={error} />}

      {/* File Upload */}
      {!parsing && results.length === 0 && (
        <Section
          title={t('parsing.upload.title')}
          description={t('parsing.upload.description')}
        >
            <label
              htmlFor="resume-file-input"
              className={cn(
                'block cursor-pointer border border-dashed px-5 py-10 text-center transition-colors sm:px-8',
                dragging
                  ? 'border-[var(--brain-ops-accent)] bg-[var(--brain-ops-accent-soft)]'
                  : 'border-[color:var(--brain-ops-border-strong)] bg-[var(--brain-ops-surface)]',
                'hover:border-[var(--brain-ops-accent)] hover:bg-[var(--brain-ops-surface-muted)]',
                'focus-within:border-[var(--brain-ops-accent)] focus-within:ring-2 focus-within:ring-[var(--brain-ops-accent-soft)]'
              )}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
            >
              <Upload className="mx-auto mb-4 size-8 text-[var(--brain-ops-text-muted)]" />
              <p className="mb-2 text-sm font-medium">{t('parsing.upload.drop')}</p>
              <p id="parsing-upload-formats" className="text-xs text-[var(--brain-ops-text-muted)]">
                {t('parsing.upload.formats')}
              </p>
              <input
                id="resume-file-input"
                type="file"
                multiple
                accept=".pdf,.docx"
                onChange={handleFileSelect}
                aria-describedby="parsing-upload-formats"
                className="sr-only"
              />
            </label>

            {selectedFiles.length > 0 && (
              <div className="mt-6 space-y-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-sm font-medium">
                    {formatMessage(t('parsing.upload.selected'), { count: selectedFiles.length })}
                  </p>
                  <Button onClick={handleStartParsing} size="lg">
                    <Upload data-icon="inline-start" />
                    {t('parsing.upload.start')}
                  </Button>
                </div>
                <OperationalList ariaLabel={t('parsing.upload.listAria')} className="max-h-60 overflow-y-auto">
                  {selectedFiles.map((file, index) => (
                    <OperationalListItem
                      key={index}
                      leading={<FileText className="size-4" />}
                      primary={<span className="block truncate">{file.name}</span>}
                      metadata={`${(file.size / 1024).toFixed(0)} KB`}
                      monospaceMetadata
                    />
                  ))}
                </OperationalList>
              </div>
            )}
        </Section>
      )}

      {/* Parsing Progress */}
      {parsing && (
        <Section
          title={t('parsing.progress.title')}
          description={progress.message}
          actionsLabel={t('parsing.actions')}
          actions={(
            <Button variant="destructive" onClick={handleStop}>
              {t('parsing.progress.stop')}
            </Button>
          )}
        >
          <div className="space-y-4 border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] p-4 sm:p-5">
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>
                  {formatMessage(t('parsing.progress.count'), {
                    current: progress.current,
                    total: progress.total,
                  })}
                </span>
                <span>
                  {progress.total > 0
                    ? Math.round((progress.current / progress.total) * 100)
                    : 0}
                  %
                </span>
              </div>
              <Progress value={progress.current} max={progress.total} />
            </div>
            {startTime && (
              <div className="flex items-center gap-2 text-sm text-[var(--brain-ops-text-muted)]">
                <Clock className="size-4" />
                <span>
                  {formatMessage(t('parsing.progress.elapsed'), {
                    duration: ((Date.now() - startTime) / 1000).toFixed(1),
                  })}
                </span>
              </div>
            )}
          </div>
        </Section>
      )}

      {/* Results */}
      {results.length > 0 && (
        <Section title={t('parsing.results.title')}>
          {!parsing ? (
            <MetricStrip
              ariaLabel={t('parsing.results.metricsAria')}
              items={[
                { id: 'success', label: t('parsing.results.succeeded'), value: successCount, tone: 'success' },
                { id: 'failed', label: t('parsing.results.failed'), value: failedCount, tone: failedCount > 0 ? 'danger' : 'neutral' },
                { id: 'duration', label: t('parsing.results.duration'), value: duration ? `${duration}s` : '—' },
              ]}
              className="mb-5"
            />
          ) : null}

          <OperationalList ariaLabel={t('parsing.results.listAria')}>
            {results.map((result, index) => {
              const isExpanded = expandedResults.has(index);
              const cvData = result.data;
              const detailsId = `parsing-result-details-${index}`;

              return (
                <OperationalListItem
                  key={index}
                  leading={result.success
                    ? <CheckCircle2 className="size-5 text-[var(--brain-ops-success)]" />
                    : <XCircle className="size-5 text-[var(--brain-ops-danger)]" />}
                  primary={<span className="block truncate">{result.filename}</span>}
                  secondary={result.error || (isExpanded && cvData) ? (
                    <div className="space-y-3">
                      {result.error ? <p>{result.error}</p> : null}
                      {isExpanded && cvData ? (
                        <div id={detailsId} className="min-w-0 border-t border-[color:var(--brain-ops-border)] pt-3">
                          <p className="mb-2 text-xs font-medium uppercase tracking-[0.1em] [font-family:var(--brain-ops-font-command)]">
                            {t('parsing.results.json')}
                          </p>
                          <pre className="max-h-96 max-w-full overflow-auto bg-[var(--brain-ops-surface-muted)] p-3 text-xs">
                            {JSON.stringify(cvData, null, 2)}
                          </pre>
                        </div>
                      ) : null}
                    </div>
                  ) : undefined}
                  metadata={result.success && result.cv ? <Badge variant="success">ID: {result.cv.slice(0, 8)}</Badge> : undefined}
                  actionsLabel={t('parsing.results.actions')}
                  actions={result.success && cvData ? (
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => toggleResultExpand(index)}
                        aria-label={isExpanded ? t('parsing.results.collapse') : t('parsing.results.expand')}
                        aria-expanded={isExpanded}
                        aria-controls={isExpanded ? detailsId : undefined}
                      >
                        {isExpanded ? (
                          <ChevronUp />
                        ) : (
                          <ChevronDown />
                        )}
                      </Button>
                  ) : undefined}
                />
              );
            })}
          </OperationalList>

          {!parsing && (
            <div className="mt-5 flex flex-col gap-2 sm:flex-row">
              <Button
                onClick={() => {
                  setResults([]);
                  setSelectedFiles([]);
                  setStartTime(null);
                  setEndTime(null);
                }}
                variant="outline"
                className="flex-1"
              >
                {t('parsing.results.more')}
              </Button>
              {projectId && successCount > 0 && (
                <Button
                  onClick={() => navigate(`/projects/${projectId}`, { state: { refreshData: true } })}
                  className="flex-1"
                >
                  <ArrowRight data-icon="inline-start" />
                  {t('parsing.results.continue')}
                </Button>
              )}
            </div>
          )}
        </Section>
      )}

      {!parsing && results.length === 0 && selectedFiles.length === 0 ? (
        <SystemState
          kind="info"
          title={t('parsing.state.readyTitle')}
          description={t('parsing.state.readyDescription')}
          indicator={<FileText className="size-5" />}
        />
      ) : null}
    </PageFrame>
  );
};
