import { ArrowUpRight, CalendarPlus, Mail, ScanLine, MapPin } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { useI18n } from '../../i18n/useI18n';
import { formatMessage } from '../../i18n/formatMessage';
import { CandidateAvatar } from './CandidateAvatar';
import type { PoolProfile } from './types';

export type ProfileAction = 'profile' | 'request' | 'contact' | 'match';

export function ProfileCard({ profile, onAction }: {
  profile: PoolProfile;
  onAction: (action: ProfileAction) => void;
}) {
  const { language, t } = useI18n();
  return (
    <article className="pool-profile-card" aria-label={profile.name}>
      <button
        type="button"
        className="pool-card-open"
        aria-label={formatMessage(t('pool.open'), { name: profile.name })}
        onClick={() => onAction('profile')}
      >
        <span className="pool-card-top">
          <span className="pool-availability">{t(profile.availability === 'available' ? 'pool.available' : 'pool.discuss')}</span>
          <ArrowUpRight aria-hidden="true" />
        </span>
        <CandidateAvatar profile={profile} large />
        <span className="pool-card-name">{profile.name}</span>
        <span className="pool-card-role">{profile.title[language]}</span>
        <span className="pool-meta"><MapPin aria-hidden="true" />{profile.location}</span>
        <span className="pool-muted">{formatMessage(t('pool.years'), { count: profile.experienceYears })}</span>
        <span className="pool-card-skills">{profile.skills.map((skill) => <span className="pool-skill-tag" key={skill.name}>{skill.name}</span>)}</span>
        <span className="pool-card-more">{t('pool.openLabel')}<ArrowUpRight aria-hidden="true" /></span>
      </button>
      <div className="pool-card-actions">
        <Button variant="ghost" aria-label={formatMessage(t('pool.interviewWith'), { name: profile.name })} onClick={() => onAction('request')}><CalendarPlus aria-hidden="true" />{t('pool.interviewAction')}</Button>
        <Button variant="ghost" aria-label={formatMessage(t('pool.contactWith'), { name: profile.name })} onClick={() => onAction('contact')}><Mail aria-hidden="true" />{t('pool.contactAction')}</Button>
        <Button variant="ghost" aria-label={formatMessage(t('pool.matchWith'), { name: profile.name })} onClick={() => onAction('match')}><ScanLine aria-hidden="true" />{t('pool.matchAction')}</Button>
      </div>
    </article>
  );
}
