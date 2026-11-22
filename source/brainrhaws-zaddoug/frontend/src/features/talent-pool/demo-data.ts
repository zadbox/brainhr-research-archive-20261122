import type { LocalizedText, PoolProfile, PoolOffer } from './types';
const text = (fr: string, en: string): LocalizedText => ({ fr, en });

// Fictional examples only. No CV extraction or production candidate data is implied.
export const demoProfiles: PoolProfile[] = [
  {
    id: 'demo-nora', name: 'Nora Benali', title: text('Data scientist senior', 'Senior data scientist'),
    location: 'Casablanca', email: 'nora.benali@example.test', phone: null, photo: { url: '/talent-pool-portraits/nora-demo.jpg', source: 'illustration' },
    experienceYears: 7, availability: 'available',
    summary: text('Conçoit des modèles prédictifs et accompagne leur mise en production. Expérience en prévision de la demande et analyse de données produit.', 'Builds predictive models and supports their deployment. Experience in demand forecasting and product analytics.'),
    skills: [
      { name: 'Python', evidence: text('Pipeline de prévision de la demande chez Atlas Analytics.', 'Demand forecasting pipeline at Atlas Analytics.') },
      { name: 'SQL', evidence: text('Modélisation de données et requêtes analytiques.', 'Data modelling and analytical queries.') },
      { name: 'Machine Learning', evidence: text('Modèles de prévision et suivi de performance.', 'Forecasting models and performance monitoring.') },
      { name: 'AWS', evidence: text('Déploiement des traitements de données sur AWS.', 'Data processing deployed on AWS.') },
    ],
    experience: [{ role: text('Data scientist senior', 'Senior data scientist'), company: 'Atlas Analytics · Démo', period: '2022 — 2026', description: text('Prévision, expérimentation et mise en production des modèles.', 'Forecasting, experimentation and model deployment.') }, { role: text('Data analyst', 'Data analyst'), company: 'North Studio · Démo', period: '2019 — 2022', description: text('Analyse produit, tableaux de bord et qualité des données.', 'Product analytics, dashboards and data quality.') }],
    education: [{ degree: text('Master en science des données', 'MSc in Data Science'), school: 'Institut de technologie · Démo', year: '2019' }],
    languages: ['fr', 'en', 'ar'], sourceCv: { filename: 'CV_DEMO_Nora_Benali.pdf', updatedAt: '2026-09-20', pageCount: 2 },
  },
  {
    id: 'demo-adam', name: 'Adam Laurent', title: text('Ingénieur full stack', 'Full stack engineer'), location: 'Paris', email: 'adam.laurent@example.test', phone: null, photo: { url: '/talent-pool-portraits/adam-demo.jpg', source: 'illustration' },
    experienceYears: 5, availability: 'discuss', summary: text('Développe des applications web et des API. Intervient sur le produit, la qualité et le déploiement.', 'Builds web applications and APIs, working across product delivery, quality and deployment.'),
    skills: [{ name: 'TypeScript', evidence: text('Applications web typées en production.', 'Typed web applications in production.') }, { name: 'React', evidence: text('Interfaces métier et composants accessibles.', 'Business interfaces and accessible components.') }, { name: 'Node.js', evidence: text('API et services de traitement.', 'APIs and processing services.') }, { name: 'SQL', evidence: text('Conception de bases PostgreSQL.', 'PostgreSQL database design.') }],
    experience: [{ role: text('Ingénieur full stack', 'Full stack engineer'), company: 'Studio Meridian · Démo', period: '2021 — 2026', description: text('Conception et livraison de produits SaaS.', 'Design and delivery of SaaS products.') }], education: [{ degree: text('Diplôme d’ingénieur informatique', 'Software engineering degree'), school: 'École numérique · Démo', year: '2021' }], languages: ['fr', 'en'], sourceCv: { filename: 'CV_DEMO_Adam_Laurent.pdf', updatedAt: '2026-09-18', pageCount: 2 },
  },
  {
    id: 'demo-ines', name: 'Inès Martin', title: text('Product designer', 'Product designer'), location: 'Lyon', email: 'ines.martin@example.test', phone: null, photo: { url: '/talent-pool-portraits/ines-demo.jpg', source: 'illustration' },
    experienceYears: 6, availability: 'available', summary: text('Structure des parcours utilisateurs et des systèmes de design pour des logiciels professionnels.', 'Designs user journeys and design systems for professional software.'),
    skills: [{ name: 'Figma', evidence: text('Bibliothèque de composants et prototypes.', 'Component library and prototypes.') }, { name: 'UX Research', evidence: text('Entretiens utilisateurs et tests de parcours.', 'User interviews and journey testing.') }, { name: 'Design Systems', evidence: text('Documentation des composants et règles d’accessibilité.', 'Component documentation and accessibility guidelines.') }],
    experience: [{ role: text('Product designer', 'Product designer'), company: 'Forma Labs · Démo', period: '2020 — 2026', description: text('Recherche utilisateur et conception de services B2B.', 'User research and B2B service design.') }], education: [{ degree: text('Master en design d’interaction', 'MA in Interaction Design'), school: 'École de design · Démo', year: '2020' }], languages: ['fr', 'en'], sourceCv: { filename: 'CV_DEMO_Ines_Martin.pdf', updatedAt: '2026-09-16', pageCount: 3 },
  },
  {
    id: 'demo-sami', name: 'Sami Amrani', title: text('Data engineer', 'Data engineer'), location: 'Rabat', email: null, phone: null, photo: { url: '/talent-pool-portraits/sami-demo.jpg', source: 'illustration' },
    experienceYears: 4, availability: 'discuss', summary: text('Construit des pipelines de données fiables et documentés. Expérience en orchestration et contrôle qualité.', 'Builds reliable, documented data pipelines with orchestration and quality controls.'),
    skills: [{ name: 'Python', evidence: text('Traitements de données et contrôles qualité.', 'Data processing and quality checks.') }, { name: 'SQL', evidence: text('Transformation et modélisation analytique.', 'Data transformation and analytical modelling.') }, { name: 'AWS', evidence: text('Stockage et traitements distribués.', 'Storage and distributed processing.') }, { name: 'Airflow', evidence: text('Orchestration des pipelines quotidiens.', 'Daily pipeline orchestration.') }],
    experience: [{ role: text('Data engineer', 'Data engineer'), company: 'Delta Data · Démo', period: '2022 — 2026', description: text('Ingestion, transformation et supervision des flux.', 'Data ingestion, transformation and monitoring.') }], education: [{ degree: text('Master en systèmes d’information', 'MSc in Information Systems'), school: 'Institut numérique · Démo', year: '2022' }], languages: ['fr', 'en', 'ar'], sourceCv: { filename: 'CV_DEMO_Sami_Amrani.pdf', updatedAt: '2026-09-12', pageCount: 2 },
  },
];

// Fictional offers for the selection UI; never passed to the matching API.
export const demoOffers: PoolOffer[] = [
  { id: 'offer-data', title: text('Data scientist senior', 'Senior data scientist'), company: 'Atlas Analytics · Demo', location: 'Casablanca', description: text('Développer les modèles de prévision et accompagner leur déploiement dans une équipe produit.', 'Build forecasting models and support their deployment in a product team.'), skills: ['Python', 'SQL', 'Machine Learning'] },
  { id: 'offer-engineering', title: text('Ingénieur full stack', 'Full stack engineer'), company: 'Studio Meridian · Demo', location: 'Paris', description: text('Concevoir les interfaces et les API d’une plateforme SaaS.', 'Design interfaces and APIs for a SaaS platform.'), skills: ['TypeScript', 'React', 'Node.js'] },
  { id: 'offer-design', title: text('Product designer', 'Product designer'), company: 'Forma Labs · Demo', location: 'Lyon', description: text('Piloter la recherche utilisateur et faire évoluer le système de design.', 'Lead user research and evolve the design system.'), skills: ['Figma', 'UX Research', 'Design Systems'] },
];
