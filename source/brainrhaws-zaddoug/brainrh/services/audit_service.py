import json
from typing import Optional, Dict, Any
from sqlmodel import Session
from brainrh.models.audit_log import AuditLogDB

class AuditService:
    @staticmethod
    def create_event(
        session: Session,
        enterprise_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        actor_user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLogDB:
        """
        Crée une entrée d'audit log dans la base de données.
        """
        metadata_json = "{}"
        if metadata:
            metadata_json = json.dumps(metadata)

        log = AuditLogDB(
            enterprise_id=enterprise_id,
            actor_user_id=str(actor_user_id) if actor_user_id is not None else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_json=metadata_json
        )
        session.add(log)
        session.commit()
        session.refresh(log)
        return log
