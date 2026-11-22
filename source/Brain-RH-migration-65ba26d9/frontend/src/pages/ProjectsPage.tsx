import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Pencil, Trash2, History, FolderOpen } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Select } from '../components/ui/select';
import { Badge } from '../components/ui/badge';
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
  CardFooter,
} from '../components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import { LoadingPage } from '../components/shared/Loading';
import { ErrorBanner } from '../components/shared/ErrorBanner';
import { EmptyState } from '../components/shared/EmptyState';
import { projectsApi } from '../api/projects';
import { enterprisesApi } from '../api/enterprises';
import type { Project, Enterprise, APIError, ProjectHistory } from '../api/types';

export const ProjectsPage: React.FC = () => {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const [selectedEnterpriseId, setSelectedEnterpriseId] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [editingProject, setEditingProject] = useState<Project | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [projectHistory, setProjectHistory] = useState<ProjectHistory | null>(null);
  const [formData, setFormData] = useState({
    nom: '',
    enterprise_id: '',
    service_demandeur: '',
    responsable_offre: '',
    contact_responsable: '',
    notes: ''
  });
  const [submitting, setSubmitting] = useState(false);

  const fetchEnterprises = async () => {
    try {
      const data = await enterprisesApi.getAll();
      setEnterprises(data);
    } catch (err) {
      console.error('Failed to fetch enterprises:', err);
    }
  };

  const fetchProjects = async (enterpriseId?: string) => {
    try {
      setLoading(true);
      setError(null);
      const data = await projectsApi.getAll(enterpriseId);
      setProjects(data);
    } catch (err) {
      setError(err as APIError);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEnterprises();
    fetchProjects();
  }, []);

  useEffect(() => {
    fetchProjects(selectedEnterpriseId || undefined);
  }, [selectedEnterpriseId]);

  const handleOpenDialog = (project?: Project) => {
    if (project) {
      setEditingProject(project);
      setFormData({
        nom: project.nom,
        enterprise_id: project.enterprise_id || '',
        service_demandeur: project.service_demandeur || '',
        responsable_offre: project.responsable_offre || '',
        contact_responsable: project.contact_responsable || '',
        notes: project.notes || ''
      });
    } else {
      setEditingProject(null);
      setFormData({
        nom: '',
        enterprise_id: selectedEnterpriseId,
        service_demandeur: '',
        responsable_offre: '',
        contact_responsable: '',
        notes: ''
      });
    }
    setDialogOpen(true);
  };

  const handleCloseDialog = () => {
    setDialogOpen(false);
    setEditingProject(null);
    setFormData({
      nom: '',
      enterprise_id: '',
      service_demandeur: '',
      responsable_offre: '',
      contact_responsable: '',
      notes: ''
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      if (editingProject) {
        await projectsApi.update(editingProject.id, formData);
      } else {
        await projectsApi.create(formData);
      }
      await fetchProjects(selectedEnterpriseId || undefined);
      handleCloseDialog();
    } catch (err) {
      setError(err as APIError);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!deletingId) return;
    setSubmitting(true);
    try {
      await projectsApi.delete(deletingId);
      await fetchProjects(selectedEnterpriseId || undefined);
      setDeleteDialogOpen(false);
      setDeletingId(null);
    } catch (err) {
      setError(err as APIError);
    } finally {
      setSubmitting(false);
    }
  };

  const openDeleteDialog = (id: string) => {
    setDeletingId(id);
    setDeleteDialogOpen(true);
  };

  const openHistoryDialog = async (projectId: string) => {
    try {
      const history = await projectsApi.getHistory(projectId);
      setProjectHistory(history);
      setHistoryDialogOpen(true);
    } catch (err) {
      setError(err as APIError);
    }
  };

  const getEnterpriseName = (enterpriseId?: string) => {
    if (!enterpriseId) return 'Non assigné';
    const enterprise = enterprises.find((e) => e.id === enterpriseId);
    return enterprise?.nom || enterpriseId;
  };

  if (loading) return <LoadingPage text="Chargement des projets..." />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Projets</h1>
          <p className="text-muted-foreground">Gérez vos projets de recrutement</p>
        </div>
        <Button onClick={() => handleOpenDialog()}>
          <Plus className="mr-2 h-4 w-4" />
          Nouveau projet
        </Button>
      </div>

      {/* Filter by enterprise */}
      <div className="flex gap-4">
        <div className="w-64">
          <Label htmlFor="enterprise-filter">Filtrer par entreprise</Label>
          <Select
            id="enterprise-filter"
            value={selectedEnterpriseId}
            onChange={(e) => setSelectedEnterpriseId(e.target.value)}
          >
            <option value="">Toutes les entreprises</option>
            {enterprises.map((enterprise) => (
              <option key={enterprise.id} value={enterprise.id}>
                {enterprise.nom}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {error && <ErrorBanner error={error} />}

      {projects.length === 0 ? (
        <EmptyState
          icon={FolderOpen}
          title="Aucun projet"
          description="Créez votre premier projet de recrutement"
          action={{
            label: 'Créer un projet',
            onClick: () => handleOpenDialog(),
          }}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((project) => (
            <Card
              key={project.id}
              className="cursor-pointer hover:shadow-lg transition-shadow"
              onClick={() => navigate(`/projects/${project.id}`)}
            >
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <CardTitle className="text-lg">{project.nom}</CardTitle>
                    <CardDescription className="mt-1">
                      {getEnterpriseName(project.enterprise_id)}
                    </CardDescription>
                  </div>
                  <Badge variant={project.status === 'actif' ? 'default' : 'secondary'}>
                    {project.status}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-muted-foreground space-y-1">
                  <p>
                    Créé le {new Date(project.created_at).toLocaleDateString('fr-FR')}
                  </p>
                  <p>
                    Modifié le {new Date(project.last_modified).toLocaleDateString('fr-FR')}
                  </p>
                </div>
              </CardContent>
              <CardFooter className="flex gap-2 justify-end">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={(e) => {
                    e.stopPropagation();
                    openHistoryDialog(project.id);
                  }}
                  aria-label="Historique"
                >
                  <History className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleOpenDialog(project);
                  }}
                  aria-label="Modifier"
                >
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={(e) => {
                    e.stopPropagation();
                    openDeleteDialog(project.id);
                  }}
                  aria-label="Supprimer"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
          <DialogClose onClick={handleCloseDialog} />
          <form onSubmit={handleSubmit}>
            <DialogHeader>
              <DialogTitle>
                {editingProject ? 'Modifier le projet' : 'Nouveau projet'}
              </DialogTitle>
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
              <Button type="button" variant="outline" onClick={handleCloseDialog} disabled={submitting}>
                Annuler
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Enregistrement...' : editingProject ? 'Modifier' : 'Créer'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent onClick={(e) => e.stopPropagation()}>
          <DialogClose onClick={() => setDeleteDialogOpen(false)} />
          <DialogHeader>
            <DialogTitle>Confirmer la suppression</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground py-4">
            Êtes-vous sûr de vouloir supprimer ce projet ? Cette action est irréversible.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)} disabled={submitting}>
              Annuler
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={submitting}>
              {submitting ? 'Suppression...' : 'Supprimer'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* History Dialog */}
      <Dialog open={historyDialogOpen} onOpenChange={setHistoryDialogOpen}>
        <DialogContent onClick={(e) => e.stopPropagation()}>
          <DialogClose onClick={() => setHistoryDialogOpen(false)} />
          <DialogHeader>
            <DialogTitle>Historique du projet</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            {projectHistory && projectHistory.total > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Timestamp</TableHead>
                    <TableHead>Candidats</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {projectHistory.items.map((item) => (
                    <TableRow key={item.matching_id}>
                      <TableCell>
                        {new Date(item.timestamp).toLocaleString('fr-FR')}
                      </TableCell>
                      <TableCell>{item.candidats_count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-8">
                Aucun historique disponible
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};
