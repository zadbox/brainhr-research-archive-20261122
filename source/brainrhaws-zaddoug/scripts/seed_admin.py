import os
import secrets
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from brainrh.database import get_session_direct, init_db
from brainrh.models.auth import TenantDB, UserDB, UserRole
from brainrh.services.auth_service import get_password_hash

def seed_database():
    # Make sure tables exist
    init_db()
    
    with get_session_direct() as session:
        # Create default tenant if not exists
        from sqlmodel import select
        
        tenant = session.exec(select(TenantDB).where(TenantDB.name == "Brain RH")).first()
        if not tenant:
            tenant = TenantDB(name="Brain RH")
            session.add(tenant)
            session.commit()
            session.refresh(tenant)
            print(f"Created default tenant: {tenant.name} ({tenant.id})")
        else:
            print("Default tenant already exists.")

        # Create default admin user
        auth_user = session.exec(select(UserDB).where(UserDB.email == "admin@brainrh.com")).first()
        if not auth_user:
            admin_password = os.getenv("BRAINRH_SEED_ADMIN_PASSWORD") or secrets.token_urlsafe(24)
            admin_user = UserDB(
                email="admin@brainrh.com",
                hashed_password=get_password_hash(admin_password),
                role=UserRole.platform_admin,
                tenant_id=tenant.id
            )
            session.add(admin_user)
            session.commit()
            print(f"Created default admin user: {admin_user.email}")
            if not os.getenv("BRAINRH_SEED_ADMIN_PASSWORD"):
                print(f"Generated admin password for this seed run: {admin_password}")
        else:
            print("Default admin user already exists.")

if __name__ == "__main__":
    print("Seeding database...")
    seed_database()
    print("Seeding complete.")
