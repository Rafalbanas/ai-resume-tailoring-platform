import argparse
import getpass
import sys

from app.core.config import Settings
from app.services.auth_store import AuthStore, PasswordPolicyError, validate_password


def reset_password() -> int:
    settings = Settings()
    store = AuthStore(settings.auth_file_path, settings.app_username, settings.app_password)
    store.initialize()

    first = getpass.getpass("New password: ")
    second = getpass.getpass("Repeat new password: ")
    if first != second:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    try:
        validate_password(first)
    except PasswordPolicyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    store.reset_password(first)
    print("Password reset successfully. Existing sessions are no longer valid.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CV Tailor administrative commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("reset-password", help="Reset the single-user password interactively")
    args = parser.parse_args()
    if args.command == "reset-password":
        return reset_password()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
