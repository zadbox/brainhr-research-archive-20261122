import type { Meta, StoryObj } from '@storybook/react-vite';
import { PageBackButton } from './PageBackButton';
import { PageFrame } from './PageFrame';
import { PageHeader } from './PageHeader';

const meta = {
  title: 'BRAIN Operations/PageBackButton',
  component: PageBackButton,
  parameters: {
    layout: 'fullscreen',
    docs: {
      description: {
        component: 'Retour de page compact et accessible, placé à gauche de l’eyebrow par PageHeader.',
      },
    },
  },
  args: {
    'aria-label': 'Back',
  },
  render: (args) => (
    <main
      data-brain-ops=""
      className="min-h-screen bg-[var(--brain-ops-canvas)] px-4 py-8 text-[var(--brain-ops-text)] sm:px-8"
    >
      <PageFrame>
        <PageHeader
          eyebrow="Recruitment project"
          backAction={<PageBackButton {...args} />}
          title="Senior platform engineer"
          description="The primary actions remain on the right while navigation stays attached to the page context."
        />
      </PageFrame>
    </main>
  ),
} satisfies Meta<typeof PageBackButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Normal: Story = {};

export const FrenchLongLabel: Story = {
  args: {
    'aria-label': 'Retourner au projet de recrutement précédent',
  },
};

export const DarkTheme: Story = {
  decorators: [
    (Story) => (
      <div className="dark">
        <Story />
      </div>
    ),
  ],
};

export const Mobile: Story = {
  args: {
    'aria-label': 'Retourner au projet de recrutement précédent',
  },
  parameters: {
    viewport: { defaultViewport: 'mobile1' },
  },
};
