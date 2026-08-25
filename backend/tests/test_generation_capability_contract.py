"""参数描述符是**唯一**的事实源:界面按它渲染控件,智能体按它知道能给什么,提交按它校验。

这条约束来自一个沉默的缺口:智能体的 generate_video 此前把 parameters 硬编码成 `{}`,
而 list_generation_models 把描述符整个剥掉了。于是「生成一段 10 秒的竖屏视频」这种最普通的
要求,智能体做不到 —— 它既传不了参数,也查不到有哪些参数可传,而两边都不报错。

校验拦在 create_generation_job(界面/智能体/工作流/定时四条路的共同入口),因为漏拦的后果
不是报错:那家供应商可能**默默忽略**不认识的参数,于是用户要的 10 秒跑出了默认的 5 秒,
而界面上一切正常。
"""

from __future__ import annotations

import pytest

from app.domain.generation.catalog import BUILTIN_MODELS, capabilities_for
from app.domain.generation.operations import GenerationDomainError, validate_against_capabilities


def _check(provider: str, model: str, kind: str, parameters=None, sources=None) -> None:
    validate_against_capabilities(provider, model, kind, parameters or {}, sources or [])


class Test按描述符校验:
    def test_模型不认的参数当场拦住(self) -> None:
        with pytest.raises(GenerationDomainError, match="不支持这些参数"):
            _check("alibaba", "qwen-image", "image", {"duration_seconds": 5})

    def test_报错里说得出可用的是哪些(self) -> None:
        """只说「不支持」等于让智能体去猜。它下一步要做的就是换一个对的键。"""
        with pytest.raises(GenerationDomainError, match="num_images"):
            _check("alibaba", "qwen-image", "image", {"没这个键": 1})

    def test_取值不在清单里也拦(self) -> None:
        with pytest.raises(GenerationDomainError, match="size 只能是"):
            _check("alibaba", "qwen-image", "image", {"size": "320x180"})

    def test_合法取值放行(self) -> None:
        _check("alibaba", "qwen-image", "image", {"size": "1024x1024", "num_images": 2})

    def test_时长按清单拦(self) -> None:
        with pytest.raises(GenerationDomainError, match="时长只能是"):
            _check("minimax", "MiniMax-H3", "video", {"duration_seconds": 7})

    def test_模型不支持的素材角色也拦(self) -> None:
        """万相没有尾帧(它的首尾帧是另一个模型)。默默丢掉的话,用户会拿到一段只用了首帧的视频。"""
        with pytest.raises(GenerationDomainError, match="不支持「last_frame」"):
            _check("alibaba", "wan2.5-t2v-preview", "video", {}, [{"asset_id": "a", "role": "last_frame"}])

    def test_支持的角色放行(self) -> None:
        _check("minimax", "MiniMax-H3", "video", {}, [{"asset_id": "a", "role": "last_frame"}])

    def test_查不到描述符的模型放行(self) -> None:
        """用户自己加的模型、ComfyUI 的工作流 —— 我们不知道它认什么,猜着拦只会挡住能用的东西。"""
        _check("某个自建", "某个模型", "video", {"随便什么": 1})

    def test_负向提示词和种子哪儿都能给(self) -> None:
        """它们不在 parameter_keys 里(那一栏说的是「这个模型有什么可调的」),但每条路都可能带。"""
        _check("minimax", "MiniMax-H3", "video", {"negative_prompt": "模糊", "seed": 42})

    def test_外链形式的素材也放行(self) -> None:
        """界面既可以选素材库里的图,也可以粘外链 —— 后者走 <role>_url 参数。"""
        _check("minimax", "MiniMax-H3", "video", {"first_frame_url": "https://e/a.png"})


class Test智能体拿得到描述符:
    def test_每个模型都报得出它认哪些参数(self) -> None:
        import mcp_server

        for item in BUILTIN_MODELS:
            capabilities = item["capabilities"]
            help_ = mcp_server._parameter_help(capabilities)
            assert set(help_) == set(capabilities.get("parameter_keys") or []), (
                f"{item['id']} 的参数说明和描述符对不上"
            )

    def test_有清单的参数要把清单带出去(self) -> None:
        """只说「支持 duration_seconds」不够 —— 智能体得知道能填 5 还是 10,否则还是在猜。"""
        import mcp_server

        help_ = mcp_server._parameter_help(capabilities_for("minimax", "MiniMax-H3", "video"))
        assert help_["duration_seconds"]["choices"] == [4, 6, 10, 15]
        assert help_["duration_seconds"]["default"] == 6

    def test_素材类参数说清楚要给什么(self) -> None:
        import mcp_server

        help_ = mcp_server._parameter_help(capabilities_for("minimax", "MiniMax-H3", "video"))
        assert "asset_id" in help_["first_frame"]
        assert "asset_id" in help_["last_frame"]

    def test_不在_mcp_里维护第二份参数名单(self) -> None:
        """在那边再列一遍的话,漏掉的那一个不会报错,只会让智能体以为它不存在。

        判据:目录里出现过的每个参数键,_parameter_help 都得处理得了 —— 不能返回空。
        """
        import mcp_server

        every_key = {key for item in BUILTIN_MODELS for key in item["capabilities"].get("parameter_keys") or []}
        fake = {"parameter_keys": sorted(every_key)}
        help_ = mcp_server._parameter_help(fake)
        assert set(help_) == every_key
        assert all(value for value in help_.values()), "有参数键翻不出任何说明"
