import { LoaderCircle, Mic, MicOff } from 'lucide-react';
import { useI18n } from '../../../i18n/useI18n';
import { Button } from '../../ui/button';

interface MicButtonProps {
  muted: boolean;
  disabled?: boolean;
  busy?: boolean;
  onToggle: () => void;
}

export function MicButton({ muted, disabled, busy, onToggle }: MicButtonProps) {
  const { t } = useI18n();

  return (
    <Button
      type="button"
      variant={muted ? 'outline' : 'default'}
      onClick={onToggle}
      disabled={disabled || busy}
      aria-pressed={!muted}
      aria-label={muted ? t('realtime.room.mic.enable') : t('realtime.room.mic.disable')}
      className="min-h-11 w-full sm:w-auto sm:min-w-32"
    >
      {busy ? (
        <>
          <LoaderCircle aria-hidden="true" className="h-4 w-4 motion-safe:animate-spin" />
          {t('realtime.room.mic.updating')}
        </>
      ) : muted ? (
        <>
          <MicOff aria-hidden="true" className="h-4 w-4" />
          {t('realtime.room.mic.muted')}
        </>
      ) : (
        <>
          <Mic aria-hidden="true" className="h-4 w-4" />
          {t('realtime.room.mic.active')}
        </>
      )}
    </Button>
  );
}
