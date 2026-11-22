import { create } from 'zustand';

interface AppState {
  sidebarCollapsed: boolean;
  selectedTenantId: string;
  clientCatalogRevision: number;
  enterpriseCatalogRevision: number;
  invalidateClientCatalog: () => void;
  invalidateEnterpriseCatalog: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setSelectedTenantId: (tenantId: string) => void;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppState>((set) => {
  // Load sidebar state from localStorage
  const storedCollapsed = localStorage.getItem('sidebar-collapsed');
  const storedTenantId = localStorage.getItem('selected-tenant-id') || '';
  const isMobileViewport = window.matchMedia('(max-width: 1023px)').matches;
  const initialCollapsed = isMobileViewport ? true : storedCollapsed ? JSON.parse(storedCollapsed) : false;

  return {
    sidebarCollapsed: initialCollapsed,
    selectedTenantId: storedTenantId,
    clientCatalogRevision: 0,
    enterpriseCatalogRevision: 0,
    invalidateClientCatalog: () => set((state) => ({
      clientCatalogRevision: state.clientCatalogRevision + 1,
    })),
    invalidateEnterpriseCatalog: () => set((state) => ({
      enterpriseCatalogRevision: state.enterpriseCatalogRevision + 1,
    })),
    setSidebarCollapsed: (collapsed) => {
      set({ sidebarCollapsed: collapsed });
      localStorage.setItem('sidebar-collapsed', JSON.stringify(collapsed));
    },
    setSelectedTenantId: (tenantId) => {
      set({ selectedTenantId: tenantId });
      localStorage.setItem('selected-tenant-id', tenantId);
    },
    toggleSidebar: () => {
      set((state) => {
        const newCollapsed = !state.sidebarCollapsed;
        localStorage.setItem('sidebar-collapsed', JSON.stringify(newCollapsed));
        return { sidebarCollapsed: newCollapsed };
      });
    },
  };
});
