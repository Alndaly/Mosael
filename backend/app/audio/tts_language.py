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
#: 计入分母的「实字」:去掉空白、数字、标点之后剩下的。
_MEANINGFUL = re.compile(r"[^\s\d\W_]", re.UNICODE)

#: 占比到多少才算「这段就是这个语言」。一两个假名是引用、是外来词、是颜文字;
#: 十分之一以上的实字都是假名,那就是一段日文。
_MIN_SHARE = 0.1
#: 也要够几个字符 —— 短句里一个假名就能超过 10%。
_MIN_COUNT = 2


def detect_script(text: str) -> str:
    """能确证的书写系统:`"ja"` / `"ko"`,证明不了就返回 `""`。

    返回空串**不代表是中文或英文**,只代表「这段文本没有给出任何硬证据」—— 调用方据此放行,
    因为这里的职责是抓确凿的不匹配,不是给每段文本贴一个语言标签。
    """
    body = text or ""
    total = len(_MEANINGFUL.findall(body))
    if total == 0:
        return ""
    for script, pattern in (("ja", _KANA), ("ko", _HANGUL)):
        hits = len(pattern.findall(body))
        if hits >= _MIN_COUNT and hits / total >= _MIN_SHARE:
            return script
    return ""


def edge_voice_language(voice: str) -> str:
    """Edge 音色 id 自带 locale(`ja-JP-NanamiNeural`)—— 语言就写在名字里,不用猜。"""
    head = (voice or "").split("-", 1)[0].strip().lower()
    return head if len(head) == 2 and head.isalpha() else ""


def clone_supports(script: str) -> bool:
    """本地克隆(F5-TTS 的 F5TTS_v1_Base)认不认这套书写系统。

    这个检查点的**权威**是模型本身:v1_Base 在中英语料上训练,vocab 里没有假名,也没有谚文。
    换一个日语微调模型的话这里要跟着改 —— 所以判据写在这一处,而不是散在调用点。
    """
    return script not in ("ja", "ko")
