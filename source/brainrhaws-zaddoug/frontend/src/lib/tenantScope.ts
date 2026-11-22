import type { Enterprise, Project } from '../api/types';

export interface TenantScopeOption {
  id: string;
  tenantId: string | null;
  tenantName: string;
  enterpriseIds: string[];
  enterpriseCount: number;
}

export function buildTenantScopeOptions(enterprises: Enterprise[]): TenantScopeOption[] {
  const groups = new Map<string, TenantScopeOption>();

  for (const enterprise of enterprises) {
    const key = enterprise.tenant_id || enterprise.id;
    const existing = groups.get(key);
    if (existing) {
      existing.enterpriseIds.push(enterprise.id);
      existing.enterpriseCount += 1;
      continue;
    }

    groups.set(key, {
      id: key,
      tenantId: enterprise.tenant_id || null,
      tenantName: enterprise.tenant_name || enterprise.nom || key,
      enterpriseIds: [enterprise.id],
      enterpriseCount: 1,
    });
  }

  return Array.from(groups.values()).sort((left, right) =>
    left.tenantName.localeCompare(right.tenantName)
  );
}

export function tenantScopeLabel(option: TenantScopeOption, companiesLabel = 'companies'): string {
  if (option.enterpriseCount <= 1) {
    return option.tenantName;
  }
  return `${option.tenantName} (${option.enterpriseCount} ${companiesLabel})`;
}

export function filterEnterprisesByTenant(
  enterprises: Enterprise[],
  selectedTenantId: string
): Enterprise[] {
  if (!selectedTenantId) {
    return enterprises;
  }
  return enterprises.filter((enterprise) => (enterprise.tenant_id || enterprise.id) === selectedTenantId);
}

export function filterProjectsByTenant(
  projects: Project[],
  enterprises: Enterprise[],
  selectedTenantId: string
): Project[] {
  if (!selectedTenantId) {
    return projects;
  }

  const enterpriseIds = new Set(
    enterprises
      .filter((enterprise) => (enterprise.tenant_id || enterprise.id) === selectedTenantId)
      .map((enterprise) => enterprise.id)
  );

  return projects.filter((project) => {
    if (!project.enterprise_id) {
      return false;
    }
    return enterpriseIds.has(project.enterprise_id);
  });
}
