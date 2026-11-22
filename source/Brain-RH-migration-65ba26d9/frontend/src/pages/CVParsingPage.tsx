import { useState, useRef, useCallback, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Upload, FileText, CheckCircle2, XCircle, Clock, ChevronDown, ChevronUp, ArrowRight } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Progress } from '../components/ui/progress';
import { Badge } from '../components/ui/badge';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '../components/ui/card';
import { Alert, AlertDescription } from '../components/ui/alert';
import { ErrorBanner } from '../components/shared/ErrorBanner';
import { EmptyState } from '../components/shared/EmptyState';
import { cvsApi } from '../api/cvs';
import type { APIError, SSEProgressEvent, SSEResultEvent } from '../api/types';
import { cn } from '../lib/utils';

interface ParseResult {
  filename: string;
  success: boolean;
  cv?: string;
  error?: string;
  data?: any;
}

export const CVParsingPage: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedFiles, setSelectedFiles] = useState<File[]>(
    location.state?.files || []
  );
  const projectId = location.state?.projectId || null;
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
    let intervalId: NodeJS.Timeout | null = null;

    if (parsing && startTime) {
      intervalId = setInterval(() => {
        setTick(t => t + 1);
      }, 100);
    }

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [parsing, startTime]);

  const handleMessage = useCallback((event: any) => {
    if (event.type === 'progress') {
      const progressData = event.data as SSEProgressEvent;
      setProgress({
        current: progressData.current,
        total: progressData.total,
        message: progressData.message,
      });
    } else if (event.type === 'result') {
      const resultData = event.data as any; // CVParseResult
      setResults((prev) => [
        ...prev,
        {
          filename: resultData.filename || 'unknown',
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
    setProgress({ current: 0, total: selectedFiles.length, message: 'Upload des fichiers...' });
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
      const urlParams = new URLSearchParams({ model: 'gpt-4o-mini' });
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
    } catch (err) {
      console.error('❌ Parsing error:', err);
      setError({ code: 'PARSE_ERROR', message: String(err) });
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Charger les CVs</h1>
          <p className="text-muted-foreground">Importez et parsez vos CVs automatiquement</p>
        </div>
      </div>

      {error && <ErrorBanner error={error} />}

      {/* File Upload */}
      {!parsing && results.length === 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Sélectionner des fichiers</CardTitle>
            <CardDescription>
              Formats acceptés: PDF, DOCX (max 10MB par fichier)
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div
              className={cn(
                'border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer',
                dragging ? 'border-primary bg-primary/5' : 'border-border',
                'hover:border-primary hover:bg-accent/50'
              )}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <p className="text-sm font-medium mb-2">
                Glissez-déposez vos fichiers ici, ou cliquez pour sélectionner
              </p>
              <p className="text-xs text-muted-foreground">
                Formats acceptés: PDF, DOCX
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
              <div className="mt-6 space-y-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">
                    {selectedFiles.length} fichier(s) sélectionné(s)
                  </p>
                  <Button onClick={handleStartParsing} size="lg">
                    <Upload className="mr-2 h-5 w-5" />
                    Charger les CVs
                  </Button>
                </div>
                <div className="space-y-1 max-h-60 overflow-y-auto">
                  {selectedFiles.map((file, index) => (
                    <div
                      key={index}
                      className="flex items-center gap-2 text-sm p-2 rounded border"
                    >
                      <FileText className="h-4 w-4 text-muted-foreground" />
                      <span className="flex-1 truncate">{file.name}</span>
                      <Badge variant="secondary">{(file.size / 1024).toFixed(0)} KB</Badge>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Parsing Progress */}
      {parsing && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Parsing en cours...</CardTitle>
                <CardDescription>{progress.message}</CardDescription>
              </div>
              <Button variant="destructive" onClick={handleStop}>
                Arrêter
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>
                  {progress.current} / {progress.total} CVs parsés
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
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Clock className="h-4 w-4" />
                <span>
                  Temps écoulé: {((Date.now() - startTime) / 1000).toFixed(1)}s
                </span>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {results.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold">Résultats</h2>
            {!parsing && (
              <div className="flex gap-4">
                <Alert variant="success" className="py-2 px-4">
                  <AlertDescription className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4" />
                    <span className="font-medium">{successCount} réussi(s)</span>
                  </AlertDescription>
                </Alert>
                {failedCount > 0 && (
                  <Alert variant="destructive" className="py-2 px-4">
                    <AlertDescription className="flex items-center gap-2">
                      <XCircle className="h-4 w-4" />
                      <span className="font-medium">{failedCount} échoué(s)</span>
                    </AlertDescription>
                  </Alert>
                )}
                {duration && (
                  <Alert className="py-2 px-4">
                    <AlertDescription className="flex items-center gap-2">
                      <Clock className="h-4 w-4" />
                      <span className="font-medium">{duration}s</span>
                    </AlertDescription>
                  </Alert>
                )}
              </div>
            )}
          </div>

          <div className="space-y-2">
            {results.map((result, index) => {
              const isExpanded = expandedResults.has(index);
              const cvData = result.data;

              return (
                <div
                  key={index}
                  className={cn(
                    'rounded-lg border',
                    result.success
                      ? 'border-green-500/50 bg-green-500/5'
                      : 'border-red-500/50 bg-red-500/5'
                  )}
                >
                  <div className="flex items-center gap-3 p-3">
                    {result.success ? (
                      <CheckCircle2 className="h-5 w-5 text-green-600 flex-shrink-0" />
                    ) : (
                      <XCircle className="h-5 w-5 text-red-600 flex-shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{result.filename}</p>
                      {result.error && (
                        <p className="text-xs text-red-600 mt-1">{result.error}</p>
                      )}
                    </div>
                    {result.success && result.cv && (
                      <Badge variant="success">ID: {result.cv.slice(0, 8)}</Badge>
                    )}
                    {result.success && cvData && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => toggleResultExpand(index)}
                      >
                        {isExpanded ? (
                          <ChevronUp className="h-4 w-4" />
                        ) : (
                          <ChevronDown className="h-4 w-4" />
                        )}
                      </Button>
                    )}
                  </div>

                  {/* Expanded CV details - JSON complet */}
                  {isExpanded && cvData && (
                    <div className="px-3 pb-3 border-t border-green-500/30 pt-3">
                      <p className="text-xs font-medium mb-2">Structure JSON parsée :</p>
                      <pre className="text-xs bg-muted p-3 rounded overflow-x-auto max-h-96 overflow-y-auto">
                        {JSON.stringify(cvData, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {!parsing && (
            <div className="flex gap-2">
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
                Analyser d'autres CVs
              </Button>
              {projectId && successCount > 0 && (
                <Button
                  onClick={() => navigate(`/projects/${projectId}`, { state: { refreshData: true } })}
                  className="flex-1"
                >
                  <ArrowRight className="mr-2 h-4 w-4" />
                  Continuer vers le projet
                </Button>
              )}
            </div>
          )}
        </div>
      )}

    </div>
  );
};
