import asyncio
import hashlib
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .db import connect, initialize, token_digest
from .storage import storage_ready

settings = Settings.from_env()
slots = asyncio.Semaphore(settings.max_uploads)
active = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.max_uploads < 1 or settings.max_bytes < 1:
        raise RuntimeError("Invalid upload limits")
    initialize(settings.database)
    yield


app = FastAPI(title="PhotoSync", version="0.1.0", lifespan=lifespan)
app.mount("/gallery-assets", StaticFiles(directory=Path(__file__).parent / "static"), name="gallery-assets")


@app.get("/", include_in_schema=False)
def gallery():
    return FileResponse(Path(__file__).parent / "static" / "index.html", headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'self'; img-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'", "X-Content-Type-Options": "nosniff"})


def authenticate(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required")
    with connect(settings.database) as db:
        device = db.execute("SELECT id FROM devices WHERE token_hash=? AND revoked=0", (token_digest(authorization[7:]),)).fetchone()
    if not device:
        raise HTTPException(401, "Invalid or revoked token")
    return device["id"]


def ready():
    return storage_ready(settings.storage, settings.marker, settings.require_nfs)


@app.get("/health")
async def health():
    available = await asyncio.to_thread(ready)
    return JSONResponse({"status": "ok" if available else "storage_unavailable", "storage_available": available}, status_code=200 if available else 503)


class CheckRequest(BaseModel):
    client_ids: list[str] = Field(max_length=500)


@app.post("/backups/check")
def check(data: CheckRequest, device: str = Depends(authenticate)):
    with connect(settings.database) as db:
        found = []
        for client_id in data.client_ids:
            row = db.execute("SELECT client_id, size, sha256 FROM backups WHERE device_id=? AND client_id=? AND state='complete'", (device, client_id)).fetchone()
            if row:
                found.append(dict(row))
    return {"backups": found}


@app.get("/backups/status")
def status(device: str = Depends(authenticate)):
    with connect(settings.database) as db:
        row = db.execute("SELECT COUNT(*) AS count, COALESCE(SUM(size),0) AS bytes FROM backups WHERE device_id=? AND state='complete'", (device,)).fetchone()
    return dict(row)


@app.get("/gallery/items")
def gallery_items(offset: int = Query(default=0, ge=0), limit: int = Query(default=12, ge=1, le=50), device: str = Depends(authenticate)):
    with connect(settings.database) as db:
        rows = db.execute("SELECT client_id, filename, size, created_at FROM backups WHERE device_id=? AND state='complete' ORDER BY created_at DESC, client_id DESC LIMIT ? OFFSET ?", (device, limit + 1, offset)).fetchall()
    return {"items": [dict(row) for row in rows[:limit]], "next_offset": offset + limit if len(rows) > limit else None}


@app.get("/gallery/items/{client_id}/content")
def gallery_content(client_id: str, device: str = Depends(authenticate)):
    with connect(settings.database) as db:
        row = db.execute("SELECT path, filename FROM backups WHERE device_id=? AND client_id=? AND state='complete'", (device, client_id)).fetchone()
    if not row:
        raise HTTPException(404, "Backup not found")
    if not ready():
        raise HTTPException(503, "Storage unavailable")
    root = settings.storage.resolve()
    path = (root / row["path"]).resolve()
    if not path.is_relative_to(root / "devices" / device) or not path.is_file():
        raise HTTPException(404, "Backup file not found")
    # Treat every original as inert bytes. The browser only displays explicitly
    # supported image types after fetching with the device's bearer token.
    return FileResponse(path, media_type="application/octet-stream", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": "attachment"})


@app.put("/backups/{client_id}")
async def upload(client_id: str, request: Request, x_filename: str = Header(), x_sha256: str = Header(), x_file_size: int = Header(), device: str = Depends(authenticate)):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", client_id):
        raise HTTPException(422, "Invalid client ID")
    if not re.fullmatch(r"[0-9a-f]{64}", x_sha256) or not 0 <= x_file_size <= settings.max_bytes:
        raise HTTPException(422, "Invalid size or SHA-256")
    if not 1 <= len(x_filename) <= 255 or any(ord(c) < 32 for c in x_filename):
        raise HTTPException(422, "Invalid filename")
    key = (device, client_id)
    if key in active:
        raise HTTPException(409, "Upload already in progress")
    active.add(key)
    temp = None
    try:
        async with slots:
            if not await asyncio.to_thread(ready):
                raise HTTPException(503, "Storage unavailable")
            with connect(settings.database) as db:
                row = db.execute("SELECT * FROM backups WHERE device_id=? AND client_id=?", key).fetchone()
                if row and (row['sha256'] != x_sha256 or row['size'] != x_file_size or row['filename'] != x_filename):
                    raise HTTPException(409, "Client ID already used with different metadata")
                if row and row['state'] == 'complete':
                    return {"client_id": client_id, "status": "complete", "sha256": row['sha256']}
                relative = row['path'] if row else f"devices/{device}/{uuid.uuid4().hex}"
                if not row:
                    db.execute("INSERT INTO backups(device_id,client_id,filename,size,sha256,path,state) VALUES (?,?,?,?,?,?,'pending')", (device, client_id, x_filename, x_file_size, x_sha256, relative))
            final = settings.storage / relative
            # A prior request may have moved the file before its database commit.
            if await asyncio.to_thread(final.is_file):
                def verify_existing():
                    digest = hashlib.sha256()
                    size = 0
                    with final.open('rb') as source:
                        while block := source.read(1024 * 1024):
                            size += len(block)
                            digest.update(block)
                    return size == x_file_size and digest.hexdigest() == x_sha256
                if not await asyncio.to_thread(verify_existing):
                    raise HTTPException(500, "Existing file failed integrity check")
            else:
                await asyncio.to_thread(final.parent.mkdir, parents=True, exist_ok=True)
                temp = final.parent / (".incoming-" + uuid.uuid4().hex)
                digest = hashlib.sha256()
                size = 0
                with temp.open("xb") as output:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > x_file_size:
                            raise HTTPException(413, "File exceeds declared size")
                        digest.update(chunk)
                        await asyncio.to_thread(output.write, chunk)
                    if size != x_file_size or digest.hexdigest() != x_sha256:
                        raise HTTPException(422, "Size or SHA-256 mismatch")
                    await asyncio.to_thread(output.flush)
                    await asyncio.to_thread(os.fsync, output.fileno())
                if not await asyncio.to_thread(ready):
                    raise HTTPException(503, "Storage unavailable")
                await asyncio.to_thread(os.replace, temp, final)
                temp = None
            with connect(settings.database) as db:
                db.execute("UPDATE backups SET state='complete' WHERE device_id=? AND client_id=?", key)
            return {"client_id": client_id, "status": "complete", "sha256": x_sha256}
    except OSError:
        raise HTTPException(503, "Storage operation failed")
    finally:
        if temp is not None:
            try:
                await asyncio.to_thread(temp.unlink, missing_ok=True)
            except OSError:
                pass
        active.discard(key)
