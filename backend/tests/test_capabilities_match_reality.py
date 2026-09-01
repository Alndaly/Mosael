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

#: 素材角色名 —— 用来把描述符的 parameter_keys 里"哪些是素材"挑出来。
_SOURCE_ROLE_NAMES = {
    "first_frame", "last_frame",
    "reference_image", "reference_video", "reference_audio",
    "source_video", "first_clip", "driving_audio",
}

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


class TestSeedance官方文档:
    """**来源是官方文档,不是真机** —— 和这个文件里其余几组不一样,标出来是因为两者的分量不同。

    docs.volcengine.com/docs/82379/1520757「创建视频生成任务」,2026-08-28 查。
    08-27 那次真机核的是每一族的**一个成员**(2.0 base 和 1.0 pro),而 fast / mini / 1.5 pro
    当时共用同族的描述符 —— 它们的规格从没被验证过,继承来的值和文档对不上四处:

      · 2.0 fast / mini 官方只到 720p,而它们继承了 base 的 1080p —— 选了必然失败;
      · 2.0 base 官方还支持 4k,我们少了一档;
      · 1.5 pro 时长下限官方是 4,继承来的是 1.0 pro 的 2 —— 选 2、3 秒会失败;
      · 1.0 pro / fast 默认分辨率官方是 1080p,我们写的 720p。

    有密钥能跑到终态之后,该把这几条升级成真机结论并挪进上面那些类。
    """

    def test_ratio取值来自文档原文(self) -> None:
        # 文档原话:「可选值:16:9、4:3、1:1、3:4、9:16、21:9、adaptive」
        assert set(C.ARK_VIDEO_RATIOS) == {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"}

    def test_默认宽高比分模型(self) -> None:
        """文档:2.0 系列 / 1.5 pro 默认 adaptive;1.0 pro 与 fast 文生视频默认 16:9。"""
        assert C.SEEDANCE_2_VIDEO_CAPABILITIES["default_aspect_ratio"] == "adaptive"
        assert C.SEEDANCE_15_VIDEO_CAPABILITIES["default_aspect_ratio"] == "adaptive"
        assert C.SEEDANCE_1_VIDEO_CAPABILITIES["default_aspect_ratio"] == "16:9"

    def test_fast与mini的分辨率只到720p(self) -> None:
        assert C.SEEDANCE_2_SMALL_VIDEO_CAPABILITIES["resolutions"] == ["480p", "720p"]
        assert "4k" in C.SEEDANCE_2_VIDEO_CAPABILITIES["resolutions"]

    def test_15pro的时长下限是4不是2(self) -> None:
        assert C.SEEDANCE_15_VIDEO_CAPABILITIES["min_duration_seconds"] == 4
        assert C.SEEDANCE_1_VIDEO_CAPABILITIES["min_duration_seconds"] == 2

    def test_seed与固定摄像头只挂在1x那一族(self) -> None:
        """文档的支持名单:seed 与 camera_fixed 都是「1.5 pro / 1.0 pro / 1.0 pro fast」,
        2.0 系列不在其中。挂错族的话,2.0 上会多出两个发过去没人认的字段。"""
        for key in ("seed", "camera_fixed"):
            assert key in C.SEEDANCE_1_VIDEO_CAPABILITIES["parameter_keys"]
            assert key not in C.SEEDANCE_2_VIDEO_CAPABILITIES["parameter_keys"]


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


class TestVeo31官方文档:
    """Google Gemini API 文档，2026-09-01：Veo 3.1 支持 720p/1080p/4k；后两档只支持 8 秒。"""

    def test_4k在目录且默认是720p(self) -> None:
        model = next(item for item in C.BUILTIN_MODELS if item["id"] == "google:veo:video")
        cap = model["capabilities"]
        assert cap["resolutions"] == ["720p", "1080p", "4k"]
        assert cap["default_resolution"] == "720p"
        assert cap["duration_by_resolution"] == {"1080p": [8], "4k": [8]}
        assert cap["supports_audio"] is True


class TestOpenAI图片参数:
    def test_高级参数有明确枚举而不是够不着的_adapter_分支(self) -> None:
        cap = C.OPENAI_IMAGE_CAPABILITIES
        assert set(cap["parameter_keys"]) >= {"quality", "background", "output_format", "moderation"}
        assert cap["parameter_choices"]["quality"] == ["auto", "low", "medium", "high"]
        assert cap["parameter_choices"]["output_format"] == ["png", "webp", "jpeg"]


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
        assert C.WAN_27_R2V_CAPABILITIES["source_limits"]["reference_image"] == 5

    def test_首尾帧和参考素材是互斥的两组(self) -> None:
        """接口原话:`first/last frame content cannot be mixed with reference media content`。

        这一条最容易被当成"建议"删掉 —— 它不是。同时给首帧和参考图,提交必然 400。
        """
        for descriptor in (
            C.SEEDANCE_2_VIDEO_CAPABILITIES,
            C.MINIMAX_VIDEO_CAPABILITIES,
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
        for descriptor in (C.WAN_27_T2V_CAPABILITIES, C.WAN_27_I2V_CAPABILITIES, C.WAN_27_R2V_CAPABILITIES):
            assert descriptor["min_duration_seconds"] == 2
            assert descriptor["max_duration_seconds"] == 15

    def test_只有两档清晰度(self) -> None:
        assert set(C.WAN_27_I2V_CAPABILITIES["resolutions"]) == {"720P", "1080P"}

    def test_素材走_media_数组(self) -> None:
        """漏了这一条的后果是提交 200、终态 `Field required: input.media` ——
        目录里挂着的 wan2.7-i2v 此前就是这样,一次都没成功过。"""
        from app.ai.providers.video import wan

        assert wan.uses_media_array("wan2.7-i2v")
        assert not wan.uses_media_array("wan2.5-i2v-preview")


class Test视频编辑与续写:
    """核查日期 2026-08-27,拿用户自己的密钥跑到终态,两条都 SUCCEEDED。

    * **视频编辑** `wan2.7-videoedit`:给一段片子加一句「把画面改成水彩画风格」,
      出的是同一段片子改过之后的样子。文档原话:输入视频「有且仅有 1 个」,2～10 秒。
    * **视频续写** `wan2.7-i2v` + media `first_clip`:成片以那一段开头,后面接着往下拍。
      接口对时长有话说 —— `first_clip duration (2.07s after trim) must be less than the
      requested duration (2s)`,也就是**总时长必须比片段长**。
    """

    def test_视频编辑有自己的描述符_不是拿参考视频凑的(self) -> None:
        """混成 reference_video 的话,用户选了「编辑」拿到的会是一段重拍的片子 ——
        画面出得来,只是根本不是他要的那一段,而界面上看不出哪里不对。"""
        assert C.WAN_VIDEO_EDIT_CAPABILITIES["modes"] == ["video-edit"]
        assert C.WAN_VIDEO_EDIT_CAPABILITIES["source_limits"]["source_video"] == 1
        assert "reference_video" not in C.WAN_VIDEO_EDIT_CAPABILITIES["source_limits"]

    def test_没视频就无从编辑(self) -> None:
        assert C.WAN_VIDEO_EDIT_CAPABILITIES["requires_source"] == [["source_video"]]

    def test_编辑的时长上限是_10_秒_不是_15(self) -> None:
        """和 2.7 生成那一族不一样(那边到 15)。抄串了就是线上失败。"""
        assert C.WAN_VIDEO_EDIT_CAPABILITIES["max_duration_seconds"] == 10

    def test_续写自成一组_不和首尾帧混用(self) -> None:
        groups = [set(group) for group in C.WAN_27_I2V_CAPABILITIES["exclusive_source_groups"]]
        assert {"first_clip"} in groups

    def test_被编辑的那段视频在万相那边叫_video(self) -> None:
        """内部不能也叫 video —— 那个词在这里什么都指(参考视频是视频,续写的片段也是)。"""
        from app.ai.providers.video import wan

        assert wan._MEDIA_TYPES["source_video"] == "video"
        assert wan._MEDIA_TYPES["first_clip"] == "first_clip"
        assert wan.uses_media_array("wan2.7-videoedit")


class Test万相27三个型号各认各的:
    """核查日期 2026-08-27,类型白名单是接口自己报的,每条都跑到终态:

      i2v  `Input should be 'first_frame', 'last_frame', 'driving_audio' or 'first_clip'`
      r2v  `Input should be 'reference_image', 'reference_video' or 'first_frame'`
      r2v  `Only first frame provided is not allowed` / `Field required: input.media`
      t2v  给什么都收,而且照样 SUCCEEDED —— 它根本不看 media
    """

    def test_文生视频一个素材角色都不声明(self) -> None:
        """这条最要命。多声明一个的后果不是报错 —— t2v 收下那张图、跑成功、片子里没有它的
        任何痕迹。用户看到的是"生成好了",而那张参考图从来没被用过。"""
        roles = [k for k in C.WAN_27_T2V_CAPABILITIES["parameter_keys"] if k in _SOURCE_ROLE_NAMES]
        assert roles == [], f"t2v 不看 media,却声明了:{roles}"

    def test_图生视频和参考生视频认的东西不一样(self) -> None:
        """共用一份描述符的话,两边都会长出对方的控件,而选错的那次要等任务失败才知道。"""
        i2v = {k for k in C.WAN_27_I2V_CAPABILITIES["parameter_keys"] if k in _SOURCE_ROLE_NAMES}
        r2v = {k for k in C.WAN_27_R2V_CAPABILITIES["parameter_keys"] if k in _SOURCE_ROLE_NAMES}
        assert i2v == {"first_frame", "last_frame", "first_clip", "driving_audio"}
        assert r2v == {"reference_image", "reference_video", "first_frame"}

    def test_参考生视频不能只给首帧(self) -> None:
        """接口原话 `Only first frame provided is not allowed` —— 这边的首帧只是辅助,
        和 i2v 那边"画面从它动起来"的首帧不是一回事。"""
        assert C.WAN_27_R2V_CAPABILITIES["requires_source"] == [["reference_image", "reference_video"]]

    def test_图生视频必须给起点(self) -> None:
        assert C.WAN_27_I2V_CAPABILITIES["requires_source"] == [["first_frame", "first_clip"]]

    def test_驱动音频只跟首帧走(self) -> None:
        """文档把合法组合列成白名单,续写 + 驱动音频不在里面。靠这条把它挡住。"""
        assert C.WAN_27_I2V_CAPABILITIES["requires_companion"]["driving_audio"] == ["first_frame"]

    def test_带参考视频时时长压到_10_秒(self) -> None:
        """文档原话:包含参考视频 2–10s,不包含 2–15s。写死 15 的话,挂了参考视频再选 12 秒
        要等任务失败才知道;写死 10 的话,不挂参考视频那条路白白少了 5 秒。"""
        assert C.WAN_27_R2V_CAPABILITIES["conditional_max_duration_seconds"] == {"reference_video": 10}


class TestEvolinkSeedance25:
    """核查日期 2026-09-01,Evolink 文档站五份 OpenAPI 逐字核
    (seedance-2.5-{text,image,reference}-to-video、video-{edit,extend})。

    Evolink 把 Seedance 2.5 的五种用法拆成**五个模型 id**,模式在名字里而不是参数里。
    此前目录里一个 2.5 的条目都没有:手动加 `seedance-2.5-image-to-video` 会经「同 vendor
    同 kind 第一条」落到 1.5 的描述符上 —— 时长被压到 4–12(实际 4–30)、默认分辨率错、
    文生不放图也能提交(实际 image_urls 必填,网关 400)。
    """

    def test_五个模式各是一个模型id(self) -> None:
        ids = {model for model, kind, _capabilities in C.EVOLINK_BUILTIN_MODELS if kind == "video"}
        for model in (
            "seedance-2.5-text-to-video",
            "seedance-2.5-image-to-video",
            "seedance-2.5-reference-to-video",
            "seedance-2.5-video-edit",
            "seedance-2.5-video-extend",
        ):
            assert model in ids, f"内置清单缺 {model} —— 用户得手动加,然后落到 1.5 的描述符上"

    def test_时长是_4_到_30_的区间(self) -> None:
        """文档原文:any integer value between 4–30 seconds,另有 -1 = 自动(描述符表达不了,
        先不放 —— 放了会被区间校验拦下)。"""
        for descriptor in (
            C.EVOLINK_SEEDANCE_25_T2V_CAPABILITIES,
            C.EVOLINK_SEEDANCE_25_I2V_CAPABILITIES,
            C.EVOLINK_SEEDANCE_25_R2V_CAPABILITIES,
            C.EVOLINK_SEEDANCE_25_VIDEO_EXTEND_CAPABILITIES,
        ):
            assert descriptor["min_duration_seconds"] == 4
            assert descriptor["max_duration_seconds"] == 30

    def test_图生视频首帧必填_尾帧可选(self) -> None:
        """文档原文:image_urls 必填、1–2 张,1 张自动为首帧、2 张按位置为首帧+尾帧。
        位置语义下「只给尾帧」会被当成首帧 —— 不报错,是悄悄生成反的。"""
        assert C.EVOLINK_SEEDANCE_25_I2V_CAPABILITIES["requires_source"] == [["first_frame"]]
        assert C.EVOLINK_SEEDANCE_25_I2V_CAPABILITIES["source_limits"] == {"first_frame": 1, "last_frame": 1}

    def test_图生视频的宽高比只收_adaptive(self) -> None:
        """文档原文:the only value this model accepts。继承公用那份比例清单的话,
        界面默认发 16:9,网关 400。"""
        assert C.EVOLINK_SEEDANCE_25_I2V_CAPABILITIES["aspect_ratios"] == ["adaptive"]

    def test_全能参考三类素材至少给一份(self) -> None:
        """文档原文:图 1–30 / 视频 1–10 / 音频 1–10,at least one must be provided。"""
        descriptor = C.EVOLINK_SEEDANCE_25_R2V_CAPABILITIES
        assert descriptor["requires_source"] == [["reference_image", "reference_video", "reference_audio"]]
        assert descriptor["source_limits"] == {
            "reference_image": 30, "reference_video": 10, "reference_audio": 10,
        }

    def test_文生视频一个素材角色都不声明(self) -> None:
        """文档原文:does not support image/video/audio input。声明了的话界面会长出素材槽,
        挂上去的图被网关 400 拒掉 —— 或者更糟:被默默忽略。"""
        roles = [k for k in C.EVOLINK_SEEDANCE_25_T2V_CAPABILITIES["parameter_keys"] if k in _SOURCE_ROLE_NAMES]
        assert roles == [], f"2.5 t2v 不收素材,却声明了:{roles}"

    def test_视频编辑只提供自动时长(self) -> None:
        """文档原文:duration 只收 -1(跟随输入,自定义时长被拒)。

        与其把参数藏掉、依赖网关默认，不如把唯一合法值明确声明为“自动”；这样界面、智能体
        和校验器看到的是同一份契约。
        """
        descriptor = C.EVOLINK_SEEDANCE_25_VIDEO_EDIT_CAPABILITIES
        assert "duration_seconds" in descriptor["parameter_keys"]
        assert descriptor["duration_special_values"] == [-1]
        assert descriptor["default_duration_seconds"] == -1

    def test_被处理的那段必填且限一份(self) -> None:
        """文档原文:the first video is the video being edited / extended。视频总数上限 10,
        所以参考视频的上限是 9 而不是 10。"""
        edit = C.EVOLINK_SEEDANCE_25_VIDEO_EDIT_CAPABILITIES
        extend = C.EVOLINK_SEEDANCE_25_VIDEO_EXTEND_CAPABILITIES
        assert edit["requires_source"] == [["source_video"]]
        assert edit["source_limits"]["source_video"] == 1
        assert edit["source_limits"]["reference_video"] == 9
        assert extend["requires_source"] == [["first_clip"]]
        assert extend["source_limits"]["first_clip"] == 1
        assert extend["source_limits"]["reference_video"] == 9


def test_这道棘轮扫得到东西() -> None:
    """假阴性比红更危险:哪天描述符改了名,上面几条会一起真空通过。"""
    assert C.WAN_VIDEO_CAPABILITIES["sizes"]
    assert C.QWEN_TEXT_IMAGE_CAPABILITIES["sizes"]
    assert C.MINIMAX_VIDEO_CAPABILITIES["duration_seconds"]
    assert C.SEEDANCE_2_VIDEO_CAPABILITIES["source_limits"]
    assert C.WAN_27_I2V_CAPABILITIES["resolutions"]
    assert C.WAN_VIDEO_EDIT_CAPABILITIES["source_limits"]
    assert C.WAN_27_I2V_CAPABILITIES["source_limits"]
    assert C.WAN_27_R2V_CAPABILITIES["source_limits"]
    assert C.EVOLINK_SEEDANCE_25_R2V_CAPABILITIES["source_limits"]
    assert C.EVOLINK_SEEDANCE_25_VIDEO_EDIT_CAPABILITIES["source_limits"]
