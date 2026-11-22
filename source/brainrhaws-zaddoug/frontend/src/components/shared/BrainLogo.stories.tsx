import type { Meta, StoryObj } from '@storybook/react-vite';
import { BrainLogo } from './BrainLogo';

const meta = {
  title: 'Shared/BrainLogo',
  component: BrainLogo,
  args: { className: 'w-16' },
  decorators: [(Story) => <div className="bg-background p-6"><Story /></div>],
} satisfies Meta<typeof BrainLogo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Light: Story = {};
export const Dark: Story = {
  decorators: [(Story) => <div className="dark bg-black p-6"><Story /></div>],
};
export const HeaderSize: Story = { args: { className: 'w-8' } };
