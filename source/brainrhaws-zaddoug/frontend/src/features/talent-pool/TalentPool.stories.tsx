import { useEffect } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { I18nContext } from '../../i18n/I18nContext';
import { messages, type Language } from '../../i18n/messages';
import { TalentPool } from './TalentPool';
import { demoProfiles, demoOffers } from './demo-data';

function PoolExample({ language = 'fr', dark = false, empty = false, long = false, noOffers = false }: { language?: Language; dark?: boolean; empty?: boolean; long?: boolean; noOffers?: boolean }) {
  useEffect(() => {
    const previous = document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', dark);
    return () => { document.documentElement.classList.toggle('dark', previous); };
  }, [dark]);
  const profiles = empty ? [] : long ? demoProfiles.map((profile, index) => index === 0 ? { ...profile, name: 'Nora Benali — Profil de démonstration au nom particulièrement long', title: { fr: 'Responsable de la plateforme de données et de l’intelligence artificielle', en: 'Head of the Data and Artificial Intelligence Platform' } } : profile) : demoProfiles;
  return <I18nContext.Provider value={{ language, setLanguage: () => {}, t: (key) => messages[language][key] }}><main data-brain-ops="" className="min-h-screen bg-[var(--brain-ops-surface)] p-5 sm:p-10"><TalentPool profiles={profiles} offers={empty || noOffers ? [] : demoOffers} /></main></I18nContext.Provider>;
}
const meta = { title: 'Talent/Pool', component: PoolExample, parameters: { layout: 'fullscreen' } } satisfies Meta<typeof PoolExample>;
export default meta;
type Story = StoryObj<typeof meta>;
export const French: Story = {};
export const EnglishDark: Story = { args: { language: 'en', dark: true } };
export const Empty: Story = { args: { empty: true } };
export const LongFrench: Story = { args: { long: true } };
export const Mobile: Story = { parameters: { viewport: { defaultViewport: 'mobile1' } } };

export const NoOffers: Story = { args: { noOffers: true } };
