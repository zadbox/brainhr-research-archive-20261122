from typing import List, Optional
from sqlmodel import Session, select
from brainrh.models.resume_version import ResumeVersionDB
from brainrh.models.talent_profile import TalentProfileDB

class ResumeService:
    @staticmethod
    def create_version(
        session: Session,
        talent_profile_id: int,
        enterprise_id: str,
        parsed_json_str: Optional[str] = None,
        storage_path: Optional[str] = None
    ) -> ResumeVersionDB:
        profile = session.get(TalentProfileDB, talent_profile_id)
        if not profile or profile.enterprise_id != enterprise_id:
            raise ValueError("Talent profile invalid or cross-enterprise link forbidden")

        # Trouver la dernière version
        statement = select(ResumeVersionDB).where(ResumeVersionDB.talent_profile_id == talent_profile_id).order_by(ResumeVersionDB.version_number.desc())
        last_version = session.exec(statement).first()
        next_version_num = (last_version.version_number + 1) if last_version else 1

        resume = ResumeVersionDB(
            talent_profile_id=talent_profile_id,
            enterprise_id=enterprise_id,
            version_number=next_version_num,
            parsed_json_str=parsed_json_str,
            storage_path=storage_path
        )
        session.add(resume)
        session.commit()
        session.refresh(resume)
        return resume

    @staticmethod
    def get_versions_for_talent(session: Session, talent_profile_id: int) -> List[ResumeVersionDB]:
        statement = select(ResumeVersionDB).where(ResumeVersionDB.talent_profile_id == talent_profile_id).order_by(ResumeVersionDB.version_number.desc())
        results = session.exec(statement).all()
        return list(results)
