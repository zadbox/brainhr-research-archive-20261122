import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Target, Play, Clock, CheckCircle2, History } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select } from '../components/ui/select';
import { Progress } from '../components/ui/progress';
import { Badge } from '../components/ui/badge';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '../components/ui/card';
import { LoadingPage } from '../components/shared/Loading';
import { ErrorBanner } from '../components/shared/ErrorBanner';
import { EmptyState } from '../components/shared/EmptyState';
import { useSSE } from '../hooks/useSSE';
import { matchingApi } from '../api/matching';
import { projectsApi } from '../api/projects';
import type { Project, APIError, SSEProgressEvent, SSEDoneEvent } from '../api/types';

interface MatchingStep {
  name: string;
  progress: number;
  message: string;
  completed: boolean;
}

const initialSteps: MatchingStep[] = [
  { name: 'Filtrage must-have', progress: 0, message: 'En attente...', completed: false },
  { name: 'Calcul similarité & Nice-have', progress: 0, message: 'En attente...', completed: false },
  { name: 'Re-ranking LLM', progress: 0, message: 'En attente...', completed: false },
];

export const MatchingPage: React.FC = () => {
  const { projectId: projectIdFromUrl } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>(projectIdFromUrl || '');
  const [topN, setTopN] = useState<number>(10);
  const model = 'gpt-4o-mini'; // Modèle fixe (pas de choix utilisateur)
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<MatchingStep[]>(initialSteps);
  const [results, setResults] = useState<any>(null);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [endTime, setEndTime] = useState<number | null>(null);

  // État pour forcer le re-rendu du timer
  const [, setTick] = useState(0);

  // 🔑 runId unique pour idempotence côté serveur
  const runIdRef = useRef<string>('');
  if (!runIdRef.current) {
    runIdRef.current = crypto.randomUUID();
  }

  // Mettre à jour le timer toutes les 100ms quand le matching est en cours
  useEffect(() => {
    if (!running || !startTime) return;

    const interval = setInterval(() => {
      setTick(prev => prev + 1);
    }, 100); // Update every 100ms for smooth display

    return () => clearInterval(interval);
  }, [running, startTime]);

  const handleMessage = useCallback((event: any) => {
    if (event.type === 'progress') {
      const progressData = event.data as SSEProgressEvent;
      setSteps((prev) => {
        const newSteps = [...prev];
        const stepMap: Record<string, number> = {
          'must_have_filtering': 0,
          'embedding': 1,
          'reranking': 2,
        };
        const stepIndex = stepMap[progressData.step.toLowerCase()];
        if (stepIndex !== undefined && newSteps[stepIndex]) {
          newSteps[stepIndex] = {
            ...newSteps[stepIndex],
            progress: (progressData.progress || 0) * 100,
            message: progressData.message || '',
            completed: (progressData.progress || 0) >= 1.0,
          };
        }
        return newSteps;
      });
    } else if (event.type === 'done') {
      const doneData = event.data as SSEDoneEvent;
      setResults(doneData.summary);
      setRunning(false);
      setEndTime(Date.now());
      // Ne marquer à 100% que les steps qui ont vraiment progressé
      setSteps((prev) => prev.map((s) => {
        if (s.progress > 0) {
          return { ...s, completed: true, progress: 100 };
        }
        return s;
      }));

      // Pas de redirection automatique - afficher les résultats sur la même page
    } else if (event.type === 'error') {
      setError(event.data as APIError);
      setRunning(false);
      setEndTime(Date.now());
    }
  }, []);

  // 📡 URL SSE avec runId pour idempotence côté serveur
  const streamUrl = useMemo(() => {
    if (!running || !selectedProjectId) return '';
    const baseUrl = matchingApi.getRunStreamUrl(selectedProjectId, topN, model);
    return `${baseUrl}&runId=${runIdRef.current}`;
  }, [running, selectedProjectId, topN, model]);

  const { close } = useSSE({
    url: streamUrl,
    enabled: running,
    onMessage: handleMessage,
    onError: (err) => {
      console.error('[MatchingPage] SSE Error:', err);
      setError({ code: 'SSE_ERROR', message: 'Connexion perdue au serveur' });
      setRunning(false);
    },
    closeOn: ['done', 'error'], // Auto-close quand matching terminé
    forceSingle: false, // Désactivé temporairement pour debug
  });

  const fetchProjects = async () => {
    try {
      setLoading(true);
      const data = await projectsApi.getAll();
      setProjects(data);
    } catch (err) {
      setError(err as APIError);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  const handleStartMatching = () => {
    if (!selectedProjectId) {
      setError({ code: 'VALIDATION_ERROR', message: 'Veuillez sélectionner un projet' });
      return;
    }

    // 🔄 Générer un nouveau runId pour chaque lancement
    runIdRef.current = crypto.randomUUID();
    console.log(`[MatchingPage] Nouveau matching avec runId: ${runIdRef.current}`);

    setError(null);
    setResults(null);
    setSteps(initialSteps);
    setStartTime(Date.now());
    setEndTime(null);
    setRunning(true);
  };

  const handleStop = () => {
    close();
    setRunning(false);
    setEndTime(Date.now());
  };

  const duration = startTime && endTime ? ((endTime - startTime) / 1000).toFixed(1) : null;

  if (loading) return <LoadingPage text="Chargement des projets..." />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Matching</h1>
          <p className="text-muted-foreground">Lancez le matching intelligent CV-Offre</p>
        </div>
      </div>

      {error && <ErrorBanner error={error} />}

      {/* Configuration - Masquée pendant et après le matching */}
      {!running && !results && (
        <Card>
          <CardHeader>
            <CardTitle>Configuration</CardTitle>
            <CardDescription>
              Sélectionnez un projet et configurez les paramètres de matching
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Sélecteur de projet - Masqué si on vient d'un projet spécifique */}
            {!projectIdFromUrl && (
              <div className="space-y-2">
                <Label htmlFor="project-select">Projet *</Label>
                <Select
                  id="project-select"
                  value={selectedProjectId}
                  onChange={(e) => setSelectedProjectId(e.target.value)}
                >
                  <option value="">Sélectionner un projet</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.nom}
                    </option>
                  ))}
                </Select>
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="top-n">Top N (reranking)</Label>
                <Input
                  id="top-n"
                  type="number"
                  min={1}
                  max={100}
                  value={topN}
                  onChange={(e) => setTopN(parseInt(e.target.value) || 10)}
                />
                <p className="text-xs text-muted-foreground">
                  Nombre de CVs à reranker avec LLM
                </p>
              </div>

            </div>

            <Button
              onClick={handleStartMatching}
              size="lg"
              className="w-full mt-4"
              disabled={running}
            >
              <Play className="mr-2 h-5 w-5" />
              Lancer le matching
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Progress */}
      {running && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Matching en cours...</CardTitle>
                  <CardDescription>
                    L'analyse peut prendre plusieurs minutes
                  </CardDescription>
                </div>
                <Button variant="destructive" onClick={handleStop}>
                  Arrêter
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {startTime && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground mb-4">
                  <Clock className="h-4 w-4" />
                  <span>
                    Temps écoulé: {((Date.now() - startTime) / 1000).toFixed(1)}s
                  </span>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Steps */}
          <div className="space-y-3">
            {steps.map((step, index) => (
              <Card key={index}>
                <CardContent className="pt-6">
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {step.completed ? (
                          <CheckCircle2 className="h-5 w-5 text-green-600" />
                        ) : (
                          <div className="h-5 w-5 rounded-full border-2 border-primary" />
                        )}
                        <span className="font-medium">{step.name}</span>
                      </div>
                      <Badge variant={step.completed ? 'success' : 'default'}>
                        {step.progress}%
                      </Badge>
                    </div>
                    <p className="text-sm text-muted-foreground pl-7">{step.message}</p>
                    <Progress value={step.progress} max={100} className="pl-7" />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Results Summary + Detailed Results */}
      {results && !running && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Résultats du Matching</CardTitle>
              <CardDescription>
                {results.results?.length || 0} candidat(s) classé(s) par score final
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Alerte si aucun CV sélectionné */}
              {(results.metadata?.filtered_must_have === 0 || results.results?.length === 0) && (
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                  <div className="flex items-start gap-3">
                    <div className="text-yellow-600">
                      <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                      </svg>
                    </div>
                    <div className="flex-1">
                      <h3 className="font-semibold text-yellow-800 mb-1">
                        Aucun CV sélectionné
                      </h3>
                      <p className="text-sm text-yellow-700">
                        Les {results.metadata?.total_cvs || 0} CVs analysés ont été éliminés lors du filtrage must-have.
                        Aucun candidat ne correspond aux critères obligatoires définis dans l'offre.
                      </p>
                      <p className="text-sm text-yellow-700 mt-2 font-medium">
                        💡 Suggestion : Vérifiez les critères must-have de l'offre ou ajoutez d'autres CVs.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground">CVs analysés</p>
                  <p className="text-2xl font-bold">
                    {results.metadata?.total_cvs || 0}
                  </p>
                </div>
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground">Must-have validés</p>
                  <p className={`text-2xl font-bold ${results.metadata?.filtered_must_have === 0 ? 'text-red-600' : ''}`}>
                    {results.metadata?.filtered_must_have || 0}
                  </p>
                </div>
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground">Top rerankés</p>
                  <p className="text-2xl font-bold">{results.metadata?.top_reranked || 0}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground">Durée</p>
                  <p className="text-2xl font-bold">
                    {duration || results.metadata?.duree_totale_s?.toFixed(1) || '0'}s
                  </p>
                </div>
              </div>

              <Button
                onClick={() => {
                  setResults(null);
                  setSteps(initialSteps);
                  setStartTime(null);
                  setEndTime(null);
                }}
                variant="outline"
                className="w-full"
              >
                Nouveau matching
              </Button>
            </CardContent>
          </Card>

          {/* Detailed Results */}
          {results.results && results.results.length > 0 && (
            <div className="space-y-4">
              <h2 className="text-2xl font-bold">Classement des candidats</h2>
              {results.results.map((cv, index) => (
                <Card key={index}>
                  <CardHeader>
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <CardTitle className="flex items-center gap-2">
                          <span className="text-muted-foreground">#{index + 1}</span>
                          <span>{cv.cv}</span>
                        </CardTitle>
                        <CardDescription>
                          Score final: {cv.score_final.toFixed(3)}
                        </CardDescription>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {/* Metrics */}
                    <div className="grid grid-cols-4 gap-4">
                      <div className="space-y-1">
                        <p className="text-xs text-muted-foreground">Score final</p>
                        <p className="text-xl font-bold">{cv.score_final.toFixed(3)}</p>
                      </div>
                      <div className="space-y-1">
                        <p className="text-xs text-muted-foreground">Score base</p>
                        <p className="text-xl font-bold">{cv.score_base.toFixed(3)}</p>
                      </div>
                      <div className="space-y-1">
                        <p className="text-xs text-muted-foreground">Malus Nice-have (×)</p>
                        <p className="text-xl font-bold">{cv.bonus_nice_have_multiplicateur.toFixed(3)}</p>
                        {cv.nice_have_manquants?.length > 0 && (
                          <p className="text-xs text-orange-600">{cv.nice_have_manquants.length} manquant(s)</p>
                        )}
                      </div>
                      <div className="space-y-1">
                        <p className="text-xs text-muted-foreground">Qualité XP (×)</p>
                        <p className="text-xl font-bold text-green-600">{cv.coefficient_qualite_experience.toFixed(2)}</p>
                      </div>
                    </div>

                    {/* Nice-have manquants */}
                    {cv.nice_have_manquants && cv.nice_have_manquants.length > 0 && (
                      <div>
                        <p className="text-sm font-semibold mb-2 text-orange-700">Nice-have manquants:</p>
                        <div className="flex flex-wrap gap-1">
                          {cv.nice_have_manquants.map((item, idx) => (
                            <Badge key={idx} variant="outline" className="text-orange-700 border-orange-300">
                              {item}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Commentaire Scoring */}
                    {cv.commentaire_scoring && (
                      <div>
                        <p className="text-sm font-semibold mb-2">Analyse du scoring:</p>
                        <div className="bg-muted p-3 rounded text-sm whitespace-pre-wrap">
                          {cv.commentaire_scoring}
                        </div>
                      </div>
                    )}

                    {/* Appréciation Globale */}
                    {cv.appreciation_globale && (
                      <div>
                        <p className="text-sm font-semibold mb-2">Appréciation RH:</p>
                        <div className="bg-blue-50 dark:bg-blue-900/20 p-3 rounded text-sm whitespace-pre-wrap border border-blue-200 dark:border-blue-800 text-gray-900 dark:text-gray-100">
                          {cv.appreciation_globale}
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      {!running && !results && projects.length === 0 && (
        <EmptyState
          icon={Target}
          title="Aucun projet disponible"
          description="Créez d'abord un projet avant de lancer un matching"
        />
      )}

      {/* Bouton Historique des résultats - Toujours visible en bas */}
      {(projectIdFromUrl || selectedProjectId) && (
        <Card>
          <CardContent className="pt-6">
            <Button
              onClick={() => navigate(`/projects/${projectIdFromUrl || selectedProjectId}/results`)}
              size="lg"
              className="w-full"
            >
              <History className="mr-2 h-5 w-5" />
              Voir l'historique des résultats
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
};
