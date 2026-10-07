import json
import stat

import pytest

from app.services.auth_store import AuthStore, PasswordPolicyError, validate_password


def test_auth_store_migrates_plaintext_to_argon2id(tmp_path):
    auth_file = tmp_path / "auth.json"
    store = AuthStore(auth_file, "test-user", "initial-password-123")
    store.initialize()

    payload = json.loads(auth_file.read_text(encoding="utf-8"))
    assert payload["username"] == "test-user"
    assert payload["password_hash"].startswith("$argon2id$")
    assert "initial-password-123" not in auth_file.read_text(encoding="utf-8")
    assert stat.S_IMODE(auth_file.stat().st_mode) == 0o600
    assert store.verify("test-user", "initial-password-123")
    assert not store.verify("test-user", "wrong-password")


def test_auth_store_reset_persists_across_instances(tmp_path):
    auth_file = tmp_path / "auth.json"
    first = AuthStore(auth_file, "test-user", "initial-password-123")
    first.initialize()
    first.reset_password("replacement-password-456")

    restarted = AuthStore(auth_file)
    restarted.initialize()
    assert restarted.verify("test-user", "replacement-password-456")
    assert not restarted.verify("test-user", "initial-password-123")


def test_change_password_requires_current_password(tmp_path):
    store = AuthStore(tmp_path / "auth.json", "test-user", "initial-password-123")
    store.initialize()
    assert not store.change_password("wrong-password", "replacement-password-456")
    assert store.verify("test-user", "initial-password-123")
    assert store.change_password("initial-password-123", "replacement-password-456")
    assert store.verify("test-user", "replacement-password-456")


def test_password_policy():
    with pytest.raises(PasswordPolicyError):
        validate_password("too-short")
