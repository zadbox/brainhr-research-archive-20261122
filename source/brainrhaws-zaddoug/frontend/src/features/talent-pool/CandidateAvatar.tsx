import { useState } from 'react';
import { useI18n } from '../../i18n/useI18n';
import { formatMessage } from '../../i18n/formatMessage';
import type { PoolProfile } from './types';

export function CandidateAvatar({ profile, large = false }: { profile: PoolProfile; large?: boolean }) {
  const { t } = useI18n();
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const url = profile.photo?.url;
  return <span className={`pool-avatar ${large ? 'pool-avatar-large' : ''}`}>
    {url && url !== failedUrl ? <img src={url} loading="lazy" decoding="async" alt={formatMessage(t(profile.photo?.source === 'illustration' ? 'pool.illustrationAlt' : 'pool.photoAlt'), { name: profile.name })} onError={() => setFailedUrl(url)} />
      : <span aria-hidden="true">{profile.name.split(' ').map((part) => part[0]).slice(0, 2).join('')}</span>}
  </span>;
}
