import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { CircleHelp } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { useAuth } from '../auth/context/AuthContext';
import { canViewSettingsPath } from '../auth/settingsAccess';
import { useAppStore } from '../../stores/useAppStore';
import { useI18n } from '../../i18n/useI18n';
import { GuideOverlay } from './GuideOverlay';
import { guideStorageKey, readGuideProgress, saveGuideProgress, type GuideProgress } from './progress';
import { getPageTour, type TourDefinition } from './tours';

const hasCompetingSurface = () => Array.from(document.querySelectorAll<HTMLElement>(
  '[role="dialog"]:not([data-page-guide]), [role="alertdialog"], dialog[open], [role="menu"], [role="listbox"]',
)).some((node) => node.getClientRects().length > 0 && node.getAttribute('aria-hidden') !== 'true');

function PageGuideSession({ tour, storageKey }: { tour: TourDefinition; storageKey: string }) {
  const { t } = useI18n();
  const [initialProgress] = useState(() => readGuideProgress(storageKey, tour.steps.length).progress);
  const [step, setStep] = useState(initialProgress?.status === 'paused' ? initialProgress.step : 0);
  const [open, setOpen] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const launcherRef = useRef<HTMLButtonElement>(null);

  const remember = (progress: GuideProgress) => {
    saveGuideProgress(storageKey, progress);
  };

  const moveTo = (index: number) => {
    setStep(index);
    remember({ status: 'paused', step: index });
  };
  const closeGuide = (restoreFocus = true) => {
    setOpen(false);
    if (restoreFocus) requestAnimationFrame(() => launcherRef.current?.focus({ preventScroll: true }));
  };

  useEffect(() => {
    const inspect = () => {
      const nextBlocked = hasCompetingSurface();
      setBlocked((current) => current === nextBlocked ? current : nextBlocked);
      if (nextBlocked) setOpen(false);
    };
    const observer = new MutationObserver(inspect);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['role', 'open', 'hidden', 'aria-hidden', 'class', 'style'],
    });
    inspect();
    return () => observer.disconnect();
  }, []);

  if (blocked) return null;

  return (
    <div data-brain-ops="" data-page-guide-entry="" className="relative z-30 mx-auto mb-4 flex w-full max-w-7xl flex-col items-end text-[var(--brain-ops-text)]">
      <Button
        ref={launcherRef}
        type="button"
        data-page-guide-launcher=""
        variant={open ? 'secondary' : 'outline'}
        className="brain-guide-launcher min-h-11 rounded-full border-[color:var(--brain-ops-border)] bg-[var(--brain-ops-surface)] px-4 shadow-sm"
        aria-expanded={open}
        aria-controls="page-help-panel"
        onClick={() => setOpen((value) => !value)}
      >
        <CircleHelp className="size-4 text-[var(--brain-ops-text)]" aria-hidden="true" />
        {t('guide.help')}
      </Button>

      {open ? (
        <GuideOverlay
          tour={tour}
          step={step}
          onStep={moveTo}
          onClose={closeGuide}
          onFinish={() => {
            remember({ status: 'completed', step });
            setStep(0);
            closeGuide(true);
          }}
        />
      ) : null}
    </div>
  );
}

export function PageGuide() {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);
  if (!user || !canViewSettingsPath(user, pathname)) return null;
  const tour = getPageTour(pathname, user.role);
  if (!tour) return null;
  if (tour.id === 'admin-users' && !user.can_manage_users) return null;
  const scope = user.role === 'platform_admin' ? selectedTenantId || 'all-clients' : user.tenant_id || 'unassigned';
  const storageKey = guideStorageKey(user.id, user.role, scope, tour.id);
  return <PageGuideSession key={`${storageKey}:${pathname}`} tour={tour} storageKey={storageKey} />;
}
