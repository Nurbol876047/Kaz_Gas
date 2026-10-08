"""Create the first SUPER_ADMIN from ADMIN_EMAIL/ADMIN_PASSWORD env vars, if set.

Run on every container start (see docker/render/entrypoint.sh). Exists so a
first admin can be provisioned on hosts where an interactive shell isn't
available (e.g. Render's free plan). Safe to run repeatedly: it no-ops once
that email already exists, and never overwrites an existing password.
"""

import asyncio
import os
from pydantic import ValidationError
from app.cli import create_admin
from app.database import Session
from app.models import Role


async def bootstrap() -> None:
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    if not email or not password:
        return
    name = os.environ.get("ADMIN_NAME", "Admin")
    async with Session() as db:
        try:
            created = await create_admin(db, email=email, name=name, password=password, role=Role.SUPER_ADMIN)
        except ValidationError as exc:
            print(f"bootstrap_admin: skipped, invalid ADMIN_EMAIL/ADMIN_PASSWORD/ADMIN_NAME: {exc}")
            return
    print(f"bootstrap_admin: {'created' if created else 'already exists, left untouched'} ({email})")


if __name__ == "__main__":
    asyncio.run(bootstrap())
