import type { Meta, StoryObj } from '@storybook/react-vite'

import { ReferenceBoard } from './ReferenceBoards'

const meta = {
  title: 'Design Reference/Workflow Boards',
  component: ReferenceBoard,
  parameters: {
    layout: 'fullscreen',
    docs: {
      description: {
        component: 'Prototypes visuels isolés. Même contenu synthétique dans les trois directions, sans appel API ni dépendance à l’application.',
      },
    },
  },
  argTypes: {
    direction: { control: 'select', options: ['ledger', 'split', 'dossier'] },
    theme: { control: 'inline-radio', options: ['light', 'dark'] },
    screen: { control: 'select', options: ['all', 'login', 'home', 'projects', 'offer', 'matching', 'results', 'users', 'settings'] },
  },
} satisfies Meta<typeof ReferenceBoard>

export default meta
type Story = StoryObj<typeof meta>

export const ACommandLedger: Story = {
  name: 'A — Command Ledger (recommandée)',
  args: { direction: 'ledger', theme: 'light', screen: 'all' },
}

export const BMissionSplit: Story = {
  name: 'B — Mission Split',
  args: { direction: 'split', theme: 'light', screen: 'all' },
}

export const CDecisionDossier: Story = {
  name: 'C — Decision Dossier',
  args: { direction: 'dossier', theme: 'light', screen: 'all' },
}

export const ScreenExplorer: Story = {
  name: 'Explorer un écran',
  args: { direction: 'ledger', theme: 'dark', screen: 'results' },
}
