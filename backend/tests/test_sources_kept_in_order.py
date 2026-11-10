"""「输入素材按先后保留」(`source_overflow = keep_first`):整片的首帧参考图按白模 → 主角 → 地点 → 其余排,
收三张的模型拿前三张、收十六张的全拿;默认仍是超了就拒。"""

from __future__ import annotations

from app.domain.generation.operations import keep_sources_that_fit

CAPS = {"parameter_keys": ["reference_image"], "source_limits": {"reference_image": 2}}


def _refs(*ids: str) -> list[dict[str, str]]:
    return [{"asset_id": one, "role": "reference_image"} for one in ids]


def test_按先后只留收得下的_重复的去掉() -> None:
    assert keep_sources_that_fit(_refs("hero", "hero", "shop", "blockout"), CAPS, "image") == _refs("hero", "shop")


def test_模型不收的角色丢掉_认不出的模型原样交回() -> None:
    sources = [*_refs("hero"), {"asset_id": "clip", "role": "first_frame"}]
    assert keep_sources_that_fit(sources, CAPS, "image") == _refs("hero")
    assert keep_sources_that_fit(sources, None, "image") == sources


def test_没有上限的角色全留() -> None:
    caps = {"parameter_keys": ["reference_image"], "source_limits": {}}
    assert keep_sources_that_fit(_refs("a", "b", "c"), caps, "image") == _refs("a", "b", "c")


def test_工作流节点_选了按先后保留才裁_默认原样交(monkeypatch) -> None:
    from app.domain.workflows.executors import subjobs

    monkeypatch.setattr(subjobs, "capabilities_of_choice", lambda db, **_: CAPS)
    config = {"provider": "p", "model": "m", "source_assets": ["hero:reference_image", "shop:reference_image",
                                                                "blockout:reference_image", ":reference_image"]}
    assert subjobs._sources_to_send(None, config, "image") == _refs("hero", "shop", "blockout")
    assert subjobs._sources_to_send(None, {**config, "source_overflow": "keep_first"}, "image") == _refs("hero", "shop")
