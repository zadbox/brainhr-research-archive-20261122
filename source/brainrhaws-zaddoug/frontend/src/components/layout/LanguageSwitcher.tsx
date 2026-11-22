import { cn } from '../../lib/utils';
import { useI18n } from '../../i18n/useI18n';
import type { Language } from '../../i18n/messages';

const languageOptions: Array<{ value: Language; shortLabel: string; nameKey: 'language.english' | 'language.french' }> = [
  { value: 'en', shortLabel: 'EN', nameKey: 'language.english' },
  { value: 'fr', shortLabel: 'FR', nameKey: 'language.french' },
];

export const LanguageSwitcher = ({ compact = false }: { compact?: boolean }) => {
  const { language, setLanguage, t } = useI18n();

  if (compact) {
    const next = languageOptions.find((option) => option.value !== language)!;
    return (
      <div role="group" aria-label={t('language.selectorLabel')}>
        <button type="button" onClick={() => setLanguage(next.value)}
          aria-label={t(next.nameKey)} title={t(next.nameKey)}
          className="brain-shell-touch-target brain-shell-square-target inline-flex shrink-0 items-center justify-center rounded-md text-xs font-medium uppercase text-[var(--brain-ops-text-muted)] hover:bg-[var(--brain-ops-surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {language.toUpperCase()}
        </button>
      </div>
    );
  }

  return (
    <div
      role="group"
      aria-label={t('language.selectorLabel')}
      className="flex items-center rounded-md border border-border bg-background/80 p-0.5"
    >
      {languageOptions.map((option) => {
        const isSelected = language === option.value;

        return (
          <button
            key={option.value}
            type="button"
            onClick={() => setLanguage(option.value)}
            aria-pressed={isSelected}
            aria-label={t(option.nameKey)}
            title={t(option.nameKey)}
            className={cn(
              'min-h-11 min-w-11 rounded px-2 font-mono text-[0.68rem] font-semibold tracking-[0.12em] transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              isSelected
                ? 'bg-foreground text-background'
                : 'text-muted-foreground hover:bg-accent hover:text-foreground'
            )}
          >
            {option.shortLabel}
          </button>
        );
      })}
    </div>
  );
};
