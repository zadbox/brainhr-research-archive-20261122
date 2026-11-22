import { useMemo, useRef, useState } from 'react';
import { ArrowRight, Search, FilePenLine, Download, Info, UsersRound } from 'lucide-react';
import { PageFrame, PageHeader, Section, SystemState, OperationsDialog, OperationsDialogContent, OperationsDialogClose } from '../../components/operations';
import { Button } from '../../components/ui/button';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui/tabs';
import { useI18n } from '../../i18n/useI18n';
import { formatMessage } from '../../i18n/formatMessage';
import { ProfileCard, type ProfileAction } from './ProfileCard';
import { ContactRequest } from './ContactRequest';
import { MatchOffer } from './MatchOffer';
import { ProfileDetail } from './ProfileDetail';
import { InterviewRequest } from './InterviewRequest';
import type { InterviewDraft, ContactDraft, PoolProfile, PoolOffer } from './types';
import './talent-pool.css';

const normalize = (text: string) => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase().trim();
type Surface = { profileId: string; view: ProfileAction };

/** A frontend preview. Its state never reads CVs, writes to an API or survives a scope change. */
export function TalentPool({ profiles, offers = [] }: { profiles: PoolProfile[]; offers?: PoolOffer[] }) {
  const { language, t } = useI18n();
  const [tab, setTab] = useState('profiles');
  const [search, setSearch] = useState('');
  const [skill, setSkill] = useState('');
  const [availability, setAvailability] = useState('');
  const [sort, setSort] = useState('recent');
  const [showDrafts, setShowDrafts] = useState(false);
  const [surface, setSurface] = useState<Surface | null>(null);
  const [drafts, setDrafts] = useState<InterviewDraft[]>([]);
  const [contactDrafts, setContactDrafts] = useState<ContactDraft[]>([]);
  const [matchSelections, setMatchSelections] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<'message' | 'match' | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const profilesTabRef = useRef<HTMLButtonElement>(null);
  const allSkills = useMemo(() => [...new Set(profiles.flatMap((profile) => profile.skills.map((item) => item.name)))].sort((a, b) => a.localeCompare(b, language)), [profiles, language]);
  const query = normalize(search);
  const filteredProfiles = useMemo(() => profiles.filter((profile) => {
    const searchable = [profile.name, profile.title[language], profile.location, ...profile.skills.map((item) => item.name)].join(' ');
    return (!query || normalize(searchable).includes(query)) && (!availability || profile.availability === availability) && (!skill || profile.skills.some((item) => item.name === skill));
  }).sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name, language) : b.sourceCv.updatedAt.localeCompare(a.sourceCv.updatedAt)), [profiles, query, availability, skill, sort, language]);
  const skillGroups = useMemo(() => allSkills.map((name) => ({ name, profiles: profiles.filter((profile) => profile.skills.some((item) => item.name === name) && (!availability || profile.availability === availability)) }))
    .filter((group) => group.profiles.length > 0 && (!query || normalize(group.name).includes(query) || group.profiles.some((profile) => normalize([profile.name, profile.title[language], profile.location].join(' ')).includes(query))))
    .sort((a, b) => b.profiles.length - a.profiles.length || a.name.localeCompare(b.name, language)), [allSkills, profiles, availability, query, language]);
  const activeProfile = profiles.find((profile) => profile.id === surface?.profileId);

  const reset = () => { setSearch(''); setSkill(''); setAvailability(''); };
  const switchSurface = (view: Surface['view']) => {
    setSurface((current) => current ? { ...current, view } : null);
    // Keep focus in the same dialog while replacing its contents.
    dialogRef.current?.focus();
    dialogRef.current?.scrollTo({ top: 0 });
  };
  const downloadDraft = (draft: InterviewDraft | ContactDraft) => {
    const isInterview = 'duration' in draft;
    const body = `${t(isInterview ? 'pool.requestNote' : 'pool.contactNote')}\n\n${t('pool.recipient')}: ${draft.recipient}\n${t('pool.subject')}: ${draft.subject}\n${isInterview ? `${t('pool.project')}: ${draft.project}\n${t('pool.duration')}: ${formatMessage(t('pool.minutes'), { count: draft.duration })}\n` : ''}\n${draft.message}\n`;
    const url = URL.createObjectURL(new Blob([body], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url; link.download = `${isInterview ? 'interview' : 'contact'}-draft-${draft.profileId}.txt`;
    document.body.append(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return <PageFrame className="talent-pool" contentClassName="gap-5 lg:gap-6" width="full">
    <PageHeader className="pb-5 sm:pb-5" title={t('pool.title')} description={t('pool.description')} actionsLabel={t('pool.drafts')} actions={<Button variant="outline" aria-pressed={showDrafts} onClick={() => { setShowDrafts((current) => !current); setSaved(null); }}><FilePenLine aria-hidden="true" className="size-4" />{t('pool.drafts')}<span className="pool-count">{drafts.length + contactDrafts.length}</span></Button>} />
    <div className="pool-preview"><Info aria-hidden="true" /><div><strong>{t('pool.preview')}</strong><p>{t('pool.previewNote')}</p></div></div>
    {saved && <p role="status" className="pool-saved">{t(saved === 'match' ? 'pool.matchSaved' : 'pool.draftSaved')}</p>}
    {showDrafts ? <Section title={t('pool.drafts')} divided={false} actionsLabel={t('pool.profiles')} actions={<Button variant="outline" onClick={() => setShowDrafts(false)}>{t('pool.viewProfiles')}</Button>}>
      {(drafts.length + contactDrafts.length) === 0 ? <SystemState kind="empty" title={t('pool.noDrafts')} description={t('pool.noDraftsHelp')} /> : <ul className="pool-drafts">{drafts.map((draft) => <li key={draft.profileId}>
        <div><span className="pool-kicker">{t('pool.draft')}</span><h3>{profiles.find((profile) => profile.id === draft.profileId)?.name}</h3><p>{draft.project}</p><p className="pool-muted">{draft.recipient} · {formatMessage(t('pool.minutes'), { count: draft.duration })}</p></div>
        <div className="pool-draft-actions"><Button variant="outline" onClick={() => setSurface({ profileId: draft.profileId, view: 'request' })}>{t('pool.editDraft')}</Button><Button variant="ghost" onClick={() => downloadDraft(draft)}><Download aria-hidden="true" className="size-4" />{t('pool.downloadDraft')}</Button></div>
      </li>)}{contactDrafts.map((draft) => <li key={`contact-${draft.profileId}`}>
        <div><span className="pool-kicker">{t('pool.contactAction')} · {t('pool.draft')}</span><h3>{profiles.find((profile) => profile.id === draft.profileId)?.name}</h3><p>{draft.subject}</p><p className="pool-muted">{draft.recipient}</p></div>
        <div className="pool-draft-actions"><Button variant="outline" onClick={() => setSurface({ profileId: draft.profileId, view: 'contact' })}>{t('pool.editDraft')}</Button><Button variant="ghost" onClick={() => downloadDraft(draft)}><Download aria-hidden="true" className="size-4" />{t('pool.downloadDraft')}</Button></div>
      </li>)}</ul>}
    </Section> : <Tabs value={tab} onValueChange={setTab}>
      <div className="pool-toolbar"><TabsList aria-label={t('pool.nav')} className="h-12"><TabsTrigger value="profiles" ref={profilesTabRef}>{t('pool.profiles')}<span className="pool-count">{profiles.length}</span></TabsTrigger><TabsTrigger value="skills">{t('pool.skills')}<span className="pool-count">{allSkills.length}</span></TabsTrigger></TabsList>
        <label className="pool-search"><Search aria-hidden="true" /><span className="sr-only">{t('pool.search')}</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('pool.searchPlaceholder')} /></label>
      </div>
      <div className="pool-filters">
        {tab === 'profiles' && <label><span className="sr-only">{t('pool.skills')}</span><select value={skill} onChange={(event) => setSkill(event.target.value)}><option value="">{t('pool.allSkills')}</option>{allSkills.map((name) => <option key={name}>{name}</option>)}</select></label>}
        <label><span className="sr-only">{t('pool.availability')}</span><select value={availability} onChange={(event) => setAvailability(event.target.value)}><option value="">{t('pool.allAvailability')}</option><option value="available">{t('pool.available')}</option><option value="discuss">{t('pool.discuss')}</option></select></label>
        {(search || availability || (tab === 'profiles' && skill)) && <Button variant="ghost" onClick={reset}>{t('pool.reset')}</Button>}
        {tab === 'profiles' && <label className="pool-sort"><span className="sr-only">{t('pool.sort')}</span><select value={sort} onChange={(event) => setSort(event.target.value)}><option value="recent">{t('pool.recent')}</option><option value="name">{t('pool.nameSort')}</option></select></label>}
      </div>
      <TabsContent value="profiles">
        <p className="pool-kicker pool-result-count" role="status">{formatMessage(t('pool.results'), { count: filteredProfiles.length })}</p>
        {filteredProfiles.length === 0 ? <SystemState kind="empty" title={t('pool.empty')} description={t('pool.emptyHelp')} /> : <ul className="pool-profile-grid">{filteredProfiles.map((profile) => <li key={profile.id}>
          <ProfileCard profile={profile} onAction={(view) => { setSaved(null); setSurface({ profileId: profile.id, view }); }} />
        </li>)}</ul>}
      </TabsContent>
      <TabsContent value="skills"><p className="pool-muted pool-skill-help">{t('pool.skillHelp')}</p>
        {skillGroups.length === 0 ? <SystemState kind="empty" title={t('pool.noSkills')} description={t('pool.emptyHelp')} /> : <ul className="pool-skill-directory">{skillGroups.map((group) => <li key={group.name}><button aria-label={formatMessage(t('pool.skillProfiles'), { count: group.profiles.length, skill: group.name })} onClick={() => { setSkill(group.name); setSearch(''); setTab('profiles'); profilesTabRef.current?.focus(); }}>
          <div><h2>{group.name}</h2><p className="pool-muted">{group.profiles.map((profile) => profile.name).join(' · ')}</p></div><span className="pool-skill-total"><UsersRound aria-hidden="true" />{group.profiles.length}<ArrowRight aria-hidden="true" /></span>
        </button></li>)}</ul>}
      </TabsContent>
    </Tabs>}
    <OperationsDialog open={Boolean(activeProfile)} onOpenChange={(open) => { if (!open) setSurface(null); }}>
      {activeProfile && <OperationsDialogContent ref={dialogRef} className={`talent-pool border-[color:var(--brain-ops-border)] outline-none ${surface?.view === 'profile' ? 'max-w-5xl' : 'max-w-2xl'}`}>
        <OperationsDialogClose className="right-2 top-2 flex size-10 items-center justify-center" aria-label={t(surface?.view === 'profile' ? 'pool.close' : surface?.view === 'request' ? 'pool.closeRequest' : 'pool.closeAction')} />
        {surface?.view === 'request' ? <InterviewRequest key={activeProfile.id} profile={activeProfile} draft={drafts.find((draft) => draft.profileId === activeProfile.id)} onClose={() => switchSurface('profile')} onSave={(draft) => {
          setDrafts((current) => [...current.filter((item) => item.profileId !== draft.profileId), draft]); setSurface(null); setSaved('message');
        }} /> : surface?.view === 'contact' ? <ContactRequest key={activeProfile.id} profile={activeProfile} draft={contactDrafts.find((draft) => draft.profileId === activeProfile.id)} onClose={() => switchSurface('profile')} onSave={(draft) => {
          setContactDrafts((current) => [...current.filter((item) => item.profileId !== draft.profileId), draft]); setSurface(null); setSaved('message');
        }} /> : surface?.view === 'match' ? <MatchOffer key={activeProfile.id} profile={activeProfile} offers={offers} selectedOfferId={matchSelections[activeProfile.id]} onClose={() => switchSurface('profile')} onSave={(offerId) => {
          setMatchSelections((current) => ({ ...current, [activeProfile.id]: offerId })); setSurface(null); setSaved('match');
        }} /> : <ProfileDetail profile={activeProfile} onRequest={() => switchSurface('request')} onContact={() => switchSurface('contact')} onMatch={() => switchSurface('match')} />}
      </OperationsDialogContent>}
    </OperationsDialog>
  </PageFrame>;
}
