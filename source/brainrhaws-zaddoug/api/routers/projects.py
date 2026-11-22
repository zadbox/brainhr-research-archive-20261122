"""
Router Projets - CRUD projets et historique matchings
"""

from typing import List, Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlmodel import Session

from lib.models import Project
from brainrh.paths import PROJECT_ROOT
from unified_project_manager import UnifiedProjectManager
from api.dependencies import (
    RBACChecker,
    get_current_user,
    get_project_tenant_context,
    get_project_writer_context,
    get_tenant_context_for_user,
    require_tenant_roles,
    resolve_project_or_404,
)
from brainrh.models.auth import UserDB, UserRole
from brainrh.models.enterprise import EnterpriseDB
from brainrh.database import get_session_dependency
from brainrh.services.application_service import ApplicationService
from brainrh.services.auth_service import (
    TenantContext,
    list_access_grants_for_user,
    list_accessible_enterprise_ids,
    list_direct_project_grant_ids,
    tenant_has_any_role,
)

router = APIRouter()

# Initialiser unified project manager (singleton)
project_manager = UnifiedProjectManager(enterprises_folder="enterprises")


class ProjectInput(BaseModel):
    """Input pour création/modification de projet"""
    nom: str
    description: Optional[str] = ""
    enterprise_id: Optional[str] = None
    service_demandeur: Optional[str] = None
    responsable_offre: Optional[str] = None
    contact_responsable: Optional[str] = None
    notes: Optional[str] = None
    status: str = "actif"


class ProjectCandidateSummary(BaseModel):
    count: int
    ready: bool
    enterprise_name: Optional[str] = None


@router.get("", response_model=List[Project])
async def list_projects(
    enterprise_id: Optional[str] = Query(None, description="Filtrer par entreprise"),
    tenant_id: Optional[str] = Query(None, description="Filtrer par tenant/client pour les vues admin"),
    status: Optional[str] = Query(None, description="Filtrer par status (actif/archive)"),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Liste tous les projets

    **Filtres optionnels:**
    - `enterprise_id`: Filtrer par entreprise
    - `status`: Filtrer par status (actif/archive)

    **Retourne:** Liste des projets
    """
    from brainrh.services.enterprise_service import EnterpriseService

    tenant_enterprise_ids = None
    if current_user.role == UserRole.platform_admin:
        if tenant_id and not enterprise_id:
            tenant_enterprise_ids = {
                enterprise["id"]
                for enterprise in EnterpriseService.list_enterprises_by_tenant(tenant_id)
            }
            projects_data = project_manager.list_projects(
                enterprise_ids=sorted(tenant_enterprise_ids),
                status=status,
            )
        else:
            projects_data = project_manager.list_projects(enterprise_id=enterprise_id, status=status)
    elif enterprise_id:
        get_tenant_context_for_user(current_user, enterprise_id)
        projects_data = project_manager.list_projects(enterprise_id=enterprise_id, status=status)
    else:
        projects_data = []
        seen_ids: set[str] = set()
        access_grants = list_access_grants_for_user(current_user)
        allowed_enterprise_ids = list_accessible_enterprise_ids(
            current_user,
            required_roles={UserRole.viewer},
            access_grants=access_grants,
        )
        enterprise_projects = project_manager.list_projects(
            enterprise_ids=allowed_enterprise_ids,
            status=status,
        )
        projects_by_enterprise = {
            allowed_enterprise_id: []
            for allowed_enterprise_id in allowed_enterprise_ids
        }
        for project_data in enterprise_projects:
            resolved_enterprise_id = project_data.get("enterprise_id")
            if resolved_enterprise_id in projects_by_enterprise:
                projects_by_enterprise[resolved_enterprise_id].append(project_data)
        for allowed_enterprise_id in allowed_enterprise_ids:
            for project_data in projects_by_enterprise[allowed_enterprise_id]:
                resolved_project_id = project_data.get("id")
                if resolved_project_id in seen_ids:
                    continue
                seen_ids.add(resolved_project_id)
                projects_data.append(project_data)
        direct_project_ids = list_direct_project_grant_ids(
            current_user,
            required_roles={UserRole.viewer},
            access_grants=access_grants,
        )
        for direct_project_id in direct_project_ids:
            if direct_project_id in seen_ids:
                continue
            project_data = project_manager.get_project(direct_project_id)
            if not project_data:
                continue
            if status and project_data.get("status") != status:
                continue
            seen_ids.add(direct_project_id)
            projects_data.append(project_data)

    if tenant_id:
        if tenant_enterprise_ids is None:
            tenant_enterprise_ids = {
                enterprise["id"]
                for enterprise in EnterpriseService.list_enterprises_by_tenant(tenant_id)
            }
        projects_data = [
            project_data
            for project_data in projects_data
            if project_data.get("enterprise_id") in tenant_enterprise_ids
        ]

    # Convertir en modèles Project
    projects = []
    for p in projects_data:
        projects.append(Project(
            id=p["id"],
            nom=p["nom"],
            enterprise_id=p.get("enterprise_id"),
            service_demandeur=p.get("service_demandeur"),
            responsable_offre=p.get("responsable_offre"),
            contact_responsable=p.get("contact_responsable"),
            notes=p.get("notes"),
            created_at=p["created_at"],
            last_modified=p["last_modified"],
            status=p["status"]
        ))

    return projects


@router.get("/by-enterprise/current", response_model=List[Project])
async def list_projects_by_enterprise(
    status: Optional[str] = Query(None, description="Filtrer par status (actif/archive)"),
    tenant: TenantContext = Depends(RBACChecker("projects:read"))
):
    """
    Route de listing multi-tenant protégée.
    Exige un `enterprise_id` (header X-Enterprise-ID ou param) et un membership actif.
    Renvoie uniquement les projets de l'entreprise ciblée.
    """
    # Filtrer strictement par l'entreprise validée dès la requête DB/FS
    projects_data = project_manager.list_projects(
        enterprise_id=tenant.enterprise_id,
        status=status
    )

    projects = []
    for p in projects_data:
        projects.append(Project(
            id=p["id"],
            nom=p["nom"],
            enterprise_id=p.get("enterprise_id"),
            service_demandeur=p.get("service_demandeur"),
            responsable_offre=p.get("responsable_offre"),
            contact_responsable=p.get("contact_responsable"),
            notes=p.get("notes"),
            created_at=p["created_at"],
            last_modified=p["last_modified"],
            status=p["status"]
        ))

    return projects


@router.get("/{project_id}/candidate-summary", response_model=ProjectCandidateSummary)
async def get_project_candidate_summary(
    project_id: str,
    tenant: TenantContext = Depends(get_project_tenant_context),
    session: Session = Depends(get_session_dependency),
):
    """Return the project overview data without loading candidate JSON files."""
    summary = ApplicationService.get_project_candidate_summary(session, project_id)
    enterprise = session.get(EnterpriseDB, tenant.enterprise_id) if tenant.enterprise_id else None
    return ProjectCandidateSummary(
        count=summary["count"],
        ready=summary["ready"],
        enterprise_name=enterprise.nom if enterprise else None,
    )


@router.post("", response_model=Project, status_code=201)
async def create_project(
    project: ProjectInput,
    current_user: UserDB = Depends(get_current_user),
):
    """
    Crée un nouveau projet

    **Body:**
    - `nom`: Nom du projet
    - `description`: Description du projet (optionnel)
    - `enterprise_id`: ID de l'entreprise (optionnel)
    - `status`: Status (actif/archive, default: actif)

    **Retourne:** Projet créé
    """
    try:
        # enterprise_id est requis dans la nouvelle structure
        if not project.enterprise_id:
            raise HTTPException(
                status_code=400,
                detail="enterprise_id est requis"
            )

        tenant = get_tenant_context_for_user(current_user, project.enterprise_id)
        require_tenant_roles(tenant, {UserRole.enterprise_admin})

        projet_data = project_manager.create_project(
            nom=project.nom,
            enterprise_id=project.enterprise_id,
            description=project.description,
            service_demandeur=project.service_demandeur,
            responsable_offre=project.responsable_offre,
            contact_responsable=project.contact_responsable,
            notes=project.notes
        )

        return Project(
            id=projet_data["id"],
            nom=projet_data["nom"],
            enterprise_id=projet_data["enterprise_id"],
            service_demandeur=projet_data.get("service_demandeur"),
            responsable_offre=projet_data.get("responsable_offre"),
            contact_responsable=projet_data.get("contact_responsable"),
            notes=projet_data.get("notes"),
            created_at=projet_data["created_at"],
            last_modified=projet_data["last_modified"],
            status=projet_data["status"]
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la création du projet: {str(e)}"
        )


@router.get("/{project_id}", response_model=Project)
async def get_project(
    project_id: str,
    tenant: TenantContext = Depends(get_project_tenant_context),
):
    """
    Récupère un projet par son ID
    """
    projet_data = resolve_project_or_404(project_id)

    return Project(
        id=projet_data["id"],
        nom=projet_data["nom"],
        enterprise_id=projet_data.get("enterprise_id"),
        service_demandeur=projet_data.get("service_demandeur"),
        responsable_offre=projet_data.get("responsable_offre"),
        contact_responsable=projet_data.get("contact_responsable"),
        notes=projet_data.get("notes"),
        created_at=projet_data["created_at"],
        last_modified=projet_data["last_modified"],
        status=projet_data["status"]
    )


@router.put("/{project_id}", response_model=Project)
async def update_project(
    project_id: str,
    project: ProjectInput,
    tenant: TenantContext = Depends(get_project_writer_context),
):
    """
    Modifie un projet existant
    """
    try:
        if not tenant_has_any_role(tenant, {UserRole.enterprise_admin}):
            raise HTTPException(status_code=403, detail="Seul un enterprise_admin peut modifier un projet")

        existing_project = resolve_project_or_404(project_id)
        existing_enterprise_id = existing_project.get("enterprise_id")
        requested_enterprise_id = project.enterprise_id if project.enterprise_id is not None else existing_enterprise_id
        if str(requested_enterprise_id or "") != str(existing_enterprise_id or ""):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Le changement de enterprise_id est bloqué dans cette route. "
                    "Utilisez un workflow de migration ou de transfert dédié."
                ),
            )

        updates = {
            "nom": project.nom,
            "status": project.status,
            "description": project.description or "",
            "enterprise_id": existing_enterprise_id,
            "service_demandeur": project.service_demandeur or "",
            "responsable_offre": project.responsable_offre or "",
            "contact_responsable": project.contact_responsable or "",
            "notes": project.notes or ""
        }

        project_manager.update_project(project_id, updates)

        projet_data = project_manager.get_project(project_id)

        return Project(
            id=projet_data["id"],
            nom=projet_data["nom"],
            enterprise_id=projet_data.get("enterprise_id"),
            service_demandeur=projet_data.get("service_demandeur"),
            responsable_offre=projet_data.get("responsable_offre"),
            contact_responsable=projet_data.get("contact_responsable"),
            notes=projet_data.get("notes"),
            created_at=projet_data["created_at"],
            last_modified=projet_data["last_modified"],
            status=projet_data["status"]
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la mise à jour du projet: {str(e)}"
        )


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    tenant: TenantContext = Depends(get_project_writer_context),
):
    """
    Archive un projet (soft delete)
    """
    try:
        if not tenant_has_any_role(tenant, {UserRole.enterprise_admin}):
            raise HTTPException(status_code=403, detail="Seul un enterprise_admin peut supprimer un projet")
        project_manager.delete_project(project_id)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la suppression du projet: {str(e)}"
        )


@router.get("/{project_id}/matchings/latest")
async def get_latest_matching(
    project_id: str,
    tenant: TenantContext = Depends(get_project_tenant_context),
):
    """
    Récupère le timestamp du dernier matching pour un projet

    **Retourne:**
    ```json
    {
      "timestamp": "2025-10-12_06-49-01"
    }
    ```
    """
    resolve_project_or_404(project_id)

    try:
        matchings = project_manager.list_matchings(project_id, tenant.enterprise_id)
        if not matchings:
            raise HTTPException(
                status_code=404,
                detail=f"Aucun matching trouvé pour le projet {project_id}"
            )

        return {
            "timestamp": matchings[0]["timestamp"]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération du dernier matching: {str(e)}"
        )


@router.get("/{project_id}/history")
async def get_project_history(
    project_id: str,
    limit: int = Query(default=50, ge=1, le=200, description="Nombre max de résultats"),
    offset: int = Query(default=0, ge=0, description="Offset pour pagination"),
    tenant: TenantContext = Depends(get_project_tenant_context),
):
    """
    Récupère l'historique des matchings d'un projet

    **Paramètres:**
    - `limit`: Nombre max de résultats (default: 50)
    - `offset`: Offset pour pagination (default: 0)

    **Retourne:**
    ```json
    {
      "total": 150,
      "items": [
        {
          "matching_id": "2025-10-11_14-30-00",
          "timestamp": "2025-10-11T14:30:00Z",
          "candidats_count": 32
        }
      ]
    }
    ```
    """
    resolve_project_or_404(project_id)

    try:
        matchings = project_manager.list_matchings(project_id, tenant.enterprise_id)

        # Pagination
        total = len(matchings)
        items = matchings[offset:offset + limit]

        return {
            "total": total,
            "items": [
                {
                    "matching_id": m["timestamp"],
                    "timestamp": m["timestamp"],
                    "candidats_count": m["candidats_count"]
                }
                for m in items
            ]
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération de l'historique: {str(e)}"
        )
