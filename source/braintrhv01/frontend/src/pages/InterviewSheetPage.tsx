import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Save, Plus, X } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '../components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import { LoadingPage } from '../components/shared/Loading';
import { ErrorBanner } from '../components/shared/ErrorBanner';
import { interviewSheetApi, type InterviewSheet, type UpdateInterviewSheetInput } from '../api/interviewSheet';
import type { APIError } from '../api/types';
import { useToast } from '../hooks/useToast';

export const InterviewSheetPage: React.FC = () => {
  const { sheetId } = useParams<{ sheetId: string }>();
  const navigate = useNavigate();
  const { success, error: showError } = useToast();

  const [sheet, setSheet] = useState<InterviewSheet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [saving, setSaving] = useState(false);

  // Local state for editing
  const [scorecard, setScorecard] = useState<any[]>([]);
  const [questions, setQuestions] = useState<any[]>([]);
  const [freeNotes, setFreeNotes] = useState('');
  const [verdict, setVerdict] = useState('');
  const [verdictDetail, setVerdictDetail] = useState('');
  const [additionalTests, setAdditionalTests] = useState(false);
  const [residualRisks, setResidualRisks] = useState('');

  // Fetch interview sheet
  const fetchSheet = async () => {
    if (!sheetId) return;

    try {
      setLoading(true);
      setError(null);

      const data = await interviewSheetApi.getById(sheetId);
      setSheet(data);

      // Initialize local state from data
      // Priorité : données sauvegardées (scorecard) > données LLM initiales (evaluation_grid)
      const gridSource = data.data.scorecard || data.data.evaluation_grid;
      if (gridSource) {
        setScorecard(
          gridSource.map((item: any) => ({
            criterion: item.criterion,
            weight: item.weight,
            description: item.description,
            score: item.score || 0,
            justification: item.justification || '',
          }))
        );
      }

      // Pour les questions, priorité aux données sauvegardées si elles ont le bon format
      if (data.data.questions) {
        const questionsData = data.data.questions;
        // Vérifier si c'est le format édité (avec champ 'question') ou format LLM (avec 'items')
        const firstQ = questionsData[0];

        if (firstQ && 'question' in firstQ) {
          // Format édité : charger tel quel
          setQuestions(
            questionsData.map((q: any) => ({
              theme: q.theme || '',
              question: q.question || '',
              criteria: q.criteria || '',
              notes: q.notes || '',
              score: q.score || 0,
              asked: q.asked || false,
              satisfactory: q.satisfactory || false,
            }))
          );
        } else {
          // Format LLM initial : convertir items en questions individuelles
          const convertedQuestions: any[] = [];
          questionsData.forEach((q: any) => {
            if (q.items && Array.isArray(q.items)) {
              q.items.forEach((item: string) => {
                convertedQuestions.push({
                  theme: q.theme || '',
                  question: item,
                  criteria: '',
                  notes: '',
                  score: 0,
                  asked: false,
                  satisfactory: false,
                });
              });
            }
          });
          setQuestions(convertedQuestions);
        }
      }

      setFreeNotes(data.data.free_notes || '');
      setVerdict(data.data.verdict || '');
      setVerdictDetail(data.data.verdict_detail || '');
      setAdditionalTests(data.data.additional_tests || false);
      setResidualRisks(data.data.residual_risks || '');

      console.log('📥 Données chargées:');
      console.log('  - verdict:', data.data.verdict);
      console.log('  - verdict_detail:', data.data.verdict_detail);
      console.log('  - free_notes:', data.data.free_notes);
    } catch (err) {
      setError(err as APIError);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSheet();
  }, [sheetId]);

  // Save changes
  const handleSave = async () => {
    if (!sheetId) return;

    try {
      setSaving(true);

      const updates: UpdateInterviewSheetInput = {
        scorecard,
        questions,
        free_notes: freeNotes,
        verdict,
        verdict_detail: verdictDetail,
        additional_tests: additionalTests,
        residual_risks: residualRisks,
        status: 'in_progress',
      };

      console.log('💾 Sauvegarde avec verdict:', verdict);
      console.log('📤 Payload envoyé:', updates);

      await interviewSheetApi.patch(sheetId, updates);
      success('Fiche enregistrée avec succès');

      // Reload to get updated data
      await fetchSheet();
    } catch (err) {
      console.error('❌ Erreur sauvegarde:', err);
      showError((err as APIError).message || 'Erreur lors de la sauvegarde');
    } finally {
      setSaving(false);
    }
  };


  // Calculate total weighted score
  const calculateTotalScore = () => {
    if (scorecard.length === 0) return 0;
    const total = scorecard.reduce((sum, item) => sum + (item.score * item.weight), 0);
    return total.toFixed(2);
  };

  // Add new question
  const addQuestion = () => {
    setQuestions([
      ...questions,
      {
        theme: '',
        question: '',
        criteria: '',
        notes: '',
        score: 0,
        asked: false,
        satisfactory: false,
      },
    ]);
  };

  // Remove question
  const removeQuestion = (index: number) => {
    setQuestions(questions.filter((_, i) => i !== index));
  };

  if (loading) {
    return <LoadingPage text="Chargement de la fiche d'entretien..." />;
  }

  if (error) {
    return (
      <div className="container mx-auto py-8">
        <ErrorBanner error={error} />
        <Button onClick={() => navigate(-1)} className="mt-4">
          <ArrowLeft className="w-4 h-4 mr-2" />
          Retour
        </Button>
      </div>
    );
  }

  if (!sheet) {
    return (
      <div className="container mx-auto py-8">
        <Card>
          <CardContent className="text-center py-12">
            <p className="text-muted-foreground mb-4">Fiche d'entretien introuvable</p>
            <Button onClick={() => navigate(-1)}>
              <ArrowLeft className="w-4 h-4 mr-2" />
              Retour
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const isCompleted = sheet.status === 'completed';

  return (
    <div className="container mx-auto py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="outline" onClick={() => navigate(-1)}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Retour
          </Button>
          <div>
            <h1 className="text-2xl font-bold">Fiche d'entretien</h1>
            <p className="text-sm text-muted-foreground">
              Candidat: {sheet.candidate_id} • Projet: {sheet.job_id}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant={isCompleted ? 'success' : sheet.status === 'in_progress' ? 'default' : 'secondary'}>
            {sheet.status === 'completed' ? 'Finalisée' : sheet.status === 'in_progress' ? 'En cours' : 'Brouillon'}
          </Badge>
          {!isCompleted && (
            <Button onClick={handleSave} disabled={saving}>
              <Save className="w-4 h-4 mr-2" />
              {saving ? 'Enregistrement...' : 'Enregistrer'}
            </Button>
          )}
        </div>
      </div>

      {/* Resume section */}
      {sheet.data.resume && (
        <Card>
          <CardHeader>
            <CardTitle>Résumé du profil</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{sheet.data.resume}</p>
          </CardContent>
        </Card>
      )}

      {/* Tabs */}
      <Tabs defaultValue="scorecard" className="space-y-6">
        <TabsList>
          <TabsTrigger value="scorecard">Scorecard</TabsTrigger>
          <TabsTrigger value="questions">Questions</TabsTrigger>
          <TabsTrigger value="notes">Notes</TabsTrigger>
          <TabsTrigger value="decision">Décision</TabsTrigger>
        </TabsList>

        {/* Scorecard Tab */}
        <TabsContent value="scorecard">
          <Card>
            <CardHeader>
              <CardTitle>Grille d'évaluation</CardTitle>
              <CardDescription>Évaluez chaque critère sur une échelle de 0 à 5</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {scorecard.map((item, index) => (
                <div key={index} className="border rounded-lg p-4 space-y-4">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-3">
                        <h3 className="font-semibold">{item.criterion}</h3>
                        <Badge variant="outline">Poids: {(item.weight * 100).toFixed(0)}%</Badge>
                      </div>
                      <p className="text-sm text-muted-foreground mt-1">{item.description}</p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-center gap-4">
                      <Label htmlFor={`score-${index}`} className="min-w-[80px]">
                        Score: {item.score}
                      </Label>
                      <input
                        id={`score-${index}`}
                        type="range"
                        min="0"
                        max="5"
                        step="0.5"
                        value={item.score}
                        onChange={(e) => {
                          const newScorecard = [...scorecard];
                          newScorecard[index].score = parseFloat(e.target.value);
                          setScorecard(newScorecard);
                        }}
                        disabled={isCompleted}
                        className="flex-1"
                      />
                      <span className="min-w-[60px] text-center font-medium">{item.score} / 5</span>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor={`justification-${index}`}>Justification</Label>
                    <Textarea
                      id={`justification-${index}`}
                      value={item.justification}
                      onChange={(e) => {
                        const newScorecard = [...scorecard];
                        newScorecard[index].justification = e.target.value;
                        setScorecard(newScorecard);
                      }}
                      disabled={isCompleted}
                      placeholder="Justifiez votre évaluation..."
                      rows={2}
                    />
                  </div>
                </div>
              ))}

              <div className="border-t pt-4 mt-6">
                <div className="flex items-center justify-between text-lg font-semibold">
                  <span>Score total pondéré:</span>
                  <span className="text-2xl">{calculateTotalScore()} / 5</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Questions Tab */}
        <TabsContent value="questions">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Questions d'entretien</CardTitle>
                  <CardDescription>Liste des questions à poser et notes</CardDescription>
                </div>
                {!isCompleted && (
                  <Button onClick={addQuestion} size="sm">
                    <Plus className="w-4 h-4 mr-2" />
                    Ajouter une question
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-6">
              {questions.map((q, index) => (
                <div key={index} className="border rounded-lg p-4 space-y-4">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 space-y-3">
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <Label htmlFor={`theme-${index}`}>Thème</Label>
                          <Input
                            id={`theme-${index}`}
                            value={q.theme}
                            onChange={(e) => {
                              const newQuestions = [...questions];
                              newQuestions[index].theme = e.target.value;
                              setQuestions(newQuestions);
                            }}
                            disabled={isCompleted}
                            placeholder="Ex: Technique, Comportemental..."
                          />
                        </div>
                        <div>
                          <Label htmlFor={`score-q-${index}`}>Score: {q.score}</Label>
                          <input
                            id={`score-q-${index}`}
                            type="range"
                            min="0"
                            max="5"
                            step="0.5"
                            value={q.score}
                            onChange={(e) => {
                              const newQuestions = [...questions];
                              newQuestions[index].score = parseFloat(e.target.value);
                              setQuestions(newQuestions);
                            }}
                            disabled={isCompleted}
                            className="w-full"
                          />
                        </div>
                      </div>

                      <div>
                        <Label htmlFor={`question-${index}`}>Question</Label>
                        <Textarea
                          id={`question-${index}`}
                          value={q.question}
                          onChange={(e) => {
                            const newQuestions = [...questions];
                            newQuestions[index].question = e.target.value;
                            setQuestions(newQuestions);
                          }}
                          disabled={isCompleted}
                          placeholder="Entrez votre question..."
                          rows={2}
                        />
                      </div>

                      <div>
                        <Label htmlFor={`criteria-${index}`}>Critères d'évaluation</Label>
                        <Textarea
                          id={`criteria-${index}`}
                          value={q.criteria}
                          onChange={(e) => {
                            const newQuestions = [...questions];
                            newQuestions[index].criteria = e.target.value;
                            setQuestions(newQuestions);
                          }}
                          disabled={isCompleted}
                          placeholder="Ce que vous recherchez dans la réponse..."
                          rows={2}
                        />
                      </div>

                      <div>
                        <Label htmlFor={`notes-${index}`}>Notes de réponse</Label>
                        <Textarea
                          id={`notes-${index}`}
                          value={q.notes}
                          onChange={(e) => {
                            const newQuestions = [...questions];
                            newQuestions[index].notes = e.target.value;
                            setQuestions(newQuestions);
                          }}
                          disabled={isCompleted}
                          placeholder="Notes sur la réponse du candidat..."
                          rows={3}
                        />
                      </div>

                      <div className="flex items-center gap-6">
                        <label className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={q.asked}
                            onChange={(e) => {
                              const newQuestions = [...questions];
                              newQuestions[index].asked = e.target.checked;
                              setQuestions(newQuestions);
                            }}
                            disabled={isCompleted}
                            className="rounded"
                          />
                          <span className="text-sm">Question posée</span>
                        </label>
                        <label className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={q.satisfactory}
                            onChange={(e) => {
                              const newQuestions = [...questions];
                              newQuestions[index].satisfactory = e.target.checked;
                              setQuestions(newQuestions);
                            }}
                            disabled={isCompleted}
                            className="rounded"
                          />
                          <span className="text-sm">Réponse satisfaisante</span>
                        </label>
                      </div>
                    </div>

                    {!isCompleted && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => removeQuestion(index)}
                        className="ml-2"
                      >
                        <X className="w-4 h-4" />
                      </Button>
                    )}
                  </div>
                </div>
              ))}

              {questions.length === 0 && (
                <div className="text-center py-8 text-muted-foreground">
                  <p>Aucune question ajoutée</p>
                  {!isCompleted && (
                    <Button onClick={addQuestion} className="mt-4">
                      <Plus className="w-4 h-4 mr-2" />
                      Ajouter votre première question
                    </Button>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Notes Tab */}
        <TabsContent value="notes">
          <Card>
            <CardHeader>
              <CardTitle>Notes libres</CardTitle>
              <CardDescription>Notes générales sur l'entretien</CardDescription>
            </CardHeader>
            <CardContent>
              <Textarea
                value={freeNotes}
                onChange={(e) => setFreeNotes(e.target.value)}
                disabled={isCompleted}
                placeholder="Vos observations générales, impressions, points à retenir..."
                rows={12}
                className="w-full"
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* Decision Tab */}
        <TabsContent value="decision">
          <Card>
            <CardHeader>
              <CardTitle>Décision finale</CardTitle>
              <CardDescription>Verdict et recommandations</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="verdict">Verdict</Label>
                <select
                  id="verdict"
                  value={verdict}
                  onChange={(e) => setVerdict(e.target.value)}
                  disabled={isCompleted}
                  className="w-full rounded-md border border-input bg-background px-3 py-2"
                >
                  <option value="">-- Sélectionner --</option>
                  <option value="retained">✅ Retenu</option>
                  <option value="reserved">⚠️ Réservé</option>
                  <option value="rejected">❌ Rejeté</option>
                </select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="verdict-detail">Justification du verdict</Label>
                <Textarea
                  id="verdict-detail"
                  value={verdictDetail}
                  onChange={(e) => setVerdictDetail(e.target.value)}
                  disabled={isCompleted}
                  placeholder="Expliquez votre décision..."
                  rows={4}
                />
              </div>

              <div className="space-y-2">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={additionalTests}
                    onChange={(e) => setAdditionalTests(e.target.checked)}
                    disabled={isCompleted}
                    className="rounded"
                  />
                  <span className="text-sm font-medium">Tests complémentaires requis</span>
                </label>
              </div>

              <div className="space-y-2">
                <Label htmlFor="residual-risks">Risques résiduels</Label>
                <Textarea
                  id="residual-risks"
                  value={residualRisks}
                  onChange={(e) => setResidualRisks(e.target.value)}
                  disabled={isCompleted}
                  placeholder="Points d'attention, risques à surveiller..."
                  rows={3}
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};
