import {
  ArrowRight,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  CircleAlert,
  FileSearch,
  Filter,
  Gauge,
  LogIn,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Users,
} from 'lucide-react'

import {
  directionMeta,
  referenceCopy,
  screenLabels,
  screens,
  type ReferenceDirection,
  type ReferenceScreen,
  type ReferenceTheme,
} from './referenceData'
import './referenceBoards.css'

type ReferenceBoardProps = {
  direction: ReferenceDirection
  theme?: ReferenceTheme
  screen?: ReferenceScreen | 'all'
}

const icons: Record<ReferenceScreen, typeof Gauge> = {
  login: LogIn,
  home: Gauge,
  projects: BriefcaseBusiness,
  offer: FileSearch,
  matching: Sparkles,
  results: SlidersHorizontal,
  users: Users,
  settings: Settings,
}

function MiniButton({ children, primary = false }: { children: React.ReactNode; primary?: boolean }) {
  return <button type="button" className={primary ? 'ref-button ref-button--primary' : 'ref-button'}>{children}</button>
}

function MiniHeader({ screen, direction }: { screen: ReferenceScreen; direction: ReferenceDirection }) {
  const Icon = icons[screen]
  return (
    <header className="ref-mini-header">
      <div className="ref-mark" aria-hidden="true">B</div>
      <div className="ref-mini-context">
        <span>{referenceCopy.workspace}</span>
        <strong>{screenLabels[screen]}</strong>
      </div>
      {direction === 'ledger' && <span className="ref-command">⌘ K</span>}
      {direction === 'split' && <Icon size={15} aria-hidden="true" />}
      {direction === 'dossier' && <span className="ref-folio">{screens.indexOf(screen) + 1}/8</span>}
    </header>
  )
}

function MiniNav({ active }: { active: ReferenceScreen }) {
  const items: Array<[ReferenceScreen, string]> = [
    ['home', 'Accueil'],
    ['projects', 'Projets'],
    ['matching', 'Matching'],
    ['users', 'Admin'],
  ]
  return (
    <nav className="ref-mini-nav" aria-label="Navigation du prototype">
      {items.map(([key, label]) => (
        <span className={active === key || (active === 'offer' && key === 'projects') || (active === 'results' && key === 'matching') ? 'is-active' : ''} key={key}>
          {label}
        </span>
      ))}
    </nav>
  )
}

function MetricStrip() {
  return (
    <div className="ref-metrics">
      {referenceCopy.metrics.map(([label, value]) => (
        <div className="ref-metric" key={label}>
          <strong>{value}</strong>
          <span>{label}</span>
        </div>
      ))}
    </div>
  )
}

function Rows({ rows, score = false }: { rows: ReadonlyArray<readonly [string, string, string]>; score?: boolean }) {
  return (
    <div className="ref-rows">
      {rows.map(([title, detail, status], index) => (
        <div className="ref-row" key={title}>
          <span className="ref-row-index">{String(index + 1).padStart(2, '0')}</span>
          <strong>{title}</strong>
          <span>{score ? `${detail}%` : detail}</span>
          <em>{status}</em>
          <ChevronRight size={13} aria-hidden="true" />
        </div>
      ))}
    </div>
  )
}

function ScreenContent({ screen }: { screen: ReferenceScreen }) {
  switch (screen) {
    case 'login':
      return (
        <div className="ref-login">
          <div className="ref-login-intro">
            <span className="ref-kicker">ESPACE SÉCURISÉ</span>
            <h3>Décidez avec les bonnes preuves.</h3>
            <p>Accédez à votre espace de recrutement.</p>
          </div>
          <form className="ref-form">
            <label>Adresse e-mail<input value="sophie@northstar.fr" readOnly /></label>
            <label>Mot de passe<input value="••••••••••" readOnly /></label>
            <MiniButton primary>Se connecter <ArrowRight size={13} /></MiniButton>
            <small>Mot de passe oublié ?</small>
          </form>
        </div>
      )
    case 'home':
      return (
        <>
          <Title title={`Bonjour ${referenceCopy.operator.split(' ')[0]}`} meta="Vendredi 1 août · Vue d’ensemble" action="Créer un projet" />
          <MetricStrip />
          <SectionTitle title="À traiter maintenant" meta="3 priorités" />
          <Rows rows={referenceCopy.projects} />
        </>
      )
    case 'projects':
      return (
        <>
          <Title title="Projets" meta="12 actifs · 4 archivés" action="Nouveau projet" />
          <div className="ref-toolbar"><span><Search size={13} /> Rechercher un projet</span><span><Filter size={13} /> Statut : Tous</span></div>
          <Rows rows={referenceCopy.projects} />
        </>
      )
    case 'offer':
      return (
        <>
          <Title title={referenceCopy.offer} meta={`${referenceCopy.projectCode} · ${referenceCopy.location}`} action="Modifier l’offre" />
          <div className="ref-two-column">
            <section><SectionTitle title="Critères de sélection" meta="3 critères" /><div className="ref-checks">{referenceCopy.criteria.map(([name, level]) => <div key={name}><Check size={13} /><strong>{name}</strong><span>{level}</span></div>)}</div></section>
            <aside><span className="ref-kicker">CONTEXTE</span><strong>{referenceCopy.project}</strong><p>Responsable : {referenceCopy.owner}</p><p>{referenceCopy.updated}</p></aside>
          </div>
        </>
      )
    case 'matching':
      return (
        <>
          <Title title="Lancer le matching" meta={`${referenceCopy.project} · 42 candidats`} action="Lancer l’analyse" />
          <div className="ref-stepper"><b>01 Offre</b><b>02 Candidats</b><b className="is-current">03 Paramètres</b></div>
          <div className="ref-two-column"><section><SectionTitle title="Périmètre" meta="Prêt à analyser" /><div className="ref-summary"><span>Offre sélectionnée<strong>{referenceCopy.offer}</strong></span><span>CV inclus<strong>42 profils</strong></span></div></section><aside><CircleAlert size={15} /><strong>Contrôle avant lancement</strong><p>3 critères obligatoires seront vérifiés.</p></aside></div>
        </>
      )
    case 'results':
      return (
        <>
          <Title title="Résultats" meta={`${referenceCopy.project} · Analyse terminée`} action="Exporter" />
          <div className="ref-result-summary"><strong>42</strong><span>profils analysés</span><b>8 recommandés</b><i>3 à examiner</i></div>
          <Rows rows={referenceCopy.candidates} score />
        </>
      )
    case 'users':
      return (
        <>
          <Title title="Utilisateurs" meta={`${referenceCopy.workspace} · 3 membres`} action="Inviter" />
          <div className="ref-toolbar"><span><Search size={13} /> Rechercher un membre</span><span><Filter size={13} /> Tous les rôles</span></div>
          <Rows rows={referenceCopy.users} />
        </>
      )
    case 'settings':
      return (
        <>
          <Title title="Paramètres" meta="Organisation et préférences" action="Enregistrer" />
          <div className="ref-settings">
            <nav><b>Organisation</b><span>Profil</span><span>Notifications</span><span>Sécurité</span></nav>
            <form className="ref-form"><label>Nom de l’organisation<input value={referenceCopy.workspace} readOnly /></label><label>Langue<select defaultValue="Français" aria-readonly="true"><option>Français</option></select></label><label>Fuseau horaire<input value="Europe/Paris" readOnly /></label></form>
          </div>
        </>
      )
  }
}

function Title({ title, meta, action }: { title: string; meta: string; action: string }) {
  return <div className="ref-title"><div><h3>{title}</h3><p>{meta}</p></div><MiniButton primary>{action}</MiniButton></div>
}

function SectionTitle({ title, meta }: { title: string; meta: string }) {
  return <div className="ref-section-title"><strong>{title}</strong><span>{meta}</span></div>
}

function ReferenceScreenFrame({ direction, screen }: { direction: ReferenceDirection; screen: ReferenceScreen }) {
  return (
    <article className={`ref-screen ref-screen--${direction}`} aria-label={`${directionMeta[direction].name} — ${screenLabels[screen]}`}>
      <MiniHeader screen={screen} direction={direction} />
      {screen !== 'login' && <MiniNav active={screen} />}
      <main className="ref-screen-content"><ScreenContent screen={screen} /></main>
    </article>
  )
}

export function ReferenceBoard({ direction, theme = 'light', screen = 'all' }: ReferenceBoardProps) {
  const meta = directionMeta[direction]
  const visibleScreens = screen === 'all' ? screens : [screen]

  return (
    <div
      data-brain-ops=""
      className={`reference-board reference-board--${direction} reference-board--${theme} ${theme === 'dark' ? 'dark' : ''}`}
    >
      <header className="reference-board__header">
        <div className="reference-board__identity"><span>{meta.code}</span><div><p>DIRECTION DE RÉFÉRENCE</p><h1>{meta.name}</h1></div></div>
        <p className="reference-board__thesis">{meta.thesis}</p>
        {direction === 'ledger' && <span className="reference-board__recommended">RECOMMANDÉE</span>}
      </header>
      <div className={screen === 'all' ? 'reference-board__grid' : 'reference-board__focus'}>
        {visibleScreens.map((screenName) => <ReferenceScreenFrame direction={direction} screen={screenName} key={screenName} />)}
      </div>
    </div>
  )
}
