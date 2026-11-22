export const screens = [
  'login',
  'home',
  'projects',
  'offer',
  'matching',
  'results',
  'users',
  'settings',
] as const

export type ReferenceScreen = (typeof screens)[number]
export type ReferenceDirection = 'ledger' | 'split' | 'dossier'
export type ReferenceTheme = 'light' | 'dark'

export const referenceCopy = {
  brand: 'BRAIN RH',
  workspace: 'Northstar Consulting',
  operator: 'Sophie Martin',
  navigation: ['Accueil', 'Projets', 'Candidats', 'Administration'],
  project: 'Lead Data Platform',
  projectCode: 'PRJ-0248',
  offer: 'Lead Data Engineer',
  location: 'Paris · Hybride',
  owner: 'Sophie Martin',
  status: 'Actif',
  updated: 'Mis à jour il y a 12 min',
  metrics: [
    ['Projets actifs', '12'],
    ['CV analysés', '486'],
    ['Matchings à revoir', '18'],
  ],
  projects: [
    ['Lead Data Platform', '42 candidats', 'En analyse'],
    ['ERP Finance', '18 candidats', 'À qualifier'],
    ['Cloud Security', '31 candidats', 'Prêt'],
  ],
  candidates: [
    ['Amine Benali', '92', 'Très pertinent'],
    ['Claire Durand', '87', 'Pertinent'],
    ['Lucas Meyer', '81', 'À examiner'],
  ],
  criteria: [
    ['Python avancé', 'Obligatoire'],
    ['Airflow', 'Obligatoire'],
    ['AWS', 'Souhaité'],
  ],
  users: [
    ['Sophie Martin', 'Administratrice', 'Actif'],
    ['Nadia Cohen', 'Recruteuse', 'Actif'],
    ['Marc Leroy', 'Manager', 'Invité'],
  ],
} as const

export const screenLabels: Record<ReferenceScreen, string> = {
  login: 'Connexion',
  home: 'Accueil',
  projects: 'Projets',
  offer: 'Détail offre',
  matching: 'Matching',
  results: 'Résultats',
  users: 'Utilisateurs',
  settings: 'Paramètres',
}

export const directionMeta: Record<
  ReferenceDirection,
  { code: string; name: string; thesis: string }
> = {
  ledger: {
    code: 'A',
    name: 'Command Ledger',
    thesis: 'Une console précise où chaque action et chaque état restent immédiatement traçables.',
  },
  split: {
    code: 'B',
    name: 'Mission Split',
    thesis: 'Une vue à deux plans qui garde la mission visible pendant que le travail avance.',
  },
  dossier: {
    code: 'C',
    name: 'Decision Dossier',
    thesis: 'Un dossier éditorial structuré pour lire les preuves avant de prendre une décision.',
  },
}
