import { useState, useEffect } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { ArrowLeft, FileText, ScanText, Target, BarChart3, Edit, Archive } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Select } from '../components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogClose,
} from '../components/ui/dialog';
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
import { enterprisesApi } from '../api/enterprises';
import { offresApi } from '../api/offres';
import { cvsApi } from '../api/cvs';
import type { Project, Offre, CV, APIError, Enterprise } from '../api/types';
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
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const [formData, setFormData] = useState({
    nom: '',
    enterprise_id: '',
    service_demandeur: '',
    responsable_offre: '',
    contact_responsable: '',
    notes: ''
  });
  const [submitting, setSubmitting] = useState(false);

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

  const fetchEnterprises = async () => {
    try {
      const data = await enterprisesApi.getAll();
      setEnterprises(data);
    } catch (err) {
      console.error('Failed to fetch enterprises:', err);
    }
  };

  const handleOpenEditDialog = () => {
    if (!project) return;
    setFormData({
      nom: project.nom,
      enterprise_id: project.enterprise_id || '',
      service_demandeur: project.service_demandeur || '',
      responsable_offre: project.responsable_offre || '',
      contact_responsable: project.contact_responsable || '',
      notes: project.notes || ''
    });
    setEditDialogOpen(true);
  };

  const handleCloseEditDialog = () => {
    setEditDialogOpen(false);
  };

  const handleSubmitEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!projectId) return;

    setSubmitting(true);
    try {
      await projectsApi.update(projectId, formData);
      await fetchData();
      handleCloseEditDialog();
    } catch (err) {
      setError(err as APIError);
      showError('Erreur', 'Impossible de modifier le projet');
    } finally {
      setSubmitting(false);
    }
  };

  useEffect(() => {
    fetchEnterprises();
  }, []);

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
        <Button variant="outline" size="sm" onClick={handleOpenEditDialog}>
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

      {/* Edit Dialog */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
          <DialogClose onClick={handleCloseEditDialog} />
          <form onSubmit={handleSubmitEdit}>
            <DialogHeader>
              <DialogTitle>Modifier le projet</DialogTitle>
            </DialogHeader>
            <div className="space-y-6 py-4">
              {/* Informations de base */}
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-foreground">Informations de base</h3>
                <div className="space-y-2">
                  <Label htmlFor="nom">Nom du projet *</Label>
                  <Input
                    id="nom"
                    value={formData.nom}
                    onChange={(e) => setFormData({ ...formData, nom: e.target.value })}
                    placeholder="Ex: Recrutement Développeur Senior"
                    required
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="enterprise_id">Entreprise *</Label>
                  <Select
                    id="enterprise_id"
                    value={formData.enterprise_id}
                    onChange={(e) => setFormData({ ...formData, enterprise_id: e.target.value })}
                    disabled={submitting}
                    required
                  >
                    <option value="">Sélectionner une entreprise</option>
                    {enterprises.map((enterprise) => (
                      <option key={enterprise.id} value={enterprise.id}>
                        {enterprise.nom}
                      </option>
                    ))}
                  </Select>
                </div>
              </div>

              {/* Informations complémentaires */}
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-foreground">Informations complémentaires</h3>
                <div className="space-y-2">
                  <Label htmlFor="service_demandeur">Service demandeur</Label>
                  <Input
                    id="service_demandeur"
                    value={formData.service_demandeur}
                    onChange={(e) => setFormData({ ...formData, service_demandeur: e.target.value })}
                    placeholder="Ex: Direction IT, RH..."
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="responsable_offre">Responsable de l'offre</Label>
                  <Input
                    id="responsable_offre"
                    value={formData.responsable_offre}
                    onChange={(e) => setFormData({ ...formData, responsable_offre: e.target.value })}
                    placeholder="Nom du responsable"
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="contact_responsable">Contact du responsable</Label>
                  <Input
                    id="contact_responsable"
                    value={formData.contact_responsable}
                    onChange={(e) => setFormData({ ...formData, contact_responsable: e.target.value })}
                    placeholder="Email ou téléphone"
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="notes">Notes</Label>
                  <Textarea
                    id="notes"
                    value={formData.notes}
                    onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                    placeholder="Notes internes sur le projet..."
                    rows={3}
                    disabled={submitting}
                  />
                </div>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={handleCloseEditDialog} disabled={submitting}>
                Annuler
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Enregistrement...' : 'Modifier'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};
