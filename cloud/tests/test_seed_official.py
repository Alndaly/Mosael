"""`python -m cloud.cli seed-official --bundle …`:幂等、按语言各发一行、密码来自环境变量。

这里走的是**真实命令行**(子进程 + 一个临时 `CLOUD_DATA_DIR`),因为部署脚本的契约就是那条
命令;断言落在它写出来的 SQLite 行上。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

CLOUD_ROOT = Path(__file__).resolve().parents[1]
SRC = CLOUD_ROOT / "src"

PLUGIN_SLUG = "mosael.official.example"
WORKFLOW_SLUG = "mosael.official.welcome"

PLUGIN_PAYLOAD = {
    "version": 1,
    "manifest": {"id": "mosael.official.example", "version": "1.0.0", "name": "Example"},
    "files": [{"path": "index.js", "text": "export default {}"}],
}

OFFICIAL_PASSWORD = "Official-Horse-9"
OTHER_OFFICIAL_PASSWORD = "Another-Official-7"


def sample_bundle() -> dict:
    """一条插件 + 一条工作流,各带中英两行;两份语言共用同一份 payload。"""
    return {
        "plugins": [
            {
                "slug": PLUGIN_SLUG,
                "locales": {
                    "zh-CN": {"title": "官方示例插件", "summary": "官方账号发布的示例插件。"},
                    "en-US": {
                        "title": "Official Example Plugin",
                        "summary": "An example plugin published by the official account.",
                    },
                },
                "license": "MIT",
                "payload": PLUGIN_PAYLOAD,
            }
        ],
        "workflows": [
            {
                "slug": WORKFLOW_SLUG,
                "locales": {
                    "zh-CN": {"title": "官方入门工作流"},
                    "en-US": {"title": "Official Welcome Workflow"},
                },
                "payload": {"version": 1, "nodes": [], "edges": []},
            }
        ],
    }


def write_bundle(tmp_path: Path, data: dict | None = None) -> Path:
    path = tmp_path / "official-bundle.json"
    path.write_text(json.dumps(data if data is not None else sample_bundle(), ensure_ascii=False), encoding="utf-8")
    return path


def run_seed(
    data_dir: Path, bundle: Path, *, official_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if not key.startswith("CLOUD_")}
    env.update({"CLOUD_DATA_DIR": str(data_dir), "PYTHONPATH": str(SRC)})
    if official_env:
        env.update(official_env)
    return subprocess.run(
        [sys.executable, "-m", "cloud.cli", "seed-official", "--bundle", str(bundle)],
        cwd=CLOUD_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def query(data_dir: Path, sql: str, params: tuple = ()):
    with sqlite3.connect(data_dir / "cloud.db") as connection:
        return connection.execute(sql, params).fetchall()


def execute(data_dir: Path, sql: str, params: tuple = ()) -> None:
    with sqlite3.connect(data_dir / "cloud.db") as connection:
        connection.execute(sql, params)
        connection.commit()


def counts(data_dir: Path) -> tuple[int, int]:
    """(账号数, 分享数)。bundle 被整份拒绝时库可能还没建出来 —— 那也是 0。"""
    if not (data_dir / "cloud.db").exists():
        return 0, 0
    users = query(data_dir, "SELECT COUNT(*) FROM cloud_users")
    shares = query(data_dir, "SELECT COUNT(*) FROM cloud_shares")
    return users[0][0], shares[0][0]


def password_hash(data_dir: Path) -> str | None:
    return query(data_dir, "SELECT password_hash FROM cloud_users WHERE official = 1")[0][0]


def test_seed_is_idempotent_and_creates_one_official_account(tmp_path):
    """③④ 跑两次只有一份;官方账号固定 handle / display_name / official=true / 默认无密码。"""
    bundle = write_bundle(tmp_path)
    data_dir = tmp_path / "data"

    first = run_seed(data_dir, bundle)
    assert first.returncode == 0, first.stderr
    assert "plugin" in first.stdout
    assert "workflow" in first.stdout

    accounts = query(
        data_dir, "SELECT email, display_name, handle, avatar_seed, official, password_hash FROM cloud_users"
    )
    assert len(accounts) == 1
    email, display_name, handle, avatar_seed, official, stored_password = accounts[0]
    assert (display_name, handle, official) == ("Mosael 官方", "mosael", 1)
    assert email == "official@mosael.example"
    # 没设 CLOUD_OFFICIAL_PASSWORD = 不写密码(不是报错);这个账号的密码登录会 401。
    assert stored_password is None
    assert avatar_seed

    # 同一条内容按语言各一行,标题 / 简介取各自语言,payload 两行完全相同。
    shares = query(
        data_dir,
        "SELECT kind, locale, title, summary, license, slug FROM cloud_shares ORDER BY kind, locale",
    )
    assert shares == [
        ("plugin", "en-US", "Official Example Plugin", "An example plugin published by the official account.", "MIT", PLUGIN_SLUG),
        ("plugin", "zh-CN", "官方示例插件", "官方账号发布的示例插件。", "MIT", PLUGIN_SLUG),
        ("workflow", "en-US", "Official Welcome Workflow", None, None, WORKFLOW_SLUG),
        ("workflow", "zh-CN", "官方入门工作流", None, None, WORKFLOW_SLUG),
    ]
    payloads = query(data_dir, "SELECT payload FROM cloud_shares WHERE slug = ? ORDER BY locale", (PLUGIN_SLUG,))
    assert [json.loads(row[0]) for row in payloads] == [PLUGIN_PAYLOAD, PLUGIN_PAYLOAD]

    # 幂等键是 (官方账号, kind, slug, locale):两次跑既不加账号也不加行。
    plugin_ids = query(data_dir, "SELECT id FROM cloud_shares WHERE slug = ? ORDER BY locale", (PLUGIN_SLUG,))
    second = run_seed(data_dir, bundle)
    assert second.returncode == 0, second.stderr
    assert query(data_dir, "SELECT COUNT(*) FROM cloud_users") == [(1,)]
    assert query(data_dir, "SELECT COUNT(*) FROM cloud_shares") == [(4,)]
    assert query(data_dir, "SELECT id FROM cloud_shares WHERE slug = ? ORDER BY locale", (PLUGIN_SLUG,)) == plugin_ids


def test_seed_writes_the_configured_password_and_rotates_it_on_every_run(tmp_path):
    """②④ 设了 CLOUD_OFFICIAL_PASSWORD → 每次种子都写它;运营改环境变量就能改密码。"""
    from cloud.security import verify_password

    bundle = write_bundle(tmp_path)
    data_dir = tmp_path / "data"

    first = run_seed(
        data_dir, bundle, official_env={"CLOUD_OFFICIAL_PASSWORD": OFFICIAL_PASSWORD}
    )
    assert first.returncode == 0, first.stderr
    stored = password_hash(data_dir)
    assert stored.startswith("$argon2id$")
    assert verify_password(OFFICIAL_PASSWORD, stored)
    assert not verify_password(OTHER_OFFICIAL_PASSWORD, stored)

    second = run_seed(
        data_dir, bundle, official_env={"CLOUD_OFFICIAL_PASSWORD": OTHER_OFFICIAL_PASSWORD}
    )
    assert second.returncode == 0, second.stderr
    rotated = password_hash(data_dir)
    assert rotated != stored
    assert verify_password(OTHER_OFFICIAL_PASSWORD, rotated)
    assert not verify_password(OFFICIAL_PASSWORD, rotated)
    # 改密码不是"发布内容":分享行一行都不变。
    assert query(data_dir, "SELECT COUNT(*) FROM cloud_shares") == [(4,)]

    # 没设就不动密码:已有的那个仍然有效(新账号没设才是"没有密码")。
    third = run_seed(data_dir, bundle)
    assert third.returncode == 0, third.stderr
    assert password_hash(data_dir) == rotated


def test_seed_reads_handle_and_email_from_the_environment_and_never_rewrites_them(tmp_path):
    """② 三个 CLOUD_OFFICIAL_* 的行为:建号时用环境变量;已存在时只有密码会被更新。"""
    bundle = write_bundle(tmp_path)
    data_dir = tmp_path / "data"

    first = run_seed(
        data_dir,
        bundle,
        official_env={
            "CLOUD_OFFICIAL_HANDLE": "official-cat",
            "CLOUD_OFFICIAL_EMAIL": "ops@example.com",
            "CLOUD_OFFICIAL_PASSWORD": OFFICIAL_PASSWORD,
        },
    )
    assert first.returncode == 0, first.stderr
    assert query(data_dir, "SELECT handle, email, official FROM cloud_users") == [
        ("official-cat", "ops@example.com", 1)
    ]

    # 再改 handle / email **不会**重写已有账号(密码是唯一的例外);也不会多建一个官方号。
    second = run_seed(
        data_dir,
        bundle,
        official_env={
            "CLOUD_OFFICIAL_HANDLE": "official-dog",
            "CLOUD_OFFICIAL_EMAIL": "other@example.com",
            "CLOUD_OFFICIAL_PASSWORD": OTHER_OFFICIAL_PASSWORD,
        },
    )
    assert second.returncode == 0, second.stderr
    assert query(data_dir, "SELECT COUNT(*) FROM cloud_users") == [(1,)]
    assert query(data_dir, "SELECT handle, email FROM cloud_users") == [("official-cat", "ops@example.com")]

    from cloud.security import verify_password

    assert verify_password(OTHER_OFFICIAL_PASSWORD, password_hash(data_dir))


def test_seed_publishes_only_the_languages_a_bundle_actually_has(tmp_path):
    """③ 只给 zh 就只发 zh 一行 —— 不编造英文;只给 en 就只发 en。"""
    bundle = write_bundle(
        tmp_path,
        {
            "plugins": [
                {
                    "slug": "mosael.official.zh-only",
                    "locales": {"zh-CN": {"title": "只有中文"}},
                    "payload": {"version": 1},
                },
                {
                    "slug": "mosael.official.en-only",
                    "locales": {"en-US": {"title": "English only"}},
                    "payload": {"version": 1},
                },
            ],
        },
    )
    data_dir = tmp_path / "data"

    result = run_seed(data_dir, bundle)
    assert result.returncode == 0, result.stderr
    assert query(data_dir, "SELECT slug, locale, title FROM cloud_shares ORDER BY slug") == [
        ("mosael.official.en-only", "en-US", "English only"),
        ("mosael.official.zh-only", "zh-CN", "只有中文"),
    ]


def test_seed_only_fills_gaps_and_never_overwrites_edits_or_user_shares(tmp_path):
    """③ 重复跑不改标题 / 简介 / payload,也不碰用户自己的分享;新条目只补它自己的语言。"""
    bundle_path = write_bundle(tmp_path)
    data_dir = tmp_path / "data"
    assert run_seed(data_dir, bundle_path).returncode == 0

    # 运营手改过的东西(中文那一行)+ 一个普通用户的分享(用户分享没有 locale 以外的新形状)。
    execute(
        data_dir,
        "UPDATE cloud_shares SET title = 'Edited Title', summary = 'Edited Summary', payload = ? "
        "WHERE slug = ? AND locale = 'zh-CN'",
        (json.dumps({"edited": True}), PLUGIN_SLUG),
    )
    execute(
        data_dir,
        "INSERT INTO cloud_users (id, email, created_at) VALUES ('u1', 'alice@example.com', '2026-01-01 00:00:00.000000')",
    )
    execute(
        data_dir,
        "INSERT INTO cloud_shares (id, owner_user_id, kind, title, payload, bytes, locale, status, downloads, "
        "created_at, updated_at) VALUES ('user-share', 'u1', 'workflow', 'User Share', '{}', 2, 'zh-CN', "
        "'listed', 0, '2026-01-01 00:00:00.000000', '2026-01-01 00:00:00.000000')",
    )

    assert run_seed(data_dir, bundle_path).returncode == 0

    edited = query(
        data_dir,
        "SELECT title, summary, payload FROM cloud_shares WHERE slug = ? AND locale = 'zh-CN'",
        (PLUGIN_SLUG,),
    )
    assert edited == [("Edited Title", "Edited Summary", json.dumps({"edited": True}))]
    assert query(data_dir, "SELECT title FROM cloud_shares WHERE id = 'user-share'") == [("User Share",)]
    # 4 条种子行 + 1 条用户分享。
    assert query(data_dir, "SELECT COUNT(*) FROM cloud_shares") == [(5,)]

    # bundle 里新增一条:只补这一条(两种语言),旧的改动仍然不动。
    grown = sample_bundle()
    grown["plugins"].append(
        {
            "slug": "mosael.official.second",
            "locales": {
                "zh-CN": {"title": "第二个官方插件"},
                "en-US": {"title": "Second Official Plugin"},
            },
            "payload": {"version": 1, "files": []},
        }
    )
    assert run_seed(data_dir, write_bundle(tmp_path, grown)).returncode == 0
    assert query(data_dir, "SELECT COUNT(*) FROM cloud_shares") == [(7,)]
    assert query(
        data_dir, "SELECT title FROM cloud_shares WHERE slug = ? AND locale = 'zh-CN'", (PLUGIN_SLUG,)
    ) == [("Edited Title",)]


def test_seed_rejects_a_malformed_bundle_without_writing_anything(tmp_path):
    """③ bundle 是外部输入:结构不对就整份拒绝,不建半个官方账号。"""
    data_dir = tmp_path / "data"

    missing_locale_title = sample_bundle()
    missing_locale_title["plugins"][0]["locales"]["zh-CN"].pop("title")
    bad = run_seed(data_dir, write_bundle(tmp_path, missing_locale_title))
    assert bad.returncode == 2, bad.stderr
    assert "title" in bad.stderr
    assert counts(data_dir) == (0, 0)

    duplicate_slug = sample_bundle()
    duplicate_slug["workflows"].append(dict(duplicate_slug["workflows"][0]))
    bad = run_seed(data_dir, write_bundle(tmp_path, duplicate_slug))
    assert bad.returncode == 2, bad.stderr
    assert counts(data_dir) == (0, 0)

    unknown_locale = sample_bundle()
    unknown_locale["plugins"][0]["locales"]["fr-FR"] = {"title": "Français"}
    bad = run_seed(data_dir, write_bundle(tmp_path, unknown_locale))
    assert bad.returncode == 2, bad.stderr
    assert "fr-FR" in bad.stderr
    assert counts(data_dir) == (0, 0)

    # 旧格式(entry 顶层 title / locale)不再接受 —— 不写"两种 bundle 都认"的兼容分支。
    old_format = sample_bundle()
    old_format["plugins"][0].pop("locales")
    old_format["plugins"][0].update({"locale": "zh-CN", "title": "旧格式"})
    bad = run_seed(data_dir, write_bundle(tmp_path, old_format))
    assert bad.returncode == 2, bad.stderr
    assert "locales" in bad.stderr or "不认识的键" in bad.stderr
    assert counts(data_dir) == (0, 0)

    oversized = sample_bundle()
    oversized["plugins"][0]["payload"] = {"blob": "x" * (2 * 1024 * 1024 + 16)}
    bad = run_seed(data_dir, write_bundle(tmp_path, oversized))
    assert bad.returncode == 2, bad.stderr
    assert "2 MB" in bad.stderr
    assert counts(data_dir) == (0, 0)


def test_seed_refuses_a_short_official_password_before_writing_anything(tmp_path):
    """④ 密码短于 CLOUD_PASSWORD_MIN_LENGTH → 启动即报错(退出码 2),不静默降级。"""
    bundle = write_bundle(tmp_path)
    data_dir = tmp_path / "data"

    bad = run_seed(data_dir, bundle, official_env={"CLOUD_OFFICIAL_PASSWORD": "short"})
    assert bad.returncode == 2, bad.stdout
    assert "CLOUD_OFFICIAL_PASSWORD" in bad.stderr
    assert "8" in bad.stderr
    assert counts(data_dir) == (0, 0)


def test_seeded_official_shares_are_public_with_the_official_author(client, config):
    """①③ 种子写出来的就是普通分享:list / detail / payload 全走公开接口,语言能筛。"""
    from conftest import api

    bundle = write_bundle(config.data_dir)
    assert run_seed(config.data_dir, bundle).returncode == 0

    from community_helpers import leaves

    zh_listing = client.get(api("/shares?kind=plugin&locale=zh-CN")).json()["items"]
    assert [item["title"] for item in zh_listing] == ["官方示例插件"]
    en_listing = client.get(api("/shares?kind=plugin&locale=en-US")).json()["items"]
    assert [item["title"] for item in en_listing] == ["Official Example Plugin"]
    # 不传 locale = 两种都返回。
    both = client.get(api("/shares?kind=plugin")).json()["items"]
    assert {item["locale"] for item in both} == {"zh-CN", "en-US"}
    assert {item["title"] for item in both} == {"官方示例插件", "Official Example Plugin"}

    item = zh_listing[0]
    assert item["author"] == {
        "display_name": "Mosael 官方",
        "handle": "mosael",
        "avatar_seed": "mosael-official",
        "official": True,
    }
    assert client.get(api(f"/shares/{item['id']}/payload")).json()["payload"] == PLUGIN_PAYLOAD
    assert client.get(api("/shares?kind=workflow&locale=zh-CN")).json()["items"][0]["author"]["official"] is True
    # 官方账号的 email 不出现在任何公开响应里,即使包是外部输入。
    for path, value in leaves(client.get(api("/shares")).json()):
        assert "email" not in path, path
        assert "official@mosael.example" not in str(value), path
