import type { Meta, StoryObj } from '@storybook/react-vite';

import { LoadingPage } from './Loading';

type LoadingReferenceProps = {
  language: 'en' | 'fr';
  theme: 'light' | 'dark';
};

function LoadingReference({ language, theme }: LoadingReferenceProps) {
  return (
    <main
      data-brain-ops=""
      className={`${theme === 'dark' ? 'dark' : ''} min-h-screen bg-[var(--brain-ops-canvas)] p-4 text-[var(--brain-ops-text)]`}
    >
      <LoadingPage text={language === 'fr' ? 'Chargement de l’offre…' : 'Loading offer…'} />
    </main>
  );
}

const meta = {
  title: 'Shared/Loading',
  component: LoadingReference,
  parameters: { layout: 'fullscreen' },
  args: { language: 'en', theme: 'light' },
  argTypes: {
    language: { control: 'inline-radio', options: ['en', 'fr'] },
    theme: { control: 'inline-radio', options: ['light', 'dark'] },
  },
} satisfies Meta<typeof LoadingReference>;

export default meta;
type Story = StoryObj<typeof meta>;

export const English: Story = {};

export const FrenchDark: Story = {
  args: { language: 'fr', theme: 'dark' },
};

export const Mobile: Story = {
  args: { language: 'fr' },
  parameters: { viewport: { defaultViewport: 'mobile1' } },
};
