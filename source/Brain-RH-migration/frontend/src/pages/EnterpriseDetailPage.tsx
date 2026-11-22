import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, FolderOpen, Archive } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
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
import { enterprisesApi } from '../api/enterprises';
import { projectsApi } from '../api/projects';
import type { Enterprise, Project, APIError } from '../api/types';
import { useToast } from '../hooks/useToast';

export const EnterpriseDetailPage: React.FC = () => {
  const { enterpriseId } = useParams<{ enterpriseId: string }>();
  const navigate = useNavigate();
  const { success, error: showError } = useToast();

  const [enterprise, setEnterprise] = useState<Enterprise | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);

  const fetchData = async () => {
    if (!enterpriseId) return;

    try {
      setLoading(true);
      setError(null);

      // Charger l'entreprise et ses projets en parallèle
      const [enterpriseData, projectsData] = await Promise.all([
        enterprisesApi.getById(enterpriseId),
        projectsApi.getAll(), // TODO: filtrer par enterprise_id
      ]);

      setEnterprise(enterpriseData);
      // Filtrer les projets de cette entreprise
      setProjects(projectsData.filter((p) => p.enterprise_id === enterpriseId));
    } catch (err) {
      setError(err as APIError);
      showError('Erreur', 'Impossible de charger les données');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [enterpriseId]);

  const handleCreateProject = () => {
    navigate(`/enterprises/${enterpriseId}/projects/new`);
  };

  const handleOpenProject = (projectId: string) => {
    navigate(`/projects/${projectId}`);
  };

  const handleArchiveProject = async (projectId: string) => {
    try {
      await projectsApi.update(projectId, { status: 'archive' });
      success('Projet archivé');
      fetchData();
    } catch (err) {
      showError('Erreur', 'Impossible d\'archiver le projet');
    }
  };

  if (loading) return <LoadingPage text="Chargement de l'entreprise..." />;
  if (!enterprise) return <div>Entreprise introuvable</div>;

  return (
    <div className="space-y-6">
      {/* Header avec breadcrumb */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => navigate('/enterprises')}>
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="flex-1">
          <div className="text-sm text-muted-foreground mb-1">
            Entreprises / {enterprise.nom}
          </div>
          <h1 className="text-3xl font-bold tracking-tight">{enterprise.nom}</h1>
          {enterprise.secteur && (
            <p className="text-muted-foreground mt-1">Secteur: {enterprise.secteur}</p>
          )}
        </div>
        <Button onClick={handleCreateProject}>
          <Plus className="mr-2 h-4 w-4" />
          Nouveau projet
        </Button>
      </div>

      {error && <ErrorBanner error={error} />}

      {/* Statistiques */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="text-center">
              <p className="text-3xl font-bold text-primary">{projects.length}</p>
              <p className="text-sm text-muted-foreground mt-1">Projets total</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-center">
              <p className="text-3xl font-bold text-success">
                {projects.filter((p) => p.status === 'actif').length}
              </p>
              <p className="text-sm text-muted-foreground mt-1">Projets actifs</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-center">
              <p className="text-3xl font-bold text-muted-foreground">
                {projects.filter((p) => p.status === 'archive').length}
              </p>
              <p className="text-sm text-muted-foreground mt-1">Projets archivés</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Liste des projets */}
      <div>
        <h2 className="text-2xl font-bold mb-4">Projets de recrutement</h2>

        {projects.length === 0 ? (
          <EmptyState
            icon={FolderOpen}
            title="Aucun projet"
            description="Créez votre premier projet de recrutement pour cette entreprise"
            action={{
              label: 'Créer un projet',
              onClick: handleCreateProject,
            }}
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {projects.map((project) => (
              <Card
                key={project.id}
                className="hover:shadow-lg transition-shadow cursor-pointer group"
                onClick={() => handleOpenProject(project.id)}
              >
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <FolderOpen className="h-8 w-8 text-primary" />
                    <Badge variant={project.status === 'actif' ? 'default' : 'secondary'}>
                      {project.status === 'actif' ? 'Actif' : 'Archivé'}
                    </Badge>
                  </div>
                  <CardTitle className="mt-4">{project.nom}</CardTitle>
                  <CardDescription>
                    Créé le {new Date(project.created_at || '').toLocaleDateString('fr-FR')}
                  </CardDescription>
                </CardHeader>
                <CardFooter className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="flex-1"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleOpenProject(project.id);
                    }}
                  >
                    Ouvrir
                  </Button>
                  {project.status === 'actif' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleArchiveProject(project.id);
                      }}
                    >
                      <Archive className="h-4 w-4" />
                    </Button>
                  )}
                </CardFooter>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
