"""Atomic, expiring login budgets shared by processes using the session database."""
import hashlib
import sqlite3
import time

from fastapi import HTTPException


class LoginLimiter:
    def __init__(self, path, limit=5, window=300, global_limit=100):
        self.path, self.limit, self.window, self.global_limit = path, limit, window, global_limit
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS login_attempts (client TEXT, created REAL)')
            db.execute('CREATE INDEX IF NOT EXISTS login_attempts_client ON login_attempts(client, created)')

    def check(self, client):
        now = time.time()
        key = hashlib.sha256(client.encode()).hexdigest()
        with sqlite3.connect(self.path, timeout=2) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM login_attempts WHERE created <= ?', (now - self.window,))
            total, local = db.execute(
                'SELECT COUNT(*), COALESCE(SUM(client = ?), 0) FROM login_attempts', (key,)
            ).fetchone()
            blocked = total >= self.global_limit or local >= self.limit
            if not blocked:
                db.execute('INSERT INTO login_attempts VALUES (?, ?)', (key, now))
        if blocked:
            raise HTTPException(429, 'Too many requests. Try again shortly.', headers={'Retry-After': str(self.window)})
