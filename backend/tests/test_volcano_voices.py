"""Which voices 火山 offers, and what happens when the account cannot be asked.

The voice id is not cosmetic: synthesis fails with an opaque `55000000 resource ID is
mismatched` unless the request names the voice's family. So the list is pulled from the
account when AK/SK are configured — that is the only source that knows each voice's family —
and falls back to a built-in list when they are not. A user without AK/SK must still get a
usable dropdown; an empty one would read as "this engine has no voices".
"""

from __future__ import annotations

import pytest

from app.ai.providers import PODCAST_SPEAKERS, VOLCANO_BUILTIN_VOICES
from app.integrations import volc_openapi
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
    voices = _voices(client, "volcano")
    assert [v["value"] for v in voices] == [v for v, _ in VOLCANO_BUILTIN_VOICES]
    assert voices[0]["label"] and voices[0]["label"] != voices[0]["value"], "labels should be readable"


def test_with_ak_sk_the_account_list_wins_and_carries_the_family(monkeypatch) -> None:
    """The family is the whole point of asking the account — synthesis needs it in a header."""
    client = _admin_client()
    client.post(
        "/api/settings/providers",
        json={"name": "v", "vendor": "volcano", "config": {"api_key": "k", "ak": "AK", "sk": "SK"}},
    )
    monkeypatch.setattr(
        "app.integrations.volc_openapi.list_all_speakers",
        lambda ak, sk: [{"VoiceType": "zh_male_custom_bigtts", "Name": "定制音色", "ResourceID": "seed-icl-2.0"}],
    )

    voices = _voices(client, "volcano")

    assert voices == [{"value": "zh_male_custom_bigtts", "label": "定制音色", "resource_id": "seed-icl-2.0"}]


def test_a_failing_account_lookup_falls_back_instead_of_erroring(monkeypatch) -> None:
    """Wrong AK/SK must not leave the user with an empty dropdown and no way to synthesise."""
    client = _admin_client()
    client.post(
        "/api/settings/providers",
        json={"name": "v", "vendor": "volcano", "config": {"api_key": "k", "ak": "bad", "sk": "bad"}},
    )

    def boom(ak, sk):
        raise volc_openapi.VolcOpenAPIError("100004 InvalidAccessKey")

    monkeypatch.setattr("app.integrations.volc_openapi.list_all_speakers", boom)

    assert [v["value"] for v in _voices(client, "volcano")] == [v for v, _ in VOLCANO_BUILTIN_VOICES]


def test_podcast_voices_are_the_saturn_set() -> None:
    """These only work on the podcast socket; offering the normal TTS voices there fails."""
    client = _admin_client()
    assert [v["value"] for v in _voices(client, "volcano-podcast")] == [v for v, _ in PODCAST_SPEAKERS]


def test_openai_voices_come_from_the_engine_constant() -> None:
    client = _admin_client()
    assert "alloy" in [v["value"] for v in _voices(client, "openai")]
    # 旧 id **不再**解析:启动迁移把库里的三处都改掉了,读取代码里不留别名(见 ADR 0006)。
    assert _voices(client, "openai-tts") == []


def test_an_engine_with_no_listable_voices_answers_empty() -> None:
    """Clone picks from the voice library, not from an engine catalogue."""
    assert _voices(_admin_client(), "clone") == []


class TestSigning:
    """The signature is the only reason the OpenAPI module exists, so pin its shape."""

    def test_the_secret_never_appears_in_the_header(self) -> None:
        headers = volc_openapi._signed_headers("AKmyaccess", "SKmysecret", "Action=ListSpeakers", b"{}")
        joined = " ".join(headers.values())
        assert "SKmysecret" not in joined, "the secret key leaked into the request"
        assert "AKmyaccess" in headers["Authorization"], "the access key identifies the caller"

    def test_the_signature_covers_the_body(self) -> None:
        """Otherwise a signed request could be replayed with different arguments."""
        one = volc_openapi._signed_headers("AK", "SK", "Action=ListSpeakers", b'{"Page": 1}')
        two = volc_openapi._signed_headers("AK", "SK", "Action=ListSpeakers", b'{"Page": 2}')
        assert one["X-Content-Sha256"] != two["X-Content-Sha256"]

    def test_missing_credentials_are_refused_before_any_request(self) -> None:
        with pytest.raises(volc_openapi.VolcOpenAPIError, match="AK"):
            volc_openapi.list_speakers("", "", "seed-tts-1.0")

    def test_one_unavailable_family_does_not_lose_the_others(self, monkeypatch) -> None:
        """An account entitled to 1.0 but not 2.0 should see the voices it has."""
        def per_family(ak, sk, family, **kwargs):
            if family == "seed-tts-1.0":
                return [{"VoiceType": "v1", "Name": "V1"}]
            raise volc_openapi.VolcOpenAPIError("not entitled")

        monkeypatch.setattr(volc_openapi, "list_speakers", per_family)
        merged = volc_openapi.list_all_speakers("AK", "SK")
        assert [s["VoiceType"] for s in merged] == ["v1"]
        assert merged[0]["ResourceID"] == "seed-tts-1.0", "the family must be stamped on"

    def test_every_family_failing_is_an_error_not_an_empty_list(self, monkeypatch) -> None:
        """Empty would be indistinguishable from "this account has no voices"."""
        def always_fail(ak, sk, family, **kwargs):
            raise volc_openapi.VolcOpenAPIError("100004 InvalidAccessKey")

        monkeypatch.setattr(volc_openapi, "list_speakers", always_fail)
        with pytest.raises(volc_openapi.VolcOpenAPIError, match="InvalidAccessKey"):
            volc_openapi.list_all_speakers("AK", "SK")
