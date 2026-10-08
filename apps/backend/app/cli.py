import argparse
import asyncio
import getpass
from sqlalchemy import select
from app.auth import password_hasher
from app.database import Session
from app.models import Admin, Role
from app.schemas import CreateAdmin


async def create_admin(db, *, email: str, name: str, password: str, role: Role = Role.SUPER_ADMIN) -> bool:
    """Create an admin unless the email is already taken. Returns whether it was created."""
    data = CreateAdmin(email=email, name=name, password=password, role=role)
    normalized_email = str(data.email).lower()
    if await db.scalar(select(Admin).where(Admin.email == normalized_email)):
        return False
    db.add(
        Admin(
            email=normalized_email,
            name=data.name,
            password_hash=password_hasher.hash(password),
            role=data.role,
        )
    )
    await db.commit()
    return True


async def main():
    parser = argparse.ArgumentParser(description="Create SUPER_ADMIN (password entered securely)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Password (12+ characters): ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords differ")
    async with Session() as db:
        if not await create_admin(db, email=args.email, name=args.name, password=password):
            raise SystemExit("Email already exists")
    print("SUPER_ADMIN created")


if __name__ == "__main__":
    asyncio.run(main())
