"""合成前的一道判断:这段文本,这个音色念得了吗。

念不了的时候会发生什么:引擎**不会报错**。它按自己认识的那套发音规则硬念一遍,产出一段
听起来像中文又不像中文的东西 —— 用户等了几十秒,拿到一段废音,而且没有任何线索说明原因。
这是最糟的失败方式:失败了却装作成功。

判据只用**书写系统**,不做语言识别:
  ・假名(平假名/片假名)只出现在日文里 —— 这是硬证据,不是猜测;
  ・谚文只出现在韩文里,同理;
  ・汉字中日共用、拉丁字母几十种语言共用 —— **它们证明不了任何事**,所以不据此拦截。

于是这道闸门只在**能确证**的时候关上:整段日文字幕交给一个中英模型,会被挡下来并说清出路;
而中文里夹一个「の」不会 —— 少数几个假名达不到阈值。宁可漏拦,不可错拦:错拦挡住的是一次
本来能成的合成,而漏拦的代价用户自己听得出来。
"""
from __future__ import annotations

import re

#: 平假名 + 片假名(不含半角片假名与中日共用的标点)。
_KANA = re.compile(r"[぀-ゟ゠-ヺー-ヿ]")
#: 谚文音节 + 字母。
_HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
#: 西里尔(俄语等)、阿拉伯、天城文(印地语)—— 同样是**只属于某一族语言**的字母表。
#: 注意这三条给出的是"字母系统",不是具体语言:西里尔也写乌克兰语、塞尔维亚语,天城文也写
#: 马拉地语。所以它们只够回答「基础模型念不了这个」,不够回答「这一定是俄语」——
#: 而这里要的正是前者。
_CYRILLIC = re.compile(r"[а-џҊ-ԧ]")
_ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
#: 计入分母的「实字」:去掉空白、数字、标点之后剩下的。
_MEANINGFUL = re.compile(r"[^\s\d\W_]", re.UNICODE)

#: 占比到多少才算「这段就是这个语言」。一两个假名是引用、是外来词、是颜文字;
#: 十分之一以上的实字都是假名,那就是一段日文。
_MIN_SHARE = 0.1
#: 也要够几个字符 —— 短句里一个假名就能超过 10%。
_MIN_COUNT = 2


def detect_script(text: str) -> str:
    """能确证的书写系统:`"ja"` / `"ko"` / `"ru"` / `"ar"` / `"hi"`,证明不了就返回 `""`。

    **拉丁字母的语言(法语、德语、西班牙语、意大利语、芬兰语)永远返回 `""`** —— 它们和英语
    共用一套字母,没有任何字符能证明"这是法语而不是英语"。所以那几门语言的权重选不出来,
    只能由用户明说要用哪一份(见 tts_models.weights_for 的 `model_id`)。装作能认出来的话,
    代价是给英文文本套上一份法语权重,而那同样是一段念不对的音频。

    返回空串**不代表是中文或英文**,只代表「这段文本没有给出任何硬证据」—— 调用方据此放行,
    因为这里的职责是抓确凿的不匹配,不是给每段文本贴一个语言标签。
    """
    body = text or ""
    total = len(_MEANINGFUL.findall(body))
    if total == 0:
        return ""
    for script, pattern in (
        ("ja", _KANA),
        ("ko", _HANGUL),
        ("ru", _CYRILLIC),
        ("ar", _ARABIC),
        ("hi", _DEVANAGARI),
    ):
        hits = len(pattern.findall(body))
        if hits >= _MIN_COUNT and hits / total >= _MIN_SHARE:
            return script
    return ""


def edge_voice_language(voice: str) -> str:
    """Edge 音色 id 自带 locale(`ja-JP-NanamiNeural`)—— 语言就写在名字里,不用猜。"""
    head = (voice or "").split("-", 1)[0].strip().lower()
    return head if len(head) == 2 and head.isalpha() else ""


def clone_supports(script: str) -> bool:
    """本地克隆**现在**念不念得了这套书写系统。

    答案不在这里 —— 它取决于这台机器上装了哪几份权重(见 audio/f5_models)。引擎什么语言都
    支持,支持范围由模型决定;此前这里写死"不认日韩",等于把一个可以通过下载解决的问题
    说成了引擎的固有限制。

    没有硬证据(空 script)一律放行:那是中英文或拿不准,默认模型就是为这种情况准备的。
    """
    if not script:
        return True
    from app.audio import f5_models

    return script in f5_models.installed_languages()
