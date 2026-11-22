import type { LabelHTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/utils';

export interface ChoiceTargetProps extends LabelHTMLAttributes<HTMLLabelElement> {
  children: ReactNode;
}

export function ChoiceTarget({ children, className, ...props }: ChoiceTargetProps) {
  return (
    <label
      {...props}
      className={cn('brain-ops-choice-target inline-flex items-center gap-3', className)}
    >
      {children}
    </label>
  );
}
