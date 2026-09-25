"""**官方价目表:各家在自己价目页上挂出来的单价,以及每一个数是从哪一页抄来的。**

## 为什么需要这张表

「按目录预填」原本只有一个价源:供应商的 `/models` 目录(或订阅登录时带回的那份)。而**多数
端点根本不在目录里报价** —— DeepSeek、百炼、方舟、Kimi、MiniMax 的官方端点都只列 id。于是
用户点下去,得到的几乎总是「没有新建规则」,几十个模型只能一条条手抄。生图、生视频、语音合成
更是从来没被预填过:目录只可能给对话的 token 价。

这张表补的就是这一块。它和 `domain/model_limits` 是同一性质:**查证过的事实**,不是猜。

## 五条约定

1. **只写查证过的。**每一条都要能在它记的那一页上找到原数;查不到、页面打不开、写得有歧义的
   一律不收(列在下面的「未收录」里)。不从同门型号外推,不用第三方汇总站当来源。
2. **按厂商原样记。**币种照抄(人民币就是 CNY,不换算成美元);厂商按「元/万字符」报的,
   `per=10_000` 记在条目上,而不是自己先除好 —— 这样对着价目页一眼能核。
3. **分档的价格只记基础档,并在备注里写明。**千问按输入长度分档、万相按分辨率分档、Seedance
   分「含不含视频输入」:计价规则没有按档位匹配的能力,所以记最常用的那一档(输入最短 / 应用
   默认的 720P / 不含视频输入),备注里把其余档位写出来,用户用的是别的档一眼就知道要改。
   拿不准哪档算"基础"的,宁可不收。
4. **分时段的价按厂商的时段原样记。**高峰 / 空闲这种按钟点变的价是**同一条规则**的价目
   (见 `domain/price_schedule`):条目的 `amount` 是厂商说的「其余时段」那个价,`time_prices`
   是它明确列出钟点的时段,`time_zone` 是它公布时段用的时区 —— 不替厂商换算成 UTC。
   厂商只说了「其余时段」的,「其余」就是基础价(DeepSeek:列出的是高峰,其余全是空闲)。
5. **中转站只按 id 精确匹配,而且只在 id 唯一属于某一家时。**中转(OpenAI 兼容端点、Evolink、
   OpenRouter)后面挂的可能是任何一家,它们自己的收费也可能和原厂不同 —— 所以只在「这个 id
   只有一家在卖」时才借用原厂价,并在规则备注里说明那是原厂价。

## 来源(2026-09 查证)

每一条都带自己的 `source`(价目页 URL)与 `checked`(查证年月),规则备注里会原样带上。
`tests/test_price_reference.py` 盯着这张表的形状:有来源、有日期、金额为正、单位与能力都是
系统认识的、换算成 micros 不丢精度、同一格不重复。

改一条就更新那一条的 `checked`;价目页改版了就整家重查,不要只改一个数。

## 未收录(2026-09 这一轮)

- **价目页上已经没有的**:deepseek-chat / deepseek-reasoner、moonshot-v1-* / kimi-latest、MiniMax-M1 /
  Text-01、Veo 3.0 / 2.0、方舟在国内已关停的 Seedance 1.5 pro / 1.0 lite、Seedream 3.0、SeedEdit 3.0。
- **只给比例、不给数字的**:百炼的缓存命中价(「标准输入价的 20% / 10%」);qwen3.8-max / flash 的缓存价
  只在控制台里有。
- **拿不准基础档的**:wan2.2-t2v-plus(没有 720P 档)、wan2.6-i2v-flash(有声 / 无声两价,适配器不指定)、
  qwen-image-3.0-pro(1K / 2K 两价)、Seedream 5.0 pro(按像素两档)、MiniMax-H3-Max(480P / 768P)。
- **计量对不上的**:qwen-tts-flash、gpt-4o-mini-tts 按 token 计价,而语音合成记的是字符数。
- **对应关系要靠推断的**:火山 seed-tts-1.0(价目页不用这个名字)。
- **应用里的连接做不了的**:方舟的豆包对话模型、MiniMax 语音与生图、Gemini 对话与生图 —— 价查到了,
  等对应的适配器接入、预设声明了能力再收(测试盯着「能力必须是这家连接提供的」)。
- **可灵(Kling)**:按「单位 / 积分」计价,国内 1 积分 = 1 元、国际 1 单位 = $0.14,一家两币;而应用
  判断不出这条连接开的是哪边的账户,又分有声 / 无声、带不带视频输入 —— 不收。
- **中转站自己的价**(Evolink、147ai 等):不是原厂价目,不在这张表的范围里;中转的目录报了价就用目录的。
  Evolink 上的 Suno(产品页写「8 积分 ≈ $0.118 / 两首」)同理不收。
- **音频生成(ADR 0022)没收的**:MiniMax 音乐(价目页把 Music-3.0 / 2.6 标成「已下线」,2026-08-20 起不再
  对新用户开放);可灵文生音效 / 视频生音效(每次 0.25 单位 / 积分,和可灵视频同一个一家两币的问题);
  百炼 qwen-audio-3.1-tts-next(按 token 计价,而文档说计费按生成时长,换算关系没写);火山音乐的预付费
  资源包(包价,不是按次价);Lyria RealTime(价目页没有列)。

## 分时段计价(2026-09 查证)

- **DeepSeek**(api-docs.deepseek.com):北京时间周一至周五(不含法定节假日)9:00–12:00、
  14:00–18:00 为高峰,其余(含周末、节假日全天)为空闲,空闲价是高峰价的一半 —— 已按时段收录。
  规则分不出法定节假日,节假日的工作日白天会按高峰价估(偏高,不会少算)。
- **火山方舟**:deepseek-v4.1-flash 同样分高峰 / 空闲(北京时间工作日 09:00–12:00、14:00–18:00);
  应用里的方舟连接只做生图/生视频,对话模型本来就不收。
- **百炼国际站**:DeepSeek 系列分忙 / 闲时(UTC+8 22:00–08:00 为闲时),部分千问模型在香港、
  法兰克福、弗吉尼亚、东京地域有夜间价;表里记的是新加坡地域的千问,那里不分时段 —— 不收。
- **没有分时段价的**:百炼国内、Kimi(国内 / 国际)、MiniMax(国内 / 国际)、OpenAI、Anthropic。
  OpenAI 的 Batch / Flex、Anthropic 的 Batch 是**调用方式**的折扣,不是时段,不按时段建模。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse

#: 这一轮查证的年月。条目默认取它;单独重查过的条目写自己的。
CHECKED = "2026-09"

#: 价格适用的地区。中国内地和国际站对同一个模型常常是两个价、两种币。
REGIONS = ("cn", "intl", "global")


@dataclass(frozen=True)
class TimePrice:
    """一个时段的挂牌价。钟点是条目 `time_zone` 里的,`weekdays` 为 ISO 星期、空 = 每天
    (语义与 domain/price_schedule 相同);`amount` 与条目的 `amount` 同单位、同 `per`。"""

    start: str
    end: str
    amount: str
    weekdays: tuple[int, ...] = ()

#: 这几家的"官方端点"本身就是中转:后面挂的是任意厂商的模型,只能按 id 借原厂价(见约定 5)。
RELAY_VENDORS = frozenset({"openai-compatible", "evolink", "openrouter"})

#: 国际站的域名。连接的 Endpoint 落在这里 → 只认 `intl` / `global` 的条目。
#: 没列出来的厂商(或 Endpoint 不在这里)按 `cn` 算 —— 表里国内厂商记的都是国内价。
_INTL_HOSTS: dict[str, tuple[str, ...]] = {
    "alibaba": ("dashscope-intl.aliyuncs.com",),
    "moonshot": ("api.moonshot.ai",),
    "minimax": ("api.minimax.io",),
    "bytedance": ("bytepluses.com", "ark.ap-southeast"),
}

#: 这几家有自己的官方 Endpoint;连接的 Endpoint 改到了别处,就是拿它的协议接了中转。
_OFFICIAL_HOSTS: dict[str, tuple[str, ...]] = {
    "openai": ("api.openai.com",),
}


@dataclass(frozen=True)
class ListPrice:
    """一个模型在一个计价单位上的挂牌价。

    `amount` 用字符串:0.8 写成浮点再乘一百万,出来的是 799999.9999;这里的数要能和价目页逐字对上。
    `per` 是厂商按多少个 `billing_unit` 报一个价 —— 「元/万字符」就是 `character` + `per=10_000`。
    `million_*` 单位本身已经是「每百万」,`per` 保持 1。
    """

    vendor: str
    model: str
    capability: str
    billing_unit: str
    amount: str
    currency: str
    source: str
    per: int = 1
    region: str = "global"
    #: 档位、条件之类要让用户知道的话,(中文, 英文) 各一句 —— 它会进规则备注,按点预填时的界面
    #: 语言取一句。分档的价、`per` 不为 1 的价必须写(约定 2、3),测试盯着。
    remark: tuple[str, str] = ("", "")
    #: True = 按前缀匹配(如带日期后缀的一族);默认精确匹配。
    prefix: bool = False
    checked: str = CHECKED
    #: 分时段价(约定 4)。`amount` 是其余时段的价;这里是厂商列出钟点的那几段。
    time_prices: tuple[TimePrice, ...] = ()
    #: 上面那些钟点的时区(IANA 名)。有时段就必须有(测试盯着)。
    time_zone: str = ""

    @property
    def unit_amount_micros(self) -> int:
        """换算成规则里存的「每个计价单位多少 micros」。表里的数保证能整除(测试盯着)。"""
        return int(Decimal(self.amount) * 1_000_000 / self.per)

    @property
    def time_prices_micros(self) -> tuple[dict[str, object], ...]:
        """换算成规则上存的时段形状(见 domain/price_schedule)。"""
        return tuple(
            {
                "start": window.start,
                "end": window.end,
                "weekdays": list(window.weekdays),
                "unit_amount_micros": int(Decimal(window.amount) * 1_000_000 / self.per),
            }
            for window in self.time_prices
        )

    def remark_for(self, locale: str) -> str:
        zh, en = self.remark
        return en if locale == "en" else zh

    def matches(self, model_id: str) -> bool:
        name = model_id.strip().lower()
        key = self.model.lower()
        return name.startswith(key) if self.prefix else name == key


def _p(
    vendor: str,
    model: str,
    capability: str,
    billing_unit: str,
    amount: str,
    currency: str,
    source: str,
    **extra: object,
) -> ListPrice:
    return ListPrice(vendor, model, capability, billing_unit, amount, currency, source, **extra)  # type: ignore[arg-type]


def _chat(
    vendor: str,
    model: str,
    currency: str,
    source: str,
    *,
    input: str,
    output: str,
    cache_read: str = "",
    cache_write: str = "",
    **extra: object,
) -> list[ListPrice]:
    """对话模型的一组 token 价(每百万)。缓存价只在价目页**写出数字**时才填 —— 只给了「输入价的
    两成」这类比例的(百炼)不填:那是我们自己算的数,不是挂牌价。"""
    units = (
        ("million_input_token", input),
        ("million_output_token", output),
        ("million_cache_read_token", cache_read),
        ("million_cache_write_token", cache_write),
    )
    return [_p(vendor, model, "chat", unit, amount, currency, source, **extra) for unit, amount in units if amount]


# ---------------------------------------------------------------------------------------------
# 表本体。每家一段,段首写价目页;条目顺序照价目页。
# ---------------------------------------------------------------------------------------------

# —— DeepSeek ——
# 只有 deepseek-flash 与 deepseek-v4-pro 两个在售;deepseek-chat / deepseek-reasoner 两页都已不列,
# deepseek-v4-flash 等旧名页脚写着「对应模型已下线」—— 都不收。
# 分时段计价(2026-09 查证):「北京时间周一至周五(不含中国法定节假日)9:00 - 12:00、14:00 - 18:00
# 为高峰时段;其余时段,包括周末及中国法定节假日全天均为空闲时段」,空闲价是高峰价的一半。
# 页面列出钟点的是高峰,空闲是「其余」—— 所以基础价记空闲价,高峰作为工作日的两个时段(约定 4)。
_DEEPSEEK = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing"
_DEEPSEEK_REMARK = (
    "基础价为空闲时段价;北京时间工作日 9:00–12:00、14:00–18:00 按高峰价(两倍)计。法定节假日官方按空闲价,"
    "规则分不出节假日,会按高峰价估",
    "Base price is the off-peak rate; weekdays 9:00–12:00 and 14:00–18:00 Beijing time use the peak rate (double). "
    "Public holidays are off-peak officially, but rules can't tell holidays apart and estimate them at peak",
)
_BEIJING = "Asia/Shanghai"
_WORKDAYS = (1, 2, 3, 4, 5)


def _deepseek(model: str, **units: tuple[str, str]) -> list[ListPrice]:
    """DeepSeek 的一个模型:每个计价单位给 (空闲价, 高峰价)。高峰是工作日的两段,其余是空闲。"""
    names = {"input": "million_input_token", "output": "million_output_token", "cache_read": "million_cache_read_token"}
    return [
        _p(
            "deepseek", model, "chat", names[unit], off_peak, "CNY", _DEEPSEEK,
            region="cn", remark=_DEEPSEEK_REMARK, time_zone=_BEIJING,
            time_prices=(
                TimePrice("09:00", "12:00", peak, _WORKDAYS),
                TimePrice("14:00", "18:00", peak, _WORKDAYS),
            ),
        )
        for unit, (off_peak, peak) in units.items()
    ]


_DEEPSEEK_PRICES = [
    *_deepseek("deepseek-flash", input=("1", "2"), output=("4", "8"), cache_read=("0.02", "0.04")),
    *_deepseek("deepseek-v4-pro", input=("4.5", "9"), output=("13.5", "27"), cache_read=("0.15", "0.3")),
]

# —— Kimi / Moonshot ——(platform.moonshot.cn / .ai 已分别跳到 platform.kimi.com / .ai)
# 只列 kimi-k3、kimi-k2.7-code(-highspeed)、kimi-k2.6;moonshot-v1-* 与 kimi-latest 已不在对话价目页上。
# 只有 K3 收缓存写入费:TTL 5 分钟那档是默认,记它;1 小时那档翻倍,写在备注里。
_KIMI_CN = "https://platform.kimi.com/docs/pricing/chat"
_KIMI_INTL = "https://platform.kimi.ai/docs/pricing/chat"
_KIMI_K3_CN_REMARK = (
    "缓存写入按默认的 5 分钟 TTL 计;1 小时 TTL 为 40 元/百万",
    "Cache write at the default 5-minute TTL; the 1-hour TTL is 40 CNY per 1M",
)
_KIMI_K3_INTL_REMARK = (
    "缓存写入按默认的 5 分钟 TTL 计;1 小时 TTL 为 $6/百万",
    "Cache write at the default 5-minute TTL; the 1-hour TTL is $6 per 1M",
)
_MOONSHOT_PRICES = [
    *_chat("moonshot", "kimi-k3", "CNY", _KIMI_CN, input="20", output="100", cache_read="2", cache_write="20", region="cn", remark=_KIMI_K3_CN_REMARK),
    *_chat("moonshot", "kimi-k2.7-code", "CNY", _KIMI_CN, input="6.5", output="27", cache_read="1.3", region="cn"),
    *_chat("moonshot", "kimi-k2.7-code-highspeed", "CNY", _KIMI_CN, input="13", output="54", cache_read="2.6", region="cn"),
    *_chat("moonshot", "kimi-k2.6", "CNY", _KIMI_CN, input="6.5", output="27", cache_read="1.1", region="cn"),
    *_chat("moonshot", "kimi-k3", "USD", _KIMI_INTL, input="3", output="15", cache_read="0.3", cache_write="3", region="intl", remark=_KIMI_K3_INTL_REMARK),
    *_chat("moonshot", "kimi-k2.7-code", "USD", _KIMI_INTL, input="0.95", output="4", cache_read="0.19", region="intl"),
    *_chat("moonshot", "kimi-k2.7-code-highspeed", "USD", _KIMI_INTL, input="1.9", output="8", cache_read="0.38", region="intl"),
    *_chat("moonshot", "kimi-k2.6", "USD", _KIMI_INTL, input="0.95", output="4", cache_read="0.16", region="intl"),
]

# —— xAI Grok ——
# 提示词达到 200K 的请求**整单**按翻倍价计;记的是 200K 以下那档。US 专属端点再贵 10%,不收。
_XAI = "https://docs.x.ai/developers/models"
_XAI_REMARK = (
    "提示词不足 200K 的价;达到 200K 的请求整单按两倍计",
    "Price below 200K prompt tokens; requests at or above 200K are billed at double for every token",
)
#: (模型, 输入, 输出, 缓存命中输入)
_XAI_ROWS = (
    ("grok-4.7", "2", "6", "0.5"),
    ("grok-4.6", "2", "6", "0.5"),
    ("grok-4.5", "2", "6", "0.3"),
    ("grok-4.3", "1.25", "2.5", "0.2"),
    ("grok-4.20-0309-reasoning", "1.25", "2.5", "0.2"),
    ("grok-4.20-0309-non-reasoning", "1.25", "2.5", "0.2"),
    ("grok-4.20-multi-agent-0309", "1.25", "2.5", "0.2"),
    ("grok-build-0.1", "1", "2", "0.2"),
)
_XAI_PRICES = [
    entry
    for model, i, o, r in _XAI_ROWS
    for entry in _chat("xai", model, "USD", _XAI, input=i, output=o, cache_read=r, remark=_XAI_REMARK)
]

# —— Anthropic Claude ——(模型 id 取自同站 models/overview 与 model-deprecations)
# 缓存写入按 5 分钟那档(1 小时那档是输入价的两倍);4.6 起 1M 窗口不加价;inference_geo=us 另加一成。
# 已退役的 Opus 4 / 4.1、Sonnet 4、Haiku 3.5 与限量开放的 Mythos 不收。
_ANTHROPIC = "https://platform.claude.com/docs/en/about-claude/pricing"
_ANTHROPIC_REMARK = (
    "缓存写入按 5 分钟那档;1 小时缓存写入为输入价的 2 倍",
    "Cache write at the 5-minute tier; 1-hour cache writes cost 2x the input price",
)
#: (模型, 输入, 输出, 缓存命中, 缓存写入 5 分钟)
_ANTHROPIC_ROWS = (
    ("claude-fable-5-1", "10", "50", "0.25", "12.5"),
    ("claude-fable-5", "10", "50", "1", "12.5"),
    ("claude-opus-5-5", "4", "20", "0.2", "5"),
    ("claude-opus-5", "5", "25", "0.5", "6.25"),
    ("claude-opus-4-8", "5", "25", "0.5", "6.25"),
    ("claude-opus-4-7", "5", "25", "0.5", "6.25"),
    ("claude-opus-4-6", "5", "25", "0.5", "6.25"),
    ("claude-opus-4-5-20251101", "5", "25", "0.5", "6.25"),
    ("claude-sonnet-5", "2", "10", "0.2", "2.5"),
    ("claude-sonnet-4-6", "3", "15", "0.3", "3.75"),
    ("claude-sonnet-4-5-20250929", "3", "15", "0.3", "3.75"),
    ("claude-haiku-4-5-20251001", "1", "5", "0.1", "1.25"),
    ("claude-haiku-4-5", "1", "5", "0.1", "1.25"),
)
_ANTHROPIC_PRICES = [
    entry
    for model, i, o, r, w in _ANTHROPIC_ROWS
    for entry in _chat(
        "anthropic", model, "USD", _ANTHROPIC, input=i, output=o, cache_read=r, cache_write=w, remark=_ANTHROPIC_REMARK
    )
]

# —— 阿里云百炼 ——(页面由脚本渲染,读的是帮助中心同域的 JSON 接口,内容与页面一致)
# 国内(北京)记人民币、国际(新加坡)记美元,各以本地价目页为准。
# 千问按**单次请求的输入长度**分档,整单按所在档计价:记最短那档,备注写出其余档。
# 缓存命中价页面只给「标准输入价的 20%(隐式)/ 10%(显式)」这样的比例,没有挂牌数字 —— 不填。
# 万相按输出分辨率分档:记 720P(应用默认),备注写 480P / 1080P。
_BAILIAN_CN = "https://help.aliyun.com/zh/model-studio/model-pricing"
_BAILIAN_INTL = "https://www.alibabacloud.com/help/en/model-studio/model-pricing"


def _tiers(zh: str, en: str) -> tuple[str, str]:
    return (f"输入长度最短一档的价;{zh}", f"Shortest input-length tier; {en}")


def _non_thinking(zh: str, en: str) -> tuple[str, str]:
    return (f"非思考模式的输出价;{zh}", f"Non-thinking output price; {en}")


def _wan(model: str, zh: str, en: str) -> tuple[str, str]:
    return (f"720P 的价;{zh}{_WAN_INPUT.get(model, ('', ''))[0]}", f"720P price; {en}{_WAN_INPUT.get(model, ('', ''))[1]}")


#: 这两个模型**输入视频也按秒计费**,而计量只记输出时长 —— 按规则算出来会偏低,备注里说清。
_WAN_INPUT = {
    "wan2.7-r2v": (";另按输入视频时长(最多 5 秒)计费", "; input video seconds (up to 5) are billed too"),
    "wan2.7-videoedit": (";输入视频时长同样计费", "; input video seconds are billed too"),
}

_ALIBABA_CHAT = [
    # 国内(北京)
    *_chat("alibaba", "qwen-max", "CNY", _BAILIAN_CN, input="2.4", output="9.6", region="cn"),
    *_chat("alibaba", "qwen3-max", "CNY", _BAILIAN_CN, input="2.5", output="10", region="cn",
           remark=_tiers("32K-128K 为 4/16 元,128K-256K 为 7/28 元", "32K-128K is 4/16 CNY, 128K-256K is 7/28 CNY")),
    *_chat("alibaba", "qwen3.8-max", "CNY", _BAILIAN_CN, input="12", output="36", region="cn"),
    *_chat("alibaba", "qwen3.8-max-prime", "CNY", _BAILIAN_CN, input="24", output="72", region="cn"),
    *_chat("alibaba", "qwen3.7-max", "CNY", _BAILIAN_CN, input="12", output="36", region="cn"),
    *_chat("alibaba", "qwen3.6-max-preview", "CNY", _BAILIAN_CN, input="9", output="54", region="cn",
           remark=_tiers("128K-256K 为 15/90 元", "128K-256K is 15/90 CNY")),
    *_chat("alibaba", "qwen-plus", "CNY", _BAILIAN_CN, input="0.8", output="2", region="cn",
           remark=_tiers(
               "非思考模式输出价,思考模式输出 8 元;128K-256K 为 2.4/20(思考 24)元,256K-1M 为 4.8/48(思考 64)元",
               "non-thinking output, thinking output is 8 CNY; 128K-256K is 2.4/20 (thinking 24) CNY, 256K-1M is 4.8/48 (thinking 64) CNY",
           )),
    *_chat("alibaba", "qwen-turbo", "CNY", _BAILIAN_CN, input="0.3", output="0.6", region="cn",
           remark=_non_thinking("思考模式输出 3 元", "thinking output is 3 CNY")),
    *_chat("alibaba", "qwen-flash", "CNY", _BAILIAN_CN, input="0.15", output="1.5", region="cn",
           remark=_tiers("128K-256K 为 0.6/6 元,256K-1M 为 1.2/12 元", "128K-256K is 0.6/6 CNY, 256K-1M is 1.2/12 CNY")),
    *_chat("alibaba", "qwen3.8-flash", "CNY", _BAILIAN_CN, input="0.8", output="2.7", region="cn"),
    *_chat("alibaba", "qwen-long", "CNY", _BAILIAN_CN, input="0.5", output="2", region="cn"),
    *_chat("alibaba", "qwen3-coder-plus", "CNY", _BAILIAN_CN, input="4", output="16", region="cn",
           remark=_tiers("32K-128K 为 6/24 元,128K-256K 为 10/40 元,256K-1M 为 20/200 元",
                         "32K-128K is 6/24 CNY, 128K-256K is 10/40 CNY, 256K-1M is 20/200 CNY")),
    *_chat("alibaba", "qwen3-coder-flash", "CNY", _BAILIAN_CN, input="1", output="4", region="cn",
           remark=_tiers("32K-128K 为 1.5/6 元,128K-256K 为 2.5/10 元,256K-1M 为 5/25 元",
                         "32K-128K is 1.5/6 CNY, 128K-256K is 2.5/10 CNY, 256K-1M is 5/25 CNY")),
    # 国际(新加坡)
    *_chat("alibaba", "qwen-max", "USD", _BAILIAN_INTL, input="1.6", output="6.4", region="intl"),
    *_chat("alibaba", "qwen3-max", "USD", _BAILIAN_INTL, input="1.2", output="6", region="intl",
           remark=_tiers("32K-128K 为 $2.4/$12,128K-256K 为 $3/$15", "32K-128K is $2.4/$12, 128K-256K is $3/$15")),
    *_chat("alibaba", "qwen3.8-max", "USD", _BAILIAN_INTL, input="2", output="6", region="intl"),
    *_chat("alibaba", "qwen-plus", "USD", _BAILIAN_INTL, input="0.4", output="1.2", region="intl",
           remark=_tiers("非思考模式输出价,思考模式输出 $4;256K-1M 为 $1.2/$3.6(思考 $12)",
                         "non-thinking output, thinking output is $4; 256K-1M is $1.2/$3.6 (thinking $12)")),
    *_chat("alibaba", "qwen-turbo", "USD", _BAILIAN_INTL, input="0.05", output="0.2", region="intl",
           remark=_non_thinking("思考模式输出 $0.5", "thinking output is $0.5")),
    *_chat("alibaba", "qwen-flash", "USD", _BAILIAN_INTL, input="0.05", output="0.4", region="intl",
           remark=_tiers("256K-1M 为 $0.25/$2", "256K-1M is $0.25/$2")),
    *_chat("alibaba", "qwen3.8-flash", "USD", _BAILIAN_INTL, input="0.15", output="0.47", region="intl"),
    *_chat("alibaba", "qwen3-coder-plus", "USD", _BAILIAN_INTL, input="1", output="5", region="intl",
           remark=_tiers("32K-128K 为 $1.8/$9,128K-256K 为 $3/$15,256K-1M 为 $6/$60",
                         "32K-128K is $1.8/$9, 128K-256K is $3/$15, 256K-1M is $6/$60")),
    *_chat("alibaba", "qwen3-coder-flash", "USD", _BAILIAN_INTL, input="0.3", output="1.5", region="intl",
           remark=_tiers("32K-128K 为 $0.5/$2.5,128K-256K 为 $0.8/$4,256K-1M 为 $1.6/$9.6",
                         "32K-128K is $0.5/$2.5, 128K-256K is $0.8/$4, 256K-1M is $1.6/$9.6")),
]

# 生图(每张)。qwen-image-3.0-pro 按 1K/2K 分两档价,拿不准基础档,不收。
_ALIBABA_IMAGE = [
    *[
        _p("alibaba", model, "image", "image", amount, currency, source, region=region)
        for model, cn, intl in (
            ("qwen-image", "0.25", "0.035"),
            ("qwen-image-plus", "0.2", "0.03"),
            ("qwen-image-max", "0.5", "0.075"),
            ("qwen-image-2.0-pro", "0.5", "0.075"),
            ("qwen-image-2.0", "0.2", "0.035"),
            ("qwen-image-edit", "0.3", "0.045"),
            ("qwen-image-edit-plus", "0.2", "0.03"),
            ("qwen-image-edit-max", "0.5", "0.075"),
        )
        for amount, currency, source, region in ((cn, "CNY", _BAILIAN_CN, "cn"), (intl, "USD", _BAILIAN_INTL, "intl"))
    ],
    _p("alibaba", "qwen-image-3.0", "image", "image", "0.18", "CNY", _BAILIAN_CN, region="cn",
       remark=("输出图 1K、2K 同价;带参考图时每张输入图另收 0.02 元", "Same price for 1K and 2K output; each input image adds 0.02 CNY")),
]

# 生视频(每秒,按输出分辨率)。wan2.2-t2v-plus 没有 720P 档、wan2.6-i2v-flash 分有声/无声两价
# 而适配器不指定是哪种 —— 拿不准基础档,不收。
_WAN_WITH_480P = ("wan2.5-t2v-preview", "wan2.5-i2v-preview")
_ALIBABA_VIDEO = [
    entry
    for model in (
        "wan2.5-t2v-preview",
        "wan2.6-t2v",
        "wan2.7-t2v",
        "wan2.5-i2v-preview",
        "wan2.6-i2v",
        "wan2.7-i2v",
        "wan2.7-r2v",
        "wan2.7-videoedit",
    )
    for entry in (
        _p("alibaba", model, "video", "video_second", "0.6", "CNY", _BAILIAN_CN, region="cn",
           remark=_wan(model,
                       ("480P 为 0.3 元/秒," if model in _WAN_WITH_480P else "") + "1080P 为 1 元/秒",
                       ("480P is 0.3 CNY/s, " if model in _WAN_WITH_480P else "") + "1080P is 1 CNY/s")),
        _p("alibaba", model, "video", "video_second", "0.1", "USD", _BAILIAN_INTL, region="intl",
           remark=_wan(model,
                       ("480P 为 $0.05/秒," if model in _WAN_WITH_480P else "") + "1080P 为 $0.15/秒",
                       ("480P is $0.05/s, " if model in _WAN_WITH_480P else "") + "1080P is $0.15/s")),
    )
]

# 语音合成(每万字符)。qwen-tts-flash / -latest 按 token 计价,而语音合成的计量是字符数,
# 对不上,不收;裸的 `qwen-tts` 这个 id 价目页上没有。
# 百炼一个汉字按 2 个字符计,而计量记的是 len(text) —— 中文会少算一半,备注里写明。
_ALIBABA_TTS = [
    _p("alibaba", model, "tts", "character", amount, currency, source, per=10_000, region=region,
       remark=(f"官方价 {listed}/万字符;一个汉字按 2 个字符计", f"Listed at {listed} per 10,000 characters; one Chinese character counts as 2"))
    for model, cn, intl in (
        ("qwen3-tts-flash", "0.8", "0.1"),
        ("cosyvoice-v2", "2", ""),
        ("cosyvoice-v3-flash", "1", "0.13"),
        ("cosyvoice-v3-plus", "2", "0.26"),
        ("cosyvoice-v3.5-flash", "0.8", ""),
        ("cosyvoice-v3.5-plus", "1.5", ""),
    )
    for amount, currency, source, region, listed in (
        (cn, "CNY", _BAILIAN_CN, "cn", f"{cn} 元" if cn else ""),
        (intl, "USD", _BAILIAN_INTL, "intl", f"${intl}" if intl else ""),
    )
    if amount
]

# —— 火山方舟(bytedance)——
# 价目页按**模型族**写(doubao-seedream-4-0),带版本号的 id 取自同站模型列表。
# Seedance 按 token 计价(元/百万 token),计费 token 数是任务回包的 usage.completion_tokens ——
# 适配器把它记成 output_tokens(见 adapters/bytedance/ark/video.seedance_metering),所以单位是
# million_output_token。分「输入含不含视频」两价、按输出分辨率分档:记 720P、不含视频输入那档。
# 已关停的(Seedance 1.5 pro / 1.0 lite、Seedream 3.0、SeedEdit 3.0 在国内)不收;
# Seedream 5.0 pro 按像素分两档价,拿不准基础档,不收。
# 豆包对话模型也在这页上,但应用里的方舟连接只做生图/生视频,记了也用不上 —— 不收。
_ARK_CN = "https://docs.volcengine.com/docs/82379/1544106"
_ARK_INTL = "https://docs.byteplus.com/en/docs/ModelArk/1544106"


def _seedance(model: str, amount: str, currency: str, source: str, region: str, zh: str, en: str) -> ListPrice:
    return _p("bytedance", model, "video", "million_output_token", amount, currency, source, region=region, remark=(zh, en))


_BYTEDANCE_PRICES = [
    # 生视频 · 国内
    _seedance("doubao-seedance-2-5-260628", "70", "CNY", _ARK_CN, "cn",
              "720P、输入不含视频的价;输入含视频为 42 元,1080P 为 77 元(含视频 46 元)",
              "720P price without video input; with video input it is 42 CNY, 1080P is 77 CNY (46 with video)"),
    _seedance("doubao-seedance-2-0-260128", "46", "CNY", _ARK_CN, "cn",
              "720P、输入不含视频的价;输入含视频为 28 元,1080P 为 51 元(含视频 31 元)",
              "720P price without video input; with video input it is 28 CNY, 1080P is 51 CNY (31 with video)"),
    _seedance("doubao-seedance-2-0-fast-260128", "37", "CNY", _ARK_CN, "cn",
              "原价,输入不含视频;输入含视频为 22 元;企业用户限时 7.5 折",
              "List price without video input; with video input it is 22 CNY; enterprise accounts get a time-limited 25% off"),
    _seedance("doubao-seedance-2-0-mini-260615", "23", "CNY", _ARK_CN, "cn",
              "原价,输入不含视频;输入含视频为 14 元;企业用户限时 4 折",
              "List price without video input; with video input it is 14 CNY; enterprise accounts get a time-limited 60% off"),
    _seedance("doubao-seedance-1-0-pro-250528", "15", "CNY", _ARK_CN, "cn",
              "在线推理价;离线推理 7.5 元;2026-11-24 下线",
              "Online inference price; offline is 7.5 CNY; retires 2026-11-24"),
    _seedance("doubao-seedance-1-0-pro-fast-251015", "4.2", "CNY", _ARK_CN, "cn",
              "在线推理价;离线推理 2.1 元;2026-11-24 下线",
              "Online inference price; offline is 2.1 CNY; retires 2026-11-24"),
    # 生视频 · 国际(BytePlus ModelArk,id 前缀与国内不同)
    _seedance("dreamina-seedance-2-5-260628", "10.7", "USD", _ARK_INTL, "intl",
              "720P、输入不含视频的价;输入含视频为 $6.4,1080P 为 $11.7(含视频 $7.0)",
              "720P price without video input; with video input it is $6.4, 1080P is $11.7 ($7.0 with video)"),
    _seedance("dreamina-seedance-2-0-260128", "7", "USD", _ARK_INTL, "intl",
              "720P、输入不含视频的价;输入含视频为 $4.3,1080P 为 $7.7(含视频 $4.7)",
              "720P price without video input; with video input it is $4.3, 1080P is $7.7 ($4.7 with video)"),
    _seedance("dreamina-seedance-2-0-fast-260128", "5.6", "USD", _ARK_INTL, "intl",
              "原价,输入不含视频;输入含视频为 $3.3;限时 75 折", "List price without video input; with video input it is $3.3; time-limited 25% off"),
    _seedance("dreamina-seedance-2-0-mini-260615", "3.5", "USD", _ARK_INTL, "intl",
              "原价,输入不含视频;输入含视频为 $2.1;限时 4 折", "List price without video input; with video input it is $2.1; time-limited 60% off"),
    _seedance("seedance-1-0-pro-250528", "2.5", "USD", _ARK_INTL, "intl",
              "在线推理价;离线推理 $1.25", "Online inference price; offline is $1.25"),
    _seedance("seedance-1-0-pro-fast-251015", "1", "USD", _ARK_INTL, "intl",
              "在线推理价;离线推理 $0.5", "Online inference price; offline is $0.5"),
    # 生图(每张;参考图免费)
    *[
        _p("bytedance", model, "image", "image", amount, "CNY", _ARK_CN, region="cn")
        for model, amount in (
            ("doubao-seedream-5-0-flash-260915", "0.12"),
            ("doubao-seedream-5-0-260128", "0.22"),
            ("doubao-seedream-5-0-lite-260128", "0.22"),
            ("doubao-seedream-4-5-251128", "0.25"),
            ("doubao-seedream-4-0-250828", "0.2"),
        )
    ],
    *[
        _p("bytedance", model, "image", "image", amount, "USD", _ARK_INTL, region="intl")
        for model, amount in (
            ("dola-seedream-5-0-flash-260915", "0.018"),
            ("seedream-5-0-lite-260128", "0.035"),
            ("seedream-4-5-251128", "0.04"),
            ("seedream-4-0-250828", "0.03"),
            ("seededit-3-0-i2i-250628", "0.03"),
        )
    ],
]

# —— 火山引擎豆包语音(volcano)——
# 只收直接写着对应名字的那一档:「豆包语音合成模型2.0」= seed-tts-2.0。seed-tts-1.0 对应哪个计费项
# 要靠推断(价目页不用这个名字),不收。
_VOLCANO_TTS = "https://www.volcengine.com/docs/6561/1359370"
_VOLCANO_PRICES = [
    _p("volcano", "seed-tts-2.0", "tts", "character", "3", "CNY", _VOLCANO_TTS, per=10_000, region="cn",
       remark=("官方价 3 元/万字符(按量后付费);预付费资源包更便宜", "Listed at 3 CNY per 10,000 characters (pay-as-you-go); prepaid packages cost less")),
]

# —— MiniMax ——(platform.minimaxi.com 的价目页已跳到 platform.minimax.cn;按量计费在 pricing-paygo 子页)
# 国内记人民币、国际站(api.minimax.io)记美元。M1 / Text-01 已不在价目页上,不收。
# 海螺 2.3 / 02 在「历史模型」一栏,仍在计价,照收;它们**按条**计价(768P 6 秒一档),记这一档。
# MiniMax-H3-Max 按 480P / 768P 两档计价,拿不准基础档,不收。语音与生图的价查到了,但应用里的
# MiniMax 连接还不做这两样(见 provider_presets),记了也用不上 —— 不收。
_MINIMAX_CN = "https://platform.minimax.cn/docs/guides/pricing-paygo"
_MINIMAX_INTL = "https://platform.minimax.io/docs/guides/pricing-paygo"
_M3_CN = ("输入不超过 512K 的价(已是官方永久五折后的价);超过 512K 为 4.2/16.8 元,缓存读 0.84 元",
          "Price for inputs up to 512K (already at the permanent 50% discount); above 512K it is 4.2/16.8 CNY, cache read 0.84")
_M3_INTL = ("输入不超过 512K 的价(已是官方永久五折后的价);超过 512K 为 $0.6/$2.4,缓存读 $0.12",
            "Price for inputs up to 512K (already at the permanent 50% discount); above 512K it is $0.6/$2.4, cache read $0.12")


def _hailuo(zh: str, en: str) -> tuple[str, str]:
    return (f"按条计价,记的是 768P 6 秒一条;{zh}", f"Priced per video; this is the 768P 6-second price; {en}")


_MINIMAX_PRICES = [
    # 对话 · 国内
    *_chat("minimax", "MiniMax-M3", "CNY", _MINIMAX_CN, input="2.1", output="8.4", cache_read="0.42", region="cn", remark=_M3_CN),
    *_chat("minimax", "MiniMax-M2.7", "CNY", _MINIMAX_CN, input="2.1", output="8.4", cache_read="0.42", cache_write="2.625", region="cn"),
    *_chat("minimax", "MiniMax-M2.7-highspeed", "CNY", _MINIMAX_CN, input="4.2", output="16.8", cache_read="0.42", cache_write="2.625", region="cn"),
    *[
        entry
        for model in ("MiniMax-M2.5", "MiniMax-M2.1", "MiniMax-M2")
        for entry in _chat("minimax", model, "CNY", _MINIMAX_CN, input="2.1", output="8.4", cache_read="0.21", cache_write="2.625", region="cn")
    ],
    # 对话 · 国际
    *_chat("minimax", "MiniMax-M3", "USD", _MINIMAX_INTL, input="0.3", output="1.2", cache_read="0.06", region="intl", remark=_M3_INTL),
    *_chat("minimax", "MiniMax-M2.7", "USD", _MINIMAX_INTL, input="0.3", output="1.2", cache_read="0.06", cache_write="0.375", region="intl"),
    *_chat("minimax", "MiniMax-M2.7-highspeed", "USD", _MINIMAX_INTL, input="0.6", output="2.4", cache_read="0.06", cache_write="0.375", region="intl"),
    *[
        entry
        for model in ("MiniMax-M2.5", "MiniMax-M2.1", "MiniMax-M2")
        for entry in _chat("minimax", model, "USD", _MINIMAX_INTL, input="0.3", output="1.2", cache_read="0.03", cache_write="0.375", region="intl")
    ],
    # 生视频
    _p("minimax", "MiniMax-H3", "video", "video_second", "0.5", "CNY", _MINIMAX_CN, region="cn",
       remark=("768P 的价;2K 为 0.8 元/秒;参考图前 5 张免费,之后每张 0.2 元;输入视频另按秒计费",
               "768P price; 2K is 0.8 CNY/s; the first 5 reference images are free, then 0.2 CNY each; input video is billed per second too")),
    _p("minimax", "MiniMax-H3", "video", "video_second", "0.08", "USD", _MINIMAX_INTL, region="intl",
       remark=("768P 的价;2K 为 $0.13/秒;超出的参考图每张 $0.04", "768P price; 2K is $0.13/s; extra reference images are $0.04 each")),
    _p("minimax", "MiniMax-Hailuo-2.3", "video", "video", "2", "CNY", _MINIMAX_CN, region="cn",
       remark=_hailuo("768P 10 秒为 4 元,1080P 6 秒为 3.5 元", "768P 10 s is 4 CNY, 1080P 6 s is 3.5 CNY")),
    _p("minimax", "MiniMax-Hailuo-2.3-Fast", "video", "video", "1.35", "CNY", _MINIMAX_CN, region="cn",
       remark=_hailuo("768P 10 秒为 2.25 元,1080P 6 秒为 2.31 元", "768P 10 s is 2.25 CNY, 1080P 6 s is 2.31 CNY")),
    _p("minimax", "MiniMax-Hailuo-02", "video", "video", "2", "CNY", _MINIMAX_CN, region="cn",
       remark=_hailuo("768P 10 秒为 4 元,1080P 6 秒为 3.5 元,512P 6 秒为 0.6 元", "768P 10 s is 4 CNY, 1080P 6 s is 3.5 CNY, 512P 6 s is 0.6 CNY")),
    _p("minimax", "MiniMax-Hailuo-2.3", "video", "video", "0.28", "USD", _MINIMAX_INTL, region="intl",
       remark=_hailuo("768P 10 秒为 $0.56,1080P 6 秒为 $0.49", "768P 10 s is $0.56, 1080P 6 s is $0.49")),
    _p("minimax", "MiniMax-Hailuo-2.3-Fast", "video", "video", "0.19", "USD", _MINIMAX_INTL, region="intl",
       remark=_hailuo("768P 10 秒为 $0.32,1080P 6 秒为 $0.33", "768P 10 s is $0.32, 1080P 6 s is $0.33")),
    _p("minimax", "MiniMax-Hailuo-02", "video", "video", "0.28", "USD", _MINIMAX_INTL, region="intl",
       remark=_hailuo("768P 10 秒为 $0.56,1080P 6 秒为 $0.49,512P 6 秒为 $0.10", "768P 10 s is $0.56, 1080P 6 s is $0.49, 512P 6 s is $0.10")),
]

# —— OpenAI ——(读的是 developers.openai.com 的价目页,Standard 档)
# GPT-6 / 5.6 / 5.5 / 5.4 输入超过 272K 的请求整单按输入与缓存 2 倍、输出 1.5 倍计;记 272K 以下那档。
# GPT Image 按 token 计价:只记**图像输出 token** 的价 —— 适配器从回包 usage.output_tokens 取数
# (见 adapters/openai/image.image_metering)。文本输入价只配得上提示词的估算值,记上它会让没回
# usage 的兼容端点显得"有价"而实际只算了几分钱,不收。
# gpt-4o-mini-tts 按 token 计价,而语音合成的计量是字符数,不收。
_OPENAI = "https://developers.openai.com/api/docs/pricing"
_OPENAI_LONG = ("输入不超过 272K 的价;超过的请求整单按输入与缓存 2 倍、输出 1.5 倍计",
                "Price for prompts up to 272K; longer requests are billed at 2x input/cache and 1.5x output for the whole request")
#: (模型, 输入, 缓存命中, 缓存写入, 输出, 是否有 272K 长上下文档)
_OPENAI_CHAT_ROWS = (
    ("gpt-6-astra", "10", "1", "12.5", "50", True),
    ("gpt-6-sol", "2", "0.2", "2.5", "10", True),
    ("gpt-6-luna", "0.1", "0.01", "0.125", "0.5", True),
    ("gpt-5.6-terra", "2", "0.2", "2.5", "12", True),
    ("gpt-5.6-luna", "0.2", "0.02", "0.25", "1.2", True),
    ("gpt-5.5", "5", "0.5", "", "30", True),
    ("gpt-5.5-pro", "30", "", "", "180", True),
    ("gpt-5.4", "2.5", "0.25", "", "15", True),
    ("gpt-5.4-pro", "30", "", "", "180", True),
    ("gpt-5.4-mini", "0.75", "0.075", "", "4.5", False),
    ("gpt-5.4-nano", "0.2", "0.02", "", "1.25", False),
    ("gpt-5.2", "1.75", "0.175", "", "14", False),
    ("gpt-5.2-pro", "21", "", "", "168", False),
    ("gpt-5.1", "1.25", "0.125", "", "10", False),
    ("gpt-5", "1.25", "0.125", "", "10", False),
    ("gpt-5-pro", "15", "", "", "120", False),
    ("gpt-5-mini", "0.25", "0.025", "", "2", False),
    ("gpt-5-nano", "0.05", "0.005", "", "0.4", False),
    ("gpt-4.1", "2", "0.5", "", "8", False),
    ("gpt-4.1-mini", "0.4", "0.1", "", "1.6", False),
    ("gpt-4.1-nano", "0.1", "0.025", "", "0.4", False),
    ("gpt-4o", "2.5", "1.25", "", "10", False),
    ("gpt-4o-mini", "0.15", "0.075", "", "0.6", False),
    ("o3", "2", "0.5", "", "8", False),
    ("o3-pro", "20", "", "", "80", False),
    ("o4-mini", "1.1", "0.275", "", "4.4", False),
)
_GPT_IMAGE_REMARK = ("只计图像输出 token;文本输入 ${text}/百万、参考图输入 ${image}/百万未计入(通常远小于输出)",
                     "Image output tokens only; text input (${text}/1M) and reference-image input (${image}/1M) are not counted (usually far below output)")
_OPENAI_PRICES = [
    *[
        entry
        for model, i, r, w, o, long in _OPENAI_CHAT_ROWS
        for entry in _chat("openai", model, "USD", _OPENAI, input=i, output=o, cache_read=r, cache_write=w,
                           **({"remark": _OPENAI_LONG} if long else {}))
    ],
    *_chat("openai", "gpt-5.6-sol", "USD", _OPENAI, input="4", output="20", cache_read="0.4", cache_write="5",
           remark=("官方标注的优惠价(至少持续到 2026-11-21);输入超过 272K 的请求整单按输入与缓存 2 倍、输出 1.5 倍计",
                   "Promotional price (through at least 2026-11-21); prompts over 272K are billed at 2x input/cache and 1.5x output")),
    *[
        _p("openai", model, "image", "million_output_token", output, "USD", _OPENAI,
           remark=(_GPT_IMAGE_REMARK[0].format(text=text, image=image), _GPT_IMAGE_REMARK[1].format(text=text, image=image)))
        for model, output, text, image in (
            ("gpt-image-2.5-sunburst", "30", "5", "8"),
            ("gpt-image-2.5-flare", "30", "5", "8"),
            ("gpt-image-2", "30", "5", "8"),
            ("gpt-image-1.5", "32", "5", "8"),
            ("gpt-image-1", "40", "5", "10"),
            ("gpt-image-1-mini", "8", "2", "2.5"),
        )
    ],
    _p("openai", "tts-1", "tts", "character", "15", "USD", _OPENAI, per=1_000_000,
       remark=("官方价 $15/百万字符", "Listed at $15 per 1M characters")),
    _p("openai", "tts-1-hd", "tts", "character", "30", "USD", _OPENAI, per=1_000_000,
       remark=("官方价 $30/百万字符", "Listed at $30 per 1M characters")),
]

# —— Google(Veo)——(应用里的 Google 连接只做 Veo 视频;Gemini 对话/生图的价查到了,用不上,不收)
# 只公布了「带音频(默认)」的价,按输出分辨率分档:记 720P,备注写其余档。
# Veo 3.0 / 2.0 已于 2026-06-30 下线,价目页不再列,不收。
_GOOGLE = "https://ai.google.dev/gemini-api/docs/pricing"
_VOLCANO_MUSIC = "https://www.volcengine.com/docs/84992/1404661"
_GOOGLE_PRICES = [
    _p("google", "veo-3.1-generate-preview", "video", "video_second", "0.4", "USD", _GOOGLE,
       remark=("带音频(默认)的价,720P 与 1080P 同价;4K 为 $0.60/秒", "With-audio (default) price, same for 720p and 1080p; 4K is $0.60/s")),
    _p("google", "veo-3.1-fast-generate-preview", "video", "video_second", "0.1", "USD", _GOOGLE,
       remark=("带音频(默认)、720P 的价;1080P 为 $0.12/秒,4K 为 $0.30/秒", "With-audio (default) 720p price; 1080p is $0.12/s, 4K is $0.30/s")),
    _p("google", "veo-3.1-lite-generate-preview", "video", "video_second", "0.05", "USD", _GOOGLE,
       remark=("带音频(默认)、720P 的价;1080P 为 $0.08/秒", "With-audio (default) 720p price; 1080p is $0.08/s")),
]

# —— 音频生成(音乐 / BGM / 音效,ADR 0022)—— 2026-09 查证。
# Lyria 按「首」报价(一次生成交回一首),记在 `audio`(按首)这个单位上。
_AUDIO_PRICES = [
    _p("google", "lyria-3.5", "audio", "audio", "0.08", "USD", _GOOGLE,
       remark=("按首计价,一次生成一首", "Priced per song; one generation returns one song")),
    _p("google", "lyria-3-pro-preview", "audio", "audio", "0.08", "USD", _GOOGLE,
       remark=("按首计价,一次生成一首", "Priced per song; one generation returns one song")),
    _p("google", "lyria-3-clip-preview", "audio", "audio", "0.04", "USD", _GOOGLE,
       remark=("按首计价,每首固定 30 秒", "Priced per song; each clip is 30 seconds")),
    # 百炼 Fun-Music:按生成音频的秒数计(回包 usage.duration 就是计费秒数),输入免费;仅北京地域。
    _p("alibaba", "fun-music-v1", "audio", "audio_second", "0.002", "CNY", _BAILIAN_CN, region="cn",
       remark=("按生成音频的秒数计,输入免费;仅北京地域", "Billed per second of generated audio, input is free; Beijing region only")),
    _p("alibaba", "fun-music-preview", "audio", "audio_second", "0.005", "CNY", _BAILIAN_CN, region="cn",
       remark=("按生成音频的秒数计,输入免费;仅北京地域", "Billed per second of generated audio, input is free; Beijing region only")),
    # 火山 AI 音乐生成:后付费(*ForTime)按成功生成的音频秒数计,人声歌曲与纯音乐同价。
    # 预付费资源包(GenSongV4 / GenBGM)按首折算约 ¥1.5,是一次性买断的包价 —— 不是按次挂牌价,不收。
    _p("volcano-music", "GenSongForTime", "audio", "audio_second", "0.002", "CNY", _VOLCANO_MUSIC, region="cn",
       remark=("后付费,按成功生成的音频秒数计", "Postpaid, billed per second of successfully generated audio")),
    _p("volcano-music", "GenBGMForTime", "audio", "audio_second", "0.002", "CNY", _VOLCANO_MUSIC, region="cn",
       remark=("后付费,按成功生成的音频秒数计", "Postpaid, billed per second of successfully generated audio")),
]

LIST_PRICES: tuple[ListPrice, ...] = (
    *_DEEPSEEK_PRICES,
    *_MOONSHOT_PRICES,
    *_XAI_PRICES,
    *_ANTHROPIC_PRICES,
    *_ALIBABA_CHAT,
    *_ALIBABA_IMAGE,
    *_ALIBABA_VIDEO,
    *_ALIBABA_TTS,
    *_BYTEDANCE_PRICES,
    *_VOLCANO_PRICES,
    *_MINIMAX_PRICES,
    *_OPENAI_PRICES,
    *_GOOGLE_PRICES,
    *_AUDIO_PRICES,
)


# ---------------------------------------------------------------------------------------------
# 查表
# ---------------------------------------------------------------------------------------------


def _host(base_url: str) -> str:
    return (urlparse(base_url or "").hostname or "").lower()


def is_relay(vendor: str, base_url: str = "") -> bool:
    """这条连接是不是中转:本身就是中转类 vendor,或者把官方 vendor 的 Endpoint 改到了别处。"""
    if vendor in RELAY_VENDORS:
        return True
    official = _OFFICIAL_HOSTS.get(vendor)
    host = _host(base_url)
    return bool(official and host and not any(host == item or host.endswith(f".{item}") for item in official))


def region_for(vendor: str, base_url: str = "") -> str:
    """这条连接按哪个地区的价:Endpoint 落在国际站就是 `intl`,否则 `cn`。"""
    host = _host(base_url)
    if host and any(marker in host for marker in _INTL_HOSTS.get(vendor, ())):
        return "intl"
    return "cn"


def _best(entries: list[ListPrice], model_id: str) -> list[ListPrice]:
    """精确匹配优先;没有就取最长的那个前缀(它的每个计价单位各一条)。"""
    exact = [entry for entry in entries if not entry.prefix and entry.matches(model_id)]
    if exact:
        return exact
    prefixed = [entry for entry in entries if entry.prefix and entry.matches(model_id)]
    if not prefixed:
        return []
    longest = max(len(entry.model) for entry in prefixed)
    return [entry for entry in prefixed if len(entry.model) == longest]


def lookup(vendor: str, model_id: str, *, region: str = "cn") -> list[ListPrice]:
    """这家自己的官方连接上,这个模型的挂牌价(每个能力 × 计价单位一条)。"""
    if not model_id.strip():
        return []
    candidates = [
        entry for entry in LIST_PRICES if entry.vendor == vendor and entry.region in (region, "global")
    ]
    return _best(candidates, model_id)


def lookup_for_relay(model_id: str) -> list[ListPrice]:
    """中转连接上的这个 id 借哪家的原厂价。

    **只认精确的 id,而且只在它唯一属于一家时。**前缀在中转上不可靠(同一个前缀可能是两家的
    不同模型);两家都卖同一个 id(百炼也挂 DeepSeek)时不知道中转背后是哪一家,干脆不借。
    同一家有国内、国际两个价时取国内那份 —— 表里国内厂商的主价目就是它。
    """
    if not model_id.strip():
        return []
    exact = [entry for entry in LIST_PRICES if not entry.prefix and entry.matches(model_id)]
    vendors = {entry.vendor for entry in exact}
    if len(vendors) != 1:
        return []
    regions = {entry.region for entry in exact}
    preferred = next((region for region in ("global", "cn", "intl") if region in regions), "")
    return [entry for entry in exact if entry.region == preferred]

