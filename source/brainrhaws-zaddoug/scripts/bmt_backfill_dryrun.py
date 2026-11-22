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
            existing_talent = session.exec(
                select(TalentProfileDB)
                .where(TalentProfileDB.enterprise_id == enterprise_id)
                .where(TalentProfileDB.email == email)
            ).first()

            talent_key = f"{enterprise_id}:{email}"
            if not existing_talent and talent_key not in seen_emails:
                talents_to_create += 1
                seen_emails.add(talent_key)

            valid_cvs += 1
            applications_to_create += 1

        print("\n=== Résumé de la simulation du Backfill v2 ===")
        print(f"TalentProfiles virtuels à créer : {talents_to_create}")
        print(f"ResumeVersions à migrer         : {valid_cvs}")
        print(f"Applications à créer            : {applications_to_create}")
        print("Note: Aucune donnée n'a été insérée en base (Dry-run complet).")

if __name__ == "__main__":
    run_dry_run_backfill()
