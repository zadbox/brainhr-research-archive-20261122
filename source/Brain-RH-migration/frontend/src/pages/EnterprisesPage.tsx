import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Pencil, Trash2, Building2, X } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogClose,
} from '../components/ui/dialog';
import { Select } from '../components/ui/select';
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
import { enterprisesApi } from '../api/enterprises';
import type { Enterprise, Contact, APIError } from '../api/types';

export const EnterprisesPage: React.FC = () => {
  const navigate = useNavigate();
  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [editingEnterprise, setEditingEnterprise] = useState<Enterprise | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [formData, setFormData] = useState({
    nom: '',
    site_web: '',
    secteur: '',
    notes: '',
    contacts: [] as Contact[]
  });
  const [submitting, setSubmitting] = useState(false);

  const fetchEnterprises = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await enterprisesApi.getAll();
      setEnterprises(data);
    } catch (err) {
      setError(err as APIError);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEnterprises();
  }, []);

  const handleOpenDialog = (enterprise?: Enterprise) => {
    if (enterprise) {
      setEditingEnterprise(enterprise);
      setFormData({
        nom: enterprise.nom,
        site_web: enterprise.site_web || '',
        secteur: enterprise.secteur || '',
        notes: enterprise.notes || '',
        contacts: enterprise.contacts || []
      });
    } else {
      setEditingEnterprise(null);
      setFormData({
        nom: '',
        site_web: '',
        secteur: '',
        notes: '',
        contacts: []
      });
    }
    setDialogOpen(true);
  };

  const handleCloseDialog = () => {
    setDialogOpen(false);
    setEditingEnterprise(null);
    setFormData({
      nom: '',
      site_web: '',
      secteur: '',
      notes: '',
      contacts: []
    });
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      if (editingEnterprise) {
        await enterprisesApi.update(editingEnterprise.id, formData);
      } else {
        await enterprisesApi.create(formData);
      }
      await fetchEnterprises();
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
      await enterprisesApi.delete(deletingId);
      await fetchEnterprises();
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

  if (loading) return <LoadingPage text="Chargement des entreprises..." />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Entreprises</h1>
          <p className="text-muted-foreground">Gérez les entreprises clientes</p>
        </div>
        <Button onClick={() => handleOpenDialog()}>
          <Plus className="mr-2 h-4 w-4" />
          Nouvelle entreprise
        </Button>
      </div>

      {error && <ErrorBanner error={error} />}

      {enterprises.length === 0 ? (
        <EmptyState
          icon={Building2}
          title="Aucune entreprise"
          description="Commencez par créer votre première entreprise"
          action={{
            label: 'Créer une entreprise',
            onClick: () => handleOpenDialog(),
          }}
        />
      ) : (
        <div className="border rounded-lg">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nom</TableHead>
                <TableHead>Secteur</TableHead>
                <TableHead>Projets</TableHead>
                <TableHead>Date de création</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {enterprises.map((enterprise) => (
                <TableRow
                  key={enterprise.id}
                  className="cursor-pointer hover:bg-muted/50"
                  onClick={() => navigate(`/enterprises/${enterprise.id}`)}
                >
                  <TableCell className="font-medium">{enterprise.nom}</TableCell>
                  <TableCell>{enterprise.secteur || '-'}</TableCell>
                  <TableCell>{enterprise.projects_count}</TableCell>
                  <TableCell>
                    {enterprise.created_at
                      ? new Date(enterprise.created_at).toLocaleDateString('fr-FR')
                      : '-'}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleOpenDialog(enterprise);
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
                          openDeleteDialog(enterprise.id);
                        }}
                        aria-label="Supprimer"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
          <DialogClose onClick={handleCloseDialog} />
          <form onSubmit={handleSubmit}>
            <DialogHeader>
              <DialogTitle>
                {editingEnterprise ? 'Modifier l\'entreprise' : 'Nouvelle entreprise'}
              </DialogTitle>
            </DialogHeader>
            <div className="space-y-6 py-4">
              {/* Informations de base */}
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-foreground">Informations de base</h3>
                <div className="space-y-2">
                  <Label htmlFor="nom">Nom *</Label>
                  <Input
                    id="nom"
                    value={formData.nom}
                    onChange={(e) => setFormData({ ...formData, nom: e.target.value })}
                    placeholder="Ex: TechCorp"
                    required
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="site_web">Site web</Label>
                  <Input
                    id="site_web"
                    type="url"
                    value={formData.site_web}
                    onChange={(e) => setFormData({ ...formData, site_web: e.target.value })}
                    placeholder="https://www.exemple.com"
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="secteur">Secteur</Label>
                  <Input
                    id="secteur"
                    value={formData.secteur}
                    onChange={(e) => setFormData({ ...formData, secteur: e.target.value })}
                    placeholder="Ex: Technologies, Finance, Santé..."
                    disabled={submitting}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="notes">Notes</Label>
                  <Textarea
                    id="notes"
                    value={formData.notes}
                    onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                    placeholder="Notes internes sur l'entreprise..."
                    rows={3}
                    disabled={submitting}
                  />
                </div>
              </div>

              {/* Contacts */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-foreground">Contacts</h3>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={addContact}
                    disabled={submitting}
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    Ajouter un contact
                  </Button>
                </div>

                {formData.contacts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Aucun contact ajouté</p>
                ) : (
                  <div className="space-y-4">
                    {formData.contacts.map((contact, index) => (
                      <div key={index} className="border rounded-lg p-4 space-y-3 bg-muted/20">
                        <div className="flex items-center justify-between">
                          <h4 className="text-sm font-medium">Contact {index + 1}</h4>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            onClick={() => removeContact(index)}
                            disabled={submitting}
                          >
                            <X className="h-4 w-4" />
                          </Button>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                          <div className="space-y-2">
                            <Label htmlFor={`contact-nom-${index}`}>Nom complet *</Label>
                            <Input
                              id={`contact-nom-${index}`}
                              value={contact.nom_complet}
                              onChange={(e) => updateContact(index, 'nom_complet', e.target.value)}
                              placeholder="Jean Dupont"
                              required
                              disabled={submitting}
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor={`contact-poste-${index}`}>Poste</Label>
                            <Input
                              id={`contact-poste-${index}`}
                              value={contact.poste || ''}
                              onChange={(e) => updateContact(index, 'poste', e.target.value)}
                              placeholder="Ex: Responsable RH"
                              disabled={submitting}
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor={`contact-email-${index}`}>Email *</Label>
                            <Input
                              id={`contact-email-${index}`}
                              type="email"
                              value={contact.email}
                              onChange={(e) => updateContact(index, 'email', e.target.value)}
                              placeholder="jean.dupont@exemple.com"
                              required
                              disabled={submitting}
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor={`contact-telephone-${index}`}>Téléphone</Label>
                            <Input
                              id={`contact-telephone-${index}`}
                              type="tel"
                              value={contact.telephone || ''}
                              onChange={(e) => updateContact(index, 'telephone', e.target.value)}
                              placeholder="+33 6 12 34 56 78"
                              disabled={submitting}
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor={`contact-canal-${index}`}>Canal préféré</Label>
                            <Select
                              id={`contact-canal-${index}`}
                              value={contact.canal_prefere || 'email'}
                              onChange={(e) => updateContact(index, 'canal_prefere', e.target.value)}
                              disabled={submitting}
                            >
                              <option value="email">Email</option>
                              <option value="telephone">Téléphone</option>
                              <option value="slack">Slack</option>
                              <option value="autre">Autre</option>
                            </Select>
                          </div>
                          <div className="space-y-2 col-span-2">
                            <Label htmlFor={`contact-notes-${index}`}>Notes</Label>
                            <Textarea
                              id={`contact-notes-${index}`}
                              value={contact.notes || ''}
                              onChange={(e) => updateContact(index, 'notes', e.target.value)}
                              placeholder="Informations complémentaires..."
                              rows={2}
                              disabled={submitting}
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={handleCloseDialog} disabled={submitting}>
                Annuler
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Enregistrement...' : editingEnterprise ? 'Modifier' : 'Créer'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent onClick={(e) => e.stopPropagation()}>
          <DialogClose onClick={() => setDeleteDialogOpen(false)} />
          <DialogHeader>
            <DialogTitle>Confirmer la suppression</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground py-4">
            Êtes-vous sûr de vouloir supprimer cette entreprise ? Cette action est irréversible.
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
              disabled={submitting}
            >
              Annuler
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={submitting}>
              {submitting ? 'Suppression...' : 'Supprimer'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
