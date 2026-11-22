import { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';

import { Button } from './button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './dialog';

interface DialogReferenceProps {
  language: 'en' | 'fr';
  theme: 'light' | 'dark';
  longContent: boolean;
}

function DialogReference({ language, theme, longContent }: DialogReferenceProps) {
  const [open, setOpen] = useState(true);
  const french = language === 'fr';
  const title = french ? 'Planifier un entretien' : 'Schedule interview';
  const description = french
    ? 'Vérifiez le créneau, la durée et les informations du candidat avant de confirmer la planification.'
    : 'Review the time slot, duration, and candidate details before confirming the schedule.';

  return (
    <main className={`${theme === 'dark' ? 'dark' : ''} min-h-screen bg-background p-8 text-foreground`}>
      <Button onClick={() => setOpen(true)}>{french ? 'Ouvrir la fenêtre' : 'Open dialog'}</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogClose aria-label={french ? 'Fermer la fenêtre' : 'Close dialog'} />
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {longContent
              ? `${description} ${description} ${description}`
              : (french ? 'Candidat : Alex Morgan' : 'Candidate: Alex Morgan')}
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {french ? 'Annuler' : 'Cancel'}
            </Button>
            <Button onClick={() => setOpen(false)}>
              {french ? 'Confirmer la planification' : 'Confirm schedule'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}

const meta = {
  title: 'UI/Dialog',
  component: DialogReference,
  parameters: { layout: 'fullscreen' },
  args: { language: 'en', theme: 'light', longContent: false },
  argTypes: {
    language: { control: 'inline-radio', options: ['en', 'fr'] },
    theme: { control: 'inline-radio', options: ['light', 'dark'] },
  },
} satisfies Meta<typeof DialogReference>;

export default meta;
type Story = StoryObj<typeof meta>;

export const DefaultOpen: Story = {};

export const FrenchLongContent: Story = {
  args: { language: 'fr', longContent: true },
};

export const DarkTheme: Story = {
  args: { theme: 'dark' },
};

export const MobileViewport: Story = {
  args: { language: 'fr', longContent: true },
  parameters: { viewport: { defaultViewport: 'mobile1' } },
};
