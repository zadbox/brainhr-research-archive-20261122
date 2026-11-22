"""Read-only, client-scoped candidate catalog backed by indexed CV metadata."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pathlib import PurePosixPath
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlmodel import select

from api.dependencies import get_current_user
from brainrh.database import get_session_direct
from brainrh.models.auth import TenantDB, UserDB, UserRole
from brainrh.models.cv import CVMetaDB
from brainrh.models.enterprise import EnterpriseDB
from brainrh.models.project import ProjectDB
from brainrh.services.auth_service import (
    list_accessible_enterprise_ids,
    list_direct_project_grant_ids,
)

router = APIRouter()


class CatalogCandidate(BaseModel):
    filename: str
    source_filename: str | None
    name: str | None
    title: str | None
    enterprise_id: str
    enterprise_name: str
    project_id: str
    project_name: str
    updated_at: str | None


class CatalogPage(BaseModel):
    items: list[CatalogCandidate]
    total: int


class CatalogScope(BaseModel):
    tenant_id: str
    tenant_name: str
    enterprise_id: str
    enterprise_name: str


@router.get("/scopes", response_model=list[CatalogScope])
def list_catalog_scopes(
    current_user: UserDB = Depends(get_current_user),
) -> list[CatalogScope]:
    """Expose only client/company names reachable through existing grants."""
    with get_session_direct() as session:
        if current_user.role == UserRole.platform_admin:
            enterprise_ids = None
        else:
            enterprise_ids = set(list_accessible_enterprise_ids(
                current_user, required_roles={UserRole.viewer}
            ))
            project_ids = list_direct_project_grant_ids(
                current_user, required_roles={UserRole.viewer}
            )
            if project_ids:
                enterprise_ids.update(enterprise_id for enterprise_id in session.exec(
                    select(ProjectDB.enterprise_id).where(ProjectDB.id.in_(project_ids))
                ).all() if enterprise_id)
            if not enterprise_ids:
                return []

        statement = (
            select(EnterpriseDB, TenantDB)
            .join(TenantDB, EnterpriseDB.tenant_id == TenantDB.id)
            .order_by(TenantDB.name, EnterpriseDB.nom)
        )
        if enterprise_ids is not None:
            statement = statement.where(EnterpriseDB.id.in_(enterprise_ids))
        return [
            CatalogScope(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                enterprise_id=enterprise.id,
                enterprise_name=enterprise.nom,
            )
            for enterprise, tenant in session.exec(statement).all()
        ]


@router.get("", response_model=CatalogPage)
def list_catalog(
    tenant_id: str = Query(..., min_length=1),
    enterprise_id: str | None = Query(None),
    search: str | None = Query(None, max_length=120),
    offset: int = Query(0, ge=0),
    limit: int = Query(40, ge=1, le=100),
    current_user: UserDB = Depends(get_current_user),
) -> CatalogPage:
    """List only indexed CVs in the requested client and authorized projects."""
    with get_session_direct() as session:
        if session.get(TenantDB, tenant_id) is None:
            raise HTTPException(status_code=404, detail="Client introuvable")

        if current_user.role == UserRole.platform_admin:
            access_filter = None
        else:
            enterprise_ids = list_accessible_enterprise_ids(
                current_user, required_roles={UserRole.viewer}
            )
            project_ids = list_direct_project_grant_ids(
                current_user, required_roles={UserRole.viewer}
            )
            if not enterprise_ids and not project_ids:
                return CatalogPage(items=[], total=0)
            access_filter = or_(
                EnterpriseDB.id.in_(enterprise_ids),
                ProjectDB.id.in_(project_ids),
            )

        filters = [EnterpriseDB.tenant_id == tenant_id]
        if enterprise_id:
            filters.append(EnterpriseDB.id == enterprise_id)
        if access_filter is not None:
            filters.append(access_filter)
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            filters.append(or_(
                CVMetaDB.filename.ilike(pattern),
                CVMetaDB.candidat_nom.ilike(pattern),
                CVMetaDB.candidat_titre.ilike(pattern),
            ))

        base = (
            select(CVMetaDB, ProjectDB, EnterpriseDB)
            .join(ProjectDB, CVMetaDB.project_id == ProjectDB.id)
            .join(EnterpriseDB, ProjectDB.enterprise_id == EnterpriseDB.id)
            .where(and_(*filters))
        )
        total = session.exec(
            select(func.count()).select_from(CVMetaDB)
            .join(ProjectDB, CVMetaDB.project_id == ProjectDB.id)
            .join(EnterpriseDB, ProjectDB.enterprise_id == EnterpriseDB.id)
            .where(and_(*filters))
        ).one()
        rows = session.exec(
            base.order_by(
                CVMetaDB.last_modified.desc(),
                CVMetaDB.project_id,
                CVMetaDB.filename,
            ).offset(offset).limit(limit)
        ).all()
        return CatalogPage(
            total=total,
            items=[
                CatalogCandidate(
                    filename=cv.filename,
                    source_filename=PurePosixPath(cv.file_path).name if cv.file_path else None,
                    name=cv.candidat_nom,
                    title=cv.candidat_titre,
                    enterprise_id=enterprise.id,
                    enterprise_name=enterprise.nom,
                    project_id=project.id,
                    project_name=project.nom,
                    updated_at=cv.last_modified.isoformat() if cv.last_modified else None,
                )
                for cv, project, enterprise in rows
            ],
        )
