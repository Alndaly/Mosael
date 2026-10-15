"""逐镜看画面:一批 ≤ 25 镜交给视觉模型判景别 / 类别 / 运镜 / 转场 / 节奏、写画面和分镜提示词,回来再由代码对账。

**模型只判,不量。** 刀口、时长、动静、台词都是代码给的,写在提示词里当事实;模型回答里的时间一律不采信。

**怎么调模型由调用方给**(`ask`:消息 → 回答正文)。素材页的任务用「分析」那条默认挑法,工作流节点用节点上的连接,
智能体用会话定下的模型 —— 记账、选连接、谁的钥匙都在调用方,这里不认识任何一种。

**对账**(reelbench video-shots 的门,改成「纠正 + 记下来」):自动跑的流程里拦住等于整条失败,所以
- 表外的词清空,记一条提示;
- 声称 strong 运镜(整幅画面必然在动)而实测几乎没动,且镜长 ≥ 1 秒 —— 判错了,去掉那个运镜,记一条「改正」;
- 声称固定而实测很大 —— 只提示(固定机位前有人跳舞,帧间差一样会爆);
- 画面描述太短或是空话 —— 提示。
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.domain.shots import vocab
from app.domain.shots.frames import SHEET_MAX, timecode

#: 一次调用交几镜:就是联系表一张的格数(一张 A 表 + 一张 B 表对应一批)。
BATCH_SIZE = SHEET_MAX
#: 画面描述至少多长才算「能拿去核对」:中文按字,英文按词。
MIN_FRAME_CHARS_ZH = 12
MIN_FRAME_WORDS_EN = 8

Ask = Callable[[list[dict[str, Any]]], str]


def assign_dialogue(shots: list[dict[str, Any]], segments: list[dict[str, Any]]) -> None:
    """把逐字稿的每一段分给它落在的那一镜(按段的中点),一镜的几段拼起来写进 `dialogue`。

    按中点而不是「有重叠就算」:一句话跨了刀口时只算一次,不会两镜各抄一遍。"""
    for shot in shots:
        shot["dialogue"] = ""
    if not shots:
        return
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        middle = (float(segment.get("start") or 0) + float(segment.get("end") or 0)) / 2
        owner = next((shot for shot in shots if shot["start"] <= middle < shot["end"]), shots[-1])
        owner["dialogue"] = f"{owner['dialogue']} {text}".strip()


def _system(lang: str) -> str:
    sizes = " / ".join(vocab.SIZES)
    categories = " / ".join(vocab.CATEGORIES)
    moves = " / ".join(f"{move}({names['zh']})" for move, (names, _cls) in vocab.CAMERA_MOVES.items())
    transitions = " / ".join(vocab.TRANSITIONS)
    rhythms = " / ".join(f"{key}({names['zh']})" for key, names in vocab.RHYTHMS.items())
    language = "English" if lang == "en" else "简体中文"
    return f"""你是拉片的剪辑指导。你会收到一段视频的一批镜头:每镜的镜号、起止时间、时长、实测动静(帧间差,0 表示整幅画面没动)、
这一镜里说的话(语音识别,可能为空),以及两张联系表 —— A 表是每镜 15% 处的一帧,B 表是 85% 处的一帧,同一个格子是同一镜,
格子左上角写着镜号和时间。逐镜判断下面这些,只用给定的词:

- size 景别(按被拍的人占画框多大判,不按焦段;黑场、字卡用 none):{sizes}
- category 这一镜在片子里干什么活(只选一个):{categories}
- camera 运镜(一到两个,写主导的那个在前):{moves}
  先问:整幅画面动了吗?画面不动、只有人在动就是 static。对照 A、B 两帧:景别变了是推拉,背景错开是摇移。
  实测动静接近 0 的镜头,不会是推、拉、摇、移、跟、甩、晃。
- transition_in 这一镜怎么进来的:{transitions}
- rhythm 观众这一刻得到了什么:{rhythms};rhythm_note 一句话说看到了什么、为什么不划走
- subjects 画面里的主体(人或物,几个词);onscreen_text 画面上的字(照抄,没有就空);audio 这一镜里谁在说 / 什么声音
- frame 一句话写看得见的东西:谁在画框的什么位置、在做什么、光从哪来、前景背景有什么(至少 12 个字;
  不写「氛围感」「高级感」「视觉冲击」这类空话)。只看这句话,要能在片子里把这一镜找出来。
- prompt 照这一镜重新生成时用的提示词:景别 + 运镜 + 主体 + 动作 + 环境 + 光线,一两句。

判不准就选最保守的那个词,把不确定写进 note。frame、rhythm_note、subjects、audio、prompt、note 用{language}写;
词表里的值照原样写英文。只输出一个 JSON 对象:{{"shots": [{{"id": "S01", "size": "", "category": "", "camera": [],
"transition_in": "cut", "rhythm": "", "rhythm_note": "", "subjects": [], "onscreen_text": "", "audio": "", "frame": "",
"prompt": "", "note": ""}}]}},每镜一项,镜号照联系表。"""


def _rows(batch: list[dict[str, Any]]) -> str:
    lines = []
    for shot in batch:
        motion = "—" if shot.get("motion") is None else f"{shot['motion']:.1f}"
        line = (f"{shot['id']}  {timecode(shot['start'])}–{timecode(shot['end'])}  {shot['seconds']:.1f}s  "
                f"实测动静 {motion}")
        if shot.get("dialogue"):
            line += f"  台词:{shot['dialogue'][:200]}"
        lines.append(line)
    return "\n".join(lines)


def _image(path: Path) -> dict[str, Any]:
    encoded = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}


def batch_messages(batch: list[dict[str, Any]], sheet_a: Path, sheet_b: Path, *, title: str, lang: str) -> list[dict[str, Any]]:
    text = f"视频:{title}\n这一批 {len(batch)} 镜:\n{_rows(batch)}\n\n第一张图是 A 表(15% 处),第二张是 B 表(85% 处)。"
    return [
        {"role": "system", "content": _system(lang)},
        {"role": "user", "content": [{"type": "text", "text": text}, _image(sheet_a), _image(sheet_b)]},
    ]


def parse_answer(text: str) -> list[dict[str, Any]]:
    """从回答里取出 `shots` 那一列。模型常把 JSON 裹在 ```json 围栏或一两句话里,从第一个 `{` 解。解不出来回空列表。"""
    body = text.strip()
    start = body.find("{")
    if start < 0:
        return []
    try:
        value, _end = json.JSONDecoder().raw_decode(body[start:])
    except json.JSONDecodeError:
        return []
    shots = value.get("shots") if isinstance(value, dict) else None
    return [one for one in shots if isinstance(one, dict)] if isinstance(shots, list) else []


def _text(value: Any, limit: int = 600) -> str:
    return str(value or "").strip()[:limit]


def _words(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [part for part in value.replace("、", ",").split(",")]
    if not isinstance(value, list):
        return []
    return [_text(item, 80) for item in value if _text(item, 80)][:8]


def _frame_too_thin(frame: str, lang: str) -> bool:
    if lang == "en":
        return len(frame.split()) < MIN_FRAME_WORDS_EN
    return len(frame.replace(" ", "")) < MIN_FRAME_CHARS_ZH


def reconcile(shot: dict[str, Any], judged: dict[str, Any], *, lang: str) -> list[dict[str, str]]:
    """把模型对这一镜的判断对过账后写进 `shot`,返回这一镜的提示。时间、动静、台词不采信模型的。"""
    hints: list[dict[str, str]] = []

    def enum(field: str, table: dict[str, Any], default: str = "") -> str:
        value = _text(judged.get(field), 40).lower()
        if value and value not in table:
            hints.append({"shot": shot["id"], "kind": "unknown_word", "field": field, "value": value})
            return default
        return value or default

    shot["size"] = enum("size", vocab.SIZES)
    shot["category"] = enum("category", vocab.CATEGORIES)
    shot["transition_in"] = enum("transition_in", vocab.TRANSITIONS, "cut")
    shot["rhythm"] = enum("rhythm", vocab.RHYTHMS)
    moves: list[str] = []
    for raw in judged.get("camera") if isinstance(judged.get("camera"), list) else [judged.get("camera")]:
        move = _text(raw, 40).lower()
        if not move:
            continue
        if move not in vocab.CAMERA_MOVES:
            hints.append({"shot": shot["id"], "kind": "unknown_word", "field": "camera", "value": move})
        elif move not in moves:
            moves.append(move)
    motion = shot.get("motion")
    if motion is not None and shot["seconds"] >= vocab.GATE_MIN_SECONDS:
        strong = [move for move in moves if vocab.camera_class(move) == "strong"]
        if strong and motion < vocab.STRONG_MIN_MOTION:
            moves = [move for move in moves if move not in strong] or ["static"]
            hints.append({"shot": shot["id"], "kind": "camera_corrected", "field": "camera", "value": ",".join(strong)})
        elif moves[:1] == ["static"] and motion > vocab.STILL_MAX_MOTION:
            hints.append({"shot": shot["id"], "kind": "static_but_moving", "field": "camera", "value": f"{motion:.1f}"})
    shot["camera"] = moves[:2]
    shot["subjects"] = _words(judged.get("subjects"))
    shot["onscreen_text"] = _text(judged.get("onscreen_text"), 300)
    shot["audio"] = _text(judged.get("audio"), 300)
    shot["frame"] = _text(judged.get("frame"))
    shot["rhythm_note"] = _text(judged.get("rhythm_note"), 300)
    shot["prompt"] = _text(judged.get("prompt"))
    shot["note"] = _text(judged.get("note"), 300)
    frame = shot["frame"]
    if not frame or _frame_too_thin(frame, lang) or any(word in frame.lower() for word in vocab.EMPTY_WORDS):
        hints.append({"shot": shot["id"], "kind": "thin_frame", "field": "frame", "value": frame[:40]})
    return hints


def rhythm_hints(shots: list[dict[str, Any]]) -> list[dict[str, str]]:
    """节奏的三条提示(只提示,是导演判断不是对错):开篇 5 秒有没有钩子;兑现前面有没有铺垫 / 递进;
    有没有连着 6 镜以上同一个角色。一镜都没标节奏就不说。"""
    marked = [shot for shot in shots if shot.get("rhythm")]
    if not marked:
        return []
    hints: list[dict[str, str]] = []
    if not any(shot.get("rhythm") == "hook" and shot["start"] < 5 for shot in shots):
        hints.append({"shot": "", "kind": "no_hook", "field": "rhythm", "value": ""})
    seen: set[str] = set()
    for shot in shots:
        if shot.get("rhythm") == "payoff" and not seen & {"setup", "build"}:
            hints.append({"shot": shot["id"], "kind": "payoff_without_setup", "field": "rhythm", "value": ""})
            break
        seen.add(str(shot.get("rhythm") or ""))
    run, previous = 0, None
    for shot in shots:
        run = run + 1 if shot.get("rhythm") and shot.get("rhythm") == previous else 1
        previous = shot.get("rhythm")
        if run == 6:
            hints.append({"shot": shot["id"], "kind": "flat_stretch", "field": "rhythm", "value": str(previous)})
    return hints


def describe_batch(batch: list[dict[str, Any]], sheet_a: Path, sheet_b: Path, ask: Ask, *, title: str,
                   lang: str) -> list[dict[str, str]]:
    """判一批、对账、写回这一批的镜头。回答里缺了哪一镜就记一条提示,那一镜留着机器量的那一半。"""
    answer = ask(batch_messages(batch, sheet_a, sheet_b, title=title, lang=lang))
    judged = {str(one.get("id") or "").strip().upper(): one for one in parse_answer(answer)}
    if not judged:
        return [{"shot": batch[0]["id"], "kind": "batch_unreadable", "field": "", "value": batch[-1]["id"]}]
    hints: list[dict[str, str]] = []
    for shot in batch:
        one = judged.get(shot["id"])
        if one is None:
            hints.append({"shot": shot["id"], "kind": "not_judged", "field": "", "value": ""})
            continue
        hints.extend(reconcile(shot, one, lang=lang))
    return hints


__all__ = ["BATCH_SIZE", "Ask", "assign_dialogue", "batch_messages", "describe_batch", "parse_answer", "reconcile",
           "rhythm_hints"]
