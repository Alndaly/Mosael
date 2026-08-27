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
        """海螺认 4–15 的每一个整数(接口自己报的清单),20 秒不在里面。"""
        _check("minimax", "MiniMax-H3", "video", {"duration_seconds": 7})
        with pytest.raises(GenerationDomainError, match="时长只能是"):
            _check("minimax", "MiniMax-H3", "video", {"duration_seconds": 20})

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
        """只说「支持 duration_seconds」不够 —— 智能体得知道能填哪几个,否则还是在猜。"""
        import mcp_server

        help_ = mcp_server._parameter_help(capabilities_for("minimax", "MiniMax-H3", "video"))
        assert help_["duration_seconds"]["choices"] == list(range(4, 16))
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


class Test角色只有一张表:
    """新增一种素材角色时,**漏掉哪一处都不会报错**。

    这条测试是为一件真事写的:角色从四种长到八种,而 mcp_server 里那份手抄的名单停在四种 ——
    参考音频、待编辑的视频、待续写的片段、驱动音频,智能体根本不知道它们存在,于是永远不会用。
    没有任何测试会红,界面也一切正常。
    """

    def test_每种角色都有名字和说明(self) -> None:
        from app.ai.providers.base import SOURCE_ROLES
        from app.domain.generation.catalog import SOURCE_ROLE_HELP, SOURCE_ROLE_LABELS

        assert set(SOURCE_ROLES) == set(SOURCE_ROLE_LABELS), "角色和中文名对不上"
        assert set(SOURCE_ROLES) == set(SOURCE_ROLE_HELP), "角色和给智能体的说明对不上"

    def test_报错和智能体读的是同一张表(self) -> None:
        """两份的话,同一个角色在报错里叫「参考图」、在智能体那儿叫别的,谁也对不上号。"""
        from app.domain.generation import operations
        from app.domain.generation.catalog import SOURCE_ROLE_LABELS

        assert operations._label("reference_video") == SOURCE_ROLE_LABELS["reference_video"]


class Test智能体拿得到素材的规矩:
    """光知道"支持哪些角色"不够 —— 智能体会同时给首帧和参考图(接口硬约束,必然 400),
    或者拿视频编辑模型不给视频。每一条都会被提交前的校验拦下,但那是一次可见的失败,
    而这些规矩本来就可以先说。"""

    def _rules(self, provider: str, model: str, kind: str) -> list[str]:
        import mcp_server

        return mcp_server._source_rules(capabilities_for(provider, model, kind))

    def test_互斥说出来(self) -> None:
        rules = self._rules("bytedance", "doubao-seedance-2-0-260128", "video")
        assert any("只能用一组" in one for one in rules)

    def test_必填说出来(self) -> None:
        assert any("必须给" in one for one in self._rules("alibaba", "wan2.7-videoedit", "video"))

    def test_搭伴说出来(self) -> None:
        rules = self._rules("bytedance", "doubao-seedance-2-0-260128", "video")
        assert any("参考音频要搭配" in one for one in rules)

    def test_张数进了参数说明(self) -> None:
        import mcp_server

        help_ = mcp_server._parameter_help(capabilities_for("bytedance", "doubao-seedance-2-0-260128", "video"))
        assert "最多 9 份" in help_["reference_image"]

    def test_没规矩的模型不要硬编出一条(self) -> None:
        """纯文生视频没有任何素材,规矩列表就该是空的 —— 凭空多一句只会让智能体去猜它的意思。"""
        assert self._rules("alibaba", "wan2.7-t2v", "video") == []


class Test模板串里的冒号:
    """`素材id:角色` 这个写法和模板串撞车了 —— 模板自己也可能带冒号。

    从左边切的话,`{{node.a:b}}` 会被腰斩成 `{{node.a` + 角色 `b}}`,报一句「未知的素材角色」,
    而用户看着自己那行写得好好的。前端序列化用的是右起规则,后端得是同一条。
    """

    def _parse(self, text: str):
        from app.domain.generation.operations import parse_source_assets

        return parse_source_assets(text, kind="video")

    def test_正常的角色照旧(self) -> None:
        assert self._parse("a1:last_frame") == [{"asset_id": "a1", "role": "last_frame"}]

    def test_模板串整条留住(self) -> None:
        assert self._parse("{{node.a:b}}")[0]["asset_id"] == "{{node.a:b}}"

    def test_模板串加角色两边都对(self) -> None:
        assert self._parse("{{gen-1.asset_id}}:reference_image") == [
            {"asset_id": "{{gen-1.asset_id}}", "role": "reference_image"}
        ]

    def test_角色拼错了要报错_不能默默走默认(self) -> None:
        """默默走默认的话:任务照样成功,只是那张图当成了别的用途,而界面上什么都没说。"""
        from app.domain.generation.operations import GenerationDomainError

        with pytest.raises(GenerationDomainError, match="bogus"):
            self._parse("a1:bogus")

    def test_不像角色名的后半段不算角色(self) -> None:
        """`C1` 有大写,不是角色名的样子 —— 那个冒号是模板串自己的。"""
        assert self._parse("{{a.b:C1}}")[0]["asset_id"] == "{{a.b:C1}}"
