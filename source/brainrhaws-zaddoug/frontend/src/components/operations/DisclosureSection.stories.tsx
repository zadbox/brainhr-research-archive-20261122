import type { Meta, StoryObj } from '@storybook/react-vite';
import { Button } from '../ui/button';
import { DisclosureSection } from './DisclosureSection';

type DisclosureReferenceProps = {
  theme: 'light' | 'dark';
  language: 'en' | 'fr';
  open: boolean;
};

function DisclosureReference({ theme, language, open }: DisclosureReferenceProps) {
  const french = language === 'fr';

  return (
    <main
      data-brain-ops=""
      className={`${theme === 'dark' ? 'dark' : ''} min-h-screen bg-[var(--brain-ops-canvas)] p-4 text-[var(--brain-ops-text)] sm:p-8`}
    >
      <div className="mx-auto max-w-3xl">
        <DisclosureSection
          key={`${language}-${open}`}
          open={open}
          title={french ? 'Enrichir l’offre (facultatif)' : 'Enrich the offer (optional)'}
          titleClassName="text-xl leading-tight tracking-[-0.01em] sm:text-2xl"
          description={french
            ? 'Examinez les compléments proposés avant de les appliquer à l’offre préparée.'
            : 'Review suggested additions before applying them to the prepared offer.'}
          metadata={french ? '6 propositions' : '6 proposals'}
        >
          <div className="flex flex-col items-start gap-3">
            <p className="text-sm leading-6 text-[var(--brain-ops-text-muted)]">
              {french
                ? 'Le contenu reste dense, lisible et accessible au clavier, y compris avec un intitulé français plus long.'
                : 'Content stays dense, readable, and keyboard accessible.'}
            </p>
            <Button>{french ? 'Appliquer la sélection' : 'Apply selection'}</Button>
          </div>
        </DisclosureSection>
      </div>
    </main>
  );
}

const meta = {
  title: 'BRAIN Operations/DisclosureSection',
  component: DisclosureReference,
  parameters: { layout: 'fullscreen' },
  args: { theme: 'light', language: 'en', open: true },
  argTypes: {
    theme: { control: 'inline-radio', options: ['light', 'dark'] },
    language: { control: 'inline-radio', options: ['en', 'fr'] },
  },
} satisfies Meta<typeof DisclosureReference>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Open: Story = {};

export const Closed: Story = { args: { open: false } };

export const FrenchLongContent: Story = { args: { language: 'fr' } };

export const Dark: Story = { args: { theme: 'dark' } };

export const Mobile: Story = {
  args: { language: 'fr' },
  parameters: { viewport: { defaultViewport: 'mobile1' } },
};
