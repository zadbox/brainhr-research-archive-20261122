import { useEffect, useState } from 'react';
import { MemoryRouter } from 'react-router-dom';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { I18nProvider } from '../../../i18n/I18nProvider';
import { useI18n } from '../../../i18n/useI18n';
import { SystemState } from '../../../components/operations';
import { AccountProfile } from './AccountProfile';
import { AccountLink } from './AccountLink';

interface ReferenceProps {
  language: 'en' | 'fr';
  theme: 'light' | 'dark';
  email: string;
  displayName?: string;
  showSignInMethods: boolean;
  signingOut: boolean;
  failOnSignOut: boolean;
  collapsed: boolean;
}

function Reference({ language, theme, email, displayName, showSignInMethods, signingOut, failOnSignOut, collapsed }: ReferenceProps) {
  const { setLanguage } = useI18n();
  const [failed, setFailed] = useState(false);
  const [signedOut, setSignedOut] = useState(false);
  useEffect(() => { setLanguage(language); }, [language, setLanguage]);
  useEffect(() => {
    const previous = document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', theme === 'dark');
    return () => { document.documentElement.classList.toggle('dark', previous); };
  }, [theme]);
  return <div data-brain-ops="" className="min-h-screen bg-[var(--brain-ops-canvas)] p-5 text-[var(--brain-ops-text)] sm:p-10">
    <div className="mb-8 max-w-64"><AccountLink email={email} collapsed={collapsed} /></div>
    {signedOut ? <SystemState kind="success" title={language === 'fr' ? 'Session de démonstration fermée' : 'Demo session signed out'} />
      : <AccountProfile email={email} displayName={displayName} showSignInMethods={showSignInMethods} signingOut={signingOut} signOutFailed={failed} onSignOut={() => failOnSignOut ? setFailed(true) : setSignedOut(true)} />}
  </div>;
}

function AccountReference(props: ReferenceProps) {
  return <I18nProvider><MemoryRouter initialEntries={['/profile']}><Reference {...props} /></MemoryRouter></I18nProvider>;
}

const meta = {
  title: 'BRAIN Operations/Account profile',
  component: AccountReference,
  parameters: { layout: 'fullscreen' },
  args: { language: 'en', theme: 'light', email: 'recruiter@example.test', showSignInMethods: true, signingOut: false, failOnSignOut: false, collapsed: false },
} satisfies Meta<typeof AccountReference>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Default: Story = {};
export const WithoutGoogleSignIn: Story = { args: { showSignInMethods: false } };
export const GoogleName: Story = { args: { displayName: 'Candidate de démonstration — équipe recrutement international', language: 'fr' } };
export const FrenchLongEmail: Story = { args: { language: 'fr', email: 'responsable.recrutement.equipe.internationale@example.test' } };
export const Dark: Story = { args: { language: 'fr', theme: 'dark' } };
export const SigningOut: Story = { args: { signingOut: true } };
export const SignOutError: Story = { args: { language: 'fr', failOnSignOut: true } };
export const CollapsedLink: Story = { args: { collapsed: true } };
