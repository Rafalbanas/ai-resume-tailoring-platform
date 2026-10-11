import hashlib
import json
import os
import secrets
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256


class PasswordPolicyError(ValueError):
    pass


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must contain at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must contain at most {MAX_PASSWORD_LENGTH} characters.")


class AuthStore:
    """Single-user Argon2id credential store backed by an atomic JSON file."""

    def __init__(self, path: Path, initial_username: str | None = None, initial_password: str | None = None):
        self.path = path
        self.initial_username = initial_username
        self.initial_password = initial_password
        self.hasher = PasswordHasher()
        self._lock = threading.RLock()

    def initialize(self) -> None:
        with self._lock:
            if self.path.exists():
                self._load()
                os.chmod(self.path, 0o600)
                return
            if not self.initial_username or not self.initial_password:
                raise RuntimeError("auth.json is missing and APP_USERNAME / APP_PASSWORD are unavailable for migration")
            validate_password(self.initial_password)
            self._write(self.initial_username, self.hasher.hash(self.initial_password))

    @property
    def credential_version(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    @property
    def username(self) -> str:
        return self._load()["username"]

    def verify(self, username: str, password: str) -> bool:
        with self._lock:
            record = self._load()
            try:
                password_valid = self.hasher.verify(record["password_hash"], password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                password_valid = False
            username_valid = secrets.compare_digest(username, record["username"])
            if password_valid and username_valid and self.hasher.check_needs_rehash(record["password_hash"]):
                self._write(record["username"], self.hasher.hash(password))
            return password_valid and username_valid

    def change_password(self, current_password: str, new_password: str) -> bool:
        with self._lock:
            record = self._load()
            if not self.verify(record["username"], current_password):
                return False
            self.reset_password(new_password)
            return True

    def reset_password(self, new_password: str) -> None:
        validate_password(new_password)
        with self._lock:
            record = self._load()
            self._write(record["username"], self.hasher.hash(new_password))

    def _load(self) -> dict[str, str]:
        try:
            record = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read credential store: {self.path}") from exc
        if not isinstance(record, dict) or not isinstance(record.get("username"), str):
            raise RuntimeError("Credential store has an invalid username")
        password_hash = record.get("password_hash")
        if not isinstance(password_hash, str) or not password_hash.startswith("$argon2id$"):
            raise RuntimeError("Credential store does not contain a valid Argon2id hash")
        return record

    def _write(self, username: str, password_hash: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        owner_source = self.path if self.path.exists() else self.path.parent
        owner = owner_source.stat()
        payload = {
            "username": username,
            "password_hash": password_hash,
            "algorithm": "argon2id",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        fd, temporary_name = tempfile.mkstemp(prefix=".auth-", suffix=".json", dir=self.path.parent)
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
            os.chmod(self.path, 0o600)
            if os.geteuid() == 0:
                os.chown(self.path, owner.st_uid, owner.st_gid)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
