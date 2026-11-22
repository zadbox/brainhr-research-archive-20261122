"""
EnterpriseScopedRepository
Helper pour construire des requêtes isolées par entreprise
"""

from typing import Type, TypeVar, Any, Optional
from sqlmodel import select

from brainrh.models import ProjectDB

T = TypeVar("T")

class EnterpriseScopedRepository:
    """Helper minimal pour le filtrage enterprise_id"""

    @staticmethod
    def query_linked_to_project(
        model: Type[T],
        enterprise_id: str,
        project_id_attr: Any = None
    ) -> Any:
        """
        Génère une requête pour les entités liées à un projet appartenant à l'entreprise.

        Args:
            model: Le modèle SQLModel cible (ex: CVMetaDB)
            enterprise_id: L'ID de l'entreprise
            project_id_attr: Attribut de relation (ex: CVMetaDB.project_id)

        Returns:
            SQLModel Select object
        """
        if project_id_attr is None:
            if hasattr(model, "project_id"):
                project_id_attr = getattr(model, "project_id")
            else:
                raise ValueError(f"Modèle {model.__name__} sans project_id défini.")

        return (
            select(model)
            .join(ProjectDB, project_id_attr == ProjectDB.id)
            .where(ProjectDB.enterprise_id == enterprise_id)
        )
