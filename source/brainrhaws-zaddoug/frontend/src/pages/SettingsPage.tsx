import { Link } from 'react-router-dom';
import { BrainCircuit, ChevronRight, Coins, FileText, Plug, Users } from 'lucide-react';
import { useAuth } from '../features/auth/context/AuthContext';
import {
  OperationalList,
  OperationalListItem,
  PageFrame,
  PageHeader,
  Section,
} from '../components/operations';
import { useI18n } from '../i18n/useI18n';
import type { TranslationKey } from '../i18n/messages';

interface SettingsModule {
  titleKey: TranslationKey;
  descriptionKey: TranslationKey;
  labelKey: TranslationKey;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  tourTarget?: string;
}

const baseModules: SettingsModule[] = [
  {
    titleKey: 'settings.section.template.title',
    descriptionKey: 'settings.section.template.description',
    labelKey: 'settings.section.template.label',
    href: '/settings/client-template',
    icon: FileText,
    tourTarget: 'settings-client-template',
  },
  {
    titleKey: 'settings.section.integrations.title',
    descriptionKey: 'settings.section.integrations.description',
    labelKey: 'settings.section.integrations.label',
    href: '/settings/integrations',
    icon: Plug,
    tourTarget: 'settings-integrations',
  },
];

export const SettingsPage: React.FC = () => {
  const { t } = useI18n();
  const { user } = useAuth();
  const canManageUsers = Boolean(user?.can_manage_users);
  const isPlatformAdmin = user?.role === 'platform_admin';

  const adminModules: SettingsModule[] = [];
  if (canManageUsers) {
    adminModules.push({
      titleKey: 'settings.section.users.title',
      descriptionKey: 'settings.section.users.description',
      labelKey: 'settings.section.users.label',
      href: '/settings/admin/users',
      icon: Users,
    });
  }
  if (isPlatformAdmin) {
    adminModules.push({
      titleKey: 'settings.section.llm.title',
      descriptionKey: 'settings.section.llm.description',
      labelKey: 'settings.section.llm.label',
      href: '/settings/admin/llm',
      icon: BrainCircuit,
    });
    adminModules.push({
      titleKey: 'settings.section.crustdata.title',
      descriptionKey: 'settings.section.crustdata.description',
      labelKey: 'settings.section.crustdata.label',
      href: '/settings/admin/crustdata',
      icon: Coins,
    });
  }

  const modules = [...adminModules, ...baseModules];

  return (
    <PageFrame width="content">
      <PageHeader
        eyebrow={t('settings.badge')}
        title={t('settings.title')}
        description={t('settings.description')}
      />

      <Section data-tour="settings-modules" title={t('settings.modules')} divided={false}>
        <OperationalList ariaLabel={t('settings.nav.aria')}>
          {modules.map((module) => {
            const Icon = module.icon;
            return (
              <OperationalListItem
                key={module.href}
                data-tour={module.tourTarget}
                leading={
                  <span className="flex size-10 items-center justify-center rounded-[var(--brain-ops-radius-structural)] border border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface-muted)]">
                    <Icon className="size-5" />
                  </span>
                }
                primary={
                  <Link
                    to={module.href}
                    className="inline-flex min-h-11 items-center gap-2 font-medium text-[var(--brain-ops-text)] underline-offset-4 hover:underline"
                  >
                    {t(module.titleKey)}
                    <ChevronRight className="size-4 text-[var(--brain-ops-text-muted)]" aria-hidden="true" />
                  </Link>
                }
                secondary={t(module.descriptionKey)}
                metadata={t(module.labelKey)}
                monospaceMetadata
              />
            );
          })}
        </OperationalList>
      </Section>
    </PageFrame>
  );
};
