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

from app.ai.providers import get_generation_adapter
from app.ai.providers.contracts.generation import GenerationRequest
from app.domain.generation.catalog import BUILTIN_MODELS, capabilities_for, known_capabilities_for
from app.domain.generation.operations import (
    GenerationDomainError,
    requested_negative_prompt,
    validate_against_capabilities,
)


def _check(provider: str, model: str, kind: str, parameters=None, sources=None) -> None:
    validate_against_capabilities(provider, model, kind, parameters or {}, sources or [])


def test_每个内置模型声明的边界值都能通过自己的适配器校验() -> None:
    """目录是产品承诺，Adapter 的公共护栏不能再用一份较小的旧白名单推翻它。

    这条测试覆盖曾经实际互相冲突的四类能力：15 秒、2K、4K，以及 -1=自动时长。
    这里只校验 Adapter 的入口契约，不发送网络请求。
    """
    for item in BUILTIN_MODELS:
        provider = get_generation_adapter(item["provider"], item["kind"])
        assert provider is not None, item["id"]
        capabilities = item["capabilities"]
        parameters: dict[str, object] = {}
        if item["kind"] == "image":
            parameters["num_images"] = int(capabilities.get("max_num_images") or 1)
        else:
            special = list(capabilities.get("duration_special_values") or [])
            durations = list(capabilities.get("duration_seconds") or [])
            parameters["duration_seconds"] = (
                special[0]
                if special and capabilities.get("default_duration_seconds") in special
                else capabilities.get("max_duration_seconds")
                or (max(durations) if durations else capabilities.get("default_duration_seconds") or 5)
            )
            resolutions = list(capabilities.get("resolutions") or [])
            if resolutions:
                parameters["resolution"] = resolutions[-1]
        provider.validate_request(
            GenerationRequest(
                kind=item["kind"],
                model=item["model"],
                prompt="contract check",
                parameters=parameters,
            )
        )


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

    def test_供应商自己的枚举参数也统一校验(self) -> None:
        _check("openai", "gpt-image-2", "image", {"quality": "high", "output_format": "webp"})
        with pytest.raises(GenerationDomainError, match="quality 只能是"):
            _check("openai", "gpt-image-2", "image", {"quality": "ultra"})

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

    def test_同供应商的未知模型也不继承另一型号的限制(self) -> None:
        """用户填了同一网关的新模型名时，我们依然是“不知道”，不是“和目录第一项一样”。

        Evolink 的目录第一项恰好是 Seedance 1.5；旧实现会让任意 Evolink 视频都继承它的
        4–12 秒限制，导致网关真实支持的 20 秒在本地被误拒。
        """
        assert known_capabilities_for("evolink", "vendor-new-video-model", "video") is None
        _check("evolink", "vendor-new-video-model", "video", {"duration_seconds": 20})

    def test_同供应商未知模型的界面描述符也不伪造第一款型号的参数(self) -> None:
        """校验放行还不够：UI 若继承 Seedance 的默认时长，提交时仍会偷偷带上 5 秒。"""
        capabilities = capabilities_for("evolink", "vendor-new-video-model", "video")
        assert capabilities == {"modes": ["text-to-video"], "parameter_keys": []}
        assert "duration_seconds" not in capabilities
        assert "source_roles" not in capabilities

    def test_参数必须由模型显式声明_不能全局放行后被静默忽略(self) -> None:
        """MiniMax Adapter 不发送 seed/negative_prompt；放行会得到“成功但没按要求生成”。"""
        with pytest.raises(GenerationDomainError, match="不支持这些参数"):
            _check("minimax", "MiniMax-H3", "video", {"seed": 42})
        _check("alibaba", "qwen-image", "image", {"seed": 42, "negative_prompt": "模糊"})

    def test_高分辨率可以约束合法时长组合(self) -> None:
        _check("google", "veo", "video", {"resolution": "4k", "duration_seconds": 8})
        with pytest.raises(GenerationDomainError, match="4k.*8"):
            _check("google", "veo", "video", {"resolution": "4k", "duration_seconds": 4})

    def test_布尔参数拒绝真值字符串(self) -> None:
        with pytest.raises(GenerationDomainError, match="prompt_extend.*布尔"):
            _check("alibaba", "qwen-image", "image", {"prompt_extend": "false"})
        _check("alibaba", "qwen-image", "image", {"prompt_extend": False})

    def test_参数里的负向提示会提升到统一请求字段(self) -> None:
        assert requested_negative_prompt("", {"negative_prompt": "模糊"}) == "模糊"
        assert requested_negative_prompt("顶层优先", {"negative_prompt": "参数值"}) == "顶层优先"

    def test_可灵普通版不冒充_omni_参考主体能力(self) -> None:
        references = [
            {"asset_id": "a", "role": "reference_image"},
            {"asset_id": "b", "role": "reference_image"},
        ]
        with pytest.raises(GenerationDomainError, match="不支持"):
            _check("kuaishou", "kling-v3", "video", {}, references)
        _check("kuaishou", "kling-v3-omni", "video", {}, references)

    def test_外链形式的素材也放行(self) -> None:
        """界面既可以选素材库里的图,也可以粘外链 —— 后者走 <role>_url 参数。"""
        _check("minimax", "MiniMax-H3", "video", {"first_frame_url": "https://e/a.png"})

    def test_外链角色也必须是这个模型声明支持的(self) -> None:
        """URL 只是素材的另一种传输形式，不能借它绕过角色约束。"""
        with pytest.raises(GenerationDomainError, match="不支持这些参数"):
            _check(
                "evolink",
                "seedance-2.5-text-to-video",
                "video",
                {"first_frame_url": "https://e/a.png"},
            )
        with pytest.raises(GenerationDomainError, match="不支持这些参数"):
            _check(
                "evolink",
                "seedance-2.5-reference-to-video",
                "video",
                {
                    "first_frame_url": "https://e/a.png",
                    "reference_image_url": "https://e/ref.png",
                },
            )

    def test_源视频的兼容别名和正式参数同权(self) -> None:
        """video_url 是 SOURCE_VIDEO 的兼容别名；别名表声明了就必须能通过统一校验。"""
        _check("evolink", "seedance-2.5-video-edit", "video", {"video_url": "https://e/a.mp4"})

    def test_区间时长可以额外声明特殊值(self) -> None:
        """Seedance 2.5 的 -1=自动，与 4–30 秒区间并存。"""
        _check("evolink", "seedance-2.5-text-to-video", "video", {"duration_seconds": -1})
        _check("evolink", "seedance-2.5-text-to-video", "video", {"duration_seconds": 30})
        with pytest.raises(GenerationDomainError, match="时长"):
            _check("evolink", "seedance-2.5-text-to-video", "video", {"duration_seconds": 3})

    @pytest.mark.parametrize("value", ["五秒", 5.5, True])
    def test_时长必须是整数_不能在适配器里崩溃或被截断(self, value) -> None:
        with pytest.raises(GenerationDomainError, match="duration_seconds.*整数"):
            _check("evolink", "seedance-2.5-text-to-video", "video", {"duration_seconds": value})

    def test_外链也算给了_必填不拦粘链接的(self) -> None:
        """requires_source 只数素材库那一路的话,粘外链的用户会被误拦在「必须给一份首帧」——
        而界面和智能体本来就可以不选素材、直接给链接,两条路进来的是同一样。"""
        _check("evolink", "seedance-2.5-image-to-video", "video", {"first_frame_url": "https://e/a.png"})
        _check("evolink", "seedance-2.5-video-edit", "video", {"source_video_url": "https://e/a.mp4"})
        with pytest.raises(GenerationDomainError, match="必须给一份首帧"):
            _check("evolink", "seedance-2.5-image-to-video", "video", {})

    def test_外链也计入份数上限(self) -> None:
        """同权是双向的:必填要认外链,上限也要认 —— 不然上限那一侧就成了漏洞。"""
        with pytest.raises(GenerationDomainError, match="最多收 1 份"):
            _check(
                "evolink", "seedance-2.5-image-to-video", "video",
                {"first_frame_url": ["https://e/a.png", "https://e/b.png"]},
            )

    def test_seedance20图生必须有首帧且尾帧不能单独提交(self) -> None:
        _check(
            "evolink",
            "seedance-2.0-image-to-video",
            "video",
            {},
            [{"asset_id": "first", "role": "first_frame"}],
        )
        _check(
            "evolink",
            "seedance-2.0-image-to-video",
            "video",
            {},
            [
                {"asset_id": "first", "role": "first_frame"},
                {"asset_id": "last", "role": "last_frame"},
            ],
        )
        with pytest.raises(GenerationDomainError, match="必须给一份首帧"):
            _check("evolink", "seedance-2.0-image-to-video", "video")
        # 图生模型的起点规则先于搭伴规则执行；只给尾帧时应直接指出缺少首帧。
        with pytest.raises(GenerationDomainError, match="必须给一份首帧"):
            _check(
                "evolink",
                "seedance-2.0-image-to-video",
                "video",
                {},
                [{"asset_id": "last", "role": "last_frame"}],
            )

    def test_seedance20参考音频必须搭配图或视频(self) -> None:
        with pytest.raises(GenerationDomainError, match="参考音频.*参考图.*参考视频"):
            _check(
                "evolink",
                "seedance-2.0-reference-to-video",
                "video",
                {},
                [{"asset_id": "audio", "role": "reference_audio"}],
            )
        _check(
            "evolink",
            "seedance-2.0-reference-to-video",
            "video",
            {},
            [
                {"asset_id": "image", "role": "reference_image"},
                {"asset_id": "audio", "role": "reference_audio"},
            ],
        )


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

    def test_布尔参数明确给出真假选项(self) -> None:
        import mcp_server

        help_ = mcp_server._parameter_help(capabilities_for("alibaba", "qwen-image", "image"))
        assert help_["prompt_extend"] == {"choices": [True, False], "default": True}

    def test_供应商枚举参数也带选项(self) -> None:
        import mcp_server

        help_ = mcp_server._parameter_help(capabilities_for("openai", "gpt-image-2", "image"))
        assert help_["quality"] == {"choices": ["auto", "low", "medium", "high"], "default": "auto"}

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
        from app.ai.providers.contracts.generation import SOURCE_ROLES
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


class Test描述符里素材规矩的形状:
    """四条素材规矩各有各的形状,写混了**不会报错** —— 只是校验时报一串天书。

    这条测试是为一件真事写的:EVOLINK_SEEDANCE_15 把「尾帧要搭配首帧」写成了
    `requires_source: {"last_frame": ["first_frame"]}` —— 那是 requires_companion 的字典
    形状,而 requires_source 是列表的列表。字典迭代出的是键字符串,于是报错把 "last_frame"
    逐字符拆开拼成「必须给一份l或a或s或t或_或f或r或a或m或e」;更糟的是
    `set("last_frame") & used` 拿字符集去碰角色名,永远为空 —— 走这份描述符的生成
    (文生视频、图生视频)全被拦下,挂不挂素材都救不了。
    """

    def test_requires_source_是列表的列表(self) -> None:
        """每一条是「这几种里至少给一份」 —— 写成字典,校验时迭代出的就是键字符串。"""
        from app.ai.providers.contracts.generation import SOURCE_ROLES

        for item in BUILTIN_MODELS:
            requires = item["capabilities"].get("requires_source") or []
            assert isinstance(requires, list), f"{item['id']} 的 requires_source 应是列表的列表"
            for options in requires:
                assert isinstance(options, (list, tuple)), (
                    f"{item['id']} 的 requires_source 里混进了 {type(options).__name__}"
                )
                for role in options:
                    assert role in SOURCE_ROLES, f"{item['id']} 的 requires_source 有未知角色 {role}"

    def test_requires_companion_是角色到列表的字典(self) -> None:
        from app.ai.providers.contracts.generation import SOURCE_ROLES

        for item in BUILTIN_MODELS:
            companions = item["capabilities"].get("requires_companion") or {}
            assert isinstance(companions, dict), f"{item['id']} 的 requires_companion 应是字典"
            for role, others in companions.items():
                assert role in SOURCE_ROLES, f"{item['id']} 的 requires_companion 有未知角色 {role}"
                assert isinstance(others, (list, tuple)), (
                    f"{item['id']} 的 requires_companion[{role}] 应是角色列表"
                )
                for other in others:
                    assert other in SOURCE_ROLES, f"{item['id']} 的 requires_companion 有未知角色 {other}"

    def test_上限与互斥组的形状(self) -> None:
        from app.ai.providers.contracts.generation import SOURCE_ROLES

        for item in BUILTIN_MODELS:
            limits = item["capabilities"].get("source_limits") or {}
            assert isinstance(limits, dict), f"{item['id']} 的 source_limits 应是字典"
            for role, cap in limits.items():
                assert role in SOURCE_ROLES, f"{item['id']} 的 source_limits 有未知角色 {role}"
                assert isinstance(cap, int) and cap >= 1, f"{item['id']} 的 source_limits[{role}] 应是正整数"
            for group in item["capabilities"].get("exclusive_source_groups") or []:
                assert isinstance(group, (list, tuple)), (
                    f"{item['id']} 的 exclusive_source_groups 里混进了 {type(group).__name__}"
                )
                for role in group:
                    assert role in SOURCE_ROLES, f"{item['id']} 的互斥组有未知角色 {role}"
