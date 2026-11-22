import os
import sys

# Bootstrapper le path pour `python3 scripts/...`
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlmodel import Session, select
from brainrh.database import engine
from brainrh.models.cv import CVMetaDB
from brainrh.models.project import ProjectDB
from brainrh.services.cv_service import CVService

def run_dry_run_backfill():
    """
    Backfill dry-run: lit tous les CV de CVMetaDB et prépare la création (en mémoire)
    de TalentProfileDB et ResumeVersionDB, ainsi que ApplicationDB.
    """
    print("=== Démarrage du Backfill Dry-Run (BMT-NEXT-018) ===")

    with Session(engine) as session:
        # Récupérer tous les CVs (legacy)
        legacy_cvs = session.exec(select(CVMetaDB)).all()
        print(f"Trouvé {len(legacy_cvs)} CVs dans cv_meta.")

        talents_to_create = 0
        applications_to_create = 0
        valid_cvs = 0

        seen_emails = set()

        for cv in legacy_cvs:
            # Récupérer le projet
            project = session.exec(select(ProjectDB).where(ProjectDB.id == cv.project_id)).first()
            if not project:
                print(f"[WARN] Projet {cv.project_id} introuvable pour le CV {cv.filename}. Ignoré.")
                continue

            enterprise_id = project.enterprise_id
            if not enterprise_id:
                print(f"[WARN] Projet {cv.project_id} n'a pas d'enterprise_id. Ignoré.")
                continue

            # Reset per-CV state
            cv_json = None

            # Lire les données enrichies du JSON pour avoir l'email
            email = None
            try:
                import json
                from brainrh.paths import PROJECT_ROOT
                if cv.json_path:
                    abs_path = PROJECT_ROOT / cv.json_path
                    if abs_path.exists():
                        with open(abs_path, 'r', encoding='utf-8') as f:
                            cv_json = json.load(f)
                            identite = cv_json.get("identite", {})
                            email = identite.get("email")
            except Exception as e:
                print(f"[WARN] Erreur de lecture JSON pour {cv.filename}: {e}")

            email = email or f"dummy_{cv.filename}@example.com"

            # Check if talent profile already exists in DB
            from brainrh.models.talent_profile import TalentProfileDB
            from brainrh.models.resume_version import ResumeVersionDB
            from brainrh.models.application import ApplicationDB

            existing_talent = session.exec(
                select(TalentProfileDB)
                .where(TalentProfileDB.enterprise_id == enterprise_id)
                .where(TalentProfileDB.email == email)
            ).first()

            talent_key = f"{enterprise_id}:{email}"
            if existing_talent:
                talent = existing_talent
            else:
                talent = TalentProfileDB(enterprise_id=enterprise_id, email=email)
                session.add(talent)
                session.commit()
                session.refresh(talent)
                talents_to_create += 1
                seen_emails.add(talent_key)

            parsed_json_str = None
            try:
                parsed_json_str = json.dumps(cv_json) if 'cv_json' in locals() and cv_json else None
            except Exception:
                pass

            resume = ResumeVersionDB(
                talent_profile_id=talent.id,
                enterprise_id=enterprise_id,
                storage_path=cv.json_path,
                parsed_json_str=parsed_json_str
            )
            session.add(resume)
            session.commit()
            session.refresh(resume)
            valid_cvs += 1

            app = ApplicationDB(
                talent_profile_id=talent.id,
                project_id=project.id,
                enterprise_id=enterprise_id,
                resume_version_id=resume.id
            )
            session.add(app)
            session.commit()
            applications_to_create += 1

        print("\n=== Résumé de l'exécution du Backfill === ")
        print(f"TalentProfiles (créés) : {talents_to_create}")
        print(f"ResumeVersions (créés) : {valid_cvs}")
        print(f"Applications (créées)  : {applications_to_create}")
        print("Note: Les données ont été insérées en base.")

if __name__ == "__main__":
    run_dry_run_backfill()
