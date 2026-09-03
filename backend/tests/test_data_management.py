from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

from app.core.config import app_version, settings
from app.core.secrets_at_rest import key_path, master_key
from tests.test_auth import fresh_client, second_client


def _rewrite_manifest(backup: bytes, **updates: object) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(backup))
    output = io.BytesIO()
    with source, zipfile.ZipFile(output, "w") as rewritten:
        for info in source.infolist():
            content = source.read(info)
            if info.filename == "manifest.json":
                manifest = json.loads(content)
                manifest.update(updates)
                content = json.dumps(manifest).encode()
            rewritten.writestr(info, content)
    return output.getvalue()


def test_backup_is_consistent_complete_and_excludes_rebuildable_data(tmp_path: Path) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "Backup workspace"}).json()
    project = client.post(
        "/api/projects", json={"workspace_id": workspace["id"], "name": "Keep me"}
    ).json()
    media_file = settings.media_dir / "assets" / "sample.txt"
    media_file.parent.mkdir(parents=True, exist_ok=True)
    media_file.write_text("sample media", encoding="utf-8")
    font_file = settings.media_dir / "fonts" / workspace["id"] / "font-1" / "caption.ttf"
    font_file.parent.mkdir(parents=True, exist_ok=True)
    font_file.write_bytes(b"font fixture")
    # Use the production key generator. Writing a fake key here poisons every later
    # encryption test because the test data directory is shared for the pytest process.
    master_key()
    assert key_path().is_file()
    excluded = {
        settings.data_dir / "logs" / "mosael.log": "private log",
        settings.data_dir / "exports" / "derived.mp4": "derived export",
        settings.data_dir / "tts" / "weights.bin": "downloaded model",
    }
    for path, content in excluded.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    response = client.post("/api/settings/data/backup")

    assert response.status_code == 200, response.text
    assert "mosael-backup" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert {
            "manifest.json",
            "data/mosael.db",
            "data/secret.key",
            "data/media/assets/sample.txt",
            f"data/media/fonts/{workspace['id']}/font-1/caption.ttf",
        } <= names
        assert not any(name.startswith(("data/logs/", "data/exports/", "data/tts/")) for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "mosael-backup"
        assert manifest["version"] == 1
        assert manifest["schema_version"] == 1
        assert manifest["files"]["data/media/assets/sample.txt"]["sha256"]
        snapshot = tmp_path / "mosael.db"
        snapshot.write_bytes(archive.read("data/mosael.db"))

    with sqlite3.connect(snapshot) as db:
        assert db.execute("select name from projects where id = ?", (project["id"],)).fetchone() == ("Keep me",)


def test_restore_stages_only_a_verified_backup() -> None:
    client = fresh_client()
    backup = client.post("/api/settings/data/backup")
    assert backup.status_code == 200

    restored = client.post(
        "/api/settings/data/restore/stage",
        files={"file": ("good.mosael-backup", backup.content, "application/zip")},
    )

    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert len(body["stage_id"]) == 32
    stage = settings.data_dir.parent / f".{settings.data_dir.name}.restore-{body['stage_id']}"
    try:
        assert (stage / "mosael.db").is_file()
        assert (stage / ".mosael-restore.json").is_file()
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def test_restore_rejects_a_backup_created_by_a_newer_app_version() -> None:
    client = fresh_client()
    backup = client.post("/api/settings/data/backup")

    response = client.post(
        "/api/settings/data/restore/stage",
        files={
            "file": (
                "future.mosael-backup",
                _rewrite_manifest(backup.content, app_version="999.0.0"),
                "application/zip",
            )
        },
    )

    assert response.status_code == 422
    assert "newer" in response.text.lower()


def test_restore_rejects_a_newer_database_schema() -> None:
    client = fresh_client()
    backup = client.post("/api/settings/data/backup")

    response = client.post(
        "/api/settings/data/restore/stage",
        files={
            "file": (
                "future-schema.mosael-backup",
                _rewrite_manifest(backup.content, schema_version=999),
                "application/zip",
            )
        },
    )

    assert response.status_code == 422
    assert "schema" in response.text.lower() and "newer" in response.text.lower()


def test_restore_rejects_database_version_that_disagrees_with_manifest(tmp_path: Path) -> None:
    client = fresh_client()
    backup = client.post("/api/settings/data/backup")
    with zipfile.ZipFile(io.BytesIO(backup.content)) as source:
        entries = {info.filename: source.read(info) for info in source.infolist()}
    database_path = tmp_path / "future.sqlite"
    database_path.write_bytes(entries["data/mosael.db"])
    with sqlite3.connect(database_path) as database:
        database.execute("PRAGMA journal_mode = DELETE")
        database.execute("PRAGMA user_version = 999")
        database.commit()
    entries["data/mosael.db"] = database_path.read_bytes()
    manifest = json.loads(entries["manifest.json"])
    manifest["files"]["data/mosael.db"] = {
        "size": len(entries["data/mosael.db"]),
        "sha256": hashlib.sha256(entries["data/mosael.db"]).hexdigest(),
    }
    entries["manifest.json"] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as rewritten:
        for name, content in entries.items():
            rewritten.writestr(name, content)

    response = client.post(
        "/api/settings/data/restore/stage",
        files={"file": ("lying-manifest.mosael-backup", output.getvalue(), "application/zip")},
    )

    assert response.status_code == 422
    assert "schema" in response.text.lower()


def test_restore_rejects_tampering_and_path_traversal() -> None:
    client = fresh_client()
    database = settings.db_path.read_bytes()

    def archive_with(entry: str, payload: bytes, *, claimed: bytes | None = None) -> bytes:
        output = io.BytesIO()
        described = payload if claimed is None else claimed
        manifest = {
            "format": "mosael-backup",
            "version": 1,
            "app_version": app_version(),
            "schema_version": 1,
            "files": {
                entry: {"size": len(described), "sha256": hashlib.sha256(described).hexdigest()},
            },
        }
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(entry, payload)
            archive.writestr("manifest.json", json.dumps(manifest))
        return output.getvalue()

    tampered = archive_with("data/mosael.db", database + b"tampered", claimed=database)
    response = client.post(
        "/api/settings/data/restore/stage",
        files={"file": ("tampered.mosael-backup", tampered, "application/zip")},
    )
    assert response.status_code == 422
    assert "checksum" in response.text.lower() or "size" in response.text.lower()

    traversal = archive_with("data/../escaped", b"owned")
    response = client.post(
        "/api/settings/data/restore/stage",
        files={"file": ("traversal.mosael-backup", traversal, "application/zip")},
    )
    assert response.status_code == 422
    assert not (settings.data_dir.parent / "escaped").exists()

    windows_traversal = archive_with(r"data/media/..\escaped", b"owned")
    response = client.post(
        "/api/settings/data/restore/stage",
        files={"file": ("windows-traversal.mosael-backup", windows_traversal, "application/zip")},
    )
    assert response.status_code == 422


def test_data_management_requires_deployment_admin() -> None:
    admin = fresh_client("admin")
    backup = admin.post("/api/settings/data/backup")
    assert backup.status_code == 200
    member = second_client("member")

    assert member.post("/api/settings/data/backup").status_code == 403
    denied = member.post(
        "/api/settings/data/restore/stage",
        files={"file": ("backup.mosael-backup", backup.content, "application/zip")},
    )
    assert denied.status_code == 403
