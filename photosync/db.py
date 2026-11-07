import hashlib
import sqlite3
from pathlib import Path


def connect(path: Path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def initialize(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
            revoked INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS backups (
            device_id TEXT NOT NULL REFERENCES devices(id), client_id TEXT NOT NULL,
            filename TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
            path TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(device_id, client_id)
        );
        """)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
