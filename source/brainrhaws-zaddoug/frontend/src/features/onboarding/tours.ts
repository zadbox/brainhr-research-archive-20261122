import { matchPath } from 'react-router-dom';
import type { TranslationKey } from '../../i18n/messages';

export interface TourStep {
  target: string;
  titleKey: TranslationKey;
  bodyKey: TranslationKey;
  selector?: string;
  textKey?: TranslationKey;
  closest?: 'section' | 'details';
  reveal?: {
    panel: 'profile' | 'matching' | 'human' | 'ai' | 'decision';
    disclosureKey?: TranslationKey;
  };
}

export interface TourDefinition {
  id: string;
  titleKey: TranslationKey;
  steps: readonly TourStep[];
}

type TourRoute = {
  path: string;
  tour: TourDefinition;
  roles?: readonly string[];
};

const createTour = (
  id: string,
  titleKey: TranslationKey,
  workspaceTarget: string,
  overviewKey: TranslationKey,
  workspaceTitleKey: TranslationKey,
  workspaceBodyKey: TranslationKey,
): TourDefinition => ({
  id,
  titleKey,
  steps: [
    {
      target: 'page-header',
      titleKey: 'guide.step.overviewTitle',
      bodyKey: overviewKey,
    },
    {
      target: workspaceTarget,
      titleKey: workspaceTitleKey,
      bodyKey: workspaceBodyKey,
    },
    {
      target: 'sidebar-navigation',
      titleKey: 'guide.step.navigationTitle',
      bodyKey: 'guide.step.navigationBody',
    },
  ],
});

const tours = {
  home: {
    id: 'home',
    titleKey: 'guide.tour.home.title',
    steps: [
      { target: 'home-overview', titleKey: 'guide.tour.home.foundationTitle', bodyKey: 'guide.tour.home.foundationBody' },
      { target: 'home-recent-activity', titleKey: 'guide.tour.home.prepareTitle', bodyKey: 'guide.tour.home.prepareBody' },
      { target: 'home-upcoming', titleKey: 'guide.tour.home.followupTitle', bodyKey: 'guide.tour.home.followupBody' },
    ],
  },
  companies: createTour('companies', 'guide.tour.companies.title', 'companies-list', 'guide.tour.companies.overview', 'guide.tour.companies.workspaceTitle', 'guide.tour.companies.workspaceBody'),
  companyDetail: createTour('company-detail', 'guide.tour.companyDetail.title', 'company-projects', 'guide.tour.companyDetail.overview', 'guide.tour.companyDetail.workspaceTitle', 'guide.tour.companyDetail.workspaceBody'),
  projects: createTour('projects', 'guide.tour.projects.title', 'projects-list', 'guide.tour.projects.overview', 'guide.tour.projects.workspaceTitle', 'guide.tour.projects.workspaceBody'),
  projectDetail: {
    id: 'project-detail',
    titleKey: 'guide.tour.projectDetail.title',
    steps: [
      { target: 'page-header', titleKey: 'guide.step.overviewTitle', bodyKey: 'guide.tour.projectDetail.overview' },
      { target: 'project-workflow', titleKey: 'guide.tour.projectDetail.workspaceTitle', bodyKey: 'guide.tour.projectDetail.workspaceBody' },
      { target: 'project-offer-step', titleKey: 'guide.tour.projectDetail.offerTitle', bodyKey: 'guide.tour.projectDetail.offerBody' },
      { target: 'project-candidates-step', titleKey: 'guide.tour.projectDetail.candidatesTitle', bodyKey: 'guide.tour.projectDetail.candidatesBody' },
      { target: 'project-matching-step', titleKey: 'guide.tour.projectDetail.matchingTitle', bodyKey: 'guide.tour.projectDetail.matchingBody' },
      { target: 'sidebar-navigation', titleKey: 'guide.step.navigationTitle', bodyKey: 'guide.step.navigationBody' },
    ],
  },
  offer: {
    id: 'offer',
    titleKey: 'guide.tour.offer.title',
    steps: [
      { target: 'page-header', titleKey: 'guide.step.overviewTitle', bodyKey: 'guide.tour.offer.overview' },
      { target: 'offer-source', titleKey: 'guide.tour.offer.sourceTitle', bodyKey: 'guide.tour.offer.sourceBody' },
      { target: 'offer-enrichment', titleKey: 'guide.tour.offer.enrichmentTitle', bodyKey: 'guide.tour.offer.enrichmentBody' },
      { target: 'offer-criteria', titleKey: 'guide.tour.offer.criteriaTitle', bodyKey: 'guide.tour.offer.criteriaBody' },
      { target: 'page-actions', titleKey: 'guide.tour.offer.saveTitle', bodyKey: 'guide.tour.offer.saveBody' },
      { target: 'offer-save-next', titleKey: 'guide.tour.offer.nextTitle', bodyKey: 'guide.tour.offer.nextBody' },
      { target: 'sidebar-navigation', titleKey: 'guide.step.navigationTitle', bodyKey: 'guide.step.navigationBody' },
    ],
  },
  cvBase: {
    id: 'cv-base',
    titleKey: 'guide.tour.cvBase.title',
    steps: [
      { target: 'page-header', titleKey: 'guide.step.overviewTitle', bodyKey: 'guide.tour.cvBase.overview' },
      { target: 'cv-summary', titleKey: 'guide.tour.cvBase.summaryTitle', bodyKey: 'guide.tour.cvBase.summaryBody' },
      { target: 'cv-import', titleKey: 'guide.tour.cvBase.importTitle', bodyKey: 'guide.tour.cvBase.importBody' },
      { target: 'cv-filters', titleKey: 'guide.tour.cvBase.filtersTitle', bodyKey: 'guide.tour.cvBase.filtersBody' },
      { target: 'cv-library', titleKey: 'guide.tour.cvBase.workspaceTitle', bodyKey: 'guide.tour.cvBase.workspaceBody' },
      { target: 'page-actions', titleKey: 'guide.tour.cvBase.nextTitle', bodyKey: 'guide.tour.cvBase.nextBody' },
      { target: 'sidebar-navigation', titleKey: 'guide.step.navigationTitle', bodyKey: 'guide.step.navigationBody' },
    ],
  },
  cvParsing: createTour('cv-parsing', 'guide.tour.cvParsing.title', 'page-content', 'guide.tour.cvParsing.overview', 'guide.tour.cvParsing.workspaceTitle', 'guide.tour.cvParsing.workspaceBody'),
  candidateSearch: createTour('candidate-search', 'guide.tour.candidateSearch.title', 'candidate-search-criteria', 'guide.tour.candidateSearch.overview', 'guide.tour.candidateSearch.workspaceTitle', 'guide.tour.candidateSearch.workspaceBody'),
  matching: {
    id: 'matching',
    titleKey: 'guide.tour.matching.title',
    steps: [
      { target: 'page-header', titleKey: 'guide.step.overviewTitle', bodyKey: 'guide.tour.matching.overview' },
      {
        target: 'matching-prerequisites',
        selector: '#matching-prerequisites-title',
        closest: 'section',
        titleKey: 'guide.tour.matching.prerequisitesTitle',
        bodyKey: 'guide.tour.matching.prerequisitesBody',
      },
      { target: 'page-content', titleKey: 'guide.tour.matching.processTitle', bodyKey: 'guide.tour.matching.processBody' },
      { target: 'sidebar-navigation', titleKey: 'guide.step.navigationTitle', bodyKey: 'guide.step.navigationBody' },
    ],
  },
  results: createTour('results', 'guide.tour.results.title', 'page-content', 'guide.tour.results.overview', 'guide.tour.results.workspaceTitle', 'guide.tour.results.workspaceBody'),
  resultDetail: createTour('result-detail', 'guide.tour.resultDetail.title', 'page-content', 'guide.tour.resultDetail.overview', 'guide.tour.resultDetail.workspaceTitle', 'guide.tour.resultDetail.workspaceBody'),
  interviews: {
    id: 'interviews',
    titleKey: 'guide.tour.interviews.title',
    steps: [
      { target: 'page-header', titleKey: 'guide.step.overviewTitle', bodyKey: 'guide.tour.interviews.overview' },
      { target: 'interviews-filter', titleKey: 'guide.tour.interviews.filterTitle', bodyKey: 'guide.tour.interviews.filterBody' },
      { target: 'interviews-list', titleKey: 'guide.tour.interviews.workspaceTitle', bodyKey: 'guide.tour.interviews.workspaceBody' },
      { target: 'sidebar-navigation', titleKey: 'guide.step.navigationTitle', bodyKey: 'guide.step.navigationBody' },
    ],
  },
  interviewDetail: {
    id: 'interview-detail',
    titleKey: 'guide.tour.interviewDetail.title',
    steps: [
      { target: 'page-header', titleKey: 'guide.step.overviewTitle', bodyKey: 'guide.tour.interviewDetail.overview' },
      { target: 'interview-profile', selector: '#interview-panel-profile', reveal: { panel: 'profile' }, titleKey: 'guide.tour.interviewDetail.profileTitle', bodyKey: 'guide.tour.interviewDetail.profileBody' },
      { target: 'interview-matching', selector: '#interview-panel-matching', reveal: { panel: 'matching' }, titleKey: 'guide.tour.interviewDetail.matchingTitle', bodyKey: 'guide.tour.interviewDetail.matchingBody' },
      { target: 'interview-human', selector: '#interview-panel-human', reveal: { panel: 'human' }, titleKey: 'guide.tour.interviewDetail.humanTitle', bodyKey: 'guide.tour.interviewDetail.humanBody' },
      {
        target: 'interview-human-add-question',
        selector: '#interview-panel-human button',
        textKey: 'interviewSheet.human.addQuestion',
        reveal: { panel: 'human' },
        titleKey: 'guide.tour.interviewDetail.questionsTitle',
        bodyKey: 'guide.tour.interviewDetail.questionsBody',
      },
      {
        target: 'interview-human-grid',
        selector: '#human-scorecard-title',
        closest: 'section',
        reveal: { panel: 'human' },
        titleKey: 'guide.tour.interviewDetail.gridTitle',
        bodyKey: 'guide.tour.interviewDetail.gridBody',
      },
      {
        target: 'interview-ai-preparation',
        selector: '#ai-plan-instructions',
        closest: 'section',
        reveal: { panel: 'ai' },
        titleKey: 'guide.tour.interviewDetail.aiPreparationTitle',
        bodyKey: 'guide.tour.interviewDetail.aiPreparationBody',
      },
      {
        target: 'interview-ai-plan',
        selector: '#interview-panel-ai details > summary',
        textKey: 'interviewSheet.ai.planDetails',
        closest: 'details',
        reveal: { panel: 'ai', disclosureKey: 'interviewSheet.ai.planDetails' },
        titleKey: 'guide.tour.interviewDetail.aiPlanTitle',
        bodyKey: 'guide.tour.interviewDetail.aiPlanBody',
      },
      {
        target: 'interview-ai-session',
        selector: '#interview-panel-ai h3',
        textKey: 'interviewSheet.ai.sessionTitle',
        closest: 'section',
        reveal: { panel: 'ai' },
        titleKey: 'guide.tour.interviewDetail.aiSessionTitle',
        bodyKey: 'guide.tour.interviewDetail.aiSessionBody',
      },
      {
        target: 'interview-recordings',
        selector: '#interview-panel-ai details > summary',
        textKey: 'interviewSheet.ai.recordings',
        closest: 'details',
        reveal: { panel: 'ai', disclosureKey: 'interviewSheet.ai.recordings' },
        titleKey: 'guide.tour.interviewDetail.recordingsTitle',
        bodyKey: 'guide.tour.interviewDetail.recordingsBody',
      },
      {
        target: 'interview-transcript',
        selector: '#interview-panel-ai details > summary',
        textKey: 'interviewSheet.ai.fullTranscript',
        closest: 'details',
        reveal: { panel: 'ai', disclosureKey: 'interviewSheet.ai.fullTranscript' },
        titleKey: 'guide.tour.interviewDetail.transcriptTitle',
        bodyKey: 'guide.tour.interviewDetail.transcriptBody',
      },
      { target: 'interview-decision', selector: '#interview-panel-decision', reveal: { panel: 'decision' }, titleKey: 'guide.tour.interviewDetail.decisionTitle', bodyKey: 'guide.tour.interviewDetail.decisionBody' },
      {
        target: 'interview-save',
        selector: 'button',
        textKey: 'interviewSheet.actions.save',
        titleKey: 'guide.tour.interviewDetail.saveTitle',
        bodyKey: 'guide.tour.interviewDetail.saveBody',
      },
      { target: 'sidebar-navigation', titleKey: 'guide.step.navigationTitle', bodyKey: 'guide.step.navigationBody' },
    ],
  },
  realtimeRedirect: {
    id: 'realtime-interview-entry',
    titleKey: 'guide.tour.realtimeRedirect.title',
    steps: [
      { target: 'page-content', titleKey: 'guide.tour.realtimeRedirect.entryTitle', bodyKey: 'guide.tour.realtimeRedirect.entryBody' },
    ],
  },
  agenda: {
    id: 'agenda',
    titleKey: 'guide.tour.agenda.title',
    steps: [
      { target: 'page-header', titleKey: 'guide.step.overviewTitle', bodyKey: 'guide.tour.agenda.overview' },
      { target: 'agenda-summary', titleKey: 'guide.tour.agenda.summaryTitle', bodyKey: 'guide.tour.agenda.summaryBody' },
      { target: 'agenda-workspace', titleKey: 'guide.tour.agenda.workspaceTitle', bodyKey: 'guide.tour.agenda.workspaceBody' },
      { target: 'agenda-events', titleKey: 'guide.tour.agenda.eventsTitle', bodyKey: 'guide.tour.agenda.eventsBody' },
      { target: 'sidebar-navigation', titleKey: 'guide.step.navigationTitle', bodyKey: 'guide.step.navigationBody' },
    ],
  },
  settings: {
    id: 'settings',
    titleKey: 'guide.tour.settings.title',
    steps: [
      { target: 'page-header', titleKey: 'guide.step.overviewTitle', bodyKey: 'guide.tour.settings.overview' },
      { target: 'settings-modules', titleKey: 'guide.tour.settings.workspaceTitle', bodyKey: 'guide.tour.settings.workspaceBody' },
      { target: 'settings-client-template', titleKey: 'guide.tour.settings.templateTitle', bodyKey: 'guide.tour.settings.templateBody' },
      { target: 'settings-integrations', titleKey: 'guide.tour.settings.integrationsTitle', bodyKey: 'guide.tour.settings.integrationsBody' },
      { target: 'sidebar-navigation', titleKey: 'guide.step.navigationTitle', bodyKey: 'guide.step.navigationBody' },
    ],
  },
  clientTemplate: createTour('client-template', 'guide.tour.clientTemplate.title', 'page-content', 'guide.tour.clientTemplate.overview', 'guide.tour.clientTemplate.workspaceTitle', 'guide.tour.clientTemplate.workspaceBody'),
  integrations: createTour('integrations', 'guide.tour.integrations.title', 'integrations-workspace', 'guide.tour.integrations.overview', 'guide.tour.integrations.workspaceTitle', 'guide.tour.integrations.workspaceBody'),
  adminUsers: createTour('admin-users', 'guide.tour.adminUsers.title', 'admin-users-workspace', 'guide.tour.adminUsers.overview', 'guide.tour.adminUsers.workspaceTitle', 'guide.tour.adminUsers.workspaceBody'),
  adminLlm: createTour('admin-llm', 'guide.tour.adminLlm.title', 'admin-llm-workspace', 'guide.tour.adminLlm.overview', 'guide.tour.adminLlm.workspaceTitle', 'guide.tour.adminLlm.workspaceBody'),
  adminCrustdata: createTour('admin-crustdata', 'guide.tour.adminCrustdata.title', 'admin-crustdata-workspace', 'guide.tour.adminCrustdata.overview', 'guide.tour.adminCrustdata.workspaceTitle', 'guide.tour.adminCrustdata.workspaceBody'),
} as const;

const globalCvTour: TourDefinition = {
  ...tours.cvBase,
  id: 'cv-base-global',
  steps: tours.cvBase.steps.filter((step) => step.target !== 'page-actions' && step.target !== 'cv-import').map((step) => {
    if (step.target === 'page-header') return { ...step, bodyKey: 'guide.tour.cvBase.globalOverview' };
    if (step.target === 'cv-library') return { ...step, titleKey: 'guide.tour.cvBase.globalTitle', bodyKey: 'guide.tour.cvBase.globalBody' };
    return step;
  }),
};

const routeTours: readonly TourRoute[] = [
  { path: '/projects/:projectId/results/:timestamp', tour: tours.resultDetail },
  { path: '/projects/:projectId/candidates/search', tour: tours.candidateSearch },
  { path: '/projects/:projectId/interviews', tour: tours.interviews },
  { path: '/projects/:projectId/offre', tour: tours.offer },
  { path: '/projects/:projectId/cvs', tour: tours.cvBase },
  { path: '/projects/:projectId/parsing', tour: tours.cvParsing },
  { path: '/projects/:projectId/matching', tour: tours.matching },
  { path: '/projects/:projectId/results', tour: tours.results },
  { path: '/projects/:projectId', tour: tours.projectDetail },
  { path: '/enterprises/:enterpriseId', tour: tours.companyDetail },
  { path: '/settings/client-template', tour: tours.clientTemplate },
  { path: '/settings/integrations', tour: tours.integrations },
  { path: '/settings/admin/users', tour: tours.adminUsers },
  { path: '/settings/admin/llm', tour: tours.adminLlm, roles: ['platform_admin'] },
  { path: '/settings/admin/crustdata', tour: tours.adminCrustdata, roles: ['platform_admin'] },
  { path: '/interviews/realtime', tour: tours.realtimeRedirect },
  { path: '/interviews/:sheetId', tour: tours.interviewDetail },
  { path: '/interviews', tour: tours.interviews },
  { path: '/agenda', tour: tours.agenda },
  { path: '/enterprises', tour: tours.companies },
  { path: '/projects', tour: tours.projects },
  { path: '/settings', tour: tours.settings },
  { path: '/integrations', tour: tours.integrations },
  { path: '/admin/users', tour: tours.adminUsers },
  { path: '/admin/llm', tour: tours.adminLlm, roles: ['platform_admin'] },
  { path: '/cvs', tour: globalCvTour },
  { path: '/parsing', tour: tours.cvParsing },
  { path: '/matching', tour: tours.matching },
  { path: '/results', tour: tours.results },
  { path: '/', tour: tours.home },
];

export const getPageTour = (pathname: string, role: string): TourDefinition | null => {
  const matchedRoute = routeTours.find(({ path }) => matchPath({ path, end: true }, pathname));

  if (!matchedRoute || (matchedRoute.roles && !matchedRoute.roles.includes(role))) {
    return null;
  }

  return matchedRoute.tour;
};
