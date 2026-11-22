import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AuthProvider } from './features/auth/context/AuthContext';
import { ProtectedRoute } from './features/auth/components/ProtectedRoute';
import { SettingsRoute } from './features/auth/components/SettingsRoute';
import { ProfilePage } from './features/auth/pages/ProfilePage';
import { SignInMethodsPage } from './features/auth/pages/SignInMethodsPage';
import { LoginPage } from './features/auth/pages/LoginPage';
import { Layout } from './components/layout/Layout';
import { HomePage } from './pages/HomePage';
import { EnterprisesPage } from './pages/EnterprisesPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { CVBasePage } from './pages/CVBasePage';
import { CVParsingPage } from './pages/CVParsingPage';
import { MatchingPage } from './pages/MatchingPage';
import { ResultsPage } from './pages/ResultsPage';
import { MatchingResultDetailPage } from './pages/MatchingResultDetailPage';
import { EnterpriseDetailPage } from './pages/EnterpriseDetailPage';
import { ProjectDetailPage } from './pages/ProjectDetailPage';
import { OffrePage } from './pages/OffrePage';
import { InterviewSheetPage } from './pages/InterviewSheetPage';
import { InterviewSheetsListPage } from './pages/InterviewSheetsListPage';
import { AgendaPage } from './pages/AgendaPage';
import { TalentPoolPage } from './pages/TalentPoolPage';
import IntegrationsPage from './pages/IntegrationsPage';
import { AdminUsersPage } from './pages/AdminUsersPage';
import { AdminLlmSettingsPage } from './pages/AdminLlmSettingsPage';
import { SettingsPage } from './pages/SettingsPage';
import { ClientCvTemplatePage } from './pages/ClientCvTemplatePage';
import { InvitationActivationPage } from './pages/InvitationActivationPage';
import { CrustdataCandidateSearchPage } from './pages/CrustdataCandidateSearchPage';
import { AdminCrustdataPage } from './pages/AdminCrustdataPage';

function LegacyRealtimeInterviewRedirect() {
  const location = useLocation();
  const sheetId = new URLSearchParams(location.search).get('sheetId');
  const state = location.state as { realtimeLaunch?: { sheetId?: string | null } } | null;
  const resolvedSheetId = sheetId || state?.realtimeLaunch?.sheetId;

  return <Navigate to={resolvedSheetId ? `/interviews/${resolvedSheetId}` : '/interviews'} replace />;
}

function AuthenticatedApp() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<HomePage />} />

        {/* Enterprises */}
        <Route path="/enterprises" element={<EnterprisesPage />} />
        <Route path="/enterprises/:enterpriseId" element={<EnterpriseDetailPage />} />

        {/* Projects */}
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/talent-pool" element={<TalentPoolPage />} />
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="/projects/:projectId/offre" element={<OffrePage />} />
        <Route path="/projects/:projectId/cvs" element={<CVBasePage />} />
        <Route path="/projects/:projectId/candidates/search" element={<CrustdataCandidateSearchPage />} />
        <Route path="/projects/:projectId/parsing" element={<CVParsingPage />} />
        <Route path="/projects/:projectId/matching" element={<MatchingPage />} />
        <Route path="/projects/:projectId/results" element={<ResultsPage />} />
        <Route path="/projects/:projectId/results/:timestamp" element={<MatchingResultDetailPage />} />


        {/* Interview sheets */}
        <Route path="/interviews" element={<InterviewSheetsListPage />} />
        <Route path="/interviews/realtime" element={<LegacyRealtimeInterviewRedirect />} />
        <Route path="/interviews/:sheetId" element={<InterviewSheetPage />} />
        <Route path="/agenda" element={<AgendaPage />} />

        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/account/sign-in" element={<SignInMethodsPage />} />

        {/* Do not mount restricted pages or start their API requests. */}
        <Route element={<SettingsRoute />}>
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/settings/client-template" element={<ClientCvTemplatePage />} />
          <Route path="/settings/integrations" element={<IntegrationsPage />} />
          <Route path="/settings/admin/users" element={<AdminUsersPage />} />
          <Route path="/settings/admin/llm" element={<AdminLlmSettingsPage />} />
          <Route path="/settings/admin/crustdata" element={<AdminCrustdataPage />} />

          {/* Compatibility routes use the same access checks. */}
          <Route path="/integrations" element={<Navigate to="/settings/integrations" replace />} />
          <Route path="/admin/users" element={<Navigate to="/settings/admin/users" replace />} />
          <Route path="/admin/llm" element={<Navigate to="/settings/admin/llm" replace />} />
        </Route>
        <Route path="/projects/:projectId/interviews" element={<InterviewSheetsListPage />} />

        {/* Legacy routes (backwards compatibility) */}
        <Route path="/cvs" element={<CVBasePage />} />
        <Route path="/parsing" element={<CVParsingPage />} />
        <Route path="/matching" element={<MatchingPage />} />
        <Route path="/results" element={<ResultsPage />} />
        
        {/* Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/activate-invitation" element={<InvitationActivationPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/*" element={<AuthenticatedApp />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
