"""
EnterpriseService - Gestion des entreprises
Couche service : DB (index) + JSON (données complètes)
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlmodel import Session, select

from brainrh.database import get_session
from brainrh.models import EnterpriseDB
from brainrh.models.auth import TenantDB
from brainrh.services.file_storage import FileStorage
from brainrh.paths import get_relative_path, ENTERPRISES_DIR


class EnterpriseService:
    """Service pour gestion des entreprises (DB + JSON)"""

    @staticmethod
    def _ensure_tenant_exists(session: Session, tenant_id: Optional[str], tenant_name: str) -> None:
        if not tenant_id:
            return
        if session.get(TenantDB, tenant_id) is not None:
            return
        session.add(TenantDB(id=tenant_id, name=tenant_name))
        session.flush()

    @staticmethod
    def _tenant_name_for_id(session, tenant_id: Optional[str]) -> Optional[str]:
        if not tenant_id:
            return None
        tenant = session.get(TenantDB, tenant_id)
        if tenant is None:
            return None
        return tenant.name

    @staticmethod
    def _tenant_names_for_ids(
        session: Session,
        tenant_ids: List[Optional[str]],
    ) -> Dict[str, str]:
        resolved_ids = {tenant_id for tenant_id in tenant_ids if tenant_id}
        if not resolved_ids:
            return {}

        tenants = session.exec(
            select(TenantDB).where(TenantDB.id.in_(resolved_ids))
        ).all()
        return {tenant.id: tenant.name for tenant in tenants}

    @staticmethod
    def list_enterprises() -> List[Dict[str, Any]]:
        """
        Liste toutes les entreprises (charge depuis DB puis JSON)

        Returns:
            Liste des entreprises (données complètes depuis JSON)
        """
        enterprises = []

        with get_session() as session:
            db_enterprises = session.exec(select(EnterpriseDB)).all()
            tenant_names = EnterpriseService._tenant_names_for_ids(
                session,
                [db_ent.tenant_id for db_ent in db_enterprises],
            )

            for db_ent in db_enterprises:
                tenant_name = (
                    tenant_names.get(db_ent.tenant_id)
                    if db_ent.tenant_id
                    else None
                )
                # Charger JSON complet
                try:
                    json_data = FileStorage.load_json(db_ent.json_path)
                    json_data.setdefault("tenant_id", db_ent.tenant_id)
                    json_data.setdefault("tenant_name", tenant_name)
                    enterprises.append(json_data)
                except FileNotFoundError:
                    # JSON manquant, reconstruire depuis DB
                    enterprises.append({
                        "id": db_ent.id,
                        "nom": db_ent.nom,
                        "tenant_id": db_ent.tenant_id,
                        "tenant_name": tenant_name,
                        "secteur": db_ent.secteur,
                        "created_at": db_ent.created_at.isoformat(),
                        "last_modified": db_ent.last_modified.isoformat()
                    })

        return enterprises

    @staticmethod
    def list_enterprise_summaries() -> List[Dict[str, Any]]:
        """Return list-view fields from the database index without remote JSON reads."""
        with get_session() as session:
            db_enterprises = session.exec(select(EnterpriseDB)).all()
            tenant_names = EnterpriseService._tenant_names_for_ids(
                session,
                [db_ent.tenant_id for db_ent in db_enterprises],
            )
            return [
                {
                    "id": db_ent.id,
                    "nom": db_ent.nom,
                    "tenant_id": db_ent.tenant_id,
                    "tenant_name": tenant_names.get(db_ent.tenant_id) if db_ent.tenant_id else None,
                    "secteur": db_ent.secteur,
                    "created_at": db_ent.created_at.isoformat(),
                    "last_modified": db_ent.last_modified.isoformat(),
                }
                for db_ent in db_enterprises
            ]

    @staticmethod
    def get_enterprise(enterprise_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère une entreprise par ID

        Args:
            enterprise_id: ID entreprise

        Returns:
            Données entreprise (JSON complet) ou None
        """
        with get_session() as session:
            db_ent = session.get(EnterpriseDB, enterprise_id)

            if not db_ent:
                return None

            tenant_name = EnterpriseService._tenant_name_for_id(session, db_ent.tenant_id)

            # Charger JSON complet
            try:
                data = FileStorage.load_json(db_ent.json_path)
                data.setdefault("tenant_id", db_ent.tenant_id)
                data.setdefault("tenant_name", tenant_name)
                return data
            except FileNotFoundError:
                # JSON manquant, reconstruire depuis DB
                return {
                    "id": db_ent.id,
                    "nom": db_ent.nom,
                    "tenant_id": db_ent.tenant_id,
                    "tenant_name": tenant_name,
                    "secteur": db_ent.secteur,
                    "created_at": db_ent.created_at.isoformat(),
                    "last_modified": db_ent.last_modified.isoformat()
                }

    @staticmethod
    def create_enterprise(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Crée une nouvelle entreprise (DB + JSON)

        Args:
            data: Données entreprise (id, nom, secteur, etc.)

        Returns:
            Données entreprise créée
        """
        enterprise_id = data["id"]
        now = datetime.now()

        # Préparer données complètes
        full_data = {
            **data,
            "created_at": now.isoformat(),
            "last_modified": now.isoformat()
        }

        # Chemin JSON
        json_path = get_relative_path(ENTERPRISES_DIR / enterprise_id / "enterprise.json")

        # 1. Sauvegarder JSON
        FileStorage.save_json(json_path, full_data)

        # 2. Insérer en DB (index)
        with get_session() as session:
            EnterpriseService._ensure_tenant_exists(
                session,
                data.get("tenant_id"),
                data.get("tenant_name") or data["nom"],
            )
            db_ent = EnterpriseDB(
                id=enterprise_id,
                nom=data["nom"],
                tenant_id=data.get("tenant_id"),
                secteur=data.get("secteur"),
                created_at=now,
                last_modified=now,
                json_path=json_path
            )
            session.add(db_ent)
            session.commit()

        return full_data

    @staticmethod
    def update_enterprise(enterprise_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Met à jour une entreprise (DB + JSON)

        Args:
            enterprise_id: ID entreprise
            updates: Champs à mettre à jour

        Returns:
            Données mises à jour ou None si introuvable
        """
        with get_session() as session:
            db_ent = session.get(EnterpriseDB, enterprise_id)

            if not db_ent:
                return None

            # Charger JSON actuel
            try:
                full_data = FileStorage.load_json(db_ent.json_path)
            except FileNotFoundError:
                full_data = {
                    "id": db_ent.id,
                    "nom": db_ent.nom,
                    "secteur": db_ent.secteur
                }

            # Appliquer mises à jour
            full_data.update(updates)
            full_data["last_modified"] = datetime.now().isoformat()

            # 1. Sauvegarder JSON
            FileStorage.save_json(db_ent.json_path, full_data)

            # 2. Mettre à jour DB (index)
            if "nom" in updates:
                db_ent.nom = updates["nom"]
            if "tenant_id" in updates:
                db_ent.tenant_id = updates["tenant_id"]
            if "secteur" in updates:
                db_ent.secteur = updates["secteur"]
            db_ent.last_modified = datetime.now()

            session.add(db_ent)
            session.commit()

        return full_data

    @staticmethod
    def get_enterprise_tenant_id(enterprise_id: str) -> Optional[str]:
        enterprise = EnterpriseService.get_enterprise(enterprise_id)
        if enterprise and enterprise.get("tenant_id"):
            return str(enterprise["tenant_id"])

        with get_session() as session:
            db_ent = session.get(EnterpriseDB, enterprise_id)
            if not db_ent:
                return None
            return db_ent.tenant_id

    @staticmethod
    def list_enterprises_by_tenant(tenant_id: str) -> List[Dict[str, Any]]:
        enterprises = EnterpriseService.list_enterprises()
        return [
            enterprise
            for enterprise in enterprises
            if str(enterprise.get("tenant_id") or "") == str(tenant_id)
        ]

    @staticmethod
    def delete_enterprise(enterprise_id: str) -> bool:
        """
        Supprime une entreprise (DB + JSON)

        Args:
            enterprise_id: ID entreprise

        Returns:
            True si supprimé, False si introuvable
        """
        with get_session() as session:
            db_ent = session.get(EnterpriseDB, enterprise_id)

            if not db_ent:
                return False

            # 1. Supprimer JSON
            try:
                FileStorage.delete_file(db_ent.json_path)
            except FileNotFoundError:
                pass

            # 2. Supprimer DB
            session.delete(db_ent)
            session.commit()

        return True
