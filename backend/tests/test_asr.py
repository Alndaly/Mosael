from __future__ import annotations

from app.ai.runtime.asr_worker import funasr_sentences_to_segments, whisperx_segments
from app.domain.voices.service import to_segment_ins
from tests.util import fresh_client


def test_funasr_sentences_map_chars_to_word_tokens() -> None:
    sentences = [{
        "text": "嗯,大家好。",
        "timestamp": [[100, 400], [600, 900], [900, 1200], [1200, 1500]],
        "spk": 0,
        "start": 100,
        "end": 1500,
    }]
    segments = funasr_sentences_to_segments(sentences)
    assert len(segments) == 1
    seg = segments[0]
    assert seg["speaker"] == "SPEAKER_00"
    assert (seg["start"], seg["end"]) == (0.1, 1.5)
    # punctuation carries no span → 4 timed chars zip with 4 spans
    assert [w["word"] for w in seg["words"]] == ["嗯", "大", "家", "好"]
    assert seg["words"][0] == {"word": "嗯", "start": 0.1, "end": 0.4}


def test_whisperx_segments_keep_timed_words_only() -> None:
    aligned = {"segments": [{
        "start": 0.0, "end": 2.0, "text": " hello world ",
        "words": [
            {"word": "hello", "start": 0.0, "end": 0.8},
            {"word": "world"},  # no timing → dropped
        ],
    }]}
    segments = whisperx_segments(aligned)
    assert segments[0]["text"] == "hello world"
    assert [w["word"] for w in segments[0]["words"]] == ["hello"]


def test_to_segment_ins_builds_tokens_and_skips_empty() -> None:
    parsed = to_segment_ins([
        {"start": 0, "end": 1.2, "text": "你好", "speaker": "SPEAKER_00",
         "words": [{"word": "你", "start": 0.0, "end": 0.5}, {"word": "好", "start": 0.5, "end": 0.5}]},
        {"start": 2, "end": 2, "text": "zero length"},
    ])
    assert len(parsed) == 1
    seg = parsed[0]
    assert seg.speaker == "SPEAKER_00" and len(seg.tokens) == 2
    # zero-length word timing padded so token stays valid
    assert seg.tokens[1].end_time > seg.tokens[1].start_time


def test_transcribe_endpoint_creates_job(monkeypatch) -> None:
    started: list[str] = []

    # 线程由任务总线派发(dispatch_job),不再是 service 自己 spawn:
    # 把总线的线程换成同步执行,再记录 worker 收到的 asset_id。
    def fake_thread(target=None, daemon=None):
        class T:
            def start(self_inner) -> None:
                target()
        return T()

    monkeypatch.setattr("app.domain.jobs.threading.Thread", fake_thread)
    monkeypatch.setattr("app.domain.voices.service._run_transcription", lambda job_id, asset_id: started.append(asset_id))
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "kind": "video", "name": "S",
              "file_key": "media/s.mp4", "media_info": {"duration": 10}},
    ).json()

    res = client.post(f"/api/assets/{asset['id']}/transcribe")
    assert res.status_code == 200
    job = res.json()
    assert job["kind"] == "transcribe" and job["status"] == "queued"
    assert started == [asset["id"]]

    image = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "kind": "image", "name": "I",
              "file_key": "media/i.png", "media_info": {}},
    ).json()
    assert client.post(f"/api/assets/{image['id']}/transcribe").status_code == 422
