"""拆镜头之「判」那一半(domain/shots/describe.py + vocab.py):封闭词表、对账、节奏提示、台词分配。

视觉调用全部用假的 `ask`(消息 → 回答正文),不碰网络。对账的判据照 ADR 0061:
表外的词清空并记提示;strong 运镜实测 < 1.5(且镜长 ≥ 1s)去掉并记「被拦」;固定而实测 > 12 只提示;
画面描述太短 / 空话提示;节奏三条(开篇钩子、兑现前有铺垫、连 6 镜同角色)。
"""

from __future__ import annotations

import json
from pathlib import Path


from app.domain.shots import describe, vocab
from app.domain.shots.frames import SHEET_MAX

# --------------------------------------------------------------------------------------
# vocab:五张封闭词表
# --------------------------------------------------------------------------------------

def test_vocab_tables_are_closed_and_aligned() -> None:
    assert set(vocab.SIZES) >= {"extreme-wide", "wide", "medium", "medium-close", "close", "extreme-close", "none"}
    assert set(vocab.CATEGORIES) >= {"establishing", "subject", "dialogue", "insert", "text-card"}
    assert set(vocab.TRANSITIONS) >= {"cut", "dissolve", "fade-in", "wipe"}
    assert set(vocab.RHYTHMS) >= {"hook", "setup", "payoff", "breath"}
    for table in (vocab.SIZES, vocab.CATEGORIES, vocab.TRANSITIONS, vocab.RHYTHMS):
        for key, names in table.items():
            assert set(names) == {"zh", "en"}, f"{key} 缺中英之一"
    for key, (names, cls) in vocab.CAMERA_MOVES.items():
        assert set(names) == {"zh", "en"}
        assert cls in ("strong", "subtle", "still"), f"{key} 的实测档不对"


def test_camera_class_and_labels() -> None:
    assert vocab.camera_class("static") == "still"
    assert vocab.camera_class("push-in") == "strong"
    assert vocab.camera_class("handheld") == "subtle"
    assert vocab.camera_class("不在表里的词") == ""
    assert vocab.label(vocab.SIZES, "close", "zh") == "特写"
    assert vocab.label(vocab.SIZES, "close", "en") == "Close-up"
    assert vocab.camera_label("push-in", "zh") == "推"


def test_empty_words_listed() -> None:
    assert "氛围感" in vocab.EMPTY_WORDS
    assert "stunning" in vocab.EMPTY_WORDS


# --------------------------------------------------------------------------------------
# assign_dialogue:按时间重叠(段的中点)分给镜头
# --------------------------------------------------------------------------------------

def _shots(*spans: tuple[float, float]) -> list[dict]:
    return [{"id": f"S{i:02d}", "start": s, "end": e, "seconds": round(e - s, 3)}
            for i, (s, e) in enumerate(spans, start=1)]


def test_assign_dialogue_by_segment_midpoint() -> None:
    shots = _shots((0.0, 2.0), (2.0, 4.0), (4.0, 6.0))
    describe.assign_dialogue(shots, [
        {"start": 0.2, "end": 1.0, "text": "第一句"},
        {"start": 1.5, "end": 2.5, "text": "跨过刀口的一句"},  # 中点 2.0 → 落在第二镜
        {"start": 5.0, "end": 5.8, "text": "最后一句"},
    ])
    assert shots[0]["dialogue"] == "第一句"
    assert shots[1]["dialogue"] == "跨过刀口的一句"
    assert shots[2]["dialogue"] == "最后一句"


def test_assign_dialogue_without_transcript_clears() -> None:
    shots = _shots((0.0, 2.0))
    shots[0]["dialogue"] = "旧的"
    describe.assign_dialogue(shots, [])
    assert shots[0]["dialogue"] == ""


def test_assign_dialogue_segment_past_end_goes_to_last_shot() -> None:
    shots = _shots((0.0, 2.0), (2.0, 4.0))
    describe.assign_dialogue(shots, [{"start": 4.5, "end": 5.0, "text": "片尾之后"}])
    assert shots[1]["dialogue"] == "片尾之后"


# --------------------------------------------------------------------------------------
# parse_answer:从模型的回答里取 shots 那一列
# --------------------------------------------------------------------------------------

def test_parse_answer_strips_fence_and_prose() -> None:
    answer = '好的,判完了:\n```json\n{"shots": [{"id": "S01", "size": "close"}]}\n```\n以上。'
    parsed = describe.parse_answer(answer)
    assert parsed == [{"id": "S01", "size": "close"}]


def test_parse_answer_unreadable_returns_empty() -> None:
    assert describe.parse_answer("没有任何 JSON") == []
    assert describe.parse_answer('{"other": 1}') == []


# --------------------------------------------------------------------------------------
# reconcile:对账
# --------------------------------------------------------------------------------------

def _judged(**overrides: object) -> dict:
    base: dict = {
        "id": "S01", "size": "close", "category": "subject", "camera": ["static"],
        "transition_in": "cut", "rhythm": "beat", "subjects": ["主播"], "onscreen_text": "",
        "audio": "主播在说话", "frame": "主播坐在桌前,背后是一扇窗,光从左侧打进来",
        "rhythm_note": "抛出数据", "prompt": "特写,固定,主播坐在桌前", "note": "",
    }
    base.update(overrides)
    return base


def _shot(**overrides: object) -> dict:
    base: dict = {"id": "S01", "start": 0.0, "end": 3.0, "seconds": 3.0, "motion": 0.2}
    base.update(overrides)
    return base


def test_reconcile_writes_judged_fields() -> None:
    shot = _shot()
    hints = describe.reconcile(shot, _judged(), lang="zh")
    assert shot["size"] == "close"
    assert shot["camera"] == ["static"]
    assert shot["subjects"] == ["主播"]
    assert "frame" in shot and len(shot["frame"]) >= 12
    assert hints == []


def test_reconcile_clears_unknown_vocab_words_and_hints() -> None:
    shot = _shot()
    hints = describe.reconcile(shot, _judged(size="中近景", category="subject", transition_in="cut",
                                             camera=["跟拍xyz"]), lang="zh")
    assert shot["size"] == ""  # 表外词清空,不猜
    assert shot["camera"] == []
    kinds = {(h["kind"], h["field"]) for h in hints}
    assert ("unknown_word", "size") in kinds
    assert ("unknown_word", "camera") in kinds


def test_reconcile_strong_move_with_still_measurement_is_corrected() -> None:
    shot = _shot(motion=0.1)  # 实测几乎没动,却声称推镜头 → 判错了
    hints = describe.reconcile(shot, _judged(camera=["push-in", "pan-left"]), lang="zh")
    assert shot["camera"] == ["static"]
    corrected = [h for h in hints if h["kind"] == "camera_corrected"]
    assert corrected and corrected[0]["value"] == "push-in,pan-left"


def test_reconcile_strong_gate_skips_short_shots() -> None:
    shot = _shot(seconds=0.5, motion=0.1, start=0.0, end=0.5)
    hints = describe.reconcile(shot, _judged(camera=["push-in"]), lang="zh")
    assert shot["camera"] == ["push-in"]  # 不到 1 秒不查
    assert [h for h in hints if h["kind"] == "camera_corrected"] == []


def test_reconcile_static_with_big_motion_hints_only() -> None:
    shot = _shot(motion=40.0)  # 声称固定,实测很大 → 只提示(画里可能在跳舞)
    hints = describe.reconcile(shot, _judged(camera=["static"]), lang="zh")
    assert shot["camera"] == ["static"]
    assert [h for h in hints if h["kind"] == "static_but_moving"] and \
           [h for h in hints if h["kind"] == "camera_corrected"] == []


def test_reconcile_thin_frame_hints() -> None:
    shot = _shot()
    hints = describe.reconcile(shot, _judged(frame="好看"), lang="zh")
    assert any(h["kind"] == "thin_frame" for h in hints)
    hints = describe.reconcile(_shot(), _judged(frame="很有氛围感的一个镜头画面"), lang="zh")
    assert any(h["kind"] == "thin_frame" for h in hints)
    en = _shot()
    describe.reconcile(en, _judged(frame="a cat"), lang="en")
    assert any(h["kind"] == "thin_frame" for h in describe.reconcile(
        _shot(), _judged(frame="two words only"), lang="en"))


# --------------------------------------------------------------------------------------
# describe_batch:一批 ≤25 镜一次调用;缺镜 / 读不出有提示
# --------------------------------------------------------------------------------------

def _tiny_sheet(tmp_path: Path, name: str) -> Path:
    from PIL import Image

    path = tmp_path / name
    Image.new("RGB", (64, 64), (30, 30, 30)).save(path, "JPEG")
    return path


def _fake_answer(shots: list[dict]) -> str:
    return json.dumps({"shots": shots}, ensure_ascii=False)


def test_describe_batch_judges_every_shot(tmp_path: Path) -> None:
    batch = [_shot(start=float(i * 3), end=float(i * 3 + 3), seconds=3.0) for i in range(25)]
    for i, shot in enumerate(batch):
        shot["id"] = f"S{i + 1:02d}"
    sheet_a, sheet_b = _tiny_sheet(tmp_path, "a.jpg"), _tiny_sheet(tmp_path, "b.jpg")
    seen: dict = {}

    def ask(messages: list) -> str:
        seen["count"] = len(messages)
        return _fake_answer([{**_judged(), "id": shot["id"]} for shot in batch])

    hints = describe.describe_batch(batch, sheet_a, sheet_b, ask, title="样片", lang="zh")
    assert all(shot["size"] == "close" for shot in batch)
    assert hints == []


def test_describe_batch_missing_shot_gets_not_judged_hint(tmp_path: Path) -> None:
    batch = [_shot(), {**_shot(), "id": "S02", "start": 3.0, "end": 6.0}]
    sheet_a, sheet_b = _tiny_sheet(tmp_path, "a.jpg"), _tiny_sheet(tmp_path, "b.jpg")
    hints = describe.describe_batch(batch, sheet_a, sheet_b, lambda _m: _fake_answer([_judged()]),
                                    title="样片", lang="zh")
    assert batch[0]["size"] == "close"
    assert "size" not in batch[1]  # 没被 judge 的镜留着机器量那一半
    assert hints == [{"shot": "S02", "kind": "not_judged", "field": "", "value": ""}]


def test_describe_batch_unreadable_answer_marks_batch(tmp_path: Path) -> None:
    batch = [_shot(), {**_shot(), "id": "S02", "start": 3.0, "end": 6.0}]
    sheet_a, sheet_b = _tiny_sheet(tmp_path, "a.jpg"), _tiny_sheet(tmp_path, "b.jpg")
    hints = describe.describe_batch(batch, sheet_a, sheet_b, lambda _m: "完全不是 JSON",
                                    title="样片", lang="zh")
    assert hints == [{"shot": "S01", "kind": "batch_unreadable", "field": "", "value": "S02"}]


def test_batch_size_matches_sheet_capacity() -> None:
    assert describe.BATCH_SIZE == SHEET_MAX == 25


# --------------------------------------------------------------------------------------
# rhythm_hints:三条节奏提示
# --------------------------------------------------------------------------------------

def _rhythm_shots(rhythms: list[str]) -> list[dict]:
    return [{"id": f"S{i:02d}", "start": float(i - 1), "end": float(i), "seconds": 1.0, "rhythm": r}
            for i, r in enumerate(rhythms, start=1)]


def test_rhythm_hints_no_hook_in_first_five_seconds() -> None:
    hints = describe.rhythm_hints(_rhythm_shots(["setup", "build", "payoff"]))
    assert any(h["kind"] == "no_hook" for h in hints)


def test_rhythm_hints_hook_in_first_five_seconds_passes() -> None:
    hints = describe.rhythm_hints(_rhythm_shots(["hook", "setup", "payoff"]))
    assert [h for h in hints if h["kind"] == "no_hook"] == []


def test_rhythm_hints_payoff_without_setup() -> None:
    hints = describe.rhythm_hints(_rhythm_shots(["hook", "payoff"]))
    assert any(h["kind"] == "payoff_without_setup" and h["shot"] == "S02" for h in hints)
    #: 有铺垫 / 递进的兑现不提示。
    hints = describe.rhythm_hints(_rhythm_shots(["hook", "setup", "payoff"]))
    assert [h for h in hints if h["kind"] == "payoff_without_setup"] == []


def test_rhythm_hints_flat_stretch_of_same_rhythm() -> None:
    hints = describe.rhythm_hints(_rhythm_shots(["beat"] * 7))
    assert any(h["kind"] == "flat_stretch" and h["shot"] == "S06" for h in hints)
    hints = describe.rhythm_hints(_rhythm_shots(["beat"] * 5))
    assert [h for h in hints if h["kind"] == "flat_stretch"] == []


def test_rhythm_hints_silent_when_nothing_marked() -> None:
    assert describe.rhythm_hints(_rhythm_shots(["", "", ""])) == []


# --------------------------------------------------------------------------------------
# 消息形状:给视觉模型的那一批 ≤25 镜,A/B 两张表 + 每镜的时间 / 实测动静 / 台词
# --------------------------------------------------------------------------------------

def test_batch_messages_carry_shot_rows_and_two_sheets(tmp_path: Path) -> None:
    sheet_a, sheet_b = _tiny_sheet(tmp_path, "a.jpg"), _tiny_sheet(tmp_path, "b.jpg")
    batch = [{**_shot(), "dialogue": "大家好"}]
    messages = describe.batch_messages(batch, sheet_a, sheet_b, title="样片", lang="zh")
    assert messages[0]["role"] == "system"
    user = messages[1]
    parts = user["content"]
    assert parts[0]["type"] == "text"
    assert "S01" in parts[0]["text"] and "0:00.0–0:03.0" in parts[0]["text"]
    assert "台词:大家好" in parts[0]["text"]
    assert [p["type"] for p in parts[1:]] == ["image_url", "image_url"]
    for part in parts[1:]:
        assert part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    #: 封闭词表写进系统提示词。
    system = messages[0]["content"]
    for word in ("push-in", "extreme-wide", "establishing", "match-cut", "payoff"):
        assert word in system
