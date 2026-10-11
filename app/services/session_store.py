"""Opaque, expiring sessions in SQLite; only SHA256 token digests are persisted."""
import hashlib
import os
import secrets
import sqlite3
import time


class SessionStore:
    def __init__(self, path, ttl=28800):
        self.path, self.ttl = path, ttl
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, expires REAL, credential TEXT)')
        os.chmod(path, 0o600)

    def connect(self):
        return sqlite3.connect(self.path)

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def create(self, credential):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires <= ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?, ?, ?)',
                       (self.digest(token), time.time() + self.ttl, credential))
        return token

    def valid(self, token, credential):
        if not token:
            return False
        with self.connect() as db:
            row = db.execute('SELECT expires, credential FROM sessions WHERE digest = ?', (self.digest(token),)).fetchone()
        return bool(row and row[0] > time.time() and secrets.compare_digest(row[1], credential))

    def revoke(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE digest = ?', (self.digest(token),))
