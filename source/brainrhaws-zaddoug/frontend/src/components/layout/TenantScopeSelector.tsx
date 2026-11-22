import { useEffect, useMemo, useState } from 'react';

import { adminUsersApi } from '../../api/adminUsers';
import type { AdminClient } from '../../api/types';
import { useAuth } from '../../features/auth/context/AuthContext';
import { useAppStore } from '../../stores/useAppStore';
import { ClientWorkspacePicker } from './ClientWorkspacePicker';

interface TenantScopeSelectorProps {
  collapsed?: boolean;
  compact?: boolean;
  onNavigate?: () => void;
}

export const TenantScopeSelector: React.FC<TenantScopeSelectorProps> = ({ collapsed, compact, onNavigate }) => {
  const { user } = useAuth();
  const selectedTenantId = useAppStore((state) => state.selectedTenantId);
  const setSelectedTenantId = useAppStore((state) => state.setSelectedTenantId);
  const catalogRevision = useAppStore((state) => state.clientCatalogRevision);
  const retryCatalog = useAppStore((state) => state.invalidateClientCatalog);
  const [clients, setClients] = useState<AdminClient[]>([]);
  const [catalogReady, setCatalogReady] = useState(false);
  const [catalogFailed, setCatalogFailed] = useState(false);
  const [loadedCatalogKey, setLoadedCatalogKey] = useState<string | null>(null);

  const isPlatformAdmin = user?.role === 'platform_admin';
  const canScopeByTenant = isPlatformAdmin;
  const userId = user?.id;
  const catalogKey = `${userId || ''}:${catalogRevision}`;
  const catalogCurrent = catalogReady && loadedCatalogKey === catalogKey;

  useEffect(() => {
    setCatalogReady(false);
    setCatalogFailed(false);
    if (!canScopeByTenant) {
      setClients([]);
      return;
    }

    setClients([]);
    let active = true;
    const load = async () => {
      try {
        const data = await adminUsersApi.getClients();
        if (!active) {
          return;
        }
        setClients(data);
        setLoadedCatalogKey(catalogKey);
        setCatalogReady(true);
      } catch {
        if (active) {
          setClients([]);
          setCatalogFailed(true);
        }
      }
    };

    void load();
    return () => {
      active = false;
    };
  }, [canScopeByTenant, catalogKey]);

  const options = useMemo(
    () => [...clients].sort((left, right) => left.name.localeCompare(right.name)),
    [clients]
  );

  useEffect(() => {
    // Do not erase the saved platform view while its catalogue is still loading.
    if (!isPlatformAdmin || !catalogCurrent) return;
    if (!options.length) {
      if (selectedTenantId) {
        setSelectedTenantId('');
      }
      return;
    }

    const selectionStillValid = !selectedTenantId || options.some((option) => option.id === selectedTenantId);
    if (!selectionStillValid) {
      setSelectedTenantId('');
      return;
    }

  }, [isPlatformAdmin, catalogCurrent, options, selectedTenantId, setSelectedTenantId]);

  if (!canScopeByTenant) {
    return null;
  }

  return <ClientWorkspacePicker clients={options} selectedTenantId={selectedTenantId}
    status={catalogFailed ? 'error' : catalogCurrent ? 'ready' : 'loading'}
    collapsed={collapsed} compact={compact} onSelect={setSelectedTenantId} onRetry={retryCatalog} onNavigate={onNavigate} />;
};
