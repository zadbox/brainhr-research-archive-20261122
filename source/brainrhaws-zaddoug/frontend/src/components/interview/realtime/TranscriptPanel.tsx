import { useEffect, useRef } from 'react';
import { MessageSquareText } from 'lucide-react';
import type { RealtimeTranscriptTurn } from '../../../api/realtimeInterview';
import { useI18n } from '../../../i18n/useI18n';
import { Badge } from '../../ui/badge';
import { Section } from '../../operations';

interface TranscriptPanelProps {
  turns: RealtimeTranscriptTurn[];
}

export function TranscriptPanel({ turns }: TranscriptPanelProps) {
  const { language, t } = useI18n();
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (turns.length === 0) {
      return;
    }

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    bottomRef.current?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'end' });
  }, [turns]);

  return (
    <Section
      title={(
        <span className="flex items-center gap-2">
          <MessageSquareText aria-hidden="true" className="h-5 w-5 text-[var(--brain-ops-accent)]" />
          {t('realtime.transcript.title')}
        </span>
      )}
      description={t('realtime.transcript.description')}
    >
      <div
        className="max-h-[32rem] space-y-3 overflow-y-auto pr-2"
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
        aria-label={t('realtime.transcript.aria')}
      >
        {turns.length === 0 ? (
          <div className="rounded-[var(--brain-ops-radius-structural)] border border-dashed border-[color:var(--brain-ops-border-strong)] bg-[var(--brain-ops-surface-muted)] p-8 text-center">
            <p className="text-sm font-medium text-[var(--brain-ops-text)]">{t('realtime.transcript.empty')}</p>
            <p className="mt-2 text-sm text-[var(--brain-ops-text-muted)]">
              {t('realtime.transcript.emptyDescription')}
            </p>
          </div>
        ) : (
          turns.map((turn, index) => (
            <div
              key={turn.id ?? `${turn.speaker}-${turn.ts}-${index}`}
              className={`rounded-[var(--brain-ops-radius-structural)] border p-4 ${
                turn.speaker === 'assistant'
                  ? 'border-[color:var(--brain-ops-accent)] bg-[var(--brain-ops-surface-muted)]'
                  : 'border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]'
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Badge variant={turn.speaker === 'assistant' ? 'default' : 'outline'}>
                  {turn.speaker === 'assistant'
                    ? t('realtime.transcript.assistant')
                    : t('realtime.transcript.candidate')}
                </Badge>
                <div className="flex items-center gap-2 text-xs text-[var(--brain-ops-text-muted)]">
                  {turn.isPartial ? <span>{t('realtime.transcript.streaming')}</span> : null}
                  <span>
                    {new Date(turn.ts).toLocaleTimeString(language === 'fr' ? 'fr-FR' : 'en-US', {
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit',
                    })}
                  </span>
                </div>
              </div>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-[var(--brain-ops-text)]">
                {turn.text}
              </p>
            </div>
          ))
        )}
        <div ref={bottomRef} />
        </div>
    </Section>
  );
}
