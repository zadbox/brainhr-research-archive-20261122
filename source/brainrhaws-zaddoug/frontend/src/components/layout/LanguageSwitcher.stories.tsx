import { useEffect } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { I18nProvider } from '../../i18n/I18nProvider';
import { useI18n } from '../../i18n/useI18n';
import { LanguageSwitcher } from './LanguageSwitcher';

interface ReferenceProps {
  language: 'en' | 'fr';
  theme: 'light' | 'dark';
  compact: boolean;
}

function Reference({ language, theme, compact }: ReferenceProps) {
  const { setLanguage } = useI18n();
  useEffect(() => { setLanguage(language); }, [language, setLanguage]);
  useEffect(() => {
    const previous = document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', theme === 'dark');
    return () => { document.documentElement.classList.toggle('dark', previous); };
  }, [theme]);
  return <div data-brain-ops="" className="flex min-h-16 items-center bg-[var(--brain-ops-surface)] p-2">
    <LanguageSwitcher compact={compact} />
  </div>;
}

function LanguageReference(props: ReferenceProps) {
  return <I18nProvider><Reference {...props} /></I18nProvider>;
}

const meta = {
  title: 'BRAIN Operations/Language switcher',
  component: LanguageReference,
  args: { language: 'en', theme: 'light', compact: true },
} satisfies Meta<typeof LanguageReference>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Compact: Story = {};
export const French: Story = { args: { language: 'fr' } };
export const Dark: Story = { args: { language: 'fr', theme: 'dark' } };
export const LoginControl: Story = { args: { compact: false } };
export const Mobile: Story = { parameters: { viewport: { defaultViewport: 'mobile1' } } };
