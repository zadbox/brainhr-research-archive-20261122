import { Activity, Bot, LoaderCircle, Mic, MicOff, TriangleAlert } from 'lucide-react';
import type { TranslationKey } from '../../../i18n/messages';
import { useI18n } from '../../../i18n/useI18n';
import { Badge } from '../../ui/badge';

export type InterviewRoomStatus =
  | 'idle'
  | 'requesting_token'
  | 'connecting'
  | 'connected'
  | 'listening'
  | 'speaking'
  | 'processing'
  | 'finalizing'
  | 'completed'
  | 'disconnected'
  | 'error';

interface StatusBadgeProps {
  status: InterviewRoomStatus;
  detail?: string;
}

const STATUS_CONFIG: Record<
  InterviewRoomStatus,
  {
    labelKey: TranslationKey;
    variant: 'default' | 'secondary' | 'destructive' | 'outline' | 'success';
    icon: React.ComponentType<{ className?: string }>;
    pulse?: boolean;
  }
> = {
  idle: {
    labelKey: 'realtime.room.status.idle',
    variant: 'outline',
    icon: Activity,
  },
  requesting_token: {
    labelKey: 'realtime.room.status.requestingToken',
    variant: 'secondary',
    icon: LoaderCircle,
    pulse: true,
  },
  connecting: {
    labelKey: 'realtime.room.status.connecting',
    variant: 'secondary',
    icon: LoaderCircle,
    pulse: true,
  },
  connected: {
    labelKey: 'realtime.room.status.connected',
    variant: 'success',
    icon: Bot,
  },
  listening: {
    labelKey: 'realtime.room.status.listening',
    variant: 'success',
    icon: Mic,
  },
  speaking: {
    labelKey: 'realtime.room.status.speaking',
    variant: 'default',
    icon: Bot,
  },
  processing: {
    labelKey: 'realtime.room.status.processing',
    variant: 'secondary',
    icon: LoaderCircle,
    pulse: true,
  },
  finalizing: {
    labelKey: 'realtime.room.status.finalizing',
    variant: 'secondary',
    icon: LoaderCircle,
    pulse: true,
  },
  completed: {
    labelKey: 'realtime.room.status.completed',
    variant: 'success',
    icon: Bot,
  },
  disconnected: {
    labelKey: 'realtime.room.status.disconnected',
    variant: 'outline',
    icon: MicOff,
  },
  error: {
    labelKey: 'realtime.room.status.error',
    variant: 'destructive',
    icon: TriangleAlert,
  },
};

export function StatusBadge({ status, detail }: StatusBadgeProps) {
  const { t } = useI18n();
  const config = STATUS_CONFIG[status];
  const Icon = config.icon;

  return (
    <div className="flex flex-wrap items-center gap-2" role="status" aria-live="polite" aria-atomic="true">
      <Badge variant={config.variant} className="gap-1.5 px-3 py-1">
        <Icon
          aria-hidden="true"
          className={config.pulse ? 'h-3.5 w-3.5 motion-safe:animate-spin' : 'h-3.5 w-3.5'}
        />
        {t(config.labelKey)}
      </Badge>
      {detail ? <span className="text-xs text-muted-foreground">{detail}</span> : null}
    </div>
  );
}
