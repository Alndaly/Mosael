"""生成里的 `@资产`(ADR 0027 阶段 2):提示词描述拼进去、参考图按描述符挑、挂不下照实说、可灵按资产建主体。

描述符用 catalog 里**真的**那几份(不另编一份假的):上限、互斥组、主体下限都是它们说的数。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import Entity, EntityReference
from app.domain.entities.mentions import attach_entities
from app.domain.generation_catalog.descriptors.video import (
    KLING_V3_OMNI_VIDEO_CAPABILITIES,
    SEEDANCE_2_VIDEO_CAPABILITIES,
)
from app.domain.generation_catalog.descriptors.image import (
    OPENAI_IMAGE_CAPABILITIES,
    QWEN_EDIT_IMAGE_CAPABILITIES,
    QWEN_TEXT_IMAGE_CAPABILITIES,
)
from app.domain.generation.operations import GenerationDomainError, validate_against_capabilities
from tests.util import fresh_client, seed_assets


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _entity(ws: str, name: str, prompt: str, refs: list[tuple[str, str]], *, parent: str | None = None,
            kind: str = "character") -> str:
    """直接落一个资产和它的参考图(`[(素材 id, 角度)]`,顺序就是 position)。素材行要先 seed。"""
    with SessionLocal() as db:
        entity = Entity(workspace_id=ws, kind=kind, name=name, prompt=prompt, parent_id=parent,
                        attributes={}, tags=[], lost_references=[])
        db.add(entity)
        db.flush()
        for position, (asset_id, role) in enumerate(refs, start=1):
            db.add(EntityReference(entity_id=entity.id, asset_id=asset_id, role=role, position=position))
        db.commit()
        return entity.id


def _expand(ws: str, ids: list[str], capabilities: dict[str, Any] | None, *,
            sources: list[dict[str, str]] | None = None, kind: str = "image", parameters: dict | None = None):
    with SessionLocal() as db:
        return attach_entities(db, ws, ids, source_assets=list(sources or []),
                               parameters=dict(parameters or {}), kind=kind, capabilities=capabilities)


def _attached(expansion) -> list[str]:
    return [entry["asset_id"] for entry in expansion.source_assets if entry["role"] == "reference_image"]


@pytest.fixture
def ws() -> str:
    client = fresh_client()
    workspace = _workspace(client)
    seed_assets(workspace, {
        "a-side": "image", "a-front": "image", "a-sheet": "image", "a-body": "image", "a-face": "image",
        "a-clip": "video",
        "b-front": "image", "b-back": "image", "b-sheet": "image",
        "c-front": "image",
    })
    return workspace


def test_提示词描述是单独的一段_不改用户写的那句(ws) -> None:
    """描述是给模型的补充:生成漏斗把它记进请求的 prompt_notes,交给供应商时才接在提示词后面。"""
    zhang = _entity(ws, "张三", "黑色短发,红围巾", [("a-front", "front")])
    expansion = _expand(ws, [zhang], OPENAI_IMAGE_CAPABILITIES)
    assert expansion.note == "张三: 黑色短发,红围巾"
    # 没写提示词描述的资产不出空行。
    blank = _entity(ws, "路人", "", [])
    assert _expand(ws, [blank], OPENAI_IMAGE_CAPABILITIES).note == ""


def test_变体继承母体的提示词描述_名字带上母体(ws) -> None:
    zhang = _entity(ws, "张三", "黑色短发", [("a-front", "front")])
    winter = _entity(ws, "冬装", "羽绒服", [], parent=zhang)
    expansion = _expand(ws, [winter], OPENAI_IMAGE_CAPABILITIES)
    assert expansion.note == "张三 · 冬装: 黑色短发，羽绒服"
    # 变体自己一张参考图都没有:用母体的,至少脸是张三的。
    assert _attached(expansion) == ["a-front"]
    assert expansion.receipt[0]["name"] == "张三 · 冬装"


def test_挑图的先后_三视图_正面_全身_其余_只挂图片(ws) -> None:
    zhang = _entity(ws, "张三", "", [
        ("a-side", "side"), ("a-clip", "concept"), ("a-body", "full_body"), ("a-front", "front"),
        ("a-face", "closeup"), ("a-sheet", "turnaround"),
    ])
    expansion = _expand(ws, [zhang], OPENAI_IMAGE_CAPABILITIES)
    assert _attached(expansion) == ["a-sheet", "a-front", "a-body", "a-side", "a-face"]
    assert expansion.receipt[0]["dropped"] == [] and expansion.receipt[0]["notes"] == []


def test_按描述符的上限挂_挂不下的照实记下(ws) -> None:
    """通义的编辑模型最多收 3 张参考图(catalog 里的数)。"""
    assert QWEN_EDIT_IMAGE_CAPABILITIES["source_limits"]["reference_image"] == 3
    zhang = _entity(ws, "张三", "", [
        ("a-side", "side"), ("a-body", "full_body"), ("a-front", "front"), ("a-face", "closeup"), ("a-sheet", "turnaround"),
    ])
    expansion = _expand(ws, [zhang], QWEN_EDIT_IMAGE_CAPABILITIES)
    assert _attached(expansion) == ["a-sheet", "a-front", "a-body"]
    row = expansion.receipt[0]
    assert row["attached"] == ["a-sheet", "a-front", "a-body"]
    assert row["dropped"] == ["a-side", "a-face"]
    assert row["notes"] == ["limit"]


def test_手挂的参考图先占名额(ws) -> None:
    zhang = _entity(ws, "张三", "", [("a-sheet", "turnaround"), ("a-front", "front"), ("a-body", "full_body")])
    manual = [{"asset_id": "c-front", "role": "reference_image"}]
    expansion = _expand(ws, [zhang], QWEN_EDIT_IMAGE_CAPABILITIES, sources=manual)
    assert _attached(expansion) == ["c-front", "a-sheet", "a-front"]
    assert expansion.receipt[0]["dropped"] == ["a-body"]


def test_两个人轮流挑_不让第一个把名额吃光(ws) -> None:
    zhang = _entity(ws, "张三", "", [("a-sheet", "turnaround"), ("a-front", "front"), ("a-body", "full_body")])
    li = _entity(ws, "李四", "", [("b-front", "front"), ("b-back", "back"), ("b-sheet", "turnaround")])
    expansion = _expand(ws, [zhang, li], QWEN_EDIT_IMAGE_CAPABILITIES)
    # 名额按轮次分(甲、乙、甲),发出去的清单按资产成组。
    assert _attached(expansion) == ["a-sheet", "a-front", "b-sheet"]
    assert [row["attached"] for row in expansion.receipt] == [["a-sheet", "a-front"], ["b-sheet"]]


def test_模型不收参考图_一张不挂_提示词照拼(ws) -> None:
    zhang = _entity(ws, "张三", "黑色短发", [("a-front", "front")])
    expansion = _expand(ws, [zhang], QWEN_TEXT_IMAGE_CAPABILITIES)
    assert _attached(expansion) == []
    assert expansion.note == "张三: 黑色短发"
    assert expansion.receipt[0]["notes"] == ["no_reference_role"]


def test_描述符查不到_不猜(ws) -> None:
    zhang = _entity(ws, "张三", "黑色短发", [("a-front", "front")])
    expansion = _expand(ws, [zhang], None)
    assert _attached(expansion) == []
    assert expansion.receipt[0]["notes"] == ["unknown_limits"]
    assert expansion.note == "张三: 黑色短发"


def test_和已挂的首帧互斥_不挂(ws) -> None:
    """Seedance 2:首尾帧和参考素材是互斥的两组(exclusive_source_groups)。"""
    zhang = _entity(ws, "张三", "", [("a-front", "front")])
    first = [{"asset_id": "c-front", "role": "first_frame"}]
    blocked = _expand(ws, [zhang], SEEDANCE_2_VIDEO_CAPABILITIES, sources=first, kind="video")
    assert _attached(blocked) == [] and blocked.receipt[0]["notes"] == ["exclusive"]
    free = _expand(ws, [zhang], SEEDANCE_2_VIDEO_CAPABILITIES, kind="video")
    assert _attached(free) == ["a-front"]
    # 挂上之后照样过描述符的校验。
    validate_against_capabilities("bytedance", "doubao-seedance-2-0-260128", "video", {}, free.source_assets,
                                  capabilities=SEEDANCE_2_VIDEO_CAPABILITIES)


def test_不收提示词的模型_不拼描述_照实说(ws) -> None:
    zhang = _entity(ws, "张三", "黑色短发", [("a-front", "front")])
    expansion = _expand(ws, [zhang], {**OPENAI_IMAGE_CAPABILITIES, "prompt": "none"})
    assert expansion.note == ""
    assert "prompt_skipped" in expansion.receipt[0]["notes"]


def test_别的工作区的资产点不了(ws) -> None:
    other = fresh_client("stranger")
    theirs = _workspace(other)
    stranger = _entity(theirs, "外人", "", [])
    from app.domain.entities.library import EntityDomainError

    with pytest.raises(EntityDomainError):
        _expand(ws, [stranger], OPENAI_IMAGE_CAPABILITIES)


class Test可灵按资产建主体:
    def test_每个资产一组_正面图排第一_组内够数(self, ws) -> None:
        caps = KLING_V3_OMNI_VIDEO_CAPABILITIES
        assert caps["source_limits"]["reference_image"] == 4 and caps["min_reference_images"] == 2
        zhang = _entity(ws, "张三", "", [("a-sheet", "turnaround"), ("a-front", "front"), ("a-body", "full_body")])
        li = _entity(ws, "李四", "", [("b-sheet", "turnaround"), ("b-front", "front")])
        expansion = _expand(ws, [zhang, li], caps, kind="video")
        groups: dict[str, list[str]] = {}
        for entry in expansion.source_assets:
            groups.setdefault(entry["subject"], []).append(entry["asset_id"])
        assert groups == {zhang: ["a-front", "a-sheet"], li: ["b-front", "b-sheet"]}
        validate_against_capabilities("kuaishou", "kling-v3-omni", "video", {}, expansion.source_assets,
                                      capabilities=caps)

    def test_凑不够两张的资产不建主体_照实说(self, ws) -> None:
        lonely = _entity(ws, "王五", "", [("c-front", "front")])
        zhang = _entity(ws, "张三", "", [("a-front", "front"), ("a-side", "side")])
        expansion = _expand(ws, [lonely, zhang], KLING_V3_OMNI_VIDEO_CAPABILITIES, kind="video")
        assert {entry["subject"] for entry in expansion.source_assets} == {zhang}
        assert expansion.receipt[0]["notes"] == ["subject_too_few"]

    def test_校验按组算下限和组数(self) -> None:
        caps = KLING_V3_OMNI_VIDEO_CAPABILITIES
        one_short = [
            {"asset_id": "x1", "role": "reference_image", "subject": "e1"},
            {"asset_id": "x2", "role": "reference_image", "subject": "e1"},
            {"asset_id": "y1", "role": "reference_image", "subject": "e2"},
        ]
        with pytest.raises(GenerationDomainError):
            validate_against_capabilities("kuaishou", "kling-v3-omni", "video", {}, one_short, capabilities=caps)

    def test_适配器每组建一个主体_名字按内容哈希(self, tmp_path: Path, monkeypatch) -> None:
        from app.ai.providers.adapters.kuaishou.kling import video as kling_video
        from app.ai.providers.adapters.kuaishou.kling.elements import element_name_for
        from app.ai.providers.contracts.generation import (
            GenerationAdapterContext,
            GenerationRequest,
            SourceAsset,
        )

        paths = {}
        for name in ("z1", "z2", "l1", "l2"):
            paths[name] = tmp_path / f"{name}.png"
            paths[name].write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode())
        request = GenerationRequest(
            kind="video",
            model="kling-v3-omni",
            prompt="两个人在街口",
            sources=(
                SourceAsset(role="reference_image", path=paths["z1"], subject="zhang"),
                SourceAsset(role="reference_image", path=paths["z2"], subject="zhang"),
                SourceAsset(role="reference_image", path=paths["l1"], subject="li"),
                SourceAsset(role="reference_image", path=paths["l2"], subject="li"),
            ),
        )
        built: list[list[str]] = []

        def fake_ensure(client, images, *, description=""):
            built.append(list(images))
            return f"el-{element_name_for(list(images))}"

        sent: dict[str, Any] = {}

        class FakeResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"data": {"task_id": "t1"}}

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *exc) -> None:
                return None

            def post(self, path, json=None):
                sent["path"], sent["body"] = path, json
                return FakeResponse()

        monkeypatch.setattr(kling_video, "ensure_element", fake_ensure)
        monkeypatch.setattr(kling_video.connection, "client", lambda context: FakeClient())
        monkeypatch.setattr(kling_video.KlingVideoAdapter, "_collect", lambda self, *args, **kwargs: "collected")

        context = GenerationAdapterContext(None, "kuaishou", "k", configured_model_id="kling-v3-omni")
        assert kling_video.KlingVideoAdapter().generate(request, context, tmp_path) == "collected"
        assert len(built) == 2, "两个资产 → 两个主体"
        elements = [one for one in sent["body"]["contents"] if one["type"] == "element"]
        assert [one["element_id"] for one in elements] == [f"el-{element_name_for(group)}" for group in built]
        assert sent["path"].startswith("/omni-video/")


# ---------------------------------------------------------------------------
# ADR 0091 §5:姿势参考
# ---------------------------------------------------------------------------

POSE_CAPS = {
    **OPENAI_IMAGE_CAPABILITIES,
    "parameter_keys": [*OPENAI_IMAGE_CAPABILITIES["parameter_keys"], "pose_reference"],
    "source_limits": {**OPENAI_IMAGE_CAPABILITIES["source_limits"], "pose_reference": 2},
}


def test_姿势资产以_pose_reference_发送_不混进参考图(ws) -> None:
    zhang = _entity(ws, "张三", "", [("a-front", "front")])
    sitting = _entity(ws, "抱膝坐", "", [("b-front", "front"), ("b-sheet", "three_quarter")], kind="pose")
    expansion = _expand(ws, [zhang, sitting], POSE_CAPS)
    entries = {(entry["asset_id"], entry["role"]) for entry in expansion.source_assets}
    assert ("a-front", "reference_image") in entries
    assert ("b-front", "pose_reference") in entries
    assert ("b-sheet", "pose_reference") in entries


def test_姿势和参考图各用各的名额(ws) -> None:
    zhang = _entity(ws, "张三", "", [("a-sheet", "turnaround"), ("a-front", "front"), ("a-body", "full_body")])
    sitting = _entity(ws, "坐姿", "", [("b-front", "front"), ("b-sheet", "three_quarter"), ("c-front", "side")], kind="pose")
    expansion = _expand(ws, [zhang, sitting], POSE_CAPS)
    attached = [entry for entry in expansion.source_assets if entry["role"] in ("reference_image", "pose_reference")]
    assert [one["asset_id"] for one in attached if one["role"] == "reference_image"] == ["a-sheet", "a-front", "a-body"]
    assert [one["asset_id"] for one in attached if one["role"] == "pose_reference"] == ["b-front", "b-sheet"]
    assert expansion.receipt[1]["dropped"] == ["c-front"]


def test_模型不收姿势参考_不悄悄降级(ws) -> None:
    sitting = _entity(ws, "坐姿", "", [("b-front", "front")], kind="pose")
    expansion = _expand(ws, [sitting], OPENAI_IMAGE_CAPABILITIES)
    assert expansion.source_assets == []
    assert expansion.receipt[0]["notes"] == ["pose_reference_unsupported"]


def test_用户明说改成参考图才降级(ws) -> None:
    sitting = _entity(ws, "坐姿", "", [("b-front", "front")], kind="pose")
    with SessionLocal() as db:
        expansion = attach_entities(
            db, ws, [sitting],
            source_assets=[], parameters={}, kind="image",
            capabilities=OPENAI_IMAGE_CAPABILITIES,
            pose_role="reference_image",
        )
    assert expansion.source_assets == [{"asset_id": "b-front", "role": "reference_image"}]
    assert expansion.receipt[0]["notes"] == []


def test_自定义参数组可以声明姿势参考() -> None:
    from app.domain.generation.custom_profiles import canonical_parameters, validate_capabilities

    assert "pose_reference" in canonical_parameters("image")
    clean = validate_capabilities(
        {"parameter_keys": ["reference_image", "pose_reference"], "source_limits": {"pose_reference": 1}},
        "image",
    )
    assert "pose_reference" in clean["parameter_keys"]
    assert "pose_reference" not in canonical_parameters("audio")


def test_生成接口接受姿势参考角色与显式降级开关() -> None:
    from pydantic import ValidationError

    from app.api.schemas import GenerationCreate, SourceAssetRef

    assert SourceAssetRef(asset_id="p", role="pose_reference").role == "pose_reference"
    body = GenerationCreate(
        workspace_id="w", provider="comfyui", model="x", kind="image",
        pose_mentions_role="reference_image",
    )
    assert body.pose_mentions_role == "reference_image"
    assert GenerationCreate(
        workspace_id="w", provider="comfyui", model="x", kind="image",
    ).pose_mentions_role == "pose_reference"
    with pytest.raises(ValidationError):
        GenerationCreate(workspace_id="w", provider="comfyui", model="x", kind="image",
                         pose_mentions_role="whatever")
