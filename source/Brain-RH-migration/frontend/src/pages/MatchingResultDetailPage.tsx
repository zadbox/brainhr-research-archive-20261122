import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, FileJson, FileSpreadsheet, Eye, ChevronDown, ChevronRight } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
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
import { matchingApi } from '../api/matching';
import type { ResultatMatching, APIError } from '../api/types';

export const MatchingResultDetailPage: React.FC = () => {
  const { projectId, timestamp } = useParams<{ projectId: string; timestamp: string }>();
  const navigate = useNavigate();

  const [results, setResults] = useState<ResultatMatching[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<APIError | null>(null);
  const [exporting, setExporting] = useState(false);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  useEffect(() => {
    const fetchResults = async () => {
      if (!projectId || !timestamp) return;

      try {
        setLoading(true);
        setError(null);
        const data = await matchingApi.getResults(projectId, timestamp);
        setResults(data);
      } catch (err) {
        setError(err as APIError);
      } finally {
        setLoading(false);
      }
    };

    fetchResults();
  }, [projectId, timestamp]);

  const toggleRowExpansion = (cv: string) => {
    setExpandedRows(prev => {
      const newSet = new Set(prev);
      if (newSet.has(cv)) {
        newSet.delete(cv);
      } else {
        newSet.add(cv);
      }
      return newSet;
    });
  };

  const handleExportExcel = async () => {
    if (!projectId || !timestamp) return;
    setExporting(true);
    try {
      const blob = await matchingApi.exportExcel(projectId, timestamp);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `matching_${projectId}_${timestamp}.xlsx`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      setError(err as APIError);
    } finally {
      setExporting(false);
    }
  };

  const handleExportJSON = async () => {
    if (!projectId || !timestamp) return;
    setExporting(true);
    try {
      const data = await matchingApi.exportJSON(projectId, timestamp);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `matching_${projectId}_${timestamp}.json`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      setError(err as APIError);
    } finally {
      setExporting(false);
    }
  };

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-green-600 font-bold';
    if (score >= 60) return 'text-blue-600 font-semibold';
    if (score >= 40) return 'text-yellow-600';
    return 'text-gray-600';
  };

  if (loading) return <LoadingPage text="Chargement des résultats..." />;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => navigate(`/projects/${projectId}/results`)}>
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="flex-1">
          <h1 className="text-3xl font-bold tracking-tight">Résultats du matching</h1>
          <p className="text-muted-foreground">
            {timestamp?.replace('_', ' à ').replace(/-/g, ':')}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleExportExcel}
            disabled={exporting}
          >
            <FileSpreadsheet className="mr-2 h-4 w-4" />
            Export Excel
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleExportJSON}
            disabled={exporting}
          >
            <FileJson className="mr-2 h-4 w-4" />
            Export JSON
          </Button>
        </div>
      </div>

      {error && <ErrorBanner error={error} />}

      {/* Résultats */}
      <Card>
        <CardHeader>
          <CardTitle>{results.length} candidat(s) trouvé(s)</CardTitle>
          <CardDescription>Cliquez sur une ligne pour voir les détails complets</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="border rounded-lg">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[40px]"></TableHead>
                  <TableHead>Rang</TableHead>
                  <TableHead>CV</TableHead>
                  <TableHead>Score Final</TableHead>
                  <TableHead>Score Base</TableHead>
                  <TableHead>Bonus Nice-have</TableHead>
                  <TableHead>Coeff. Qualité</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((result, index) => (
                  <>
                    <TableRow
                      key={result.cv}
                      className="cursor-pointer hover:bg-accent"
                      onClick={() => toggleRowExpansion(result.cv)}
                    >
                      <TableCell>
                        {expandedRows.has(result.cv) ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </TableCell>
                      <TableCell className="font-medium">{index + 1}</TableCell>
                      <TableCell className="font-mono text-xs">{result.cv}</TableCell>
                      <TableCell>
                        <span className={getScoreColor(result.score_final * 100)}>
                          {(result.score_final * 100).toFixed(1)}
                        </span>
                      </TableCell>
                      <TableCell>{(result.score_base * 100).toFixed(1)}</TableCell>
                      <TableCell>
                        {result.bonus_nice_have_multiplicateur.toFixed(2)}x
                      </TableCell>
                      <TableCell>
                        {result.coefficient_qualite_experience.toFixed(2)}x
                      </TableCell>
                    </TableRow>
                    {expandedRows.has(result.cv) && (
                      <TableRow>
                        <TableCell colSpan={7} className="bg-muted/50">
                          <div className="p-4 space-y-4">
                            {/* Formule */}
                            <div className="bg-background p-3 rounded border">
                              <p className="text-sm font-semibold mb-2">Formule de calcul</p>
                              <p className="text-sm font-mono">
                                Score Final = {result.score_base.toFixed(3)} × {result.bonus_nice_have_multiplicateur.toFixed(2)} × {result.coefficient_qualite_experience.toFixed(2)} = {result.score_final.toFixed(3)}
                              </p>
                            </div>

                            {/* Nice-have manquants */}
                            {result.nice_have_manquants && result.nice_have_manquants.length > 0 && (
                              <div>
                                <p className="text-sm font-semibold mb-2">Nice-have manquants</p>
                                <div className="flex flex-wrap gap-2">
                                  {result.nice_have_manquants.map((nh) => (
                                    <Badge key={nh} variant="outline">{nh}</Badge>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Commentaire scoring */}
                            {result.commentaire_scoring && (
                              <div>
                                <p className="text-sm font-semibold mb-2">Commentaire scoring</p>
                                <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                                  {result.commentaire_scoring}
                                </p>
                              </div>
                            )}

                            {/* Appréciation globale */}
                            {result.appreciation_globale && (
                              <div>
                                <p className="text-sm font-semibold mb-2">Appréciation globale</p>
                                <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                                  {result.appreciation_globale}
                                </p>
                              </div>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
