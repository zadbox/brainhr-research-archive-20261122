import { useNavigate } from 'react-router-dom';
import {
  Building2,
  FolderOpen,
  FileText,
  Target,
  BarChart3,
  ArrowRight,
} from 'lucide-react';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from '../components/ui/card';
import { Button } from '../components/ui/button';

interface DashboardCard {
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  path: string;
  color: string;
}

const dashboardCards: DashboardCard[] = [
  {
    title: 'Entreprises',
    description: 'Gérez vos entreprises clientes',
    icon: Building2,
    path: '/enterprises',
    color: 'text-blue-600',
  },
  {
    title: 'Projets',
    description: 'Gérez vos projets de recrutement',
    icon: FolderOpen,
    path: '/projects',
    color: 'text-purple-600',
  },
  {
    title: 'Base CVs',
    description: 'Uploadez et gérez vos CVs',
    icon: FileText,
    path: '/cvs',
    color: 'text-green-600',
  },
  {
    title: 'Matching',
    description: 'Lancez le matching intelligent',
    icon: Target,
    path: '/matching',
    color: 'text-red-600',
  },
  {
    title: 'Résultats',
    description: 'Consultez les résultats de matching',
    icon: BarChart3,
    path: '/results',
    color: 'text-indigo-600',
  },
];

export const HomePage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="space-y-8">
      {/* Hero Section */}
      <div className="text-center space-y-6">
        <div className="flex items-center justify-center">
          <img
            src="/logorhplus.png"
            alt="BRAIN RH+"
            className="h-20 w-auto"
          />
        </div>
        <h1 className="text-5xl font-bold tracking-tight">
          BRAIN RH<span className="text-primary">+</span>
        </h1>
        <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
          Plateforme intelligente de matching CV-Offre propulsée par l'IA
        </p>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {dashboardCards.map((card) => {
          const Icon = card.icon;
          return (
            <Card
              key={card.path}
              className="hover:shadow-lg transition-shadow cursor-pointer group"
              onClick={() => navigate(card.path)}
            >
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div className={`p-3 rounded-lg bg-muted ${card.color}`}>
                    <Icon className="h-6 w-6" />
                  </div>
                </div>
                <CardTitle className="mt-4">{card.title}</CardTitle>
                <CardDescription>{card.description}</CardDescription>
              </CardHeader>
              <CardFooter>
                <Button
                  variant="ghost"
                  className="w-full group-hover:bg-accent"
                  onClick={(e) => {
                    e.stopPropagation();
                    navigate(card.path);
                  }}
                >
                  Accéder
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </CardFooter>
            </Card>
          );
        })}
      </div>

      {/* Info Section */}
      <Card className="bg-muted/50">
        <CardContent className="pt-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-center">
            <div>
              <p className="text-3xl font-bold text-primary">100%</p>
              <p className="text-sm text-muted-foreground mt-1">
                Automatisé avec IA
              </p>
            </div>
            <div>
              <p className="text-3xl font-bold text-primary">4 étapes</p>
              <p className="text-sm text-muted-foreground mt-1">
                Pipeline de matching
              </p>
            </div>
            <div>
              <p className="text-3xl font-bold text-primary">Temps réel</p>
              <p className="text-sm text-muted-foreground mt-1">
                Résultats instantanés
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Getting Started */}
      <Card>
        <CardHeader>
          <CardTitle>Pour commencer</CardTitle>
          <CardDescription>Suivez ces étapes pour votre premier matching</CardDescription>
        </CardHeader>
        <CardContent>
          <ol className="space-y-3">
            <li className="flex items-start gap-3">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-bold flex-shrink-0">
                1
              </div>
              <div>
                <p className="font-medium">Créez une entreprise</p>
                <p className="text-sm text-muted-foreground">
                  Allez dans Entreprises et créez votre première entreprise cliente
                </p>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-bold flex-shrink-0">
                2
              </div>
              <div>
                <p className="font-medium">Créez un projet</p>
                <p className="text-sm text-muted-foreground">
                  Dans Projets, créez un nouveau projet de recrutement
                </p>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-bold flex-shrink-0">
                3
              </div>
              <div>
                <p className="font-medium">Parsez des CVs</p>
                <p className="text-sm text-muted-foreground">
                  Uploadez et analysez vos CVs dans Base CVs
                </p>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-bold flex-shrink-0">
                4
              </div>
              <div>
                <p className="font-medium">Lancez le matching</p>
                <p className="text-sm text-muted-foreground">
                  Utilisez Matching pour trouver les meilleurs candidats
                </p>
              </div>
            </li>
          </ol>
        </CardContent>
        <CardFooter>
          <Button onClick={() => navigate('/enterprises')} size="lg" className="w-full">
            Commencer maintenant
            <ArrowRight className="ml-2 h-5 w-5" />
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
};
