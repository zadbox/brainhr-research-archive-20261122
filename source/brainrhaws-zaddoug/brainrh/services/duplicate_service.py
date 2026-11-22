from typing import List, Optional
from sqlmodel import Session, select, or_
from brainrh.models.talent_profile import TalentProfileDB

class DuplicateService:
    @staticmethod
    def detect_duplicates(
        session: Session,
        enterprise_id: str,
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        phone: Optional[str] = None
    ) -> List[TalentProfileDB]:
        """
        Détecte les candidats existants dans la même entreprise.
        Dédoublonnage "soft" (suggestion de doublons potentiels).
        """
        if not email and not phone and not (first_name and last_name):
            return []

        conditions = []
        if email:
            conditions.append(TalentProfileDB.email == email)
        if phone:
            conditions.append(TalentProfileDB.phone == phone)
        if first_name and last_name:
            conditions.append(
                (TalentProfileDB.first_name == first_name) &
                (TalentProfileDB.last_name == last_name)
            )

        statement = select(TalentProfileDB).where(
            TalentProfileDB.enterprise_id == enterprise_id,
            or_(*conditions)
        )
        return list(session.exec(statement).all())
