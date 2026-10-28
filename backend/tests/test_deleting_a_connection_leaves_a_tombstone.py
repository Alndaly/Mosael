"""删连接是**立碑**,不是抹除:列表里不再有它,而它的历史照旧算得出来。

病在 `domain/providers/connections.delete_connection` 那一句 `db.delete(profile)`:引用连接的
几个外键写的都是 `ondelete="SET NULL"`(`generation_jobs`、`agent_sessions`、`provider_usage_events`
的 `provider_profile_id`),行一没,那些记录上的**出处**当场变成 NULL,而且没有任何代码回填。
工作流详情的「最近的产出」拿 `provider_profile_id == profile.id` 查(`domain/server_workflows._runs`),
从此再也认不出那些产出;用量记录也不再说得清钱花在哪条连接上。

同一个仓库里早有这条判断:`GenerationSession` 的 `origin_kind`/`origin_id` **故意不设外键**,注释写着
「要的正是『东西删了,会话照旧』」。这里钉住同一件事,外加最容易漏的那半边 —— **删掉的那条不许从
任何可选列表里回来**(它只是历史认得出的一块碑,不是一条能选的连接)。

跟着连接走的那些照旧跟着走(钥匙、模型行、参数组、价目规则):它们是「这条连接现在怎么用」,
不是历史。留着的话,某个人「这项能力的默认模型」会一直指着一条已经删掉的连接。
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Asset, GenerationJob, ProviderCredential, ProviderModel, ProviderProfile
from app.domain import server_workflows
from app.domain.providers import selection
from app.domain.providers.credentials import get as credential_of
from tests.util import fresh_client

T0 = datetime(2026, 10, 1, 10, 0, 0)


def _connection(client, name: str, base_url: str = "https://x.example/v1") -> str:
    created = client.post(
        "/api/settings/providers",
        json={
            "name": name,
            "vendor": "openai-compatible",
            "config": {"base_url": base_url, "default_model": "m", "api_key": "k"},
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _workspace(client) -> str:
    made = client.post("/api/workspaces", json={"name": "W"})
    assert made.status_code == 200, made.text
    return made.json()["id"]


def _made_with(profile_id: str, workspace_id: str, *, asset_id: str, model: str = "m") -> None:
    """这个工作区里**用这条连接**做出来的一份产出:生成记录 + 素材,出处指着连接。"""
    with SessionLocal() as db:
        db.add(Asset(id=asset_id, workspace_id=workspace_id, kind="audio", name="做出来的", source="ai", media_info={}))
        db.flush()
        db.add(
            GenerationJob(
                id=f"gen-{asset_id}", workspace_id=workspace_id, provider="plugin:some.plugin", model=model, kind="audio",
                request={"prompt": "x"}, result_asset_id=asset_id, provider_profile_id=profile_id,
                created_at=T0, updated_at=T0,
            )
        )
        db.commit()


def test_删掉的连接从列表里消失_而它的历史产出照旧算得出来() -> None:
    """正题:`delete_connection` 之后,工作流库算「最近的产出」用的那一跳还认得出这条连接。"""
    client = fresh_client()
    profile_id = _connection(client, "要删的")
    workspace_id = _workspace(client)
    _made_with(profile_id, workspace_id, asset_id="made-by-it")

    assert client.delete(f"/api/settings/providers/{profile_id}").status_code == 204

    # ① 连接列表里不再有它。
    assert profile_id not in {row["id"] for row in client.get("/api/settings/providers").json()}

    with SessionLocal() as db:
        # ② 记录上的出处没有被抹成 NULL(此前的外键 SET NULL 就是在这里动的手)。
        record = db.get(GenerationJob, "gen-made-by-it")
        assert record.provider_profile_id == profile_id

        profile = db.get(ProviderProfile, profile_id)
        # 碑立着,行还在 —— 这是历史能认出它的全部理由。
        assert profile is not None and profile.deleted_at is not None

        # ②的正面:`_runs` 是工作流库算「这张工作流最近的产出」的那一跳,它按 profile.id 查。
        # 这里用真实的那个函数,不另写一份等价判据 —— 拿它算得出那一份产出。
        runs = server_workflows._runs(db, SimpleNamespace(id=""), profile, workspace_id, ["m"], [], limit=5)
        found, more = server_workflows._produced(db, runs, workspace_id, limit=10)
        assert [one["asset_id"] for one in found] == ["made-by-it"], "删连接之后,它做出来的产出还算得出来"
        assert more is False


def test_删掉的那条不许从任何可选列表里回来() -> None:
    """最容易漏的回归:碑还在库里,于是它可能悄悄回到选择器、默认值、按 id 的每一条路上。"""
    client = fresh_client()
    profile_id = _connection(client, "要删的")
    assert client.delete(f"/api/settings/providers/{profile_id}").status_code == 204

    # 生成选项(创作页 / 智能体挑模型的那一份)里没有它。
    options = client.get("/api/generation/options?kind=image").json()
    assert profile_id not in {one["provider_profile_id"] for one in options}
    # 设置页「某能力下的模型」里没有它。
    models = client.get("/api/settings/capability-models/chat").json()
    assert profile_id not in {one["provider_profile_id"] for one in models}

    with SessionLocal() as db:
        # 按 vendor 找可选连接、按 id 解析连接,两条路都不认它。
        assert selection.find_enabled_connection(db, "openai-compatible", profile_id, owner_user_id=None) is None
        assert selection.find_enabled_connection(db, "openai-compatible", owner_user_id=None) is None
        assert selection.list_enabled_connections(db) == []

    # 以为它还活着的那几条路:改它、再删一次、探活、拿它生成 —— 都当它不存在(404)。
    assert client.patch(f"/api/settings/providers/{profile_id}", json={"name": "改个名"}).status_code == 404
    assert client.delete(f"/api/settings/providers/{profile_id}").status_code == 404
    assert client.get(f"/api/settings/providers/{profile_id}/health").status_code == 404
    assert client.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "k2"}).status_code == 404


def test_钥匙和模型行照旧跟着连接走_留下的是出处() -> None:
    """「这条连接现在怎么用」跟着删(否则默认模型会一直指着一条删掉的连接),历史留下。"""
    client = fresh_client()
    profile_id = _connection(client, "要删的")

    with SessionLocal() as db:
        assert credential_of(db, profile_id, db.get(ProviderProfile, profile_id).owner_user_id) is not None
        assert db.scalars(select(ProviderModel).where(ProviderModel.provider_profile_id == profile_id)).all()

    assert client.delete(f"/api/settings/providers/{profile_id}").status_code == 204

    with SessionLocal() as db:
        assert db.scalars(select(ProviderCredential).where(ProviderCredential.profile_id == profile_id)).all() == []
        assert db.scalars(select(ProviderModel).where(ProviderModel.provider_profile_id == profile_id)).all() == []
        # 而那一行还在:删的是连接,不是它做过什么。
        assert db.get(ProviderProfile, profile_id) is not None


def test_删一条连接不带坏别的_同名端点照建() -> None:
    """默认连接、新建连接、同一个 base_url 的第二条 —— 都不受影响。"""
    client = fresh_client()
    kept = _connection(client, "留着的")
    doomed = _connection(client, "要删的")

    assert client.delete(f"/api/settings/providers/{doomed}").status_code == 204

    listed = {row["id"] for row in client.get("/api/settings/providers").json()}
    assert listed == {kept}, "留下的那条照旧在列表里"

    # 同一个 base_url 再建一条:删掉的那条不挡路(unique 若在墓碑行上,这里会 500)。
    again = _connection(client, "同端点再建一条")
    assert again != doomed
    assert again in {row["id"] for row in client.get("/api/settings/providers").json()}

    with SessionLocal() as db:
        assert selection.find_enabled_connection(db, "openai-compatible", kept, owner_user_id=None) is not None
        assert selection.find_enabled_connection(db, "openai-compatible", again, owner_user_id=None) is not None
