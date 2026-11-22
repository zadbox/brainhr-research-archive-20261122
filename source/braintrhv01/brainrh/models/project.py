"""
Modèle Project pour la base de données
Table projects = index uniquement, JSON complet dans fichier
"""

from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class ProjectDB(SQLModel, table=True):
    """
    Table projects (INDEX UNIQUEMENT)
    Données complètes dans JSON pointé par json_path
    """
    __tablename__ = "projects"

    id: str = Field(primary_key=True, description="ID unique projet")
    nom: str = Field(index=True, description="Nom projet")
    enterprise_id: Optional[str] = Field(
        default=None,
        foreign_key="enterprises.id",
        index=True,
        description="ID entreprise parente (NULL si legacy)"
    )
    description: Optional[str] = Field(default=None, description="Description projet")
    status: str = Field(default="actif", index=True, description="Statut (actif/archive)")
    created_at: datetime = Field(default_factory=datetime.now, description="Date création")
    last_modified: datetime = Field(default_factory=datetime.now, description="Date modification")
    json_path: str = Field(description="Chemin relatif vers JSON complet")

    class Config:
        extra = "allow"
