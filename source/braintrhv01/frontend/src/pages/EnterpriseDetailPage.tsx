import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, FolderOpen, Archive, Save, X, Building2, Mail, Phone, Globe, Edit } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Select } from '../components/ui/select';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from '../components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { LoadingPage } from '../components/shared/Loading';
import { ErrorBanner } from '../components/shared/ErrorBanner';
import { EmptyState } from '../components/shared/EmptyState';
import { enterprisesApi } from '../api/enterprises';
import { projectsApi } from '../api/projects';
import type { Enterprise, Project, APIError, Contact } from '../api/types';
import { useToast } from '../hooks/useToast';

export const EnterpriseDetailPage: React.FC = () => {
  const { enterpriseId } = useParams<{ enterpriseId: string }>();
  const navigate = useNavigate();
  const { success, error: showError } = useToast();

  const [enterprise, setEnterprise] = useState<Enterprise | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  // Form state pour l'édition de l'entreprise
  const [formData, setFormData] = useState({
    nom: '',
    site_web: '',
    secteur: '',
    notes: '',
    contacts: [] as Contact[]
  });

  // States pour la création de projet
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [projectFormData, setProjectFormData] = useState({
    nom: '',
    enterprise_id: enterpriseId || '',
    service_demandeur: '',
    responsable_offre: '',
    contact_responsable: '',
    notes: ''
  });
  const [submitting, setSubmitting] = useState(false);

  const fetchData = async () => {
    if (!enterpriseId) return;

    try {
      setLoading(true);
      setError(null);

      // Charger l'entreprise et ses projets en parallèle
      const [enterpriseData, projectsData] = await Promise.all([
        enterprisesApi.getById(enterpriseId),
        projectsApi.getAll(),
      ]);

      setEnterprise(enterpriseData);
      setFormData({
        nom: enterpriseData.nom,
        site_web: enterpriseData.site_web || '',
        secteur: enterpriseData.secteur || '',
        notes: enterpriseData.notes || '',
        contacts: enterpriseData.contacts || []
      });
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

  const handleSave = async () => {
    if (!enterprise) return;

    try {
      setSaving(true);
      await enterprisesApi.update(enterprise.id, formData);
      success('Modifications enregistrées');
      setEditing(false);
      // Recharger les données
      await fetchData();
    } catch (err) {
      showError('Erreur', 'Impossible d\'enregistrer les modifications');
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (!enterprise) return;
    // Restaurer les données originales
    setFormData({
      nom: enterprise.nom,
      site_web: enterprise.site_web || '',
      secteur: enterprise.secteur || '',
      notes: enterprise.notes || '',
      contacts: enterprise.contacts || []
    });
    setEditing(false);
  };

  const addContact = () => {
    setFormData({
      ...formData,
      contacts: [
        ...formData.contacts,
        {
          nom_complet: '',
          email: '',
          poste: '',
          telephone: '',
          canal_prefere: 'email',
          notes: ''
        }
      ]
    });
  };

  const removeContact = (index: number) => {
    setFormData({
      ...formData,
      contacts: formData.contacts.filter((_, i) => i !== index)
    });
  };

  const updateContact = (index: number, field: keyof Contact, value: string) => {
    const updatedContacts = [...formData.contacts];
    updatedContacts[index] = {
      ...updatedContacts[index],
      [field]: value
    };
    setFormData({
      ...formData,
      contacts: updatedContacts
    });
  };

  const handleCreateProject = () => {
    // Ouvrir la modale avec l'enterprise_id pré-rempli
    setProjectFormData({
      nom: '',
      enterprise_id: enterpriseId || '',
      service_demandeur: '',
      responsable_offre: '',
      contact_responsable: '',
      notes: ''
    });
    setProjectDialogOpen(true);
  };

  const handleCloseProjectDialog = () => {
    setProjectDialogOpen(false);
    setProjectFormData({
      nom: '',
      enterprise_id: enterpriseId || '',
      service_demandeur: '',
      responsable_offre: '',
      contact_responsable: '',
      notes: ''
    });
  };

  const handleSubmitProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!enterpriseId) return;

    setSubmitting(true);
    try {
      // Créer le projet via l'API avec enterprise_id
      await projectsApi.create({
        ...projectFormData,
        enterprise_id: enterpriseId
      });
      success('Projet créé avec succès');
      handleCloseProjectDialog();
      // Recharger les données pour afficher le nouveau projet
      await fetchData();
    } catch (err) {
      showError('Erreur', 'Impossible de créer le projet');
      console.error('Erreur création projet:', err);
    } finally {
      setSubmitting(false);
    }
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
        </div>
        <Button onClick={handleCreateProject}>
          <Plus className="mr-2 h-4 w-4" />
          Nouveau projet
        </Button>
      </div>

      {error && <ErrorBanner error={error} />}

      {/* Onglets Fiche / Tableau de bord */}
      <Tabs defaultValue="dashboard" className="space-y-6">
        <TabsList>
          <TabsTrigger value="dashboard">Tableau de bord</TabsTrigger>
          <TabsTrigger value="fiche">Fiche entreprise</TabsTrigger>
        </TabsList>

        {/* Onglet Tableau de bord */}
        <TabsContent value="dashboard" className="space-y-6">
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
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/projects/${project.id}`);
                        }}
                      >
                        <Edit className="h-4 w-4" />
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
        </TabsContent>

        {/* Onglet Fiche entreprise */}
        <TabsContent value="fiche" className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Informations de l'entreprise</CardTitle>
                  <CardDescription>Détails et informations de contact</CardDescription>
                </div>
                {!editing ? (
                  <Button onClick={() => setEditing(true)}>Modifier</Button>
                ) : (
                  <div className="flex gap-2">
                    <Button variant="outline" onClick={handleCancel} disabled={saving}>
                      <X className="mr-2 h-4 w-4" />
                      Annuler
                    </Button>
                    <Button onClick={handleSave} disabled={saving}>
                      <Save className="mr-2 h-4 w-4" />
                      {saving ? 'Enregistrement...' : 'Enregistrer'}
                    </Button>
                  </div>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Informations de base */}
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <Building2 className="h-4 w-4" />
                  Informations générales
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="nom">Nom *</Label>
                    {editing ? (
                      <Input
                        id="nom"
                        value={formData.nom}
                        onChange={(e) => setFormData({ ...formData, nom: e.target.value })}
                        placeholder="Ex: TechCorp"
                        required
                      />
                    ) : (
                      <p className="text-base font-medium">{enterprise.nom}</p>
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="secteur">Secteur</Label>
                    {editing ? (
                      <Input
                        id="secteur"
                        value={formData.secteur}
                        onChange={(e) => setFormData({ ...formData, secteur: e.target.value })}
                        placeholder="Ex: Technologies, Finance, Santé..."
                      />
                    ) : (
                      <p className="text-base">{enterprise.secteur || '-'}</p>
                    )}
                  </div>
                  <div className="space-y-2 md:col-span-2">
                    <Label htmlFor="site_web" className="flex items-center gap-2">
                      <Globe className="h-4 w-4" />
                      Site web
                    </Label>
                    {editing ? (
                      <Input
                        id="site_web"
                        type="url"
                        value={formData.site_web}
                        onChange={(e) => setFormData({ ...formData, site_web: e.target.value })}
                        placeholder="https://www.exemple.com"
                      />
                    ) : (
                      enterprise.site_web ? (
                        <a href={enterprise.site_web} target="_blank" rel="noopener noreferrer" className="text-base text-primary hover:underline">
                          {enterprise.site_web}
                        </a>
                      ) : (
                        <p className="text-base text-muted-foreground">-</p>
                      )
                    )}
                  </div>
                  <div className="space-y-2 md:col-span-2">
                    <Label htmlFor="notes">Notes</Label>
                    {editing ? (
                      <Textarea
                        id="notes"
                        value={formData.notes}
                        onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                        placeholder="Notes internes sur l'entreprise..."
                        rows={3}
                      />
                    ) : (
                      <p className="text-base whitespace-pre-wrap">{enterprise.notes || '-'}</p>
                    )}
                  </div>
                </div>
              </div>

              {/* Contacts */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                    <Mail className="h-4 w-4" />
                    Contacts
                  </h3>
                  {editing && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={addContact}
                    >
                      <Plus className="mr-2 h-4 w-4" />
                      Ajouter un contact
                    </Button>
                  )}
                </div>

                {formData.contacts.length === 0 ? (
                  <p className="text-base text-muted-foreground">Aucun contact</p>
                ) : (
                  <div className="space-y-4">
                    {formData.contacts.map((contact, index) => (
                      <Card key={index} className="bg-muted/20">
                        <CardContent className="pt-6">
                          {editing && (
                            <div className="flex justify-end mb-2">
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                onClick={() => removeContact(index)}
                              >
                                <X className="h-4 w-4" />
                              </Button>
                            </div>
                          )}
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <div className="space-y-2">
                              <Label>Nom complet</Label>
                              {editing ? (
                                <Input
                                  value={contact.nom_complet}
                                  onChange={(e) => updateContact(index, 'nom_complet', e.target.value)}
                                  placeholder="Jean Dupont"
                                  required
                                />
                              ) : (
                                <p className="text-base font-medium">{contact.nom_complet}</p>
                              )}
                            </div>
                            <div className="space-y-2">
                              <Label>Poste</Label>
                              {editing ? (
                                <Input
                                  value={contact.poste || ''}
                                  onChange={(e) => updateContact(index, 'poste', e.target.value)}
                                  placeholder="Ex: Responsable RH"
                                />
                              ) : (
                                <p className="text-base">{contact.poste || '-'}</p>
                              )}
                            </div>
                            <div className="space-y-2">
                              <Label className="flex items-center gap-2">
                                <Mail className="h-3 w-3" />
                                Email
                              </Label>
                              {editing ? (
                                <Input
                                  type="email"
                                  value={contact.email}
                                  onChange={(e) => updateContact(index, 'email', e.target.value)}
                                  placeholder="jean.dupont@exemple.com"
                                />
                              ) : (
                                <a href={`mailto:${contact.email}`} className="text-base text-primary hover:underline">
                                  {contact.email}
                                </a>
                              )}
                            </div>
                            <div className="space-y-2">
                              <Label className="flex items-center gap-2">
                                <Phone className="h-3 w-3" />
                                Téléphone
                              </Label>
                              {editing ? (
                                <Input
                                  type="tel"
                                  value={contact.telephone || ''}
                                  onChange={(e) => updateContact(index, 'telephone', e.target.value)}
                                  placeholder="+33 6 12 34 56 78"
                                />
                              ) : (
                                <p className="text-base">{contact.telephone || '-'}</p>
                              )}
                            </div>
                            <div className="space-y-2">
                              <Label>Canal préféré</Label>
                              {editing ? (
                                <Select
                                  value={contact.canal_prefere || 'email'}
                                  onChange={(e) => updateContact(index, 'canal_prefere', e.target.value)}
                                >
                                  <option value="email">Email</option>
                                  <option value="telephone">Téléphone</option>
                                  <option value="slack">Slack</option>
                                  <option value="autre">Autre</option>
                                </Select>
                              ) : (
                                <p className="text-base capitalize">{contact.canal_prefere || 'email'}</p>
                              )}
                            </div>
                            {(editing || contact.notes) && (
                              <div className="space-y-2 md:col-span-2">
                                <Label>Notes</Label>
                                {editing ? (
                                  <Textarea
                                    value={contact.notes || ''}
                                    onChange={(e) => updateContact(index, 'notes', e.target.value)}
                                    placeholder="Informations complémentaires..."
                                    rows={2}
                                  />
                                ) : (
                                  <p className="text-base whitespace-pre-wrap">{contact.notes}</p>
                                )}
                              </div>
                            )}
                          </div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Modale de création de projet */}
      <Dialog open={projectDialogOpen} onOpenChange={setProjectDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <form onSubmit={handleSubmitProject}>
            <DialogHeader>
              <DialogTitle>Nouveau projet</DialogTitle>
            </DialogHeader>
            <div className="space-y-6 py-4">
              {/* Informations de base */}
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-foreground">Informations de base</h3>
                <div className="space-y-2">
                  <Label htmlFor="project-nom">Nom du projet *</Label>
                  <Input
                    id="project-nom"
                    value={projectFormData.nom}
                    onChange={(e) => setProjectFormData({ ...projectFormData, nom: e.target.value })}
                    placeholder="Ex: Recrutement Développeur Senior"
                    required
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="project-service">Service demandeur</Label>
                  <Input
                    id="project-service"
                    value={projectFormData.service_demandeur}
                    onChange={(e) => setProjectFormData({ ...projectFormData, service_demandeur: e.target.value })}
                    placeholder="Ex: IT, RH, Marketing..."
                    disabled={submitting}
                  />
                </div>
              </div>

              {/* Contact et responsable */}
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-foreground">Contact et suivi</h3>
                <div className="space-y-2">
                  <Label htmlFor="project-responsable">Responsable de l'offre</Label>
                  <Input
                    id="project-responsable"
                    value={projectFormData.responsable_offre}
                    onChange={(e) => setProjectFormData({ ...projectFormData, responsable_offre: e.target.value })}
                    placeholder="Ex: Marie Dupont"
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="project-contact">Contact responsable</Label>
                  <Input
                    id="project-contact"
                    type="email"
                    value={projectFormData.contact_responsable}
                    onChange={(e) => setProjectFormData({ ...projectFormData, contact_responsable: e.target.value })}
                    placeholder="Ex: marie.dupont@entreprise.com"
                    disabled={submitting}
                  />
                </div>
              </div>

              {/* Notes */}
              <div className="space-y-2">
                <Label htmlFor="project-notes">Notes internes</Label>
                <Textarea
                  id="project-notes"
                  value={projectFormData.notes}
                  onChange={(e) => setProjectFormData({ ...projectFormData, notes: e.target.value })}
                  placeholder="Notes et informations complémentaires..."
                  rows={3}
                  disabled={submitting}
                />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={handleCloseProjectDialog} disabled={submitting}>
                Annuler
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Création...' : 'Créer le projet'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};
