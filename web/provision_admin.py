"""Provision the admin (owner) account — run on the host.

    python -m web.provision_admin --email you@gmail.com --set-password
    python -m web.provision_admin --email you@gmail.com --claim-orphans

Creates/promotes the admin, keyed on email (an OAuth login with the same email
resolves to this account). --set-password sets its email+password login;
--claim-orphans adopts pre-existing unowned data (and moves the legacy shared
library into the admin's folder).
"""

from __future__ import annotations

import argparse
import getpass
import sys

from web.core import config
from web.core.metadata import get_db
from web.passwords import hash_password


def _emit(text: str) -> None:
    """Write one line of this command's output."""
    sys.stdout.write(text + "\n")


MIN_PASSWORD_LENGTH = 10


class PasswordTooShortError(SystemExit):
    """The chosen admin password is shorter than the minimum."""

    def __init__(self) -> None:
        """Build the message shown on exit."""
        super().__init__(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")


class _Args(argparse.Namespace):
    """The parsed command line."""

    email: str = ""
    name: str = "Admin"
    claim_orphans: bool = False
    set_password: bool = False
    password: str | None = None


def main() -> None:
    """Create or promote an admin account from the command-line options."""
    ap = argparse.ArgumentParser(description="Create or promote the admin account.")
    ap.add_argument("--email", required=True, help="the owner's email (match your login address)")
    ap.add_argument("--name", default="Admin")
    ap.add_argument("--claim-orphans", action="store_true", help="assign unowned tenant rows to the admin")
    ap.add_argument("--set-password", action="store_true", help="set the admin's email+password login (prompts)")
    ap.add_argument("--password", help="password for --set-password (else prompts; avoid in shell history)")
    args = ap.parse_args(namespace=_Args())

    db = get_db()
    if args.set_password:
        pw = args.password or getpass.getpass("New admin password: ")
        if len(pw) < MIN_PASSWORD_LENGTH:
            raise PasswordTooShortError
        admin = db.create_local_admin(args.email, hash_password(pw), name=args.name)
    else:
        admin = db.ensure_admin(args.email, args.name)
    _emit(f"Admin: {admin.email}  (id {admin.id}, provider {admin.provider}, is_admin={admin.is_admin})")
    if args.claim_orphans:
        n = db.claim_orphans(admin.id)
        _emit(f"Assigned {n} previously-unowned row(s) to the admin.")
        moved = _migrate_library(admin.id)
        _emit(f"Moved {moved} legacy library upload(s) into the admin's folder.")


def _migrate_library(admin_id: str) -> int:
    """Move the shared (legacy) library uploads into the admin's per-user folder."""
    base = config.ROOT_DIR / "library"
    if not base.is_dir():
        return 0
    dest = base / admin_id
    moved = 0
    for p in base.iterdir():
        if p.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            p.rename(dest / p.name)
            moved += 1
    return moved


if __name__ == "__main__":
    main()
