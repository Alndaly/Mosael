"""Deployment-level application update and plugin registry download sources."""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_update_feed_url
from app.domain.plugins import registry
from tests.util import fresh_client, second_client

URL = "/api/settings/install-source"


def test_download_source_urls_persist_and_registry_consumer_reads_the_same_value() -> None:
    client = fresh_client()
    initial = client.get(URL).json()
    assert initial["update_feed_url"] == initial["plugin_registry_url"] == ""

    feed = "https://updates.example.com/mosael/"
    index = "https://plugins.example.com/registry.json"
    saved = client.put(URL, json={"update_feed_url": feed, "plugin_registry_url": index})
    assert saved.status_code == 200, saved.text
    assert saved.json()["update_feed_url"] == feed
    assert saved.json()["plugin_registry_url"] == index
    assert client.get(URL).json()["update_feed_url"] == feed

    with SessionLocal() as db:
        assert registry.index_url(db) == index

    assert client.put(URL, json={"plugin_registry_url": ""}).status_code == 200
    with SessionLocal() as db:
        assert registry.index_url(db) == registry.DEFAULT_REGISTRY_URL


def test_download_source_updates_are_partial() -> None:
    client = fresh_client()
    feed = "https://updates.example.com/stable/"
    index = "https://plugins.example.com/registry.json"
    assert client.put(URL, json={
        "pip_index": "tsinghua", "update_feed_url": feed, "plugin_registry_url": index,
    }).status_code == 200

    new_feed = "https://updates.example.com/beta/"
    got = client.put(URL, json={"update_feed_url": new_feed}).json()
    assert got["update_feed_url"] == new_feed
    assert got["plugin_registry_url"] == index
    assert got["pip_index"] == "tsinghua"

    new_index = "https://plugins.example.com/next.json"
    got = client.put(URL, json={"plugin_registry_url": new_index}).json()
    assert got["update_feed_url"] == new_feed
    assert got["plugin_registry_url"] == new_index
    assert got["pip_index"] == "tsinghua"


def test_download_source_urls_are_trimmed_and_only_the_feed_gets_a_trailing_slash() -> None:
    client = fresh_client()
    got = client.put(URL, json={
        "update_feed_url": "  https://updates.example.com/mosael  ",
        "plugin_registry_url": "  https://plugins.example.com/registry.json  ",
    })
    assert got.status_code == 200, got.text
    assert got.json()["update_feed_url"] == "https://updates.example.com/mosael/"
    assert got.json()["plugin_registry_url"] == "https://plugins.example.com/registry.json"


def test_download_source_urls_reject_non_http_and_incomplete_urls() -> None:
    client = fresh_client()
    for field in ("update_feed_url", "plugin_registry_url"):
        for value in ("updates.example.com", "ftp://updates.example.com/mosael", "https:///missing-host"):
            response = client.put(URL, json={field: value})
            assert response.status_code == 422, (field, value, response.text)
    current = client.get(URL).json()
    assert current["update_feed_url"] == current["plugin_registry_url"] == ""


def test_download_source_write_permission_is_unchanged() -> None:
    client = fresh_client()
    feed = "https://updates.example.com/mosael/"
    assert client.put(URL, json={"update_feed_url": feed}).status_code == 200

    member = second_client()
    assert member.get(URL).status_code == 200
    assert member.put(URL, json={
        "update_feed_url": "https://evil.example.com/feed/",
        "plugin_registry_url": "https://evil.example.com/registry.json",
    }).status_code == 403
    assert client.get(URL).json()["update_feed_url"] == feed


def test_old_deployment_config_gets_an_empty_update_feed_url() -> None:
    client = fresh_client()
    index = "https://plugins.example.com/registry.json"
    assert client.put(URL, json={"plugin_registry_url": index}).status_code == 200

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config DROP COLUMN update_feed_url"))
    engine.dispose()
    _migrate_update_feed_url()
    _migrate_update_feed_url()

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT plugin_registry_url, update_feed_url FROM deployment_config")).all()
    assert rows == [(index, "")]
    current = client.get(URL).json()
    assert current["plugin_registry_url"] == index
    assert current["update_feed_url"] == ""
