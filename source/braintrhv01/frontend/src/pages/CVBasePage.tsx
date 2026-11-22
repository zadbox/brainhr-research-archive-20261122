import { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams, useParams } from 'react-router-dom';
import { Upload, FileText, Trash2, ArrowRight, ArrowLeft, Search, ChevronDown, ChevronUp, Filter } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Select } from '../components/ui/select';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from '../components/ui/card';
import { LoadingPage } from '../components/shared/Loading';
import { ErrorBanner } from '../components/shared/ErrorBanner';
import { EmptyState } from '../components/shared/EmptyState';
import { cvsApi } from '../api/cvs';
import type { CV, APIError } from '../api/types';
import { cn } from '../lib/utils';

export const CVBasePage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { projectId: urlProjectId } = useParams<{ projectId: string }>();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Si on arrive depuis un projet (URL), afficher ce projet. Sinon (menu latéral), afficher "tous"
  const [selectedProjectId, setSelectedProjectId] = useState<string>(urlProjectId || searchParams.get('project') || 'tous');
  const [cvs, setCvs] = useState<CV[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [dragging, setDragging] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedCVs, setExpandedCVs] = useState<Set<string>>(new Set());
  const [filterCompetence, setFilterCompetence] = useState('');
  // Filtre entreprise: "tout" par défaut (toutes les entreprises)
  const [filterEntreprise, setFilterEntreprise] = useState<string>('tout');
  // État de progression parsing
  const [parsing, setParsing] = useState(false);
  const [parsingProgress, setParsingProgress] = useState({ current: 0, total: 0 });


  const fetchCVs = async (projectId: string) => {
    try {
      setLoading(true);
      setError(null);

      // Si projectId est "tous", récupérer tous les CVs
      if (projectId === 'tous') {
        const data = await cvsApi.getAll();
        setCvs(data);
      } else {
        const data = await cvsApi.getByProject(projectId);
        setCvs(data);
      }
    } catch (err) {
      console.error('Failed to fetch CVs:', err);
      setCvs([]);
    } finally {
      setLoading(false);
    }
  };


  // Mettre à jour selectedProjectId quand urlProjectId change
  useEffect(() => {
    if (urlProjectId && urlProjectId !== selectedProjectId) {
      setSelectedProjectId(urlProjectId);
    }
  }, [urlProjectId]);

  useEffect(() => {
    if (selectedProjectId) {
      fetchCVs(selectedProjectId);
    } else {
      setCvs([]);
      setLoading(false);
    }
  }, [selectedProjectId]);

  // Charger les CVs au démarrage si selectedProjectId est "tous"
  useEffect(() => {
    if (selectedProjectId === 'tous') {
      fetchCVs('tous');
    }
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setSelectedFiles(Array.from(e.target.files));
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files) {
      setSelectedFiles(Array.from(e.dataTransfer.files));
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
    if (selectedFiles.length === 0) {
      setError({
        message: 'Veuillez sélectionner au moins un fichier CV avant de continuer.',
        code: 'NO_FILES_SELECTED'
      });
      return;
    }

    if (!selectedProjectId || selectedProjectId === 'tous') {
      setError({
        message: 'Veuillez sélectionner un projet spécifique pour charger des CVs.',
        code: 'NO_PROJECT_SELECTED'
      });
      return;
    }

    setParsing(true);
    setParsingProgress({ current: 0, total: selectedFiles.length });
    setError(null);

    try {
      // Upload files via FormData + SSE parsing
      const formData = new FormData();
      selectedFiles.forEach((file) => {
        formData.append('files', file);
      });

      const urlParams = new URLSearchParams({ model: 'gpt-4o-mini' });
      urlParams.append('project_id', selectedProjectId);
      const url = `${cvsApi.getParseStreamUrl()}?${urlParams.toString()}`;

      const response = await fetch(url, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`HTTP ${response.status}: ${errorText}`);
      }

      // Read SSE stream and update progress
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error('No response body');
      }

      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.trim()) continue;

          const eventMatch = line.match(/^event: (.+)$/m);
          const dataMatch = line.match(/^data: (.+)$/m);

          if (eventMatch && dataMatch) {
            const eventType = eventMatch[1];
            const data = JSON.parse(dataMatch[1]);

            if (eventType === 'progress') {
              setParsingProgress({ current: data.current, total: data.total });
            } else if (eventType === 'done') {
              break;
            }
          }
        }
      }

      // Refresh CV list
      await fetchCVs(selectedProjectId);

      // Clear selected files
      setSelectedFiles([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }

    } catch (err) {
      console.error('❌ Parsing error:', err);
      setError({ code: 'PARSE_ERROR', message: String(err) });
    } finally {
      setParsing(false);
      setParsingProgress({ current: 0, total: 0 });
    }
  };

  const handleDeleteCV = async (cvId: string) => {
    try {
      await cvsApi.delete(cvId);
      if (selectedProjectId) {
        await fetchCVs(selectedProjectId);
      }
    } catch (err) {
      setError(err as APIError);
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
  const uniqueEntreprises = Array.from(
    new Set(
      cvs
        .filter(cv => cv.enterprise_nom)
        .map(cv => cv.enterprise_nom!)
    )
  ).sort();

  // Filter CVs based on search and filters
  // Si on arrive depuis un projet (urlProjectId), pas de filtre entreprise
  const filteredCVs = cvs.filter(cv => {
    const matchesSearch =
      !searchQuery ||
      cv.identite?.nom?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      cv.identite?.prenom?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      cv.identite?.email?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      cv.titre?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      cv.cv.toLowerCase().includes(searchQuery.toLowerCase());

    const matchesCompetence =
      !filterCompetence ||
      cv.competences_techniques.some(c => c.toLowerCase().includes(filterCompetence.toLowerCase())) ||
      cv.competences_transversales.some(c => c.toLowerCase().includes(filterCompetence.toLowerCase()));

    // Filtre entreprise seulement si on vient du menu latéral (pas de urlProjectId)
    const matchesEntreprise = urlProjectId
      ? true  // Pas de filtre entreprise si on vient d'un projet
      : (!filterEntreprise || filterEntreprise === 'tout' || cv.enterprise_nom === filterEntreprise);

    return matchesSearch && matchesCompetence && matchesEntreprise;
  });

  if (loading && selectedProjectId) return <LoadingPage text="Chargement des CVs..." />;

  return (
    <div className="space-y-6">
      {/* Header avec bouton retour si projet spécifique */}
      {urlProjectId ? (
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate(`/projects/${urlProjectId}`)}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div className="flex-1 flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold tracking-tight">Base CVs du projet</h1>
              <p className="text-muted-foreground">Gérez et uploadez vos CVs</p>
            </div>
            {cvs.length > 0 && (
              <Button
                onClick={() => navigate(`/projects/${urlProjectId}/matching`)}
                size="lg"
              >
                Étape suivante : Matching
                <ArrowRight className="ml-2 h-5 w-5" />
              </Button>
            )}
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Base CVs</h1>
            <p className="text-muted-foreground">Gérez et uploadez vos CVs</p>
          </div>
        </div>
      )}

      {error && <ErrorBanner error={error} />}

      {/* File Upload Area */}
      <Card>
        <CardHeader>
          <CardTitle>Upload de CVs</CardTitle>
          <CardDescription>
            Glissez-déposez vos fichiers PDF ou DOCX, ou cliquez pour sélectionner
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div
            className={cn(
              'border-2 border-dashed rounded-lg p-8 text-center transition-colors',
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
              Formats acceptés: PDF, DOCX (max 10MB par fichier)
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
            <div className="mt-4 space-y-2">
              <p className="text-sm font-medium">{selectedFiles.length} fichier(s) sélectionné(s):</p>
              <div className="space-y-1">
                {selectedFiles.map((file, index) => (
                  <div key={index} className="flex items-center gap-2 text-sm">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                    <span className="flex-1 truncate">{file.name}</span>
                    <Badge variant="secondary">{(file.size / 1024).toFixed(1)} KB</Badge>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
        <CardFooter className="flex-col gap-3">
          <Button
            onClick={handleUploadAndParse}
            className="w-full"
            size="lg"
            disabled={parsing || selectedFiles.length === 0}
          >
            <Upload className="mr-2 h-5 w-5" />
            {parsing ? 'Parsing en cours...' : 'Charger les CVs'}
          </Button>

          {/* Barre de progression */}
          {parsing && (
            <div className="w-full space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">
                  Parsing des CVs: {parsingProgress.current} / {parsingProgress.total}
                </span>
                <span className="font-medium">
                  {Math.round((parsingProgress.current / parsingProgress.total) * 100)}%
                </span>
              </div>
              <div className="w-full bg-secondary rounded-full h-2.5 overflow-hidden">
                <div
                  className="bg-primary h-2.5 rounded-full transition-all duration-300"
                  style={{ width: `${(parsingProgress.current / parsingProgress.total) * 100}%` }}
                />
              </div>
            </div>
          )}
        </CardFooter>
      </Card>

      {/* CVs List */}
      {selectedProjectId && selectedProjectId !== '' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold">
              CVs parsés ({filteredCVs.length}/{cvs.length})
            </h2>
          </div>

          {/* Search and Filters */}
          {cvs.length > 0 && (
            <Card>
              <CardContent className="pt-6">
                <div className={`grid grid-cols-1 gap-4 ${urlProjectId ? 'md:grid-cols-2' : 'md:grid-cols-3'}`}>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="Rechercher par nom, email, titre..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="pl-9"
                    />
                  </div>
                  <div className="relative">
                    <Filter className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="Filtrer par compétence..."
                      value={filterCompetence}
                      onChange={(e) => setFilterCompetence(e.target.value)}
                      className="pl-9"
                    />
                  </div>
                  {/* Filtre entreprise seulement si on vient du menu latéral */}
                  {!urlProjectId && (
                    <Select
                      value={filterEntreprise}
                      onChange={(e) => setFilterEntreprise(e.target.value)}
                    >
                      <option value="tout">Toutes les entreprises</option>
                      {uniqueEntreprises.map((entreprise) => (
                        <option key={entreprise} value={entreprise}>
                          {entreprise}
                        </option>
                      ))}
                    </Select>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {cvs.length === 0 ? (
            <EmptyState
              icon={FileText}
              title="Aucun CV"
              description="Commencez par parser des CVs pour ce projet"
            />
          ) : filteredCVs.length === 0 ? (
            <EmptyState
              icon={Search}
              title="Aucun résultat"
              description="Aucun CV ne correspond à vos critères de recherche"
            />
          ) : (
            <div className="space-y-3">
              {filteredCVs.map((cv) => {
                const isExpanded = expandedCVs.has(cv.cv);
                return (
                  <Card key={cv.cv}>
                    <CardHeader className="pb-3">
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <CardTitle className="text-base">
                            {cv.identite?.prenom} {cv.identite?.nom || cv.cv}
                          </CardTitle>
                          <CardDescription>
                            {cv.titre || 'Pas de titre'}
                          </CardDescription>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => toggleCVExpand(cv.cv)}
                        >
                          {isExpanded ? (
                            <ChevronUp className="h-4 w-4" />
                          ) : (
                            <ChevronDown className="h-4 w-4" />
                          )}
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-3 text-sm">
                        {cv.identite?.email && (
                          <p className="text-muted-foreground">{cv.identite.email}</p>
                        )}
                        {cv.identite?.telephone && (
                          <p className="text-muted-foreground">{cv.identite.telephone}</p>
                        )}

                        {/* Compétences techniques */}
                        {cv.competences_techniques.length > 0 && (
                          <div>
                            <p className="font-medium mb-1">Compétences techniques</p>
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

                        {/* Expanded details - JSON complet */}
                        {isExpanded && (
                          <div className="pt-3 border-t">
                            <p className="text-xs font-medium mb-2">Structure JSON complète :</p>
                            <pre className="text-xs bg-muted p-3 rounded overflow-x-auto max-h-96 overflow-y-auto">
                              {JSON.stringify(cv, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    </CardContent>
                    <CardFooter className="pt-3">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDeleteCV(cv.cv)}
                        className="w-full text-destructive hover:text-destructive"
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        Supprimer
                      </Button>
                    </CardFooter>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
