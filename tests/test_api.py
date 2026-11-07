import hashlib
import importlib
import os
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / ".photosync-storage-id").write_text("test-volume")
    monkeypatch.setenv("PHOTOSYNC_STORAGE", str(storage))
    monkeypatch.setenv("PHOTOSYNC_DATABASE", str(tmp_path / "db" / "data.sqlite"))
    monkeypatch.setenv("PHOTOSYNC_STORAGE_ID", "test-volume")
    monkeypatch.setenv("PHOTOSYNC_REQUIRE_NFS", "0")
    import photosync.app as module
    importlib.reload(module)
    from photosync.db import connect, token_digest
    with TestClient(module.app) as test_client:
        with connect(module.settings.database) as db:
            db.execute("INSERT INTO devices(id,name,token_hash) VALUES (?,?,?)", ("device1", "test", token_digest("test-token")))
        yield test_client, module, storage


def headers(data):
    return {"Authorization": "Bearer test-token", "X-Filename": "photo.jpg", "X-Sha256": hashlib.sha256(data).hexdigest(), "X-File-Size": str(len(data))}


def test_upload_retry_and_device_auth(client):
    api, module, storage = client
    data = b"image contents" * 1000
    assert api.get("/backups/status").status_code == 401
    result = api.put("/backups/item_1", headers=headers(data), content=data)
    assert result.status_code == 200
    assert api.put("/backups/item_1", headers=headers(data), content=data).status_code == 200
    assert len(list((storage / "devices").rglob("[!.]*"))) >= 1
    result = api.post("/backups/check", headers=headers(data), json={"client_ids": ["item_1", "missing"]})
    assert result.json()["backups"][0]["sha256"] == hashlib.sha256(data).hexdigest()
    assert api.get("/backups/status", headers=headers(data)).json()["count"] == 1
    assert api.put("/backups/item_1", headers=headers(b"different"), content=b"different").status_code == 409


def test_mismatch_and_storage_unavailable(client):
    api, module, storage = client
    h = headers(b"expected")
    assert api.put("/backups/bad", headers=h, content=b"bad").status_code == 422
    assert not list(storage.rglob(".incoming-*"))
    (storage / ".photosync-storage-id").unlink()
    assert api.get("/health").status_code == 503
    assert api.put("/backups/other", headers=headers(b"test"), content=b"test").status_code == 503


def test_recover_after_move_before_commit(client):
    api, module, storage = client
    from photosync.db import connect
    data = b"already moved"
    relative = "devices/device1/" + uuid.uuid4().hex
    path = storage / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    with connect(module.settings.database) as db:
        db.execute("INSERT INTO backups(device_id,client_id,filename,size,sha256,path,state) VALUES (?,?,?,?,?,?,'pending')", ("device1", "recovery", "photo.jpg", len(data), hashlib.sha256(data).hexdigest(), relative))
    assert api.put("/backups/recovery", headers=headers(data), content=data).status_code == 200
    assert api.get("/backups/status", headers=headers(data)).json()["count"] == 1


def test_gallery_auth_isolation_and_content(client):
    api, module, storage = client
    from photosync.db import connect, token_digest
    data = b"image contents"
    assert api.put("/backups/picture", headers=headers(data), content=data).status_code == 200
    assert api.get("/").status_code == 200
    assert api.get("/gallery/items").status_code == 401
    assert api.get("/gallery/items/picture/content").status_code == 401
    items = api.get("/gallery/items", headers=headers(data)).json()["items"]
    assert len(items) == 1 and items[0]["filename"] == "photo.jpg"
    response = api.get("/gallery/items/picture/content", headers=headers(data))
    assert response.content == data
    assert response.headers["content-type"] == "application/octet-stream"
    with connect(module.settings.database) as db:
        db.execute("INSERT INTO devices(id,name,token_hash) VALUES (?,?,?)", ("device2", "other", token_digest("other-token")))
    other = {"Authorization": "Bearer other-token"}
    assert api.get("/gallery/items", headers=other).json()["items"] == []
    assert api.get("/gallery/items/picture/content", headers=other).status_code == 404
    (storage / ".photosync-storage-id").unlink()
    assert api.get("/gallery/items/picture/content", headers=headers(data)).status_code == 503


def test_gallery_pagination(client):
    api, module, storage = client
    from photosync.db import connect
    with connect(module.settings.database) as db:
        for i in range(3):
            db.execute("INSERT INTO backups(device_id,client_id,filename,size,sha256,path,state) VALUES (?,?,?,?,?,?,'complete')", ("device1", f"id{i}", "photo.jpg", 1, "a" * 64, f"devices/device1/{i}"))
    first = api.get("/gallery/items?limit=2", headers=headers(b"")).json()
    assert len(first["items"]) == 2 and first["next_offset"] == 2
    second = api.get("/gallery/items?limit=2&offset=2", headers=headers(b"")).json()
    assert len(second["items"]) == 1 and second["next_offset"] is None
