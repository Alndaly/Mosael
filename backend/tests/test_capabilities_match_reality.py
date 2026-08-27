"""描述符要和供应商的真实接口对得上。

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。

这里**不打真实接口**(那要密钥、要花钱、要等几分钟)。它钉的是**已经用真机核过的那些结论**
不被悄悄改回去 —— 每一条都标了核查日期和当时接口的原话。

## 核查这类东西时踩过的坑

**「提交成功」不等于「支持」。** 万相(DashScope)提交时根本不校验参数:传 duration=3
返回 200,任务跑起来才回 `duration customization is not supported`。只看提交响应的话,
会把每一个参数都当成"支持"。**必须等任务终态。**

**接口的错误信息常常直接给出权威清单。** 万相视频传一个不在清单里的尺寸,它会回
`size must be in 1080*1920,1920*1080,…` —— 比翻文档准,因为那是这一刻的真实行为。
"""

from __future__ import annotations

RATCHET = True

from app.domain.generation import catalog as C


class Test万相视频:
    """核查日期 2026-08-27。接口原话:
    `size must be in 1080*1920,1920*1080,1440*1440,1632*1248,1248*1632,480*832,832*480,624*624`
    """

    AUTHORITATIVE = {
        "1080*1920", "1920*1080", "1440*1440", "1632*1248",
        "1248*1632", "480*832", "832*480", "624*624",
    }

    def test_尺寸不超出接口给的清单(self) -> None:
        """多写一个的后果不是报错,是用户选了它、任务跑到一半才失败。
        此前 `1280*720` / `720*1280` 就是这样 —— 两个都不在清单里。"""
        declared = set(C.WAN_VIDEO_CAPABILITIES["sizes"])
        assert declared <= self.AUTHORITATIVE, f"这些尺寸接口不认:{sorted(declared - self.AUTHORITATIVE)}"

    def test_默认尺寸在清单里(self) -> None:
        assert C.WAN_VIDEO_CAPABILITIES["default_size"] in self.AUTHORITATIVE

    def test_时长只有_5_秒(self) -> None:
        """真机验过:3s 和 8s 提交都返回 200,任务终态是 FAILED
        `duration customization is not supported`。**这条最容易被"提交成功"骗到。**"""
        assert C.WAN_VIDEO_CAPABILITIES["duration_seconds"] == [5]


class TestSeedance2:
    """核查日期 2026-08-27,doubao-seedance-2-0-260128。
    3s → 400;4s/7s/12s/15s → 200 且任务成功;16s → 400。
    """

    def test_时长是区间不是枚举(self) -> None:
        cap = C.SEEDANCE_2_VIDEO_CAPABILITIES
        assert cap["duration_seconds"] == []
        assert (cap["min_duration_seconds"], cap["max_duration_seconds"]) == (4, 15)


class Test通义图像:
    """核查日期 2026-08-27,qwen-image。接口原话:`Size 1*1 is out of range [512*512, 2048*2048]`。

    声明的五个档**逐个跑过,全都成功**。真实范围比这宽(区间内任意尺寸),留五个常用档
    是有意的保守 —— 不是错。
    """

    def test_声明的档都在接口允许的范围内(self) -> None:
        for size in C.QWEN_TEXT_IMAGE_CAPABILITIES["sizes"]:
            width, height = (int(part) for part in size.replace("*", "x").split("x"))
            assert 512 <= width <= 2048, f"{size} 的宽超出 [512, 2048]"
            assert 512 <= height <= 2048, f"{size} 的高超出 [512, 2048]"


class TestSeedream4:
    """核查日期 2026-08-27。接口原话:`image size must be at least 921600 pixels`。

    真机逐个跑过:1280x720 / 960x960 / 1024x1024 / 2048x2048 / 2560x1440 / 4096x4096 全部通过。
    **约束是总像素数,不是固定档** —— 原注释推断"故不提供 1024 档"是错的(1024x1024 是
    1048576 像素,高于下限)。
    """

    def test_每个档都过得了像素下限(self) -> None:
        cap = C.SEEDREAM_4_IMAGE_CAPABILITIES
        low = cap["min_size_pixels"]
        for size in cap["sizes"]:
            width, height = (int(part) for part in size.split("x"))
            assert width * height >= low, f"{size} 只有 {width * height} 像素,低于下限 {low}"

    def test_常用横屏档在表里(self) -> None:
        """1280x720 此前不在表里,而它正好是下限、也是最常用的横屏尺寸。"""
        assert "1280x720" in C.SEEDREAM_4_IMAGE_CAPABILITIES["sizes"]


class TestComfyUI:
    """核查日期 2026-08-27,本地 ComfyUI 0.34.0。端到端跑通:工作流转换(14 节点)→ 参数注入
    → 提交 → 35 秒生成成功。

    **它的能力取决于用户装的工作流**,所以描述符里那几个尺寸档只是缺省值 —— 真正可调的
    参数由 extract_workflow_params 从工作流里扫出来(那次扫到 20 个,并正确识别出
    prompt / negative / seed 三个角色)。
    """

    def test_声明了需要工作流模板(self) -> None:
        """漏了这条的话,界面会把 ComfyUI 当成一个开箱即用的模型 —— 而它没有工作流跑不了。"""
        assert C.COMFYUI_VIDEO_CAPABILITIES.get("requires_workflow_template") is True


class TestOpenAI图像:
    """核查日期 2026-08-27(gpt-image-2,经 147ai)。接口原话:
    `Width and height must both be divisible by 16.` 与
    `Requested resolution is below the current minimum pixel budget.`

    实测:1024x1024 / 1536x1024 / 1024x1536 / 1280x720 / 1920x1088 / 896x896 通过;
    768x768、1024x576、832x480、512x512 被拒。**约束是整除 16 + 像素下限,不是固定档。**
    """

    def test_每个档的宽高都能被_16_整除(self) -> None:
        cap = C.OPENAI_IMAGE_CAPABILITIES
        for size in cap["sizes"]:
            width, height = (int(part) for part in size.split("x"))
            assert width % cap["size_multiple_of"] == 0, f"{size} 的宽不是 16 的倍数"
            assert height % cap["size_multiple_of"] == 0, f"{size} 的高不是 16 的倍数"

    def test_每个档都在像素下限之上(self) -> None:
        """下限二分在 (589824, 802816] 之间。低于它的档选了必然失败。"""
        for size in C.OPENAI_IMAGE_CAPABILITIES["sizes"]:
            width, height = (int(part) for part in size.split("x"))
            assert width * height > 589824, f"{size} 只有 {width * height} 像素,实测这一档会被拒"

    def test_常用横屏档在表里(self) -> None:
        assert "1280x720" in C.OPENAI_IMAGE_CAPABILITIES["sizes"]


class Test海螺视频:
    """核查日期 2026-08-27,MiniMax-H3 的 /v2/video_generation。接口原话:
    `supported durations: 4s, 5s, 6s, 7s, 8s, 9s, 10s, 11s, 12s, 13s, 14s, 15s`
    `supported resolutions: 768P, 2K`
    """

    def test_十二个时长档一个都不能少(self) -> None:
        """此前只写了 4/6/10/15 四个 —— 剩下八个用户在界面上根本选不到。"""
        assert set(C.MINIMAX_VIDEO_CAPABILITIES["duration_seconds"]) == set(range(4, 16))

    def test_便宜的那一档在表里(self) -> None:
        """768P 是跑得快、便宜的那一档,做草稿正该用它;此前表里只有 2K。"""
        assert set(C.MINIMAX_VIDEO_CAPABILITIES["resolutions"]) == {"768P", "2K"}


class Test参考素材的份数上限:
    """核查日期 2026-08-27。火山方舟与 MiniMax 各自报出的数字**完全一致**。

    火山原话:
      `expected at most 9 reference images but got 10 instead`
      `expected at most 3 video contents but got 4 instead`
      `expected at most 3 audio contents but got 4 instead`
      `expected at most one first frame image content but got 2 instead`
    MiniMax 原话(中文):
      `reference 场景参考图最多 9 张` / `参考视频最多 3 个` / `参考音频最多 3 段`
    """

    AUTHORITATIVE = {
        "first_frame": 1, "last_frame": 1,
        "reference_image": 9, "reference_video": 3, "reference_audio": 3,
    }

    def test_火山和海螺都按接口给的数字来(self) -> None:
        """多写一份的后果不是报错,是用户挂满十张、提交时吃一个英文 400。"""
        for descriptor in (C.SEEDANCE_2_VIDEO_CAPABILITIES, C.MINIMAX_VIDEO_CAPABILITIES):
            assert descriptor["source_limits"] == self.AUTHORITATIVE

    def test_万相是另一套数字_别照抄(self) -> None:
        """文档原话:参考图像 + 参考视频不超过 5 个。每家自己一套,抄串了就是线上失败。"""
        assert C.WAN_27_VIDEO_CAPABILITIES["source_limits"]["reference_image"] == 5

    def test_首尾帧和参考素材是互斥的两组(self) -> None:
        """接口原话:`first/last frame content cannot be mixed with reference media content`。

        这一条最容易被当成"建议"删掉 —— 它不是。同时给首帧和参考图,提交必然 400。
        """
        for descriptor in (
            C.SEEDANCE_2_VIDEO_CAPABILITIES,
            C.MINIMAX_VIDEO_CAPABILITIES,
            C.WAN_27_VIDEO_CAPABILITIES,
        ):
            groups = [set(group) for group in descriptor["exclusive_source_groups"]]
            assert {"first_frame", "last_frame"} in groups
            assert {"reference_image", "reference_video", "reference_audio"} in groups

    def test_参考音频不能单独上场(self) -> None:
        """接口原话:`reference_audio cannot be the only reference input`。"""
        companions = C.SEEDANCE_2_VIDEO_CAPABILITIES["requires_companion"]["reference_audio"]
        assert set(companions) == {"reference_image", "reference_video"}


class TestSeedance1:
    """核查日期 2026-08-27,方舟 doubao-seedance-1-0-pro-250528。接口原话:
    `duration ... must be greater than or equal to 2` / `must be less than or equal to 12`
    2/3/5/10/12 秒的任务都跑到了 succeeded;`2k` 被拒。
    """

    def test_时长是_2_到_12_的区间_不是两个档(self) -> None:
        assert C.SEEDANCE_1_VIDEO_CAPABILITIES["duration_seconds"] == []
        assert C.SEEDANCE_1_VIDEO_CAPABILITIES["min_duration_seconds"] == 2
        assert C.SEEDANCE_1_VIDEO_CAPABILITIES["max_duration_seconds"] == 12

    def test_它在方舟上_不在_LAS(self) -> None:
        """拿方舟密钥打 LAS 一律 401 —— 那条路从来没通过,而设置里只让配一份火山密钥。"""
        assert C.SEEDANCE_1_VIDEO_CAPABILITIES["endpoint"] == "ark"

    def test_不认_2k(self) -> None:
        assert "2k" not in [one.lower() for one in C.SEEDANCE_1_VIDEO_CAPABILITIES["resolutions"]]


class Test万相27:
    """核查日期 2026-08-27,拿用户自己的密钥跑到终态。接口原话:
    `Field required: input.media`(拿 2.5 的 img_url 形状打 2.7 的下场)
    `Duration should be between 2 and 15`
    `Input should be '1080P' or '720P'`
    """

    def test_时长是_2_到_15_的区间(self) -> None:
        assert C.WAN_27_VIDEO_CAPABILITIES["min_duration_seconds"] == 2
        assert C.WAN_27_VIDEO_CAPABILITIES["max_duration_seconds"] == 15

    def test_只有两档清晰度(self) -> None:
        assert set(C.WAN_27_VIDEO_CAPABILITIES["resolutions"]) == {"720P", "1080P"}

    def test_素材走_media_数组(self) -> None:
        """漏了这一条的后果是提交 200、终态 `Field required: input.media` ——
        目录里挂着的 wan2.7-i2v 此前就是这样,一次都没成功过。"""
        from app.ai.providers.video import wan

        assert wan.uses_media_array("wan2.7-i2v")
        assert not wan.uses_media_array("wan2.5-i2v-preview")


def test_这道棘轮扫得到东西() -> None:
    """假阴性比红更危险:哪天描述符改了名,上面几条会一起真空通过。"""
    assert C.WAN_VIDEO_CAPABILITIES["sizes"]
    assert C.QWEN_TEXT_IMAGE_CAPABILITIES["sizes"]
    assert C.MINIMAX_VIDEO_CAPABILITIES["duration_seconds"]
    assert C.SEEDANCE_2_VIDEO_CAPABILITIES["source_limits"]
    assert C.WAN_27_VIDEO_CAPABILITIES["resolutions"]
