import { FileText, MapPin, Mail, Phone, CalendarPlus, ScanLine } from 'lucide-react';
import { OperationsDialogTitle, Section } from '../../components/operations';
import { Button } from '../../components/ui/button';
import { useI18n } from '../../i18n/useI18n';
import { formatMessage } from '../../i18n/formatMessage';
import { CandidateAvatar } from './CandidateAvatar';
import type { PoolProfile } from './types';

export function ProfileDetail({ profile, onRequest, onContact, onMatch }: { profile: PoolProfile; onRequest: () => void; onContact: () => void; onMatch: () => void }) {
  const { language, t } = useI18n();
  return <>
    <header className="pool-detail-header">
      <CandidateAvatar profile={profile} large />
      <div>
        <OperationsDialogTitle className="text-2xl leading-tight">{profile.name}</OperationsDialogTitle>
        <p className="pool-role">{profile.title[language]}</p>
        <p className="pool-meta"><MapPin aria-hidden="true" />{profile.location}<span>·</span>{formatMessage(t('pool.years'), { count: profile.experienceYears })}</p>
        {!profile.photo && <p className="pool-muted text-xs">{t('pool.photoMissing')}</p>}
        {profile.photo?.source === 'illustration' && <p className="pool-muted text-xs">{t('pool.illustration')}</p>}
      </div>
    </header>
    <div className="pool-detail-grid">
      <div className="pool-detail-main">
        <Section title={t('pool.overview')} headingAs="h3"><p className="pool-copy">{profile.summary[language]}</p></Section>
        <Section title={t('pool.skills')} description={t('pool.evidence')} headingAs="h3">
          <ul className="pool-evidence-list">{profile.skills.map((skill) => <li key={skill.name}><strong>{skill.name}</strong><p>{skill.evidence[language]}</p></li>)}</ul>
        </Section>
        <Section title={t('pool.experience')} headingAs="h3">
          <ul className="pool-history">{profile.experience.map((experience) => <li key={`${experience.company}-${experience.period}`}>
            <p className="pool-kicker">{experience.period}</p><h4>{experience.role[language]}</h4><p className="pool-muted">{experience.company}</p><p className="pool-copy">{experience.description[language]}</p>
          </li>)}</ul>
        </Section>
        <Section title={t('pool.education')} headingAs="h3"><ul className="pool-history">{profile.education.map((education) => <li key={`${education.school}-${education.year}`}><h4>{education.degree[language]}</h4><p className="pool-muted">{education.school} · {education.year}</p></li>)}</ul></Section>
      </div>
      <aside className="pool-detail-aside">
        <Button onClick={onRequest} className="w-full"><CalendarPlus aria-hidden="true" className="size-4" />{t('pool.request')}</Button>
        <Button onClick={onContact} variant="outline" className="w-full"><Mail aria-hidden="true" className="size-4" />{t('pool.contactAction')}</Button>
        <Button onClick={onMatch} variant="outline" className="w-full"><ScanLine aria-hidden="true" className="size-4" />{t('pool.matchTitle')}</Button>
        <Section title={t('pool.contact')} headingAs="h3"><dl className="pool-contact"><div><dt><Mail aria-hidden="true" /><span className="sr-only">{t('pool.recipient')}</span></dt><dd>{profile.email ?? t('pool.notProvided')}</dd></div><div><dt><Phone aria-hidden="true" /><span className="sr-only">{t('pool.phone')}</span></dt><dd>{profile.phone ?? t('pool.notProvided')}</dd></div></dl></Section>
        <Section title={t('pool.availability')} headingAs="h3"><p>{t(profile.availability === 'available' ? 'pool.available' : 'pool.discuss')}</p></Section>
        <Section title={t('pool.languages')} headingAs="h3"><p>{profile.languages.map((code) => new Intl.DisplayNames([language], { type: 'language' }).of(code)).join(' · ')}</p></Section>
        <Section title={t('pool.cv')} headingAs="h3"><div className="pool-source"><FileText aria-hidden="true" /><strong>{profile.sourceCv.filename}</strong></div><p className="pool-muted">{formatMessage(t('pool.pages'), { count: profile.sourceCv.pageCount })} · {new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(profile.sourceCv.updatedAt))}</p><p className="pool-muted mt-3">{t('pool.cvNote')}</p></Section>
      </aside>
    </div>
  </>;
}
