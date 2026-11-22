from typing import List, Optional
from sqlmodel import Session, select
from brainrh.models.talent_profile import TalentProfileDB

class TalentProfileService:
    @staticmethod
    def create_profile(
        session: Session,
        enterprise_id: str,
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        phone: Optional[str] = None
    ) -> TalentProfileDB:
        profile = TalentProfileDB(
            enterprise_id=enterprise_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone=phone
        )
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile

    @staticmethod
    def get_profile(session: Session, profile_id: int) -> Optional[TalentProfileDB]:
        return session.get(TalentProfileDB, profile_id)

    @staticmethod
    def list_profiles(session: Session, enterprise_id: str, email: Optional[str] = None) -> List[TalentProfileDB]:
        statement = select(TalentProfileDB).where(TalentProfileDB.enterprise_id == enterprise_id)
        if email:
            statement = statement.where(TalentProfileDB.email == email)
        results = session.exec(statement).all()
        return list(results)
