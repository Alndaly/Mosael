"""一个模型的预览图是不是 NSFW:插件这一侧能交出的两种依据(ADR 0038 §9 的第 2、3 种)。

- **元数据推断**(`metadata`):LoRA 训练标签(`ss_tag_frequency`)里成人标签占的比重,文件名和标题里的关键词。不联网、
  不要额外的模型;会漏(没写标签的、名字起得含蓄的),也可能错(训练集里偶尔一两张)—— 所以标签要占到训练图的一成才算;
- **Civitai 的标记**(`civitai`):对上了 Civitai 上的版本(经 Mosael 下载的、按哈希查到的,见 provenance)时,作者 / 站方
  给这个模型打的 `nsfw`。

这里只交出依据(每条 `{"source", "nsfw", …}`),**不下结论**:宿主把它们和手动标记、本机识别预览图合成一个判断,
手动的压过别的(见宿主的 domain/model_library)。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

#: 训练标签里算成人内容的(Danbooru / e621 的写法,下划线当空格、不分大小写)。只收**明说**的:裸、性器官、性行为;
#: `breasts`、`swimsuit`、`lingerie` 这些 SFW 图上也常见的不算。
EXPLICIT_TAGS = frozenset({
    "nsfw", "explicit", "rating:explicit", "rating explicit",
    "nude", "nudity", "naked", "completely nude", "topless", "bottomless", "breasts out", "nipple slip",
    "nipples", "areolae", "areola", "pussy", "vagina", "penis", "testicles", "erection", "anus", "genitals",
    "pubic hair", "uncensored", "censored", "mosaic censoring", "bar censor",
    "sex", "vaginal", "anal", "oral", "fellatio", "irrumatio", "cunnilingus", "paizuri", "handjob", "footjob",
    "masturbation", "fingering", "cum", "cum in pussy", "cum on body", "creampie", "ejaculation", "after sex",
    "sex toy", "dildo", "vibrator", "ahegao", "futanari", "hentai", "porn",
})
#: 文件名、标题里的词(驼峰拆开、按非字母切开后整词比):名字就说明白了的。
EXPLICIT_WORDS = frozenset({
    "nsfw", "hentai", "porn", "porno", "xxx", "nude", "nudes", "nudity", "naked", "lewd", "uncensored", "erotic",
    "sex", "blowjob", "fellatio", "cock", "dick", "penis", "pussy", "vagina", "nipple", "nipples", "tits", "cum",
    "creampie", "anal", "paizuri", "ahegao", "futanari", "futa", "bdsm",
})
#: 一个成人标签占到训练图的多少才算(按训练标签里出现最多的那个标签的次数当图数 —— 触发词、画风标签每张都有)。
TAG_SHARE = 0.1
#: 缓存里留下的成人标签:比重不到这个的不留(一两张图里的偶然),最多留几个。
KEPT_SHARE = 0.02
KEPT_TAGS = 8
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[a-z]+")


def _tag(raw: str) -> str:
    """训练标签的写法收成一种:下划线当空格、去掉权重括号和转义、小写。"""
    text = raw.strip().lower().replace("_", " ").replace("\\", "")
    return re.sub(r"^[(\[{]+|[)\]}]+$|:[\d.]+$", "", text).strip()


def tag_shares(counts: Counter[str]) -> dict[str, float]:
    """训练标签(标签 → 出现次数)里的成人标签各占多少(相对出现最多的那个标签)。缓存记的就是它(见 library._inputs)。"""
    if not counts:
        return {}
    top = max(counts.values())
    if top <= 0:
        return {}
    shares: dict[str, float] = {}
    for raw, count in counts.items():
        tag = _tag(raw)
        if tag in EXPLICIT_TAGS:
            shares[tag] = max(shares.get(tag, 0.0), round(count / top, 3))
    kept = sorted(((tag, share) for tag, share in shares.items() if share >= KEPT_SHARE), key=lambda one: (-one[1], one[0]))
    return dict(kept[:KEPT_TAGS])


def name_words(*texts: str) -> list[str]:
    """文件名、标题里说明是成人内容的词(驼峰拆开再认:`BlowjobComic`、`NippleSizeSlider`)。"""
    found: list[str] = []
    for text in texts:
        for word in _WORD.findall(_CAMEL.sub(" ", text or "").lower()):
            if word in EXPLICIT_WORDS and word not in found:
                found.append(word)
    return found


def signals(name: str, title: str, shares: dict[str, float], civitai: dict[str, Any] | None) -> list[dict[str, Any]]:
    """一个文件的 NSFW 依据。元数据只在**说是**时才交(它说不出「安全」);Civitai 两种都交。"""
    out: list[dict[str, Any]] = []
    tags = [tag for tag, share in shares.items() if share >= TAG_SHARE]
    words = name_words(name.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0], title)
    if tags or words:
        entry: dict[str, Any] = {"source": "metadata", "nsfw": True}
        if tags:
            entry["tags"] = tags
        if words:
            entry["words"] = words
        out.append(entry)
    if civitai:
        out.append({"source": "civitai", "nsfw": bool(civitai.get("nsfw"))})
    return out
