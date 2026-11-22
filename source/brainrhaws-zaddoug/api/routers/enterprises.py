"""
Router Entreprises - CRUD entreprises clientes
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import get_current_user, get_tenant_context_for_user, require_tenant_roles
from brainrh.database import get_session_direct
from brainrh.models.auth import TenantDB, UserDB, UserRole
from lib.models import Enterprise
from brainrh.paths import PROJECT_ROOT
from brainrh.services.auth_service import list_accessible_enterprise_ids
from enterprise_manager import EnterpriseManager

router = APIRouter()

# Initialiser enterprise manager (singleton)
enterprise_manager = EnterpriseManager(enterprises_folder="enterprises")


class ContactInput(BaseModel):
    """Contact d'une entreprise"""
    nom_complet: str
    poste: Optional[str] = None
    email: str
    telephone: Optional[str] = None
    canal_prefere: Optional[str] = None  # email, telephone, slack, autre
    notes: Optional[str] = None


class EnterpriseInput(BaseModel):
    """Input pour création/modification d'entreprise"""
    nom: str
    tenant_id: Optional[str] = None
    site_web: Optional[str] = None
    secteur: Optional[str] = None
    notes: Optional[str] = None
    contacts: List[ContactInput] = []


def _require_platform_admin(current_user: UserDB) -> None:
    if current_user.role != UserRole.platform_admin:
        raise HTTPException(status_code=403, detail="Action réservée au platform_admin")


@router.get("", response_model=List[Enterprise])
async def list_enterprises(
    tenant_id: Optional[str] = Query(None, description="Filtrer par tenant/client pour les vues admin"),
    current_user: UserDB = Depends(get_current_user),
):
    """
    Liste toutes les entreprises

    **Retourne:** Liste des entreprises
    """
    enterprises_data = enterprise_manager.list_enterprises()
    if current_user.role != UserRole.platform_admin:
        allowed_ids = set(
            list_accessible_enterprise_ids(current_user, required_roles={UserRole.viewer})
        )
        enterprises_data = [enterprise for enterprise in enterprises_data if enterprise.get("id") in allowed_ids]
    if tenant_id:
        enterprises_data = [
            enterprise
            for enterprise in enterprises_data
            if str(enterprise.get("tenant_id") or enterprise.get("id")) == str(tenant_id)
        ]

    # Convertir en modèles Enterprise
    enterprises = []
    for e in enterprises_data:
        enterprises.append(Enterprise(
            id=e["id"],
            nom=e["nom"],
            tenant_id=e.get("tenant_id"),
            tenant_name=e.get("tenant_name"),
            secteur=e.get("secteur", ""),
            created_at=e.get("created_at"),
            last_modified=e.get("last_modified"),
            projects_count=e.get("projects_count", 0)
        ))

    return enterprises


@router.post("", response_model=Enterprise, status_code=201)
async def create_enterprise(
    enterprise: EnterpriseInput,
    current_user: UserDB = Depends(get_current_user),
):
    """
    Crée une nouvelle entreprise

    **Body:**
    - `nom`: Nom de l'entreprise (obligatoire)
    - `site_web`: Site web (optionnel)
    - `secteur`: Secteur d'activité (optionnel)
    - `notes`: Notes (optionnel)
    - `contacts`: Liste des contacts (optionnel)

    **Retourne:** Entreprise créée
    """
    try:
        _require_platform_admin(current_user)
        tenant_id = (enterprise.tenant_id or "").strip()
        if not tenant_id:
            raise HTTPException(
                status_code=400,
                detail="tenant_id requis pour créer une entreprise",
            )
        with get_session_direct() as session:
            if session.get(TenantDB, tenant_id) is None:
                raise HTTPException(status_code=404, detail="Client/tenant introuvable")

        # Convertir les contacts en dict
        contacts_data = [contact.model_dump() for contact in enterprise.contacts]

        enterprise_data = enterprise_manager.create_enterprise(
            nom=enterprise.nom,
            tenant_id=tenant_id,
            site_web=enterprise.site_web or "",
            secteur=enterprise.secteur or "",
            notes=enterprise.notes or "",
            contacts=contacts_data
        )

        return Enterprise(
            id=enterprise_data["id"],
            nom=enterprise_data["nom"],
            tenant_id=enterprise_data.get("tenant_id"),
            tenant_name=enterprise_data.get("tenant_name"),
            site_web=enterprise_data.get("site_web", ""),
            secteur=enterprise_data.get("secteur", ""),
            notes=enterprise_data.get("notes", ""),
            contacts=enterprise_data.get("contacts", []),
            created_at=enterprise_data.get("created_at"),
            last_modified=enterprise_data.get("last_modified"),
            projects_count=0
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la création de l'entreprise: {str(e)}"
        )


@router.get("/{enterprise_id}", response_model=Enterprise)
async def get_enterprise(
    enterprise_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    """
    Récupère une entreprise par son ID
    """
    if current_user.role != UserRole.platform_admin:
        get_tenant_context_for_user(current_user, enterprise_id)

    enterprise_data = enterprise_manager.get_enterprise(enterprise_id)

    if not enterprise_data:
        raise HTTPException(
            status_code=404,
            detail=f"Entreprise {enterprise_id} introuvable"
        )

    return Enterprise(
        id=enterprise_data["id"],
        nom=enterprise_data["nom"],
        tenant_id=enterprise_data.get("tenant_id"),
        tenant_name=enterprise_data.get("tenant_name"),
        site_web=enterprise_data.get("site_web", ""),
        secteur=enterprise_data.get("secteur", ""),
        notes=enterprise_data.get("notes", ""),
        contacts=enterprise_data.get("contacts", []),
        created_at=enterprise_data.get("created_at"),
        last_modified=enterprise_data.get("last_modified"),
        projects_count=enterprise_data.get("projects_count", 0)
    )


@router.put("/{enterprise_id}", response_model=Enterprise)
async def update_enterprise(
    enterprise_id: str,
    enterprise: EnterpriseInput,
    current_user: UserDB = Depends(get_current_user),
):
    """
    Modifie une entreprise existante
    """
    try:
        existing_enterprise = enterprise_manager.get_enterprise(enterprise_id)
        if not existing_enterprise:
            raise HTTPException(
                status_code=404,
                detail=f"Entreprise {enterprise_id} introuvable"
            )

        existing_tenant_id = existing_enterprise.get("tenant_id")
        requested_tenant_id = enterprise.tenant_id if enterprise.tenant_id is not None else existing_tenant_id
        if str(requested_tenant_id or "") != str(existing_tenant_id or ""):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Le changement de tenant_id est bloqué dans cette route. "
                    "Utilisez un workflow de migration ou de transfert dédié."
                ),
            )

        if current_user.role != UserRole.platform_admin:
            tenant = get_tenant_context_for_user(current_user, enterprise_id)
            require_tenant_roles(tenant, {UserRole.enterprise_admin})

        # Convertir les contacts en dict
        contacts_data = [contact.model_dump() for contact in enterprise.contacts]

        updates = {
            "nom": enterprise.nom,
            "tenant_id": existing_tenant_id,
            "site_web": enterprise.site_web or "",
            "secteur": enterprise.secteur or "",
            "notes": enterprise.notes or "",
            "contacts": contacts_data
        }

        success = enterprise_manager.update_enterprise(enterprise_id, updates)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Entreprise {enterprise_id} introuvable"
            )

        enterprise_data = enterprise_manager.get_enterprise(enterprise_id)

        return Enterprise(
            id=enterprise_data["id"],
            nom=enterprise_data["nom"],
            tenant_id=enterprise_data.get("tenant_id"),
            tenant_name=enterprise_data.get("tenant_name"),
            site_web=enterprise_data.get("site_web", ""),
            secteur=enterprise_data.get("secteur", ""),
            notes=enterprise_data.get("notes", ""),
            contacts=enterprise_data.get("contacts", []),
            created_at=enterprise_data.get("created_at"),
            last_modified=enterprise_data.get("last_modified"),
            projects_count=enterprise_data.get("projects_count", 0)
        )

    except HTTPException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la mise à jour de l'entreprise: {str(e)}"
        )


@router.delete("/{enterprise_id}", status_code=204)
async def delete_enterprise(
    enterprise_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    """
    Supprime une entreprise et tous ses projets
    """
    try:
        _require_platform_admin(current_user)
        success = enterprise_manager.delete_enterprise(enterprise_id)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Entreprise {enterprise_id} introuvable"
            )

    except HTTPException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la suppression de l'entreprise: {str(e)}"
        )
