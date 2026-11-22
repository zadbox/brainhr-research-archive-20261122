import { useState, useEffect } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { ArrowLeft, FileText, ScanText, Target, BarChart3, Edit, Archive } from 'lucide-react';
import { Button } from '../components/ui/button';
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
import { projectsApi } from '../api/projects';
import { offresApi } from '../api/offres';
import { cvsApi } from '../api/cvs';
import type { Project, Offre, CV, APIError } from '../api/types';
import { useToast } from '../hooks/useToast';

export const ProjectDetailPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { error: showError } = useToast();

  const [project, setProject] = useState<Project | null>(null);
  const [offre, setOffre] = useState<Offre | null>(null);
  const [cvs, setCvs] = useState<CV[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);

  const fetchData = async () => {
    if (!projectId) return;

    try {
      setLoading(true);
      setError(null);

      const projectData = await projectsApi.getById(projectId);
      setProject(projectData);

      // Charger l'offre si elle existe
      try {
        const offreData = await offresApi.getByProject(projectId);
        setOffre(offreData);
      } catch {
        setOffre(null);
      }

      // Charger les CVs
      try {
        const cvsData = await cvsApi.getByProject(projectId);
        setCvs(cvsData);
      } catch {
        setCvs([]);
      }
    } catch (err) {
      setError(err as APIError);
      showError('Erreur', 'Impossible de charger le projet');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [projectId]);

  // Rafraîchir les données quand on revient sur la page (ex: après parsing CVs)
  useEffect(() => {
    if (location.state?.refreshData) {
      fetchData();
      // Nettoyer le state pour éviter de rafraîchir à chaque render
      navigate(location.pathname, { replace: true, state: {} });
    }
  }, [location.state]);

  if (loading) return <LoadingPage text="Chargement du projet..." />;
  if (!project) return <div>Projet introuvable</div>;

  return (
    <div className="space-y-6">
      {/* Header avec breadcrumb */}
      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => project.enterprise_id ? navigate(`/enterprises/${project.enterprise_id}`) : navigate('/projects')}
        >
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="flex-1">
          <div className="text-sm text-muted-foreground mb-1">
            {project.enterprise_id ? `Entreprises / ${project.enterprise_id} / Projets` : 'Projets'}
          </div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight">{project.nom}</h1>
            <Badge variant={project.status === 'actif' ? 'default' : 'secondary'}>
              {project.status}
            </Badge>
          </div>
        </div>
        <Button variant="outline" size="sm">
          <Edit className="mr-2 h-4 w-4" />
          Modifier
        </Button>
        {project.status === 'actif' && (
          <Button variant="outline" size="sm">
            <Archive className="mr-2 h-4 w-4" />
            Archiver
          </Button>
        )}
      </div>

      {error && <ErrorBanner error={error} />}

      {/* Hub central du projet */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* 1. Offre d'emploi */}
        <Card className="cursor-pointer hover:shadow-lg transition-shadow">
          <CardHeader>
            <div className="flex items-start justify-between">
              <FileText className="h-8 w-8 text-primary" />
              <Badge variant={offre ? 'default' : 'secondary'}>
                {offre ? 'Créée' : 'À créer'}
              </Badge>
            </div>
            <CardTitle>Offre d'emploi</CardTitle>
            <CardDescription>
              {offre
                ? `${offre.must_have?.length || 0} must-have, ${offre.nice_have?.length || 0} nice-have`
                : 'Créez l\'offre pour ce poste'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              className="w-full"
              variant={offre ? 'outline' : 'default'}
              onClick={() => navigate(`/projects/${projectId}/offre`)}
            >
              {offre ? 'Modifier l\'offre' : 'Créer l\'offre'}
            </Button>
          </CardContent>
        </Card>

        {/* 2. CVs */}
        <Card className="cursor-pointer hover:shadow-lg transition-shadow">
          <CardHeader>
            <div className="flex items-start justify-between">
              <ScanText className="h-8 w-8 text-primary" />
              <Badge variant={cvs.length > 0 ? 'default' : 'secondary'}>
                {cvs.length} CVs
              </Badge>
            </div>
            <CardTitle>Base de CVs</CardTitle>
            <CardDescription>
              {cvs.length > 0
                ? `${cvs.length} CV(s) parsé(s) et prêt(s) pour le matching`
                : 'Uploadez et parsez des CVs'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              className="w-full"
              variant={cvs.length > 0 ? 'outline' : 'default'}
              onClick={() => navigate(`/projects/${projectId}/cvs`)}
            >
              {cvs.length > 0 ? 'Gérer les CVs' : 'Ajouter des CVs'}
            </Button>
          </CardContent>
        </Card>

        {/* 3. Matching */}
        <Card className="cursor-pointer hover:shadow-lg transition-shadow">
          <CardHeader>
            <div className="flex items-start justify-between">
              <Target className="h-8 w-8 text-primary" />
              <Badge variant={cvs.length > 0 ? 'default' : 'secondary'}>
                {cvs.length > 0 ? 'Prêt' : 'Bloqué'}
              </Badge>
            </div>
            <CardTitle>Lancer le matching</CardTitle>
            <CardDescription>
              {cvs.length === 0
                ? 'Ajoutez des CVs d\'abord'
                : 'Tous les prérequis sont OK'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              className="w-full"
              disabled={cvs.length === 0}
              onClick={() => navigate(`/projects/${projectId}/matching`)}
            >
              Lancer le matching
            </Button>
          </CardContent>
        </Card>

        {/* 4. Résultats */}
        <Card className="cursor-pointer hover:shadow-lg transition-shadow">
          <CardHeader>
            <div className="flex items-start justify-between">
              <BarChart3 className="h-8 w-8 text-primary" />
              <Badge variant="secondary">Historique</Badge>
            </div>
            <CardTitle>Résultats de matching</CardTitle>
            <CardDescription>Consultez l'historique des matchings</CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              className="w-full"
              variant="outline"
              onClick={() => navigate(`/projects/${projectId}/results`)}
            >
              Voir les résultats
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};
