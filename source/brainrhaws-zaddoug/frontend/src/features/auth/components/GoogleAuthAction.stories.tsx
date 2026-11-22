import { useEffect, useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { apiClient } from '../../../api/client';
import { I18nProvider } from '../../../i18n/I18nProvider';
import { useI18n } from '../../../i18n/useI18n';
import { GoogleAuthAction } from './GoogleAuthAction';

interface ReferenceProps { language: 'en' | 'fr'; theme: 'light' | 'dark'; mode: 'login' | 'invite' | 'link'; enabled: boolean }

function Reference({ language, theme, mode, enabled }: ReferenceProps) {
  const { setLanguage } = useI18n();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const adapter = apiClient.defaults.adapter;
    const wasDark = document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', theme === 'dark');
    setLanguage(language);
    // Story-only provider: no credentials leave the preview and no Google navigation occurs.
    apiClient.defaults.adapter = async config => {
      if (config.url === '/auth/google/config') return { data: { enabled }, status: 200, statusText: 'OK', headers: {}, config };
      throw new Error('Synthetic provider unavailable');
    };
    setReady(true);
    return () => {
      apiClient.defaults.adapter = adapter;
      document.documentElement.classList.toggle('dark', wasDark);
    };
  }, [enabled, language, setLanguage, theme]);
  return <div data-brain-ops="" className="min-h-screen bg-[var(--brain-ops-canvas)] p-6 text-[var(--brain-ops-text)]">
    <div className="mx-auto max-w-md">{ready && <GoogleAuthAction key={`${mode}-${enabled}`} mode={mode} invitationToken="synthetic-story-invitation" />}</div>
  </div>;
}

function GoogleReference(props: ReferenceProps) { return <I18nProvider><Reference {...props} /></I18nProvider>; }
const meta = { title: 'BRAIN Operations/Google authentication', component: GoogleReference, parameters: { layout: 'fullscreen' },
  args: { language: 'en', theme: 'light', mode: 'login', enabled: true } } satisfies Meta<typeof GoogleReference>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Login: Story = {};
export const MobileFrenchLogin: Story = { args: { language: 'fr' }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const FrenchInvitation: Story = { args: { language: 'fr', mode: 'invite' } };
export const DarkLinkAndError: Story = { args: { language: 'fr', theme: 'dark', mode: 'link' } };
export const Disabled: Story = { args: { enabled: false } };
