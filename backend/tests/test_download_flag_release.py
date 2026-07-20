"""A failed model download must not wedge the downloader for the life of the process.

start_download refuses while _store.downloading() is true, and _run_download set that flag
before doing any work. Anything escaping the body — an unspawnable worker, a disk error, a bug
— left the flag set, so every later download was rejected with 「已有模型正在下载」 and only a
restart cleared it. One bad attempt disabled the feature.
"""

from __future__ import annotations

import pytest

from app.audio import asr_models, tts_models


@pytest.mark.parametrize(
    ("module", "any_id"),
    [(asr_models, None), (tts_models, None)],
    ids=["asr", "tts"],
)
def test_a_crashing_download_releases_the_flag(module, any_id, monkeypatch) -> None:
    model_id = next(iter(module._BY_ID))

    def explode(_id: str) -> None:
        raise RuntimeError("worker could not start")

    monkeypatch.setattr(module, "_download_body", explode)
    module._store.set(model_id, module._Live(status="downloading", message="准备下载…"))

    module._run_download(model_id)

    assert not module._store.downloading(), "the flag survived a failed download"
    status = module._store.get(model_id)
    assert status is not None and status.status == "failed"
    assert "worker could not start" in status.message


@pytest.mark.parametrize(("module",), [(asr_models,), (tts_models,)], ids=["asr", "tts"])
def test_the_failure_reason_reaches_the_user(module, monkeypatch) -> None:
    """A silent failure here is indistinguishable from a download that is merely slow."""
    model_id = next(iter(module._BY_ID))

    monkeypatch.setattr(
        module, "_download_body", lambda _id: (_ for _ in ()).throw(OSError("No space left on device"))
    )
    module._run_download(model_id)

    status = module._store.get(model_id)
    assert "No space left on device" in status.message
