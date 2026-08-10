"""「ModelScope」这一项从来没做过任何和 HuggingFace 不同的事。

    HF_ENDPOINTS = {
        "hf":        "https://huggingface.co",
        "hf-mirror": "https://hf-mirror.com",
        "modelscope": "https://huggingface.co",   # ← 和第一项一模一样
    }

两个引擎都一样:F5 的权重只在 HF 上;Fish 的源码从 GitHub 拉、权重走 `snapshot_download`,
认的还是 `HF_ENDPOINT`。也就是说选它和选「HuggingFace」是同一件事,只是名字不同。

它的代价是实打实的:

- 用户按名字选它,以为走的是国内的 ModelScope —— 那是一句谎。
- 为了不撒这个谎,我先给它挂了长长的括号解释"它其实不是它",又改成按引擎条件渲染;
  而条件渲染的下拉项撞上 Radix 的一条规矩(当前值没有对应 Item 时会把值清空并回调),
  于是**每次刷新页面表单都会自己变脏**:顶上常驻「改了还没保存」、下载被挡、
  下拉显示成一片空白 —— 用户报的「每次刷新页面下载源都会变动,导致要重新保存」。

一个不做事的选项,养出了三层补丁。删掉它,连同那三层。已存的值迁移到等价的 `hf`。
"""

from __future__ import annotations

from app.domain import tts_config


def test_there_is_no_modelscope_source() -> None:
    """它和 hf 指向同一个端点 —— 留着只会让人按名字做错判断。"""
    assert "modelscope" not in tts_config.HF_ENDPOINTS


def test_every_remaining_source_points_somewhere_distinct() -> None:
    """选项之间必须真的有区别,否则那不是选项,是装饰。"""
    endpoints = list(tts_config.HF_ENDPOINTS.values())
    assert len(endpoints) == len(set(endpoints)), tts_config.HF_ENDPOINTS


def test_a_stored_modelscope_row_is_migrated() -> None:
    """老库里存着 modelscope 的那一行要迁移过去 —— 否则它会落到 `get` 的兜底(hf-mirror)上,
    而那是**另一个**端点:用户什么都没改,下载源却悄悄换了人。"""
    from app.core.db import SessionLocal
    from app.db.models import TtsConfig
    from tests.util import fresh_client

    fresh_client()
    with SessionLocal() as db:
        db.merge(TtsConfig(id="default", engine="fish-speech", source="modelscope"))
        db.commit()

    tts_config.migrate_legacy_sources()

    with SessionLocal() as db:
        assert db.get(TtsConfig, "default").source == "hf"


def test_the_migration_leaves_real_choices_alone() -> None:
    from app.core.db import SessionLocal
    from app.db.models import TtsConfig
    from tests.util import fresh_client

    fresh_client()
    with SessionLocal() as db:
        db.merge(TtsConfig(id="default", engine="f5-tts", source="hf-mirror"))
        db.commit()

    tts_config.migrate_legacy_sources()

    with SessionLocal() as db:
        assert db.get(TtsConfig, "default").source == "hf-mirror"
