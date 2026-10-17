"""Per-account durable budgets, with process-wide shared admission for expensive work."""
import asyncio
import os
import sqlite3
import time
from contextlib import asynccontextmanager

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool


class ResourceBudget:
    def __init__(self, data_dir, *, daily_calls=300, disk_bytes=512 * 1024 * 1024):
        self.data_dir, self.daily_calls, self.disk_bytes = data_dir, daily_calls, disk_bytes
        self.path = data_dir / 'resource_usage.sqlite3'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS usage (day INTEGER PRIMARY KEY, calls INTEGER NOT NULL)')
        os.chmod(self.path, 0o600)
        self.ai_slots = asyncio.Semaphore(1)
        self.cpu_slots = asyncio.Semaphore(1)
        self.mutation_slots = asyncio.Semaphore(1)
        self.body_slots = asyncio.Semaphore(2)

    def charge(self):
        day = int(time.time() // 86400)
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM usage WHERE day < ?', (day - 1,))
            row = db.execute('SELECT calls FROM usage WHERE day=?', (day,)).fetchone()
            if row and row[0] >= self.daily_calls:
                from app.services.ai_provider import AIProviderError
                raise AIProviderError('The daily AI call budget has been reached. Try again tomorrow.')
            db.execute('INSERT INTO usage VALUES (?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1', (day,))

    def check_disk(self):
        size = 0
        count = 0
        for root, dirs, files in os.walk(self.data_dir, followlinks=False):
            dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(root, name))]
            count += len(files) + len(dirs)
            if count > 10000:
                raise HTTPException(507, 'Account file count quota reached. Remove old history.')
            for name in files:
                path = os.path.join(root, name)
                try:
                    if not os.path.islink(path):
                        size += os.stat(path).st_size
                except FileNotFoundError:
                    pass
            if size + 64 * 1024 * 1024 > self.disk_bytes:
                raise HTTPException(507, 'Account storage quota reached. Remove old documents or history.')

    @asynccontextmanager
    async def ai_call(self):
        # Both accounts share this semaphore. No unbounded queue of model calls.
        async with self.ai_slots:
            await run_in_threadpool(self.charge)
            yield
