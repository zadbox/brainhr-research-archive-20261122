import type { Meta, StoryObj } from '@storybook/react-vite';
import type { CV } from '../../api/types';
import { I18nProvider } from '../../i18n/I18nProvider';
import { CandidateProfileDetails } from './CandidateProfileDetails';

const completeProfile: CV = {
  cv: 'alex-martin.json',
  identite: { prenom: 'Alex', nom: 'Martin' },
  titre: 'Lead data engineer',
  resume_professionnel: 'Data engineer avec huit ans d’expérience dans la conception de plateformes analytiques fiables.',
  competences_techniques: ['Python', 'AWS', 'PostgreSQL'],
  competences_transversales: ['Leadership', 'Communication', 'Résolution de problèmes'],
  langues: ['Français — natif', 'Anglais — courant'],
  experiences_professionnelles: [{
    poste: 'Lead data engineer',
    entreprise: 'Atelier Données',
    date_debut: '2022',
    date_fin: 'Aujourd’hui',
    missions: ['Pilotage d’une équipe de six personnes', 'Industrialisation des pipelines de données'],
  }],
  formations: [{ diplome: 'Master informatique', ecole: 'Université de Lille', annee: '2017' }],
  certifications: ['AWS Solutions Architect'],
  projets: [{ nom: 'Modernisation analytique', description: 'Migration progressive sans interruption de service.' }],
};

const emptyProfile: CV = {
  cv: 'profil-minimal.json',
  competences_techniques: [],
  competences_transversales: [],
  langues: [],
  experiences_professionnelles: [],
  formations: [],
  certifications: [],
  projets: [],
};

type StoryProps = {
  profile: CV;
  language: 'en' | 'fr';
  theme: 'light' | 'dark';
};

function ProfileStory({ profile, language, theme }: StoryProps) {
  window.localStorage.setItem('brainrh-language', language);

  return (
    <I18nProvider key={language}>
      <main
        data-brain-ops=""
        className={`${theme === 'dark' ? 'dark' : ''} min-h-screen bg-[var(--brain-ops-canvas)] p-4 text-[var(--brain-ops-text)] sm:p-8`}
      >
        <div className="mx-auto max-w-4xl bg-[var(--brain-ops-surface)] px-4 sm:px-6">
          <CandidateProfileDetails cv={profile} />
        </div>
      </main>
    </I18nProvider>
  );
}

const meta = {
  title: 'Candidates/CandidateProfileDetails',
  component: ProfileStory,
  parameters: { layout: 'fullscreen' },
  args: { profile: completeProfile, language: 'en', theme: 'light' },
  argTypes: {
    language: { control: 'inline-radio', options: ['en', 'fr'] },
    theme: { control: 'inline-radio', options: ['light', 'dark'] },
  },
} satisfies Meta<typeof ProfileStory>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Normal: Story = {};

export const SparseEmpty: Story = { args: { profile: emptyProfile } };

export const LongFrench: Story = {
  args: {
    language: 'fr',
    profile: {
      ...completeProfile,
      resume_professionnel: 'Responsable de plateformes de données distribuées, habituée à coordonner des équipes pluridisciplinaires et à traduire des contraintes réglementaires complexes en décisions techniques compréhensibles, mesurables et durables. identifiant-sans-espaces-qui-doit-rester-lisible-sur-mobile-0123456789abcdefghijklmnopqrstuvwxyz',
      experiences_professionnelles: [{
        poste: 'Responsable de l’ingénierie des données et de la gouvernance analytique',
        entreprise: 'Organisation internationale des services numériques',
        date_debut: 'Janvier 2019',
        date_fin: 'Aujourd’hui',
        missions: [{ description: 'Conception d’une trajectoire de modernisation pluriannuelle' }, 'Accompagnement des équipes métiers en français et en anglais'],
      }],
    },
  },
};

export const Dark: Story = { args: { theme: 'dark' } };

export const Mobile: Story = {
  args: { language: 'fr' },
  parameters: { viewport: { defaultViewport: 'mobile1' } },
};
