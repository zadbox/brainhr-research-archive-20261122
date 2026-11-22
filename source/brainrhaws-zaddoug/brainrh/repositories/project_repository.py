"""
ProjectRepository
Couche d'accès aux données de base de données pour les projets
"""

from typing import List, Optional
from sqlmodel import Session, select

from brainrh.models import ProjectDB


class ProjectRepository:
    """Repository pour accéder aux ProjectDB"""

    @staticmethod
    def list_projects(session: Session, enterprise_id: Optional[str] = None, status: Optional[str] = None) -> List[ProjectDB]:
        """Liste les projets depuis la base de données avec des filtres (tenant-aware)"""
        query = select(ProjectDB)

        if enterprise_id:
            query = query.where(ProjectDB.enterprise_id == enterprise_id)

        if status:
            query = query.where(ProjectDB.status == status)

        return session.exec(query).all()

    @staticmethod
    def get_project(session: Session, project_id: str) -> Optional[ProjectDB]:
        """Récupère un projet par ID depuis la base de données"""
        return session.get(ProjectDB, project_id)
