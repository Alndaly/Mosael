"""语言对不上时,合成**不会失败** —— 它会交出一段废音。

用户报的原话:「明明是日文,配出来的声音是中文和听不懂的声音」。引擎不认识假名,就按自己那套
发音规则硬念一遍,然后报成功。等了几十秒、消耗了额度,拿到一段没法用的音频,而且没有任何线索
指向原因 —— 这是最糟的失败方式:失败了却装作成功。

所以判据只用**书写系统**(假名、谚文是硬证据),并且只在能确证时关闸:错拦挡住的是一次本来
能成的合成,而漏拦的代价用户自己听得出来。
"""
from __future__ import annotations

import pytest

from app.ai.runtime.tts_language import clone_supports, detect_script, edge_voice_language
from app.domain.voices.voices import VoiceError, _refuse_if_unspeakable


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
        _refuse_if_unspeakable("お漏らし。ここに寝てる", "clone", "", "f5-tts")
    # 报错要指出**出路**,不然用户只知道被拒绝了。
    assert "Edge" in str(exc.value)


def test_a_matching_voice_is_let_through() -> None:
    """Edge 的音色 id 自带 locale —— 日文配 ja-JP 的音色,正是该放行的情形。"""
    assert edge_voice_language("ja-JP-NanamiNeural") == "ja"
    _refuse_if_unspeakable("お漏らし。ここに寝てる", "edge", "ja-JP-NanamiNeural", "")


def test_a_chinese_voice_id_is_refused_for_japanese_text() -> None:
    """火山的内置音色叫 `zh_female_…` —— 语言就写在名字里,不用猜。"""
    with pytest.raises(VoiceError):
        _refuse_if_unspeakable("お漏らし。ここに寝てる", "volcano", "zh_female_cancan_mars_bigtts", "")


def test_unknown_voice_language_is_let_through() -> None:
    """账号里的自定义音色、以及 OpenAI 那种多语言引擎 —— 音色语言未知就放行。

    这里的职责是抓**确凿的**不匹配,不是给每个音色贴标签;拿不准时挡住用户是越权。
    """
    _refuse_if_unspeakable("お漏らし。ここに寝てる", "openai", "alloy", "")
    _refuse_if_unspeakable("お漏らし。ここに寝てる", "volcano", "my_custom_voice_42", "")
