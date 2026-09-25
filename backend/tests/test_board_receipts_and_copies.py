"""画板回执与复制的边界 —— 这几条都是「不报错、只是东西没了」的那种。"""

from __future__ import annotations

from types import SimpleNamespace

from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _board(client, ws: str, canvas: dict) -> str:
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": canvas})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _deliver(board_id: str, item_id: str, job: SimpleNamespace) -> None:
    from app.core.db import SessionLocal
    from app.domain.boards import deliver_generated, receipt_to_item

    with SessionLocal() as db:
        deliver_generated(db, job, receipt_to_item(board_id, item_id))


def _canvas(client, ws: str, board_id: str) -> dict:
    return client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]


def test_产出落回时画板上的标记还在() -> None:
    """标记和 items 平级 —— 回执只动它那一格,不该顺手把整张板的书签清掉。"""
    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, {
        "items": [{"id": "img", "kind": "image", "x": 0, "y": 0, "run": {"status": "running", "job_id": "job-1"}}],
        "edges": [],
        "markers": [{"id": "m1", "name": "开头", "x": 10, "y": 20}],
    })

    _deliver(board_id, "img", SimpleNamespace(id="job-1", status="succeeded", result={"asset_ids": ["a1"]}))

    canvas = _canvas(client, ws, board_id)
    assert canvas["items"][0]["asset_id"] == "a1"
    assert [one["id"] for one in canvas["markers"]] == ["m1"], "产出一落回来,用户放的标记全没了"


def test_失败回执同样不动标记() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, {
        "items": [{"id": "img", "kind": "image", "x": 0, "y": 0, "run": {"status": "running", "job_id": "job-1"}}],
        "edges": [],
        "markers": [{"id": "m1", "name": "开头", "x": 10, "y": 20}],
    })

    _deliver(board_id, "img", SimpleNamespace(id="job-1", status="failed", result=None, error="炸了"))

    assert [one["id"] for one in _canvas(client, ws, board_id)["markers"]] == ["m1"]


def test_同一格再出一次多张_多出来的那几张不撞上一轮的() -> None:
    """一次出两张:占位那一格拿第一张,第二张另起一格。**再生成一次**同样出两张时,第二张的新格子
    不能和上一轮那一格同名 —— 撞了的话整次回执被 normalize 拒掉,产出一张都没落回来,
    那一格永远停在「生成中」。"""
    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, {
        "items": [{"id": "img", "kind": "image", "x": 0, "y": 0, "width": 200,
                   "run": {"status": "running", "job_id": "job-1"}}],
        "edges": [],
    })
    _deliver(board_id, "img", SimpleNamespace(id="job-1", status="succeeded", result={"asset_ids": ["a1", "a2"]}))
    first = _canvas(client, ws, board_id)
    assert [one["asset_id"] for one in first["items"]] == ["a1", "a2"]

    # 第二轮:同一格重新进入生成(place_pending 的效果),再交回两张。
    from app.core.db import SessionLocal
    from app.domain.boards import place_pending

    with SessionLocal() as db:
        place_pending(db, workspace_id=ws, board_id=board_id, item={
            "id": "img", "kind": "image", "x": 0, "y": 0, "run": {"status": "running", "job_id": "job-2"},
        })
    _deliver(board_id, "img", SimpleNamespace(id="job-2", status="succeeded", result={"asset_ids": ["b1", "b2"]}))

    items = {one["id"]: one for one in _canvas(client, ws, board_id)["items"]}
    # 占位那一格就地换成这一轮的第一张;上一轮多出来的那格原样留着;这一轮多出来的另起一格。
    assert {key: one["asset_id"] for key, one in items.items()} == {"img": "b1", "img-2": "a2", "img-3": "b2"}, (
        f"第二轮的产出没落回来:{items}"
    )
    assert all((one.get("run") or {}).get("status") == "succeeded" for one in items.values()), "还有一格停在生成中"
    assert items["img-3"]["x"] != items["img-2"]["x"], "新的一格正好叠在上一轮那一格上,看着像只出了一张"


def test_起任务后才撞上并发保存_占位照样落下_任务照样起(monkeypatch) -> None:
    """版本检查在建任务**之前**做(没花钱时拒);可建任务到摆占位之间还有一段窗口 —— 同一个人的
    自动保存正好在这时落库,占位就撞 409。此前那一刻任务已经建好了(钱在路上),而占位没摆、
    线程没起:任务中心里一条永远排队的任务,画布上什么都没有,用户看到的是一句「有冲突」。

    摆占位是服务端对**一格**的合并,不是客户端快照 —— 它该合到最新的画布上,而不是被这次保存挡回去。"""
    import app.domain.generation as generation
    import app.domain.generation.runner as runner
    from app.core.db import SessionLocal
    from app.domain.boards import update_board
    from app.domain.boards.actions import Slot, generate_on_board

    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, {"items": [{"id": "img", "kind": "image", "x": 0, "y": 0}], "edges": []})
    user_id = client.get("/api/auth/me").json()["id"]
    started: list[str] = []

    def create_job_while_user_autosaves(db, **_kwargs):
        with SessionLocal() as other:
            update_board(other, workspace_id=ws, board_id=board_id, canvas={
                "items": [{"id": "img", "kind": "image", "x": 40, "y": 0},
                          {"id": "n1", "kind": "note", "x": 400, "y": 0, "text": "刚加的"}],
                "edges": [],
            })
        return SimpleNamespace(id="gen-1", provider="p", provider_profile_id="pp", model="m"), SimpleNamespace(id="job-1")

    monkeypatch.setattr(generation, "create_generation_job", create_job_while_user_autosaves)
    monkeypatch.setattr(runner, "start_generation_thread", started.append)

    revision = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["revision"]
    with SessionLocal() as db:
        generate_on_board(
            db, workspace_id=ws, slot=Slot(board_id, "img", 0, 0, revision), actor_id=user_id, kind="image",
            prompt="一只猫", provider="p", provider_profile_id="pp", model="m", parameters={}, source_assets=[],
            form={"prompt": "一只猫"},
        )

    assert started == ["gen-1"], "任务建了却没起 —— 任务中心里永远排着一条"
    items = {one["id"]: one for one in _canvas(client, ws, board_id)["items"]}
    assert items["img"]["run"] == {"status": "running", "job_id": "job-1"}
    assert items["img"]["x"] == 40, "占位把并发保存里用户刚拖的位置盖回去了"
    assert "n1" in items, "占位把并发保存里刚加的那一项抹掉了"


def _live_board(client, ws: str) -> str:
    """一张板,上面那一格正在跑一个真由服务端摆下的任务(job-1)。"""
    from app.core.db import SessionLocal
    from app.domain.boards import place_pending

    board_id = _board(client, ws, {"items": [{"id": "img", "kind": "image", "x": 0, "y": 0,
                                               "form": {"prompt": "一只猫"}}], "edges": []})
    with SessionLocal() as db:
        place_pending(db, workspace_id=ws, board_id=board_id, item={
            "id": "img", "kind": "image", "x": 0, "y": 0, "form": {"prompt": "一只猫"},
            "run": {"status": "running", "job_id": "job-1"},
        })
    return board_id


def test_客户端存回来的快照不能把正在跑的任务抹掉() -> None:
    """撤销一步就回到「点生成之前」:那份快照里这一格是空槽。它存回来的话任务还在跑(钱已经花了),
    画布上却成了一个能再点一次生成的空槽 —— 这正是「以为没点中又点了一次」的那条路。
    运行态归服务端:只有摆占位和回执能改它。"""
    client = fresh_client()
    ws = _workspace(client)
    board_id = _live_board(client, ws)
    revision = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["revision"]

    undone = {"items": [{"id": "img", "kind": "image", "x": 30, "y": 0, "form": {"prompt": "一只猫"}}], "edges": []}
    saved = client.patch(f"/api/boards/{board_id}", json={"workspace_id": ws, "base_revision": revision, "canvas": undone})

    assert saved.status_code == 200, saved.text
    item = saved.json()["canvas"]["items"][0]
    assert item["run"] == {"status": "running", "job_id": "job-1"}, "客户端的快照把在跑的任务抹掉了"
    assert item["x"] == 30, "用户那一侧的改动(位置)照常生效"


def test_正在跑的那一格不能再起一个任务(monkeypatch) -> None:
    """一格同一时刻只有一个任务。第二次点生成时第一轮还在跑:此前照样建第二个任务(第二份钱),
    占位换成第二轮 —— 而第一轮的回执回来时照样填进这一格。"""
    import pytest

    import app.domain.generation as generation
    from app.core.db import SessionLocal
    from app.domain.boards import BoardDomainError
    from app.domain.boards.actions import Slot, generate_on_board

    client = fresh_client()
    ws = _workspace(client)
    board_id = _live_board(client, ws)
    user_id = client.get("/api/auth/me").json()["id"]
    created: list[str] = []

    def create_generation_job(db, **_kwargs):
        created.append("job")
        raise AssertionError("不该走到建任务这一步")

    monkeypatch.setattr(generation, "create_generation_job", create_generation_job)

    with SessionLocal() as db, pytest.raises(BoardDomainError):
        generate_on_board(
            db, workspace_id=ws, slot=Slot(board_id, "img", 0, 0), actor_id=user_id, kind="image",
            prompt="一只猫", provider="p", provider_profile_id="pp", model="m", parameters={}, source_assets=[],
            form={"prompt": "一只猫"},
        )

    assert created == [], "第一轮还在跑,又建了第二个任务"


def test_正文里_at_到的素材不会在失败后变成槽位里挂着的素材(monkeypatch) -> None:
    """发出去的 source_assets = 槽位挂的 + 正文里 @ 到的(见前端 mergeSourceAssets);表单里的
    source_assets 只是**槽位**那一半,@ 的那几份记在 mentioned_asset_ids 上。此前占位把发出去的
    合并清单写回表单,跑挂了重试时 @ 过的素材出现在槽位里 —— 正文里删掉那个 @,它照样被发出去。"""
    import app.domain.generation as generation
    import app.domain.generation.runner as runner
    from app.core.db import SessionLocal
    from app.domain.boards.actions import Slot, generate_on_board

    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, {"items": [{"id": "img", "kind": "image", "x": 0, "y": 0}], "edges": []})
    user_id = client.get("/api/auth/me").json()["id"]
    monkeypatch.setattr(
        generation, "create_generation_job",
        lambda db, **_: (SimpleNamespace(id="gen-1", provider="p", provider_profile_id="pp", model="m"), SimpleNamespace(id="job-1")),
    )
    monkeypatch.setattr(runner, "start_generation_thread", lambda _id: None)
    slot_only = [{"asset_id": "slot-a", "role": "reference_image"}]
    form = {"prompt": "像 @猫 那样", "source_assets": slot_only, "mentioned_asset_ids": ["cat"]}

    with SessionLocal() as db:
        generate_on_board(
            db, workspace_id=ws, slot=Slot(board_id, "img", 0, 0), actor_id=user_id, kind="image",
            prompt="像 猫 那样", provider="p", provider_profile_id="pp", model="m", parameters={},
            source_assets=[*slot_only, {"asset_id": "cat", "role": "reference_image"}], form=form,
        )
    _deliver(board_id, "img", SimpleNamespace(id="job-1", status="failed", result=None, error="炸了"))

    saved = _canvas(client, ws, board_id)["items"][0]["form"]
    assert saved["source_assets"] == slot_only, "@ 到的素材被写进了槽位"
    assert saved["mentioned_asset_ids"] == ["cat"]


def test_念出来时选的引擎和发音人留在节点表单上_失败后原样重试(monkeypatch) -> None:
    """音频节点的表单是「念什么 + 用哪把嗓子」。引擎音色那条路的嗓子记在 engine/engine_voice 上,
    而摆占位时表单被整个换成 {prompt, voice_id} —— 跑挂了回来重试,面板落回第一个引擎,
    用户挑好的发音人没了。"""
    import app.domain.voices.engine_catalog as engine_catalog
    import app.domain.voices.voices as voices

    monkeypatch.setattr(engine_catalog, "synthesis_params", lambda db, **kwargs: {})
    monkeypatch.setattr(voices, "start_synthesis", lambda db, **kwargs: SimpleNamespace(id="job-tts"))

    client = fresh_client()
    ws = _workspace(client)
    form = {"prompt": "你好", "voice_id": "", "engine": "edge", "engine_voice": "zh-CN-XiaoxiaoNeural"}
    board_id = _board(client, ws, {"items": [{"id": "a1", "kind": "audio", "x": 0, "y": 0, "form": form}], "edges": []})

    spoken = client.post(f"/api/boards/{board_id}/speak", json={
        "workspace_id": ws, "item_id": "a1", "text": "你好", "engine": "edge", "engine_voice": "zh-CN-XiaoxiaoNeural",
    })
    assert spoken.status_code == 200, spoken.text
    placed = spoken.json()["canvas"]["items"][0]
    assert placed["run"] == {"status": "running", "job_id": "job-tts"}
    assert (placed["form"]["engine"], placed["form"]["engine_voice"]) == ("edge", "zh-CN-XiaoxiaoNeural")

    _deliver(board_id, "a1", SimpleNamespace(id="job-tts", status="failed", result=None, error="超时"))
    failed = _canvas(client, ws, board_id)["items"][0]
    assert failed["form"] == form, "跑挂了之后表单不是用户提交时的样子,重试要重新挑一遍"


def test_创建副本时正在写的便签不带着写作中过去() -> None:
    """便签写作是同步的,没有 job_id —— 可它同样只落回原板那一格。副本里那张便签带着 running
    过去的话,永远等不到写完,一直显示「写作中」。和带 job_id 的那种是同一条规则。"""
    from app.core.db import SessionLocal
    from app.domain.boards import set_text_write_run

    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, {"items": [{"id": "n1", "kind": "note", "x": 0, "y": 0, "text": ""}], "edges": []})
    with SessionLocal() as db:
        set_text_write_run(db, workspace_id=ws, board_id=board_id, item_id="n1", status="running")

    copied = client.post(f"/api/boards/{board_id}/duplicate", json={"workspace_id": ws})

    assert copied.status_code == 200, copied.text
    assert "run" not in copied.json()["canvas"]["items"][0]


def test_智能体往画板上放一个够不着的文档或场景_开卡时就拒() -> None:
    """edit_board 在开卡时先干跑一遍,「写坏的算子要在批准之前就失败」。可干跑只过了形状校验,
    引用那一道(文档在不在、场景是不是这个工作区的)留到了批准之后 —— 用户点了同意才看到报错。"""
    import pytest

    from app.core.db import SessionLocal
    from app.domain.agent.confirmations import ConfirmationError, request_confirmation

    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, {"items": [], "edges": []})

    with SessionLocal() as db:
        for op in (
            {"kind": "add_item", "type": "document", "note_id": "no-such-note", "note_revision": 1},
            {"kind": "add_item", "type": "scene", "scene_id": "no-such-scene"},
        ):
            with pytest.raises(ConfirmationError):
                request_confirmation(
                    db, workspace_id=ws, tool="edit_board", requested_by="agent",
                    payload={"board_id": board_id, "operations": [op]},
                )


def _deleted_note_board(client, ws: str) -> tuple[str, dict]:
    """一张引用了某篇文档的板,那篇文档随后被删掉了 —— 画板上留着一个坏掉的引用。"""
    note = client.post("/api/notes", json={"workspace_id": ws, "title": "品牌规范", "markdown": "蓝色"}).json()
    item = {"id": "doc", "kind": "document", "x": 0, "y": 0, "note_id": note["id"], "note_revision": 1}
    board_id = _board(client, ws, {"items": [item], "edges": []})
    trash = client.patch(f"/api/notes/{note['id']}", json={**note, "base_revision": 1, "trashed": True}).json()
    client.delete(f"/api/notes/{note['id']}", params={"workspace_id": ws, "base_revision": trash["revision"]})
    return board_id, item


def test_引用的文档删掉之后_画板照样能创建副本() -> None:
    """坏掉的引用在原板上照样能挪、能删(见 _validate_scene_references);副本是同样的项,
    不该因为那一格就整张复制不出来。"""
    client = fresh_client()
    ws = _workspace(client)
    board_id, _item = _deleted_note_board(client, ws)

    made = client.post(f"/api/boards/{board_id}/duplicate", json={"workspace_id": ws, "name": "副本"})

    assert made.status_code == 200, made.text
    assert [one["kind"] for one in made.json()["canvas"]["items"]] == ["document"]


def test_引用的文档删掉之后_复制那一格不会让整张板存不下() -> None:
    """画布上「复制」一格是换了 id 的同一份引用。此前保留判断认的是**格子的 id**,于是复制出来的
    那格被当成新引用去校验、校验失败 —— 之后每一次自动保存都被整个拒掉,用户只看到「画板没能保存」。"""
    client = fresh_client()
    ws = _workspace(client)
    board_id, item = _deleted_note_board(client, ws)
    revision = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["revision"]

    saved = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "base_revision": revision,
        "canvas": {"items": [item, {**item, "id": "doc-copy", "x": 40}], "edges": []},
    })

    assert saved.status_code == 200, saved.text
