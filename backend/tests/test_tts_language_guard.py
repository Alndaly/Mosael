"""语言对不上时,合成**不会失败** —— 它会交出一段废音。

用户报的原话:「明明是日文,配出来的声音是中文和听不懂的声音」。引擎不认识假名,就按自己那套
发音规则硬念一遍,然后报成功。等了几十秒、消耗了额度,拿到一段没法用的音频,而且没有任何线索
指向原因 —— 这是最糟的失败方式:失败了却装作成功。

所以判据只用**书写系统**(假名、谚文是硬证据),并且只在能确证时关闸:错拦挡住的是一次本来
能成的合成,而漏拦的代价用户自己听得出来。
"""
from __future__ import annotations

import pytest

from app.ai.runtime.f5_models import clone_supports
from app.ai.runtime.tts_language import detect_script
from app.domain.voices.voices import _refuse_if_unspeakable
from app.domain.voices.errors import VoiceError
from app.domain.voices.voice_ref import VoiceRef


def test_kana_is_hard_evidence_of_japanese() -> None:
    assert detect_script("三日前のだったらちょっとお腹壊しちゃうかな") == "ja"
    assert detect_script("お漏らし。") == "ja"
    # 汉字混在里面也一样 —— 认的是假名,不是"看起来像什么"。
    assert detect_script("反せするんですここにいつも寝てるんでしょ？") == "ja"


def test_a_stray_kana_in_chinese_is_not_japanese() -> None:
    """中文里夹一个「の」是外来写法,不是一段日文。

    错拦比漏拦糟:它挡住的是一次本来能成的合成,而用户根本不知道自己触发了什么规则。
    """
    assert detect_script("这个词在日语里叫の,很有意思") == ""


def test_chinese_and_english_give_no_evidence_at_all() -> None:
    """汉字中日共用、拉丁字母几十种语言共用 —— 它们**证明不了**语言,所以不据此拦截。"""
    assert detect_script("这是一段中文") == ""
    assert detect_script("Hello world") == ""
    assert detect_script("") == ""


def test_korean_too() -> None:
    assert detect_script("안녕하세요 반갑습니다") == "ko"
    assert clone_supports("ko") is False


def test_clone_model_reads_chinese_and_english_only() -> None:
    """本地克隆用的是 F5TTS_v1_Base:中英语料训练,vocab 里没有假名。"""
    assert clone_supports("ja") is False
    assert clone_supports("") is True


def test_japanese_into_the_clone_engine_is_refused_up_front() -> None:
    with pytest.raises(VoiceError) as exc:
        _refuse_if_unspeakable("お漏らし。ここに寝てる", VoiceRef("builtin:clone", cloned_voice="v", model="f5-tts"))
    # 报错要指出**出路**,不然用户只知道被拒绝了。
    assert "Edge" in str(exc.value)


def test_a_matching_voice_is_let_through() -> None:
    """音色目录上 Nanami 声明的是 `ja-JP` —— 日文配它,正是该放行的情形(BCP 47 只看主语言)。"""
    _refuse_if_unspeakable("お漏らし。ここに寝てる", VoiceRef("builtin:edge", voice="ja-JP-NanamiNeural"))


def test_a_voice_declared_chinese_is_refused_for_japanese_text() -> None:
    """语言只认音色目录上的声明(ADR 0087):Edge 的晓晓、火山内置的灿灿都声明了中文。"""
    with pytest.raises(VoiceError):
        _refuse_if_unspeakable("お漏らし。ここに寝てる", VoiceRef("builtin:edge", voice="zh-CN-XiaoxiaoNeural"))
    with pytest.raises(VoiceError):
        _refuse_if_unspeakable("お漏らし。ここに寝てる", VoiceRef("builtin:volcano", voice="zh_female_cancan_mars_bigtts"))


def test_unknown_voice_language_is_let_through() -> None:
    """OpenAI 那种多语言音色(目录上不声明语言)、账号里的自定义音色(不在内置目录里)—— 语言未知就放行。

    这里的职责是抓**确凿的**不匹配,不是给每个音色贴标签;拿不准时挡住用户是越权。
    """
    _refuse_if_unspeakable("お漏らし。ここに寝てる", VoiceRef("builtin:openai", voice="alloy"))
    _refuse_if_unspeakable("お漏らし。ここに寝てる", VoiceRef("builtin:volcano", voice="my_custom_voice_42"))


def test_the_guard_does_not_parse_ids_any_more() -> None:
    """**不从 id 里猜**:长得像中文音色的 id,只要不在目录里(账号现拉的、手填的),合成前就不拦 ——
    合成前的检查不为它签名现拉账号清单;账号音色的语言由界面在提交前按它拿到的目录提示。"""
    _refuse_if_unspeakable("お漏らし。ここに寝てる", VoiceRef("builtin:volcano", voice="zh_female_not_in_catalogue_bigtts"))
