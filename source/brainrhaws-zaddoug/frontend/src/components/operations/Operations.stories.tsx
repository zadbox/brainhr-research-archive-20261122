import type { Meta, StoryObj } from '@storybook/react-vite';
import { ArrowRight, BriefcaseBusiness, RefreshCw } from 'lucide-react';
import { Button } from '../ui/button';
import {
  ContextStrip,
  MetricStrip,
  OperationalList,
  OperationalListItem,
  PageFrame,
  PageHeader,
  Section,
  SystemState,
} from './index';

interface OperationsReferenceProps {
  theme: 'light' | 'dark';
}

function OperationsReference({ theme }: OperationsReferenceProps) {
  return (
    <main
      data-brain-ops=""
      className={`${theme === 'dark' ? 'dark' : ''} min-h-screen bg-[var(--brain-ops-canvas)] px-4 py-8 text-[var(--brain-ops-text)] sm:px-8`}
    >
      <PageFrame>
        <PageHeader
          eyebrow="Registre de pilotage"
          title="Recrutement — Ingénieur plateforme senior"
          description="Une référence maintenable des composants BRAIN Operations, avec des libellés longs et des états réalistes."
          actionsLabel="Actions du projet"
          actions={(
            <>
              <Button variant="outline" disabled>Voir l’offre</Button>
              <Button>
                Continuer
                <ArrowRight aria-hidden="true" className="size-4" />
              </Button>
            </>
          )}
        />

        <ContextStrip
          ariaLabel="Contexte du projet"
          items={[
            { id: 'client', label: 'Client', value: 'Northstar Industries' },
            { id: 'project', label: 'Projet', value: 'Ingénieur plateforme senior — Casablanca' },
            { id: 'owner', label: 'Responsable', value: 'Équipe recrutement', detail: 'Mis à jour il y a 12 minutes' },
          ]}
        />

        <MetricStrip
          ariaLabel="Indicateurs de décision"
          items={[
            { id: 'profiles', label: 'Profils analysés', value: '128', detail: 'Tous les CV reçus' },
            { id: 'qualified', label: 'Vivier qualifié', value: '24', detail: 'Critères obligatoires validés', tone: 'success' },
            { id: 'attention', label: 'À vérifier', value: '3', detail: 'Preuves partielles', tone: 'warning' },
          ]}
        />

        <Section
          title="Activité récente"
          description="Les éléments restent lisibles sur mobile et avec des contenus FR/EN de longueur variable."
        >
          <OperationalList ariaLabel="Activité du projet">
            <OperationalListItem
              leading={<BriefcaseBusiness aria-hidden="true" className="size-5" />}
              primary="Matching terminé"
              secondary="24 candidats qualifiés sur 128 profils analysés"
              metadata="01 AOÛT 2026 · 14:32"
              actionsLabel="Actions du matching"
              actions={<Button variant="ghost" size="sm">Ouvrir le dossier</Button>}
            />
            <OperationalListItem
              primary="Offre validée"
              secondary="Les critères obligatoires et les compétences souhaitées sont prêts pour le matching."
              metadata="31 JUILLET 2026 · 17:08"
            />
          </OperationalList>
        </Section>

        <Section title="États système" divided>
          <div className="grid gap-4">
            <SystemState
              kind="loading"
              title="Chargement des résultats…"
              description="Les données de décision sont en cours de préparation."
              indicator={<RefreshCw className="size-5 animate-spin motion-reduce:animate-none" />}
            />
            <SystemState
              kind="empty"
              title="Aucun matching pour ce projet"
              description="Lancez le premier matching pour créer un dossier de décision."
              actionLabel="Action de l’état vide"
              action={<Button>Lancer le matching</Button>}
            />
            <SystemState
              kind="error"
              title="Les résultats ne sont pas disponibles"
              description="Réessayez dans quelques instants. Aucune donnée n’a été modifiée."
              actionLabel="Action de récupération"
              action={<Button variant="outline">Réessayer</Button>}
            />
          </div>
        </Section>
      </PageFrame>
    </main>
  );
}

const meta = {
  title: 'BRAIN Operations/Foundation',
  component: OperationsReference,
  parameters: {
    layout: 'fullscreen',
    docs: {
      description: {
        component: 'Référence vivante des primitives partagées. Vérifie la hiérarchie, les contenus longs, les états et le responsive sans dépendre des API.',
      },
    },
  },
  args: { theme: 'light' },
  argTypes: {
    theme: { control: 'inline-radio', options: ['light', 'dark'] },
  },
} satisfies Meta<typeof OperationsReference>;

export default meta;
type Story = StoryObj<typeof meta>;

export const FrenchContentAndStates: Story = {};

export const DarkTheme: Story = {
  args: { theme: 'dark' },
};

export const MobileViewport: Story = {
  parameters: {
    viewport: { defaultViewport: 'mobile1' },
  },
};

export const NeutralEmptyState: Story = {
  render: ({ theme }) => (
    <main
      data-brain-ops=""
      className={`${theme === 'dark' ? 'dark' : ''} min-h-64 bg-[var(--brain-ops-canvas)] p-4 text-[var(--brain-ops-text)] sm:p-8`}
    >
      <SystemState
        kind="empty"
        title="Aucun projet pour le moment"
        description="Créez un projet depuis l’action principale de l’en-tête."
      />
    </main>
  ),
};

export const NeutralInformationState: Story = {
  render: ({ theme }) => (
    <main data-brain-ops="" className={`${theme === 'dark' ? 'dark' : ''} min-h-64 bg-[var(--brain-ops-canvas)] p-4 sm:p-8`}>
      <SystemState kind="info" title="Sélectionnez un projet" description="Les résultats apparaîtront après sélection du projet." />
    </main>
  ),
};
