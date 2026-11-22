import type { Meta, StoryObj } from '@storybook/react-vite';
import { History, Pencil, Trash2 } from 'lucide-react';
import { RowActionMenu } from './RowActionMenu';

const meta = {
  title: 'BRAIN Operations/Row action menu',
  component: RowActionMenu,
  parameters: {
    layout: 'centered',
    docs: {
      description: {
        component: 'Menu compact et accessible pour les actions secondaires et destructives d’une ligne.',
      },
    },
  },
  decorators: [
    (Story, context) => (
      <main
        data-brain-ops=""
        className={`${context.globals.theme === 'dark' ? 'dark' : ''} min-h-64 min-w-80 bg-[var(--brain-ops-canvas)] p-8 text-[var(--brain-ops-text)]`}
      >
        <Story />
      </main>
    ),
  ],
  args: {
    triggerLabel: 'Actions',
    menuLabel: 'Actions pour Ingénieur plateforme senior',
    items: [
      { id: 'history', label: 'Historique', icon: <History className="size-4" />, onSelect: () => undefined },
      { id: 'edit', label: 'Modifier', icon: <Pencil className="size-4" />, onSelect: () => undefined },
      {
        id: 'delete',
        label: 'Supprimer',
        icon: <Trash2 className="size-4" />,
        onSelect: () => undefined,
        destructive: true,
      },
    ],
  },
} satisfies Meta<typeof RowActionMenu>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  play: ({ canvasElement }) => {
    canvasElement.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')?.click();
  },
};

export const LongFrenchContent: Story = {
  args: {
    menuLabel: 'Actions pour Responsable de la transformation des systèmes d’information internationaux',
    items: [
      {
        id: 'history',
        label: 'Consulter l’historique complet',
        icon: <History className="size-4" />,
        onSelect: () => undefined,
      },
      {
        id: 'edit',
        label: 'Modifier les informations',
        icon: <Pencil className="size-4" />,
        onSelect: () => undefined,
      },
      {
        id: 'delete',
        label: 'Supprimer définitivement',
        icon: <Trash2 className="size-4" />,
        onSelect: () => undefined,
        destructive: true,
      },
    ],
  },
  play: ({ canvasElement }) => {
    canvasElement.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')?.click();
  },
};

export const DarkTheme: Story = {
  globals: { theme: 'dark' },
  play: ({ canvasElement }) => {
    canvasElement.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')?.click();
  },
};

export const MobileViewport: Story = {
  parameters: { viewport: { defaultViewport: 'mobile1' } },
  play: ({ canvasElement }) => {
    canvasElement.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')?.click();
  },
};
