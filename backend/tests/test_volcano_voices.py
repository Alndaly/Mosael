"""Which voices 火山 offers, and what happens when the account cannot be asked.

The voice id is not cosmetic: synthesis fails with an opaque `55000000 resource ID is
mismatched` unless the request names the voice's family. So the list is pulled from the
account when AK/SK are configured — that is the only source that knows each voice's family —
and falls back to a built-in list when they are not. A user without AK/SK must still get a
usable dropdown; an empty one would read as "this engine has no voices".
"""

from __future__ import annotations

import pytest

from app.ai.providers.adapters.bytedance.volcano.speech import PODCAST_SPEAKERS, VOLCANO_BUILTIN_VOICES
from app.ai.providers.adapters.bytedance.volcano import speakers
from tests.util import fresh_client


def _admin_client():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    return client


def _voices(client, engine: str) -> list[dict]:
    res = client.get(f"/api/tts/voices?engine={engine}")
    assert res.status_code == 200, res.text
    return res.json()


def test_without_ak_sk_the_builtin_list_is_served() -> None:
    client = _admin_client()
    voices = _voices(client, "builtin:volcano")
    assert [v["id"] for v in voices] == [v.id for v in VOLCANO_BUILTIN_VOICES]
    assert voices[0]["label"] and voices[0]["label"] != voices[0]["id"], "labels should be readable"


def test_with_ak_sk_the_account_list_wins_and_carries_the_family(monkeypatch) -> None:
    """The family is the whole point of asking the account — synthesis needs it in a header."""
    client = _admin_client()
    client.post(
        "/api/settings/providers",
        json={"name": "v", "vendor": "volcano", "config": {"api_key": "k", "ak": "AK", "sk": "SK"}},
    )
    monkeypatch.setattr(
        "app.ai.providers.adapters.bytedance.volcano.speech.list_all_speakers",
        lambda ak, sk: [{"VoiceType": "zh_male_custom_bigtts", "Name": "定制音色", "ResourceID": "seed-icl-2.0"}],
    )

    voices = _voices(client, "builtin:volcano")

    #: 账号现拉的标成 `account`;资源族放在只有火山 Adapter 解释的 `extra` 里;语言由火山的 id 约定(`zh_…`)翻出来(ADR 0087)。
    assert voices == [{"id": "zh_male_custom_bigtts", "label": "定制音色", "source": "account", "languages": ["zh"],
                       "gender": "", "styles": [], "models": [], "preview_url": "",
                       "extra": {"resource_id": "seed-icl-2.0"}, "is_default": False}]


def test_account_voices_take_a_language_only_from_a_known_prefix(monkeypatch) -> None:
    """白名单,不是「任意两个字母」:账号里自建的 `my_voice_42` 不该被认成某种语言 —— 认错了会拦下一次本来能成的合成。"""
    from app.ai.providers import VoiceCatalogContext
    from app.ai.providers.adapters.bytedance.volcano.speech import VolcanoSpeechAdapter

    monkeypatch.setattr(
        "app.ai.providers.adapters.bytedance.volcano.speech.list_all_speakers",
        lambda ak, sk: [{"VoiceType": "ja_female_x_bigtts", "Name": "a"}, {"VoiceType": "my_voice_42", "Name": "b"}],
    )
    voices = VolcanoSpeechAdapter.voices(VoiceCatalogContext(connection_extra={"ak": "AK", "sk": "SK"}))
    assert [(voice.id, voice.languages) for voice in voices] == [("ja_female_x_bigtts", ("ja",)), ("my_voice_42", ())]


def test_a_failing_account_lookup_falls_back_instead_of_erroring(monkeypatch) -> None:
    """Wrong AK/SK must not leave the user with an empty dropdown and no way to synthesise."""
    client = _admin_client()
    client.post(
        "/api/settings/providers",
        json={"name": "v", "vendor": "volcano", "config": {"api_key": "k", "ak": "bad", "sk": "bad"}},
    )

    def boom(ak, sk):
        raise speakers.VolcOpenAPIError("100004 InvalidAccessKey")

    monkeypatch.setattr("app.ai.providers.adapters.bytedance.volcano.speech.list_all_speakers", boom)

    assert [v["id"] for v in _voices(client, "builtin:volcano")] == [v.id for v in VOLCANO_BUILTIN_VOICES]


def test_podcast_voices_are_the_saturn_set() -> None:
    """These only work on the podcast socket; offering the normal TTS voices there fails."""
    client = _admin_client()
    assert [v["id"] for v in _voices(client, "builtin:volcano-podcast")] == [v.id for v in PODCAST_SPEAKERS]


def test_openai_voices_come_from_the_engine_constant() -> None:
    client = _admin_client()
    assert "alloy" in [v["id"] for v in _voices(client, "builtin:openai")]
    # 旧 id **不再**解析:启动迁移把库里的三处都改掉了,读取代码里不留别名(见 ADR 0006)。
    assert _voices(client, "openai-tts") == []


def test_an_engine_with_no_listable_voices_answers_empty() -> None:
    """Clone picks from the voice library, not from an engine catalogue."""
    assert _voices(_admin_client(), "builtin:clone") == []


class TestSigning:
    """The signature is the only reason the OpenAPI module exists, so pin its shape."""

    def test_the_secret_never_appears_in_the_header(self) -> None:
        headers = speakers._signed_headers("AKmyaccess", "SKmysecret", "Action=ListSpeakers", b"{}")
        joined = " ".join(headers.values())
        assert "SKmysecret" not in joined, "the secret key leaked into the request"
        assert "AKmyaccess" in headers["Authorization"], "the access key identifies the caller"

    def test_the_signature_covers_the_body(self) -> None:
        """Otherwise a signed request could be replayed with different arguments."""
        one = speakers._signed_headers("AK", "SK", "Action=ListSpeakers", b'{"Page": 1}')
        two = speakers._signed_headers("AK", "SK", "Action=ListSpeakers", b'{"Page": 2}')
        assert one["X-Content-Sha256"] != two["X-Content-Sha256"]

    def test_missing_credentials_are_refused_before_any_request(self) -> None:
        with pytest.raises(speakers.VolcOpenAPIError, match="AK"):
            speakers.list_speakers("", "", "seed-tts-1.0")

    def test_one_unavailable_family_does_not_lose_the_others(self, monkeypatch) -> None:
        """An account entitled to 1.0 but not 2.0 should see the voices it has."""
        def per_family(ak, sk, family, **kwargs):
            if family == "seed-tts-1.0":
                return [{"VoiceType": "v1", "Name": "V1"}]
            raise speakers.VolcOpenAPIError("not entitled")

        monkeypatch.setattr(speakers, "list_speakers", per_family)
        merged = speakers.list_all_speakers("AK", "SK")
        assert [s["VoiceType"] for s in merged] == ["v1"]
        assert merged[0]["ResourceID"] == "seed-tts-1.0", "the family must be stamped on"

    def test_every_family_failing_is_an_error_not_an_empty_list(self, monkeypatch) -> None:
        """Empty would be indistinguishable from "this account has no voices"."""
        def always_fail(ak, sk, family, **kwargs):
            raise speakers.VolcOpenAPIError("100004 InvalidAccessKey")

        monkeypatch.setattr(speakers, "list_speakers", always_fail)
        with pytest.raises(speakers.VolcOpenAPIError, match="InvalidAccessKey"):
            speakers.list_all_speakers("AK", "SK")
