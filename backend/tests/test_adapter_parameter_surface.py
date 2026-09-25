"""Adapter 声明的参数面必须对得起它自己的代码。

目录查不到某个模型时,界面拿的就是这个面(见 ADR 0015)。声明错了的后果是界面摆出一个发不
出去的旋钮 —— 而这正是这套设计要消灭的那种沉默:用户拨了,以为生效了,直到供应商拒掉才知道。

声明 `surface_depends_on_model = False` 要同时满足两条,这里逐条盯着:
  1. 换个模型名,构造出的请求除了 model 字段本身**逐字节相同**;
  2. 面里每一项**没设就不发**(或它的默认值正是今天已经在发的那个)。

第 2 条是"暴露它是安全的"的全部理由:用户不动它,线上一个字节都不变。
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from app.ai.providers.contracts.generation import SOURCE_ROLES, GenerationRequest
from app.ai.providers.registry import _GENERATION_ADAPTERS


def _independent() -> list[tuple[tuple[str, str], Any]]:
    return [(key, a) for key, a in sorted(_GENERATION_ADAPTERS.items()) if not a.surface_depends_on_model]


#: 已经核过"不按模型名分支"且"没设就不发"的通道。**只能有意增减** —— 退回保守会让那条通道上
#: 目录认不出的模型静默回到零参数,而用户看到的是"这个模型就是没参数"。真发现某个网关开始按
#: 模型分支了,改这里,并在提交信息里说清是哪一处分支。
DECLARED_INDEPENDENT = {
    ("openai", "image"),
    ("openai-compatible", "image"),
    ("evolink", "image"),
    ("evolink", "video"),
    # 音频(ADR 0022):Suno 的请求体按「给了什么」选模式,不看模型名;Lyria 没有结构化参数,
    # 两项都是「设了才拼进提示词」。
    ("evolink", "audio"),
    ("google", "audio"),
}


def test_声明独立的通道清单只能有意增减() -> None:
    assert {key for key, _ in _independent()} == DECLARED_INDEPENDENT, (
        "声明 surface_depends_on_model=False 的通道和清单对不上。加了要核两条性质"
        "(不按模型名分支 / 没设就不发),减了要说清是哪一处分支。"
    )


@pytest.mark.parametrize("key, adapter", _independent(), ids=lambda v: str(v))
def test_声明与模型无关的面里不含素材角色(key, adapter) -> None:
    """素材角色是"这个模型做哪种任务",按模型变得厉害,不该混进标量面。"""
    roles = set(SOURCE_ROLES)
    assert not (set(adapter.parameter_surface) & roles), (
        f"{key} 的参数面里混进了素材角色:{sorted(set(adapter.parameter_surface) & roles)}"
    )


@pytest.mark.parametrize("key, adapter", _independent(), ids=lambda v: str(v))
def test_声明与模型无关的Adapter源码里没有按模型名的分支(key, adapter) -> None:
    """语法这一层先拦一道 —— 行为那条更强,但它只覆盖得到有请求构造函数的 Adapter。"""
    import ast

    source = Path(inspect.getfile(type(adapter))).read_text(encoding="utf-8")
    offenders = [
        f"L{node.lineno}: if {ast.unparse(node.test)[:80]}"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.If, ast.IfExp)) and "model" in ast.unparse(node.test)
    ]
    assert not offenders, (
        f"{key} 声明了 surface_depends_on_model=False,但源码里按模型名分支了:\n  "
        + "\n  ".join(offenders)
    )


def _request(model: str, **parameters: Any) -> GenerationRequest:
    return GenerationRequest(
        kind="image", prompt="p", negative_prompt="", model=model, parameters=dict(parameters), sources=()
    )


class Test_OpenAI图片通道:
    """用户撞上的就是这一条:四个 gemini、一个手填别名、一个本地模型全挂在它下面。"""

    def test_换个模型名请求逐字节相同(self) -> None:
        from app.ai.providers.adapters.openai.image import build_submit_payload

        a = build_submit_payload(_request("gpt-image-2"))
        b = build_submit_payload(_request("某个我们没见过的模型"))
        assert a.pop("model") != b.pop("model")
        assert a == b

    def test_面里每一项没设就不发(self) -> None:
        """这条是"暴露它是安全的"的理由。`n` 是例外:它恒发,但默认值就是今天发的那个。"""
        from app.ai.providers.adapters.openai.image import OpenAIImageAdapter, build_submit_payload

        bare = build_submit_payload(_request("m"))
        assert set(bare) == {"model", "prompt", "n"} and bare["n"] == 1
        for key in OpenAIImageAdapter.parameter_surface:
            if key == "num_images":
                continue
            assert key not in bare, f"{key} 在用户没设时就被发出去了"

    def test_设了才出现在请求里(self) -> None:
        from app.ai.providers.adapters.openai.image import build_submit_payload

        payload = build_submit_payload(_request("m", size="1024x1024", quality="high", num_images=3))
        assert payload["size"] == "1024x1024" and payload["quality"] == "high" and payload["n"] == 3


def test_兜底给键但一个取值都不声称() -> None:
    """摆出尺寸输入框却不说哪些尺寸有效,是诚实的;什么都不摆则读起来像"这个模型没有参数"。

    **取值必须一个都不给。** 漏出去一个默认值或一张清单,界面就会选中它并提交 —— 用户没选过
    的值被发出去。这条闸曾经靠"键也为空"把着,那是承重的;界面改成"不知道就空着"之后,
    把门的变成这一条断言。
    """
    from app.domain.generation.catalog import (
        adapter_parameter_surface,
        capabilities_are_known,
        fallback_capabilities,
    )

    caps = fallback_capabilities("openai-compatible", "image")
    assert caps["parameter_keys"] == list(adapter_parameter_surface("openai-compatible", "image"))
    assert set(caps) == {"modes", "parameter_keys"}, (
        f"兜底声称了取值:{sorted(set(caps) - {'modes', 'parameter_keys'})}"
    )
    #: 键知道了,值仍然没人验证过 —— 这两件事是分开的。
    assert capabilities_are_known("openai-compatible", "随便什么型号", "image") is False


def test_依赖模型名的通道保持保守() -> None:
    """seedance 那几个真的按模型分支(t2v 和 i2v 是两件事),猜错就是给文生视频摆首帧槽位。"""
    from app.domain.generation.catalog import fallback_capabilities

    assert fallback_capabilities("bytedance", "video")["parameter_keys"] == []


class Test_Evolink网关:
    """一个纯转发的中转,目录里挂着 29 行(22 个视频模型)。它不看模型名,所以目录认不出的
    型号也能拿到这几个键 —— 而那正是中转最常见的处境:上游天天上新,我们的表永远慢一拍。"""

    def _video(self, model: str, **parameters: Any) -> GenerationRequest:
        return GenerationRequest(
            kind="video", prompt="p", negative_prompt="", model=model,
            parameters=dict(parameters), sources=(),
        )

    def test_换个模型名请求逐字节相同(self) -> None:
        from app.ai.providers.adapters.evolink.generation import build_image_payload, build_video_payload

        a = build_image_payload(_request("z-image-turbo"))
        b = build_image_payload(_request("上游昨天刚上的型号"))
        assert a.pop("model") != b.pop("model")
        assert a == b

        va = build_video_payload(self._video("seedance-2.5-text-to-video"))
        vb = build_video_payload(self._video("上游昨天刚上的型号"))
        assert va.pop("model") != vb.pop("model")
        assert va == vb

    def test_面里每一项没设就不发(self) -> None:
        from app.ai.providers.adapters.evolink.generation import build_image_payload, build_video_payload
        from app.ai.providers.registry import _GENERATION_ADAPTERS

        bare_image = build_image_payload(_request("m"))
        for key in _GENERATION_ADAPTERS[("evolink", "image")].parameter_surface:
            wire = {"num_images": "n", "size": "size"}[key]
            assert wire not in bare_image, f"{key} 在用户没设时就被发出去了"

        bare_video = build_video_payload(self._video("m"))
        wire_names = {
            "duration_seconds": "duration", "resolution": "quality",
            "aspect_ratio": "aspect_ratio", "generate_audio": "generate_audio",
        }
        for key in _GENERATION_ADAPTERS[("evolink", "video")].parameter_surface:
            assert wire_names[key] not in bare_video, f"{key} 在用户没设时就被发出去了"

    def test_两个kind各有各的面(self) -> None:
        """一个类注册了两个 kind。共用一份面的话,图片模型会摆出时长旋钮。"""
        from app.ai.providers.registry import _GENERATION_ADAPTERS

        image = set(_GENERATION_ADAPTERS[("evolink", "image")].parameter_surface)
        video = set(_GENERATION_ADAPTERS[("evolink", "video")].parameter_surface)
        assert image and video and not (image & video)
