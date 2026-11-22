import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Eye, BarChart3, Calendar, ArrowLeft } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select } from '../components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
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
import { projectsApi } from '../api/projects';
import type { Project, APIError, ProjectHistory } from '../api/types';

export const ResultsPage: React.FC = () => {
  const { projectId: projectIdFromUrl } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>(projectIdFromUrl || '');
  const [matchingHistory, setMatchingHistory] = useState<ProjectHistory | null>(null);
  const [dateFilter, setDateFilter] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);

  const fetchProjects = async () => {
    try {
      const data = await projectsApi.getAll();
      setProjects(data);
    } catch (err) {
      console.error('Failed to fetch projects:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchMatchingHistory = async (projectId: string) => {
    try {
      setLoading(true);
      setError(null);
      const history = await projectsApi.getHistory(projectId);
      setMatchingHistory(history);
    } catch (err) {
      setError(err as APIError);
      setMatchingHistory(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  useEffect(() => {
    if (selectedProjectId) {
      fetchMatchingHistory(selectedProjectId);
    } else {
      setMatchingHistory(null);
    }
  }, [selectedProjectId]);

  // Filtrer l'historique par date
  const filteredHistory = matchingHistory?.items.filter((item) => {
    if (!dateFilter) return true;
    const itemDate = item.timestamp.split('_')[0]; // Format: 2025-10-12_07-15-47
    return itemDate.includes(dateFilter);
  }) || [];

  if (loading && !selectedProjectId) return <LoadingPage text="Chargement des projets..." />;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        {projectIdFromUrl && (
          <Button variant="ghost" size="icon" onClick={() => navigate(`/projects/${projectIdFromUrl}`)}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
        )}
        <div className="flex-1">
          <h1 className="text-3xl font-bold tracking-tight">Historique des résultats</h1>
          <p className="text-muted-foreground">Consultez tous les matchings effectués</p>
        </div>
      </div>

      {error && <ErrorBanner error={error} />}

      {/* Sélection projet - Masqué si on vient d'un projet spécifique */}
      {!projectIdFromUrl && (
        <Card>
          <CardHeader>
            <CardTitle>Sélection du projet</CardTitle>
            <CardDescription>
              Choisissez un projet pour voir l'historique complet de ses matchings
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="project-select">Projet</Label>
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
          </CardContent>
        </Card>
      )}

      {/* Historique des matchings */}
      {selectedProjectId && matchingHistory && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Historique des matchings</CardTitle>
                <CardDescription>
                  {matchingHistory.total} matching(s) effectué(s)
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Calendar className="h-4 w-4 text-muted-foreground" />
                <Input
                  type="date"
                  value={dateFilter}
                  onChange={(e) => setDateFilter(e.target.value)}
                  placeholder="Filtrer par date"
                  className="w-auto"
                />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {filteredHistory.length === 0 ? (
              <EmptyState
                icon={BarChart3}
                title="Aucun matching"
                description="Aucun matching trouvé pour ce filtre"
              />
            ) : (
              <div className="border rounded-lg">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Date & Heure</TableHead>
                      <TableHead>Candidats</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredHistory.map((item) => (
                      <TableRow
                        key={item.matching_id}
                        className="cursor-pointer hover:bg-accent"
                        onClick={() => navigate(`/projects/${selectedProjectId}/results/${item.matching_id}`)}
                      >
                        <TableCell className="font-mono text-sm">
                          {item.timestamp.replace('_', ' à ').replace(/-/g, ':')}
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">{item.candidats_count} CV</Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <Eye className="h-4 w-4 text-muted-foreground" />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

    </div>
  );
};
