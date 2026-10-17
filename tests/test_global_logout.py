"""Account-wide revocation and absolute session expiry across store instances."""
from app.services.session_store import SessionStore


def test_session_ttl_is_absolute_and_revoke_all_reaches_other_store_instances(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr('app.services.session_store.time.time', lambda: clock[0])
    first = SessionStore(tmp_path / 'sessions.sqlite3', ttl=28800)
    second = SessionStore(first.path, ttl=28800)
    token = first.create('credential')
    clock[0] += 28799
    assert second.valid(token, 'credential')
    clock[0] += 1
    assert not first.valid(token, 'credential')
    tokens = [first.create('credential'), second.create('credential')]
    second.revoke_all()
    assert all(not first.valid(value, 'credential') for value in tokens)
