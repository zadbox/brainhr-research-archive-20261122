import { Download, PlayCircle, Video } from 'lucide-react';
import { API_BASE_URL } from '../../../api/client';
import type { InterviewRecordingArtifact } from '../../../api/interviewAppointments';
import { Badge } from '../../ui/badge';
import { premiumSubPanelClass } from '../../shared/PremiumPage';
import { useI18n } from '../../../i18n/useI18n';
import type { TranslationKey } from '../../../i18n/messages';

interface RecordingLinksProps {
  recordings: InterviewRecordingArtifact[];
  title?: string;
  maxItems?: number;
  compact?: boolean;
}

const RECORDING_STATUS_KEYS: Record<string, TranslationKey> = {
  available: 'recordings.status.available',
  completed: 'recordings.status.completed',
  processing: 'recordings.status.processing',
  pending: 'recordings.status.pending',
  failed: 'recordings.status.failed',
};

function absoluteUrl(value?: string | null): string | null {
  if (!value) return null;
  if (/^https?:\/\//i.test(value)) return value;
  if (value.startsWith('/')) return `${API_BASE_URL}${value}`;
  return null;
}

function recordingLabel(recording: InterviewRecordingArtifact, fallback: string): string {
  const raw =
    recording.title ||
    recording.name ||
    recording.id ||
    recording.uid ||
    recording.roomName ||
    fallback;
  const label = String(raw);
  return label.includes('/') ? label.split('/').pop() || label : label;
}

function recordingDate(recording: InterviewRecordingArtifact, locale: string): string | null {
  const raw = recording.created_at || recording.started_at || recording.uploaded_at;
  if (!raw || typeof raw !== 'string') return null;
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(locale, {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function recordingSize(recording: InterviewRecordingArtifact): string | null {
  const bytes = typeof recording.size_bytes === 'number' ? recording.size_bytes : null;
  if (!bytes || bytes <= 0) return null;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.ceil(bytes / 1024)} KB`;
}

function recordingViewUrl(recording: InterviewRecordingArtifact): string | null {
  return absoluteUrl(
    recording.view_url ||
      recording.url ||
      recording.recordingUrl ||
      (typeof recording.link === 'string' ? recording.link : null)
  );
}

function recordingDownloadUrl(recording: InterviewRecordingArtifact): string | null {
  return absoluteUrl(
    recording.download_url ||
      recording.downloadUrl ||
      (typeof recording.downloadLink === 'string' ? recording.downloadLink : null)
  );
}

export function RecordingLinks({
  recordings,
  title,
  maxItems = 3,
  compact = false,
}: RecordingLinksProps) {
  const { language, t } = useI18n();
  const visibleRecordings = recordings.filter(Boolean).slice(0, maxItems);
  const remaining = Math.max(0, recordings.length - visibleRecordings.length);
  const resolvedTitle = title || t('recordings.title');

  if (visibleRecordings.length === 0) return null;

  return (
    <div className={`${premiumSubPanelClass} space-y-3 p-4`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Video className="h-4 w-4 text-primary" />
          <span>{resolvedTitle}</span>
        </div>
        <Badge variant="outline">{recordings.length}</Badge>
      </div>

      <div className="space-y-2">
        {visibleRecordings.map((recording, index) => {
          const viewUrl = recordingViewUrl(recording);
          const downloadUrl = recordingDownloadUrl(recording);
          const rawStatus = recording.status ? String(recording.status) : 'available';
          const statusKey = RECORDING_STATUS_KEYS[rawStatus.toLowerCase()];
          const status = statusKey ? t(statusKey) : rawStatus;
          const meta = [
            recording.provider ? String(recording.provider) : null,
            recording.resolution ? String(recording.resolution) : recording.video_size ? String(recording.video_size) : null,
            recordingDate(recording, language === 'fr' ? 'fr-FR' : 'en-GB'),
            recordingSize(recording),
          ].filter(Boolean);

          return (
            <div
              key={`${recording.id || recording.uid || index}`}
              className="flex flex-col gap-3 overflow-hidden rounded-md border border-border/70 bg-background/70 p-3 sm:flex-row sm:items-start sm:justify-between"
            >
              <div className="min-w-0 space-y-1">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="max-w-full break-all text-sm font-medium">
                    {recordingLabel(recording, t('recordings.item').replace('{{number}}', String(index + 1)))}
                  </span>
                  <Badge variant={rawStatus.toLowerCase() === 'failed' ? 'destructive' : 'secondary'}>{status}</Badge>
                </div>
                {!compact && meta.length > 0 && (
                  <p className="break-all text-xs text-muted-foreground">{meta.join(' · ')}</p>
                )}
              </div>

              <div className="flex shrink-0 flex-wrap items-center gap-2">
                {viewUrl && (
                  <a
                    href={viewUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-8 items-center justify-center gap-2 rounded-md border border-input bg-background px-3 text-xs font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                  >
                    <PlayCircle className="h-3.5 w-3.5" />
                    {t('recordings.open')}
                  </a>
                )}
                {downloadUrl && (
                  <a
                    href={downloadUrl}
                    download
                    className="inline-flex h-8 items-center justify-center gap-2 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/80"
                  >
                    <Download className="h-3.5 w-3.5" />
                    {t('recordings.download')}
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {remaining > 0 && (
        <p className="text-xs text-muted-foreground">
          {t('recordings.more').replace('{{count}}', String(remaining))}
        </p>
      )}
    </div>
  );
}
