import type { Meta, StoryObj } from '@storybook/react-vite';

import { Toast } from './toast';

type ToastReferenceProps = {
  language: 'en' | 'fr';
  theme: 'light' | 'dark';
  type: 'success' | 'error' | 'warning' | 'info';
  longContent: boolean;
};

function ToastReference({ language, theme, type, longContent }: ToastReferenceProps) {
  const french = language === 'fr';
  const title = french ? 'Modifications enregistrées' : 'Changes saved';
  const description = longContent
    ? (french
      ? 'Les informations ont été enregistrées et sont maintenant disponibles dans le dossier de recrutement.'
      : 'The information was saved and is now available in the recruitment workspace.')
    : undefined;

  return (
    <main data-brain-ops="" className={`${theme === 'dark' ? 'dark' : ''} min-h-screen bg-[var(--brain-ops-canvas)] p-4 text-[var(--brain-ops-text)]`}>
      <div className="ml-auto flex w-full max-w-[22rem] flex-col items-end">
        <Toast
          id="toast-story"
          title={title}
          description={description}
          type={type}
          closeLabel={french ? 'Fermer' : 'Close'}
          onClose={() => undefined}
        />
      </div>
    </main>
  );
}

const meta = {
  title: 'UI/Toast',
  component: ToastReference,
  parameters: { layout: 'fullscreen' },
  args: { language: 'en', theme: 'light', type: 'success', longContent: false },
  argTypes: {
    language: { control: 'inline-radio', options: ['en', 'fr'] },
    theme: { control: 'inline-radio', options: ['light', 'dark'] },
    type: { control: 'inline-radio', options: ['success', 'error', 'warning', 'info'] },
  },
} satisfies Meta<typeof ToastReference>;

export default meta;
type Story = StoryObj<typeof meta>;

export const CompactSuccess: Story = {};

export const CompactSuccessWithUsefulDetail: Story = {
  args: { longContent: true },
};

export const FrenchLongMessage: Story = {
  args: { language: 'fr', longContent: true },
};

export const DarkError: Story = {
  args: { theme: 'dark', type: 'error', longContent: true },
};

export const MobileWarning: Story = {
  args: { language: 'fr', type: 'warning', longContent: true },
  parameters: { viewport: { defaultViewport: 'mobile1' } },
};
