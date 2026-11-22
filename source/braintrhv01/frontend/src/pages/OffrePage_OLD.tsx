import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Save, Sparkles, Loader2, CheckCircle } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card';
import { LoadingPage } from '../components/shared/Loading';
import { ErrorBanner } from '../components/shared/ErrorBanner';
import { offresApi } from '../api/offres';
import { projectsApi } from '../api/projects';
import type {
  Offre,
  APIError,
  Project,
  EnrichmentResult,
  EnrichmentSelections,
  QuestionResponses,
} from '../api/types';
import { useToast } from '../hooks/useToast';

export const OffrePage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { success, error: showError } = useToast();

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<APIError | null>(null);

  // Offre data (structure parsée)
  const [offreData, setOffreData] = useState<Offre>({
    sections: {
      titre: '',
      description: '',
      competences_techniques: [],
      competences_transversales: [],
      langues: [],
      experiences_professionnelles: [],
      formations: [],
      certifications: [],
      projets: [],
    },
    must_have: [],
    nice_have: [],
  });

  // Enrichissement states
  const [enriching, setEnriching] = useState(false);
  const [enrichmentResult, setEnrichmentResult] = useState<EnrichmentResult | null>(null);
  const [selections, setSelections] = useState<EnrichmentSelections>({
    competences: [],
    outils: [],
    langages: [],
    certifications: [],
    missions: [],
  });
  const [questionResponses, setQuestionResponses] = useState<QuestionResponses>({});

  useEffect(() => {
    if (!projectId) return;
    fetchData();
  }, [projectId]);

  const fetchData = async () => {
    if (!projectId) return;

    try {
      setLoading(true);
      setError(null);

      // Load project
      const projectData = await projectsApi.getById(projectId);
      setProject(projectData);

      // Try to load existing offre
      try {
        const existingOffre = await offresApi.getByProject(projectId);
        setOffreData(existingOffre);
      } catch {
        // No offre yet, start with empty form
      }
    } catch (err) {
      setError(err as APIError);
      showError('Erreur', 'Impossible de charger le projet');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!projectId) return;

    setSaving(true);
    try {
      await offresApi.upsert(projectId, offreData);
      success('Offre sauvegardée', "L'offre a été enregistrée avec succès");
    } catch (err) {
      setError(err as APIError);
      showError('Erreur', "Impossible de sauvegarder l'offre");
    } finally {
      setSaving(false);
    }
  };

  const handleEnrichWithAI = async () => {
    if (!projectId || !offreData.sections.description) {
      showError('Erreur', "Veuillez d'abord saisir une description");
      return;
    }

    setEnriching(true);
    try {
      const result = await offresApi.enrich(projectId, offreData.sections.description);
      setEnrichmentResult(result);
      // Reset selections
      setSelections({
        competences: [],
        outils: [],
        langages: [],
        certifications: [],
        missions: [],
      });
      setQuestionResponses({});
      success(
        'Enrichissement terminé',
        `Score de complétude: ${result.coverage_score}%`
      );
    } catch (err) {
      setError(err as APIError);
      showError('Erreur', "Échec de l'enrichissement IA");
    } finally {
      setEnriching(false);
    }
  };

  const toggleSelection = (category: keyof EnrichmentSelections, index: number) => {
    setSelections((prev) => {
      const newSelections = { ...prev };
      if (newSelections[category].includes(index)) {
        newSelections[category] = newSelections[category].filter((i) => i !== index);
      } else {
        newSelections[category] = [...newSelections[category], index];
      }
      return newSelections;
    });
  };

  const applySelections = () => {
    if (!enrichmentResult) return;

    const { propositions } = enrichmentResult;
    const newOffreData = { ...offreData };

    // Appliquer les sélections de compétences
    selections.competences.forEach((idx) => {
      const comp = propositions.competences[idx];
      if (comp && !newOffreData.sections.competences_techniques.includes(comp.name)) {
        newOffreData.sections.competences_techniques.push(comp.name);
      }
      // Ajouter aux must_have/nice_have selon le type
      if (comp.type === 'must' && !newOffreData.must_have.includes(comp.name)) {
        newOffreData.must_have.push(comp.name);
      } else if (comp.type === 'nice' && !newOffreData.nice_have.includes(comp.name)) {
        newOffreData.nice_have.push(comp.name);
      }
    });

    // Appliquer les outils
    selections.outils.forEach((idx) => {
      const outil = propositions.outils[idx];
      if (outil && !newOffreData.sections.competences_techniques.includes(outil.name)) {
        newOffreData.sections.competences_techniques.push(outil.name);
      }
    });

    // Appliquer les langages
    selections.langages.forEach((idx) => {
      const lang = propositions.langages[idx];
      if (lang && !newOffreData.sections.competences_techniques.includes(lang.name)) {
        newOffreData.sections.competences_techniques.push(lang.name);
      }
    });

    // Appliquer les certifications
    selections.certifications.forEach((idx) => {
      const cert = propositions.certifications[idx];
      if (cert && !newOffreData.sections.certifications.includes(cert.name)) {
        newOffreData.sections.certifications.push(cert.name);
      }
    });

    // Appliquer les missions
    selections.missions.forEach((idx) => {
      const mission = propositions.missions[idx];
      if (mission && !newOffreData.sections.projets.includes(mission.text)) {
        newOffreData.sections.projets.push(mission.text);
      }
    });

    // Intégrer les réponses aux questions dans description
    if (Object.keys(questionResponses).length > 0) {
      let updatedDescription = newOffreData.sections.description;
      updatedDescription += '\n\n--- Informations complémentaires ---\n';
      Object.entries(questionResponses).forEach(([question, response]) => {
        updatedDescription += `\nQ: ${question}\nR: ${response}\n`;
      });
      newOffreData.sections.description = updatedDescription;
    }

    setOffreData(newOffreData);
    setEnrichmentResult(null); // Fermer le panneau d'enrichissement
    success(
      'Sélections appliquées',
      "Les éléments sélectionnés ont été intégrés à l'offre"
    );
  };

  if (loading) return <LoadingPage text="Chargement de l'offre..." />;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => navigate(`/projects/${projectId}`)}
        >
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="flex-1">
          <div className="text-sm text-muted-foreground mb-1">
            {project?.nom} / Offre d'emploi
          </div>
          <h1 className="text-3xl font-bold tracking-tight">
            {offreData.sections.titre || 'Nouvelle offre'}
          </h1>
        </div>
        <Button onClick={handleSave} disabled={saving}>
          <Save className="mr-2 h-4 w-4" />
          {saving ? 'Enregistrement...' : 'Enregistrer'}
        </Button>
      </div>

      {error && <ErrorBanner error={error} />}

      {/* Form */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main form - Left column (2/3) */}
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Offre d'emploi</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="titre">Titre du poste *</Label>
                <Input
                  id="titre"
                  value={offreData.sections.titre}
                  onChange={(e) =>
                    setOffreData({
                      ...offreData,
                      sections: { ...offreData.sections, titre: e.target.value },
                    })
                  }
                  placeholder="Ex: Développeur Backend Senior"
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">Description du poste *</Label>
                <Textarea
                  id="description"
                  value={offreData.sections.description}
                  onChange={(e) =>
                    setOffreData({
                      ...offreData,
                      sections: { ...offreData.sections, description: e.target.value },
                    })
                  }
                  placeholder="Décrivez le poste, les missions, les responsabilités..."
                  rows={10}
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="competences">Compétences techniques</Label>
                <Textarea
                  id="competences"
                  value={offreData.sections.competences_techniques.join(', ')}
                  onChange={(e) =>
                    setOffreData({
                      ...offreData,
                      sections: {
                        ...offreData.sections,
                        competences_techniques: e.target.value
                          .split(',')
                          .map((s) => s.trim())
                          .filter(Boolean),
                      },
                    })
                  }
                  placeholder="Python, Django, PostgreSQL (séparés par des virgules)"
                  rows={3}
                />
              </div>
            </CardContent>
          </Card>

          {/* Must-have / Nice-have */}
          <Card>
            <CardHeader>
              <CardTitle>Critères de sélection</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="must-have">Must-have (critères éliminatoires)</Label>
                <Textarea
                  id="must-have"
                  value={offreData.must_have.join('\n')}
                  onChange={(e) =>
                    setOffreData({
                      ...offreData,
                      must_have: e.target.value.split('\n').filter(Boolean),
                    })
                  }
                  placeholder="Un critère par ligne"
                  rows={5}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="nice-have">Nice-to-have (bonus)</Label>
                <Textarea
                  id="nice-have"
                  value={offreData.nice_have.join('\n')}
                  onChange={(e) =>
                    setOffreData({
                      ...offreData,
                      nice_have: e.target.value.split('\n').filter(Boolean),
                    })
                  }
                  placeholder="Un critère par ligne"
                  rows={5}
                />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Enrichment panel - Right column (1/3) */}
        <div className="space-y-6">
          {/* Enrichissement ROME */}
          <Card>
            <CardHeader>
              <CardTitle>Enrichissement ROME</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Enrichissez avec le référentiel ROME (Pôle Emploi/France Travail).
              </p>
              <Button
                disabled
                variant="outline"
                className="w-full"
              >
                Enrichir avec ROME
              </Button>
              <p className="text-xs text-muted-foreground">
                Nécessite un code ROME valide (à venir)
              </p>
            </CardContent>
          </Card>

          {/* Enrichissement IA */}
          <Card>
            <CardHeader>
              <CardTitle>Enrichissement IA</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Utilisez GPT-5 mini pour enrichir automatiquement votre offre.
              </p>
              <div className="space-y-2">
                <Label htmlFor="metier-label">Libellé du métier cible</Label>
                <Input
                  id="metier-label"
                  value={offreData.sections.titre}
                  onChange={(e) =>
                    setOffreData({
                      ...offreData,
                      sections: { ...offreData.sections, titre: e.target.value },
                    })
                  }
                  placeholder="Ex: Développeur Python, Data Scientist..."
                />
              </div>
              <Button
                onClick={handleEnrichWithAI}
                disabled={enriching || !offreData.sections.description}
                className="w-full"
              >
                {enriching ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Enrichissement en cours...
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    Enrichir avec IA
                  </>
                )}
              </Button>

              {enriching && (
                <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
                    <p className="text-sm text-blue-900">GPT-5 mini analyse votre offre...</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Enrichment propositions (full width below) */}
      {enrichmentResult && !enriching && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>
                📋 Propositions IA (Complétude: {enrichmentResult.coverage_score}%)
              </CardTitle>
              <Button onClick={applySelections} disabled={
                Object.values(selections).every((arr) => arr.length === 0) &&
                Object.keys(questionResponses).length === 0
              }>
                <CheckCircle className="mr-2 h-4 w-4" />
                Appliquer les sélections
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Compétences */}
            {enrichmentResult.propositions.competences.length > 0 && (
              <div>
                <h3 className="font-semibold mb-3">Compétences Techniques</h3>
                <div className="space-y-2">
                  {enrichmentResult.propositions.competences.map((comp, idx) => (
                    <div
                      key={idx}
                      className="flex items-start gap-3 p-3 border rounded-lg hover:bg-accent"
                    >
                      <input
                        type="checkbox"
                        checked={selections.competences.includes(idx)}
                        onChange={() => toggleSelection('competences', idx)}
                        className="mt-1"
                      />
                      <div className="flex-1">
                        <div className="font-medium">
                          {comp.name}{' '}
                          <span className="text-xs text-muted-foreground">({comp.type})</span>
                        </div>
                        <div className="text-sm text-muted-foreground">{comp.rationale}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Outils */}
            {enrichmentResult.propositions.outils.length > 0 && (
              <div>
                <h3 className="font-semibold mb-3">Outils</h3>
                <div className="space-y-2">
                  {enrichmentResult.propositions.outils.map((outil, idx) => (
                    <div
                      key={idx}
                      className="flex items-start gap-3 p-3 border rounded-lg hover:bg-accent"
                    >
                      <input
                        type="checkbox"
                        checked={selections.outils.includes(idx)}
                        onChange={() => toggleSelection('outils', idx)}
                        className="mt-1"
                      />
                      <div className="flex-1">
                        <div className="font-medium">{outil.name}</div>
                        <div className="text-sm text-muted-foreground">{outil.rationale}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Langages */}
            {enrichmentResult.propositions.langages.length > 0 && (
              <div>
                <h3 className="font-semibold mb-3">Langages de Programmation</h3>
                <div className="space-y-2">
                  {enrichmentResult.propositions.langages.map((lang, idx) => (
                    <div
                      key={idx}
                      className="flex items-start gap-3 p-3 border rounded-lg hover:bg-accent"
                    >
                      <input
                        type="checkbox"
                        checked={selections.langages.includes(idx)}
                        onChange={() => toggleSelection('langages', idx)}
                        className="mt-1"
                      />
                      <div className="flex-1">
                        <div className="font-medium">{lang.name}</div>
                        <div className="text-sm text-muted-foreground">{lang.rationale}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Certifications */}
            {enrichmentResult.propositions.certifications.length > 0 && (
              <div>
                <h3 className="font-semibold mb-3">Certifications</h3>
                <div className="space-y-2">
                  {enrichmentResult.propositions.certifications.map((cert, idx) => (
                    <div
                      key={idx}
                      className="flex items-start gap-3 p-3 border rounded-lg hover:bg-accent"
                    >
                      <input
                        type="checkbox"
                        checked={selections.certifications.includes(idx)}
                        onChange={() => toggleSelection('certifications', idx)}
                        className="mt-1"
                      />
                      <div className="flex-1">
                        <div className="font-medium">{cert.name}</div>
                        <div className="text-sm text-muted-foreground">{cert.rationale}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Missions */}
            {enrichmentResult.propositions.missions.length > 0 && (
              <div>
                <h3 className="font-semibold mb-3">Missions Complémentaires</h3>
                <div className="space-y-2">
                  {enrichmentResult.propositions.missions.map((mission, idx) => (
                    <div
                      key={idx}
                      className="flex items-start gap-3 p-3 border rounded-lg hover:bg-accent"
                    >
                      <input
                        type="checkbox"
                        checked={selections.missions.includes(idx)}
                        onChange={() => toggleSelection('missions', idx)}
                        className="mt-1"
                      />
                      <div className="flex-1">
                        <div className="font-medium">{mission.text}</div>
                        <div className="text-sm text-muted-foreground">{mission.rationale}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Questions de clarification */}
            {enrichmentResult.propositions.questions_clarification.length > 0 && (
              <div>
                <h3 className="font-semibold mb-3">💬 Questions de Clarification</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  Répondez à ces questions pour enrichir automatiquement l'offre.
                </p>
                <div className="space-y-4">
                  {enrichmentResult.propositions.questions_clarification.map((question, idx) => (
                    <div key={idx} className="space-y-2">
                      <Label htmlFor={`question-${idx}`}>
                        Question {idx + 1}: {question}
                      </Label>
                      <Input
                        id={`question-${idx}`}
                        value={questionResponses[question] || ''}
                        onChange={(e) =>
                          setQuestionResponses({
                            ...questionResponses,
                            [question]: e.target.value,
                          })
                        }
                        placeholder="Votre réponse..."
                      />
                    </div>
                  ))}
                </div>
                {Object.keys(questionResponses).length > 0 && (
                  <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                    <p className="text-sm text-blue-900">
                      📝 {Object.keys(questionResponses).length} réponse(s) prête(s) à être
                      intégrée(s)
                    </p>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
};
