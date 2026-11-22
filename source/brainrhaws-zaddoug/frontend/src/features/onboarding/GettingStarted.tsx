import { ArrowRight, Building2, Check, Circle, FolderOpen } from 'lucide-react';
import { Button } from '../../components/ui/button';
import type { TranslationKey } from '../../i18n/messages';
import { useI18n } from '../../i18n/useI18n';

type GettingStartedProps = {
  companyCount: number;
  projectCount: number;
  role: string;
  onNavigate: (path: string) => void;
};

type JourneyStepProps = {
  complete: boolean;
  current: boolean;
  label: string;
  detail: string;
  icon: typeof Building2;
};

function JourneyStep({ complete, current, label, detail, icon: Icon }: JourneyStepProps) {
  return (
    <li className="relative flex min-w-0 gap-3 sm:gap-4">
      <span
        className={`relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full border ${complete ? 'border-[color:var(--brain-ops-success)] bg-[var(--brain-ops-success)] text-white' : current ? 'border-[color:var(--brain-ops-accent)] bg-[var(--brain-ops-accent-soft)] text-[var(--brain-ops-accent)]' : 'border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] text-[var(--brain-ops-text-muted)]'}`}
        aria-hidden="true"
      >
        {complete ? <Check className="size-4" /> : current ? <Icon className="size-4" /> : <Circle className="size-3" />}
      </span>
      <span className="min-w-0 pt-0.5">
        <span className="block text-sm font-semibold text-[var(--brain-ops-text)]">{label}</span>
        <span className="mt-1 block text-sm leading-5 text-[var(--brain-ops-text-muted)]">{detail}</span>
      </span>
    </li>
  );
}

export function GettingStarted({ companyCount, projectCount, role, onNavigate }: GettingStartedProps) {
  const { t } = useI18n();
  const hasCompany = companyCount > 0;
  const hasProject = projectCount > 0;
  const canProvisionCompany = role === 'platform_admin';
  const canCreateProject = ['platform_admin', 'client_admin', 'enterprise_admin'].includes(role);
  const completed = Number(hasCompany) + Number(hasProject);
  const nextPath = !hasCompany ? '/enterprises' : '/projects';
  const actionKey: TranslationKey | null = !hasCompany
    ? canProvisionCompany ? 'onboarding.action.companies' : null
    : canCreateProject ? 'onboarding.action.projects' : 'onboarding.action.viewProjects';
  const companyTitleKey: TranslationKey = !hasCompany && !canProvisionCompany
    ? 'onboarding.company.waitingTitle'
    : 'onboarding.company.title';
  const companyDetailKey: TranslationKey = hasCompany
    ? 'onboarding.company.done'
    : canProvisionCompany ? 'onboarding.company.todo' : 'onboarding.company.waiting';
  const projectTitleKey: TranslationKey = !hasProject && hasCompany && !canCreateProject
    ? 'onboarding.project.restrictedTitle'
    : 'onboarding.project.title';
  const projectDetailKey: TranslationKey = hasProject
    ? 'onboarding.project.done'
    : hasCompany && !canCreateProject ? 'onboarding.project.restricted' : 'onboarding.project.todo';

  return (
    <section
      aria-labelledby="getting-started-title"
      className="brain-getting-started relative overflow-hidden border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)]"
    >
      <div className="grid min-w-0 gap-6 p-5 sm:p-6 lg:grid-cols-[minmax(0,0.75fr)_minmax(20rem,1.25fr)] lg:gap-10 lg:p-8">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-[var(--brain-ops-accent)] [font-family:var(--brain-ops-font-command)]">
            {t('onboarding.eyebrow')}
          </p>
          <h2 id="getting-started-title" className="mt-3 text-xl font-semibold leading-tight tracking-[-0.02em] sm:text-2xl">
            {t('onboarding.title')}
          </h2>
          <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--brain-ops-text-muted)]">
            {t('onboarding.description')}
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            {actionKey ? (
              <Button type="button" onClick={() => onNavigate(nextPath)}>
                {t(actionKey)}
                <ArrowRight className="size-4" aria-hidden="true" />
              </Button>
            ) : null}
            <span className="text-xs text-[var(--brain-ops-text-muted)] [font-family:var(--brain-ops-font-command)]">
              {t('onboarding.progress').replace('{{completed}}', String(completed)).replace('{{total}}', '2')}
            </span>
          </div>
        </div>

        <ol className="relative grid gap-5 before:absolute before:bottom-5 before:left-[0.9375rem] before:top-5 before:w-px before:bg-[var(--brain-ops-border)]">
          <JourneyStep complete={hasCompany} current={!hasCompany} label={t(companyTitleKey)} detail={t(companyDetailKey)} icon={Building2} />
          <JourneyStep complete={hasProject} current={hasCompany && !hasProject} label={t(projectTitleKey)} detail={t(projectDetailKey)} icon={FolderOpen} />
        </ol>
      </div>
    </section>
  );
}
