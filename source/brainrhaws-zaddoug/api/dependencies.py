"""
FastAPI dependencies.

This module keeps the existing utility dependencies and adds authentication
helpers without changing the public imports used by older routers.
"""

import os
from pathlib import Path
from typing import Dict, Optional, Tuple

from dotenv import load_dotenv
from fastapi import HTTPException, Request, status, Depends
from openai import OpenAI

from brainrh import paths as brainrh_paths
from brainrh.models.auth import UserDB, MembershipDB, UserRole
from brainrh.services.auth_service import (
    get_current_user_from_token,
    get_membership_for_user,
    list_accessible_enterprise_ids,
    resolve_access_context_for_user,
    TenantContext,
    tenant_has_any_role,
)

load_dotenv(brainrh_paths.PROJECT_ROOT / ".env")


def get_openai_client() -> OpenAI:
    """
    Retourne un client OpenAI configuré.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY non trouvée dans les variables d'environnement")

    return OpenAI(api_key=api_key)


def get_projects_dir() -> Path:
    """
    Retourne le dossier racine des projets.
    """
    return brainrh_paths.PROJECT_ROOT / "projects"


def get_project_dir(project_id: str) -> Path:
    """
    Retourne le dossier d'un projet spécifique.
    """
    return get_projects_dir() / project_id


def get_cvs_parsed_dir(project_id: str) -> Path:
    """
    Retourne le dossier des CVs parsés d'un projet.
    """
    return get_project_dir(project_id) / "cvs_parsed"


def get_offres_dir(project_id: str) -> Path:
    """
    Retourne le dossier des offres d'un projet.
    """
    return get_project_dir(project_id) / "offres"


def get_historique_dir(project_id: str) -> Path:
    """
    Retourne le dossier de l'historique d'un projet.
    """
    return get_project_dir(project_id) / "historique"


def get_current_user(request: Request) -> UserDB:
    token = request.cookies.get("access_token")
    if not token:
        authorization = request.headers.get("Authorization")
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ")[1]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return get_current_user_from_token(token)


# ---------------------------------------------------------------------------
# Membership helpers — non obligatoires sur les routes existantes
# ---------------------------------------------------------------------------

def get_current_membership(
    request: Request,
    enterprise_id: Optional[str] = None,
) -> Optional[MembershipDB]:
    """Retourne le membership actif de l'utilisateur courant pour une enterprise.

    Retourne None si l'utilisateur n'est pas authentifié ou n'a pas de membership.
    N'est pas obligatoire sur les routes existantes.
    enterprise_id peut être passé via header X-Enterprise-ID ou paramètre explicite.
    """
    try:
        user = get_current_user(request)
    except HTTPException:
        return None

    eid = enterprise_id or request.headers.get("X-Enterprise-ID")
    if not eid:
        return None

    return get_membership_for_user(user.id, eid)


def get_tenant_context(
    request: Request,
    enterprise_id: Optional[str] = None,
) -> TenantContext:
    """Retourne le TenantContext de l'utilisateur courant.

    Lève une 403 si l'utilisateur n'a pas de membership actif pour l'enterprise demandée.
    À utiliser uniquement sur des routes qui nécessitent un contexte enterprise explicite.
    """
    user = get_current_user(request)
    eid = enterprise_id or request.headers.get("X-Enterprise-ID")

    if not eid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="enterprise_id requis (header X-Enterprise-ID ou paramètre).",
        )

    return resolve_access_context_for_user(user, enterprise_id=eid)


def get_tenant_context_for_user(user: UserDB, enterprise_id: str) -> TenantContext:
    """Construit un TenantContext pour un user donné sur une enterprise donnée."""
    if not enterprise_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="enterprise_id requis.",
        )

    return resolve_access_context_for_user(user, enterprise_id=enterprise_id)


def require_tenant_roles(tenant: TenantContext, allowed_roles: set[UserRole]) -> TenantContext:
    """Valide qu'un TenantContext porte un rôle autorisé."""
    if tenant_has_any_role(tenant, allowed_roles):
        return tenant

    allowed = ", ".join(role.value for role in sorted(allowed_roles, key=lambda role: role.value))
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Rôle {tenant.role.value} insuffisant. Rôles autorisés: {allowed}.",
    )


def resolve_project_or_404(project_id: str) -> dict:
    """Résout un projet depuis la source canonique DB/JSON ou lève 404."""
    from brainrh.services.project_service import ProjectService

    project = ProjectService.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Projet {project_id} introuvable",
        )

    return project


def require_project_access(
    project_id: str,
    tenant: UserDB,
    allowed_roles: set[UserRole],
) -> TenantContext:
    """Valide l'accès d'un user au tenant réel du projet."""
    tenant_context = resolve_access_context_for_user(tenant, project_id=project_id)
    return require_tenant_roles(tenant_context, allowed_roles)


def require_project_reader(project_id: str, tenant: UserDB) -> TenantContext:
    """Autorise la lecture projet pour tout rôle au moins viewer."""
    return require_project_access(
        project_id,
        tenant,
        {UserRole.viewer},
    )


def require_project_writer(project_id: str, tenant: UserDB) -> TenantContext:
    """Autorise les actions recrutement projet pour tout rôle au moins recruiter."""
    return require_project_access(
        project_id,
        tenant,
        {UserRole.recruiter},
    )


def _project_access_error_payload(exc: HTTPException) -> Dict[str, str]:
    if isinstance(exc.detail, dict):
        code = str(exc.detail.get("code") or "PROJECT_ACCESS_ERROR")
        message = str(exc.detail.get("message") or code)
        return {"code": code, "message": message}
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        code = "AUTH_REQUIRED"
    elif exc.status_code == status.HTTP_404_NOT_FOUND:
        code = "PROJECT_NOT_FOUND"
    elif exc.status_code == status.HTTP_403_FORBIDDEN:
        code = "PROJECT_ACCESS_DENIED"
    elif exc.status_code == status.HTTP_400_BAD_REQUEST:
        code = "PROJECT_ACCESS_INVALID"
    else:
        code = "PROJECT_ACCESS_ERROR"

    return {
        "code": code,
        "message": str(exc.detail),
    }


def require_project_access_sse(
    project_id: str,
    tenant: UserDB,
    allowed_roles: set[UserRole],
) -> Tuple[Optional[TenantContext], Optional[Dict[str, str]]]:
    """Version SSE: retourne un payload d'erreur au lieu de lever HTTPException."""
    try:
        return require_project_access(project_id, tenant, allowed_roles), None
    except HTTPException as exc:
        return None, _project_access_error_payload(exc)


def require_project_access_sse_for_request(
    request: Request,
    project_id: str,
    allowed_roles: set[UserRole],
) -> Tuple[Optional[TenantContext], Optional[Dict[str, str]]]:
    """Version SSE complète: authentifie puis autorise sans lever d'exception HTTP."""
    try:
        user = get_current_user(request)
    except HTTPException as exc:
        return None, _project_access_error_payload(exc)

    return require_project_access_sse(project_id, user, allowed_roles)


def get_project_tenant_context(
    request: Request,
    project_id: str,
) -> TenantContext:
    """Résout le contexte tenant d'un projet depuis son enterprise_id."""
    user = get_current_user(request)
    return require_project_reader(project_id, user)


def get_project_writer_context(
    request: Request,
    project_id: str,
) -> TenantContext:
    """Contexte projet autorisant les écritures RH standards."""
    user = get_current_user(request)
    return require_project_writer(project_id, user)


def get_matching_id_tenant_context(
    request: Request,
    matching_id: str,
) -> TenantContext:
    """Résout le contexte tenant depuis un matching_id legacy project/timestamp."""
    parts = matching_id.split("/")
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format matching_id invalide. Attendu: {project_id}/{timestamp}",
        )

    project_id, _ = parts
    return get_project_tenant_context(request, project_id)


# ---------------------------------------------------------------------------
# RBAC Checker (BMT-NEXT-009)
# ---------------------------------------------------------------------------

class RBACChecker:
    """Dépendance FastAPI pour valider une permission via le TenantContext.

    Vérifie d'abord si la permission est explicitement dans `tenant.scopes`.
    Sinon, s'appuie sur le rôle `tenant.role` :
    - platform_admin : tout
    - enterprise_admin : tout (limité à son enterprise via le contexte)
    - recruiter : lecture (read:*) + actions de base
    - viewer : lecture uniquement (read:*)
    """

    def __init__(self, permission: str):
        self.permission = permission

    def __call__(self, tenant: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        # 1. Scopes explicites parsés une seule fois
        if "*" in tenant.scopes or self.permission in tenant.scopes:
            return tenant

        # 2. Heuristiques par role (RBAC minimaliste)
        if tenant_has_any_role(tenant, {UserRole.enterprise_admin}):
            return tenant

        if tenant_has_any_role(tenant, {UserRole.recruiter}):
            if self.permission.startswith("read:") or self.permission.endswith(":read"):
                return tenant
            # Exemples de permissions de base tolérées pour recruiter (ancien et nouveau format)
            if self.permission in ["recruit:basic", "action:match", "candidates:write", "matches:run"]:
                return tenant

        if tenant_has_any_role(tenant, {UserRole.viewer}):
            if self.permission.startswith("read:") or self.permission.endswith(":read"):
                return tenant

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission '{self.permission}' refusée pour le rôle {tenant.role.value}"
        )
