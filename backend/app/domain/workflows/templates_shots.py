"""内置模板「拆解参考视频」的图:选视频 → 拆镜头 →(可选)转写口播 → 逐镜看画面 → 报告 → 总结 → 笔记。

和 templates_analysis 里那三条的分界:那三条取数靠 TikHub / 内嵌浏览器(链接进),这一条**起点是素材库里
已有的视频**(ADR 0061 §4)。镜头表、联系表、逐镜判断全走 domain/shots 的三个新节点 —— 刀口 / 时长 / 动静是
代码量出来的,只有「看画面」和「写总结」花钱。

由 templates.py 统一重新导出;调用方照旧从 templates 取。
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import pick_text
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.template_requirements import CHAT_MODEL, TRANSCRIPTION_ENGINE, requirement
from app.domain.workflows.templates_models import ModelChoice
from app.domain.workflows.templates_schemas import _object

REFERENCE_VIDEO_SHOTS = "reference_video_shots"

#: 写拆解总结那一步的 JSON Schema:结构、节奏曲线、钩子、可复用的手法,外加整份 markdown 和笔记标题。
_SUMMARY_FIELDS = {
    "title": {"type": "string", "description": "笔记标题:片子名 + 一句话定性"},
    "verdict": {"type": "string", "description": "一句话总评:这条片子靠什么成立"},
    "structure": {"type": "string", "description": "整体结构:几段式、各段在干什么、怎么衔接"},
    "pacing": {"type": "string", "description": "节奏曲线:哪里快哪里慢、为什么、和情绪的关系"},
    "hook": {"type": "string", "description": "前 5 秒的钩子:抛了什么、怎么留人"},
    "techniques": {"type": "array", "items": {"type": "string"},
                   "description": "最值得复用的拍摄手法,逐条写清怎么照做"},
    "report_markdown": {"type": "string", "description": "完整拆解(markdown,含上面各部分)"},
}

_SUMMARY_SYSTEM = """你是一名资深短视频编导,擅长拉片拆解。你会收到一份参考视频的完整镜头表:每一镜的镜号、起止时间、
时长、实测动静、景别、类别、运镜、转场、节奏、画面描述、这一镜的台词,以及照着重生的分镜提示词;另有判画面时的
对账提示(哪一镜的判断被代码纠正过、为什么 —— 被纠正过的运镜说法不要照抄)。镜头表里的数字(镜长、每分钟几刀)
是代码量出来的,是事实,照用,不要自己重算也不要改镜头表。基于它写一份给创作者照着做的拆解:整体结构、节奏曲线
(哪里快哪里慢、为什么)、前 5 秒的钩子、最值得复用的拍摄手法;开始参数里点了拆解重点的话,单独回应那个方向。
只输出符合 JSON Schema 的对象。"""

SHOTS_TEMPLATE_CATALOG: list[dict[str, Any]] = [
    {
        "id": REFERENCE_VIDEO_SHOTS,
        "name": {"zh": "拆解参考视频:镜头表 + 联系表 + 报告", "en": "Break down a reference video: shot list, contact sheets, report"},
        "summary": {
            "zh": "选素材库里的一条视频,先用代码量出刀口和每一镜的动静(不花钱、不是模型猜的),取每镜两帧拼成联系表;"
                  "可选转写口播,把台词按时间分给每一镜;再让视觉模型逐镜判景别、运镜、转场、节奏,写画面描述和照着重生的"
                  "分镜提示词(每批最多 25 镜一次调用,代码对账:表外的词当场清掉、声称在动而实测没动的运镜被拦下并记下);"
                  "最后代码出镜头表报告,模型写拆解总结(结构、节奏曲线、钩子、可复用的手法),存成笔记交付。"
                  "花费量级:一镜不多花,25 镜一次视觉调用 —— 一条 1 分钟、30 镜的视频是两次视觉调用,加写总结的一次对话。"
                  "起点是素材库里已有的视频;想拆链接里的片子,先用「从链接导入」把它下载进素材库。",
            "en": "Pick a video from the asset library. Code first measures every cut and each shot's motion (free, not guessed by"
                  " a model) and grabs two frames per shot into contact sheets; optionally transcribe the speech so lines are"
                  " assigned to each shot by timecode. A vision model then judges framing, camera work, transitions and rhythm"
                  " shot by shot, and writes a picture description plus a storyboard prompt to recreate it (up to 25 shots per"
                  " call; code reconciles afterwards: out-of-vocabulary words are dropped, and camera moves the pixels don't"
                  " show are corrected and recorded). Code produces the shot-list report, a model writes the breakdown"
                  " (structure, pacing curve, hook, reusable techniques), and it is saved as a note and handed over. Cost: no"
                  " extra spend per shot, 25 shots per vision call — a one-minute, 30-shot video costs two vision calls plus one"
                  " chat call for the summary. The starting point is a video already in the asset library; to break down a link,"
                  " import it into the library first with Import from link.",
        },
        "requires": [
            requirement(CHAT_MODEL, zh="AI 对话模型(逐镜看画面 + 写拆解总结)", en="A chat model (shot judging and the breakdown summary)"),
            requirement(TRANSCRIPTION_ENGINE, zh="可选:转写引擎(给每一镜分台词)", en="Optional: a transcription engine (dialogue per shot)", optional=True),
            requirement(None, zh="素材库里的一条视频(链接进来的先用「从链接导入」)", en="A video in the asset library (import links first)"),
        ],
        "stages": {
            "zh": ["选视频", "拆镜头:代码量刀口 / 动静,取帧拼联系表(不花钱)", "可选:转写口播,按时间分给每一镜",
                   "逐镜看画面:视觉模型判景别 / 运镜 / 转场 / 节奏,代码对账(花钱)", "镜头表报告(代码算,不花钱)",
                   "写拆解总结:结构、节奏曲线、钩子、可复用的手法", "存成笔记(总结 + 镜头表 + 分镜提示词)", "交付"],
            "en": ["Pick a video", "Detect shots: code measures cuts and motion, frames into contact sheets (free)",
                   "Optional: transcribe the speech, lines assigned to shots by timecode",
                   "Judge each shot: a vision model assesses framing, camera, transitions, rhythm; code reconciles (paid)",
                   "Shot-list report (computed by code, free)",
                   "Write the breakdown: structure, pacing curve, hook, reusable techniques",
                   "Save as a note (summary, shot list, storyboard prompts)", "Hand over"],
        },
    },
]


def reference_video_shots_graph(*, chat: ModelChoice, locale: str | None = None) -> dict[str, Any]:
    """选视频 → 拆镜头 →(可选)转写口播 → 逐镜看画面 → 镜头表报告 → 写拆解总结 → 存成笔记 → 交付。

    转写排在拆镜头**后面**、逐镜看画面**前面**:量刀口不依赖逐字稿,而判画面之前逐字稿得到 ——
    judge 会按这一刻的逐字稿重分台词(domain/shots/breakdowns.judge),晚到的台词照样进提示词。
    不转写(开始参数 transcribe_speech 选「否」)照样跑:每一镜只有机器量出来的那一半。
    """

    def text(zh: str, en: str) -> str:
        return pick_text({"zh": zh, "en": en}, locale)

    def node(node_id: str, node_type: str, name: dict[str, str], col: float, row: float,
             config: dict[str, Any]) -> None:
        nodes.append({
            "id": node_id, "type": node_type, "name": name,
            "position": {"x": 40 + int(col * 320), "y": 60 + int(row * 190)}, "config": config,
        })

    def edge(source: str, target: str, handle: str | None = None) -> None:
        item: dict[str, Any] = {"id": f"{source}__{target}", "source": source, "target": target}
        if handle:
            item["source_handle"] = handle
            item["id"] += f"__{handle}"
        edges.append(item)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    node("start", "start", {"zh": "设置拆解重点", "en": "Set the breakdown focus"}, 0, 2.2, {
        "params": {
            "transcribe_speech": "yes",
            "focus": "",
        },
    })
    node("source_video", "asset", {"zh": "选择要拆解的参考视频", "en": "Pick the reference video"}, 1, 2.2, {
        "asset_id": "",
    })
    node("detect", "detect_shots",
         {"zh": "拆镜头(刀口 / 动静 / 联系表)", "en": "Detect shots (cuts, motion, contact sheets)"}, 2, 2.2, {
        "asset_id": "{{source_video.asset_id}}",
        "save_sheets": "no",
    })
    #: 转写是可选用 start.transcribe_speech 关掉的:不转写就只看画面,台词那一列空着。
    node("want_speech", "condition", {"zh": "要转写口播分台词吗", "en": "Transcribe the speech for dialogue?"}, 3, 2.2, {
        "left": "{{start.transcribe_speech}}", "op": "not_equals", "right": "no",
    })
    node("transcript", "transcribe_asset",
         {"zh": "转写口播(带时间码)", "en": "Transcribe the speech with timecodes"}, 4, 1.2, {
        "asset_id": "{{source_video.asset_id}}",
    })
    node("transcript_section", "template", {"zh": "逐字稿附在笔记后", "en": "Attach the transcript"}, 5, 1.2, {
        "template": "## " + text("口播逐字稿", "Transcript") + "\n\n{{transcript.text}}",
    })
    node("describe", "describe_shots",
         {"zh": "逐镜看画面(景别 / 运镜 / 节奏)", "en": "Judge each shot (framing, camera, rhythm)"}, 6, 2.2, {
        "asset_id": "{{source_video.asset_id}}",
        "profile_id": chat.profile_id,
        "model": chat.model,
    })
    node("report", "shot_report", {"zh": "镜头表报告", "en": "Shot-list report"}, 7, 2.2, {
        "asset_id": "{{source_video.asset_id}}",
    })
    node("summary", "llm",
         {"zh": "写拆解总结(结构 / 节奏 / 钩子 / 手法)", "en": "Write the breakdown (structure, pacing, hook, moves)"},
         8, 2.2, {
        "profile_id": chat.profile_id,
        "model": chat.model,
        "preset": "balanced",
        "system": _SUMMARY_SYSTEM,
        "prompt": "素材:{{source_video.name}}({{source_video.duration}} 秒)\n拆解重点(可能为空):{{start.focus}}\n\n"
                  "## 镜头表\n\n{{report.report_markdown}}\n\n## 判画面对账提示(可能为空)\n{{describe.hints}}\n\n"
                  "## 口播逐字稿(可能为空)\n{{transcript.text}}",
        "response_format": "json_schema",
        "json_schema_name": "reference_video_breakdown",
        "json_schema": _object(_SUMMARY_FIELDS, list(_SUMMARY_FIELDS)),
        "json_schema_strict": "true",
        "temperature": 0.3,
        "max_tokens": 12000,
    })
    node("save_note", "note_create",
         {"zh": "存成笔记(总结 + 镜头表 + 分镜提示词)", "en": "Save as a note (summary, shot list, prompts)"}, 9, 2.2, {
        "title": "{{summary.json.title}}",
        "markdown": "> {{summary.json.verdict}}\n\n{{summary.json.report_markdown}}\n\n---\n\n"
                    "## " + text("镜头表与分镜提示词", "Shot list and storyboard prompts") + "\n\n"
                    "{{report.report_markdown}}\n\n{{transcript_section.text}}",
        "tags": text("参考视频拆解", "reference video breakdown"),
    })
    node("done_notice", "notify", {"zh": "拆解完成通知", "en": "Breakdown ready"}, 10, 2.2, {
        "title": text("参考视频拆解已存成笔记", "The reference-video breakdown is saved as a note"),
        "body": "{{source_video.name}} —— {{summary.json.verdict}}",
    })
    node("output", "output", {"zh": "交付拆解与镜头表", "en": "Hand over the breakdown and the shot list"}, 11, 2.2, {
        "values": {
            "note_id": "{{save_note.note_id}}",
            "title": "{{summary.json.title}}",
            "verdict": "{{summary.json.verdict}}",
            "summary_markdown": "{{summary.json.report_markdown}}",
            "shot_report_markdown": "{{report.report_markdown}}",
            "stats": "{{report.stats}}",
            "shot_count": "{{report.shot_count}}",
            "judged_batches": "{{describe.judged}}",
            "hints": "{{describe.hints}}",
            "video_asset_id": "{{source_video.asset_id}}",
            "transcript": "{{transcript.text}}",
        },
    })

    edge("start", "source_video")
    edge("source_video", "detect")
    edge("detect", "want_speech")
    edge("want_speech", "transcript", "true")
    edge("transcript", "transcript_section")
    edge("want_speech", "describe", "false")
    edge("transcript_section", "describe")
    edge("describe", "report")
    edge("report", "summary")
    edge("summary", "save_note")
    edge("save_note", "done_notice")
    edge("done_notice", "output")

    return normalize_graph(
        {"meta": {"template_id": REFERENCE_VIDEO_SHOTS, "template_version": 1, "source": "official"},
         "nodes": nodes, "edges": edges},
        node_types=NODE_TYPES,
    )
