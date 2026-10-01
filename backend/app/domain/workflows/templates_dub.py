"""内置模板「视频译配」的图(和带改口型的那一版):视频 → 逐字稿 → 逐句翻译 → 译文字幕 → 变速配音 →(改口型)→ 导出。

由 templates.py 统一重新导出;调用方照旧从 templates 取。
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import pick_text
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.templates_models import ModelChoice


TRANSLATED_DUB = "translated_dub"

TRANSLATED_DUB_LIPSYNC = "translated_dub_lipsync"


def translated_dub_graph(
    *, chat: ModelChoice | None = None, voice_id: str = "", lipsync: bool = False, locale: str | None = None,
) -> dict[str, Any]:
    """视频 → 逐字稿 → 逐句翻译 → 译文字幕 → 变速配音 →(改口型)→ 导出。

    `lipsync`:「视频译配 · 改口型」(ADR 0028 阶段 3)—— 配完音再让原片的嘴对上配音轨(`dub_lipsync`:按句间空当
    切块改口型,接回整段放到最上面一条新视频轨,原片不动),然后才导出。前面几步一模一样,所以是同一张图多一个节点,
    不另抄一份(抄出来的两份改一处就得改两处)。节点上的授权确认留空,由跑的人确认。

    **逐句翻译,不是整篇翻译。** 配音要对得上画面,所以每一句必须知道自己是第几秒到第几秒的 ——
    而那个时间码只存在于原始段落里。整篇丢给翻译再切回句子,切点不可能和原来一致(译文的句数
    本来就和原文不一样),于是每一句都会往后错一点,越到后面错得越多。逐句走,时间码是白拿的:
    第 i 条译文配第 i 段的时间,按构造对齐。

    **但「逐句」说的是切分,不是逐个发请求。** 这一步曾经是 loop_foreach 套一个 translate ——
    N 次串行节点调用、每次一个新连接,而免费翻译端点按 IP 限流,串起来正好踩在它的节流上
    (真机上第 1/31 次就 429)。现在是一个 translate_lines 节点:同样按段切,但 8 路并发、
    共用一条会重试的连接,顺序不变。

    **配音靠变速塞回原长度,不是靠裁剪。** 同一句话译成另一种语言,长度天然对不上;裁掉尾巴等于
    把话说一半,留空则对不上口型。变速改的是片段的 speed(渲染时 atempo),无损、可撤销、事后
    还能在检查器里逐条微调 —— 这是 `dub_subtitles` 的 match_duration。变速只在 0.9–1.5 倍之间
    (再快就像快进了),1.5 倍还念不完的先占用到下一句开始之前的空当(见 voices/subtitle_dub._speed_for)。

    `chat`:翻译用的对话连接与模型(建图时按这个人挑好,见 templates._chat_model);不给就留空,由用户在节点上选。
    `locale`:图里给人看的默认值(新项目的名字、完成通知)在建图这一刻定语言,和节点名同一条。此前写死中文。
    """
    chat = chat or ModelChoice()

    def text(zh: str, en: str) -> str:
        return pick_text({"zh": zh, "en": en}, locale)

    nodes: list[dict[str, Any]] = [
        {
            "id": "start",
            "type": "start",
            "name": {"zh": "开始译配", "en": "Start the translated dub"},
            "position": {"x": -270, "y": 260},
            # **目标语言和音色留在它们各自的节点上,不提成起始参数。**
            # 提上来看似更"通用",实际是把两个真控件换成一个自由文本框:`start.params` 在节点
            # 表里是无类型的 `{"type": "object"}`,值那一列只能填字符串或引用上游输出 ——
            # 而起始节点没有上游。留在节点上,`target_lang` 有 9 种语言的下拉、音色有
            # 按引擎列出的真正的选择器。
            # 要让"运行时问我一次"成立,缺的是**起始参数能声明类型**这件事,那是引擎级的口子,
            # 不是这条模板能绕过去的。
            "config": {"params": {}},
        },
        {
            "id": "source_video",
            "type": "asset",
            "name": {"zh": "选择要配音的视频", "en": "Pick the video to dub"},
            "position": {"x": 40, "y": 260},
            "config": {"asset_id": ""},
        },
        {
            "id": "dub_project",
            "type": "project_sequence_create",
            "name": {"zh": "建立非破坏性配音副本", "en": "Create a non-destructive dubbing copy"},
            "position": {"x": 350, "y": 420},
            "config": {
                "name": "{{source_video.name}} · " + text("译配版", "Dubbed"),
                "width": "{{source_video.width}}",
                "height": "{{source_video.height}}",
                "fps": "{{source_video.fps}}",
            },
        },
        {
            "id": "video_on_timeline",
            "type": "timeline_append",
            "name": {"zh": "把原视频接到时间线", "en": "Put the source video on the timeline"},
            "position": {"x": 670, "y": 420},
            "config": {
                "sequence_id": "{{dub_project.sequence_id}}",
                "asset_id": "{{source_video.asset_id}}",
                "track_id": "{{dub_project.video_track_id}}",
                "start": 0,
                "end": "{{source_video.duration}}",
            },
        },
        {
            "id": "verbatim_transcript",
            "type": "transcribe_asset",
            "name": {"zh": "生成带时间码逐字稿", "en": "Transcribe with timecodes"},
            "position": {"x": 350, "y": 120},
            "config": {"asset_id": "{{source_video.asset_id}}"},
        },
        {
            "id": "translate_lines",
            "type": "translate_lines",
            "name": {"zh": "逐句翻译成目标语言", "en": "Translate line by line into the target language"},
            "position": {"x": 990, "y": 120},
            "config": {
                # 直接收 segments:节点自己从每段里取 text,不需要模板层写 `{{loop.item.text}}`。
                "texts": "{{verbatim_transcript.segments}}",
                #: 默认英文;模板说明的步骤里写着「选目标语言」—— 在这个节点上选。
                "target_lang": "en",
                #: 识别出的原文语言:和目标语言一样时翻译节点直接拒(译配成同一种语言就是白花一遍翻译和配音的钱)。
                "source_lang": "{{verbatim_transcript.language}}",
                # **官方模板不走免费端点。** 它按出口 IP 封禁,而且是持续的 ——
                # 真机上直接请求拿到的是 Google 的 "Sorry..." 拦截页,重试多少次都一样
                # (机房、VPN、代理出口尤其容易中)。一条官方模板不能把成败押在这上面。
                # 这条链路本来就在用用户自己的供应商(转写、配音都是),翻译用同一套不是新的
                # 花费面;而且 LLM 读的是整句,译文比逐词接口好。节点上仍然可以换回 google。
                "engine": "builtin:chat",
                #: 用哪条连接、哪个模型写死在节点上(建图时按这个人的对话模型挑,和前置检查同一个)。
                #: 此前只写了 engine,运行时回退到「最早建的那条连接」,不管它会不会对话。
                "profile_id": chat.profile_id,
                "model": chat.model,
            },
        },
        {
            "id": "translated_subtitles",
            "type": "generate_subtitles",
            "name": {"zh": "按原时间码铺译文字幕", "en": "Lay the translated subtitles on the original timecodes"},
            "position": {"x": 1310, "y": 260},
            "config": {
                "sequence_id": "{{dub_project.sequence_id}}",
                "segments": "{{verbatim_transcript.segments}}",
                "texts": "{{translate_lines.texts}}",
                # 只念译文的话就把这里改成 yes、并把下一个节点的 line 改成 last:
                # 屏幕上两行(原文/译文),嘴里只念下面那行。
                "keep_original": "no",
                # 逐字稿的时间是**素材内**的时间;视频接在第几秒由上一步说了算。
                "offset": "{{video_on_timeline.timeline_start}}",
            },
        },
        {
            "id": "dubbing",
            "type": "dub_subtitles",
            "name": {"zh": "逐条配音并压回原段落长度", "en": "Dub each line and fit it back into its slot"},
            "position": {"x": 1630, "y": 260},
            "config": {
                "sequence_id": "{{dub_project.sequence_id}}",
                "clip_ids": "{{translated_subtitles.clip_ids}}",
                "match_duration": "yes",
                "line": "all",
                # **译配要的是替换,不是叠加。** 闪避把原声压到 30%,而两边都是人声 ——
                # 观众听见的是两个人同时说话,只是一个小声点(真机上报回来的正是这个)。
                #
                # 但整轨静音会把**背景音乐**一起带走 —— 说话声和音乐混在同一条轨上。
                # 所以先拆:人声那半丢掉、背景音留着,配音叠在背景音之上。装了分离引擎才做得到；
                # 没装时在排配音任务前明确失败，绝不能把用户选择静默改成整轨静音。
                "original_audio": "separate",
                "engine": "builtin:clone",
                "voice": voice_id,
            },
        },
        {
            "id": "export_dubbed_video",
            "type": "export_sequence",
            "name": {"zh": "导出译配成片(字幕烧进画面)", "en": "Export the dubbed video (subtitles burned in)"},
            "position": {"x": 1950, "y": 260},
            "config": {"sequence_id": "{{dub_project.sequence_id}}"},
        },
        {
            "id": "done_notice",
            "type": "notify",
            "name": {"zh": "译配完成通知", "en": "Dubbing finished notice"},
            "position": {"x": 2260, "y": 260},
            #: 不说「整条删掉即可回到原样」:只去掉人声(separate)时原片片段被静音、背景音另放了一条轨 ——
            #: 删掉配音轨回不到原样。原声实际怎么处理的由 original_audio_note 如实说。
            "config": {
                "title": text("视频译配与字幕已完成", "Translated dub and subtitles are ready"),
                "body": "{{source_video.name}} " + text(
                    "已生成 {{dubbing.done}} 条配音(失败 {{dubbing.failed}} 条),配音在单独一条轨上。",
                    "got {{dubbing.done}} dubbed lines ({{dubbing.failed}} failed) on a track of their own. ",
                ) + "{{dubbing.original_audio_note}}{{dubbing.overlap_note}}",
            },
        },
        {
            "id": "output",
            "type": "output",
            "name": {"zh": "交付逐字稿、译文、字幕与成片", "en": "Hand over the transcript, the translation, the subtitles and the export"},
            "position": {"x": 2570, "y": 260},
            "config": {
                "values": {
                    "source_asset_id": "{{source_video.asset_id}}",
                    "source_language": "{{verbatim_transcript.language}}",
                    "verbatim_transcript": "{{verbatim_transcript.text}}",
                    "translated_lines": "{{translate_lines.texts}}",
                    "subtitle_track_id": "{{translated_subtitles.track_id}}",
                    "subtitle_count": "{{translated_subtitles.count}}",
                    "dub_track_id": "{{dubbing.track_id}}",
                    "original_audio": "{{dubbing.original_audio}}",
                    "dubbed_lines": "{{dubbing.done}}",
                    "failed_lines": "{{dubbing.failed}}",
                    "project_id": "{{dub_project.project_id}}",
                    "sequence_id": "{{dub_project.sequence_id}}",
                    "final_asset_id": "{{export_dubbed_video.asset_id}}",
                }
            },
        },
    ]
    if lipsync:
        nodes.insert(next(index for index, node in enumerate(nodes) if node["id"] == "export_dubbed_video"), {
            "id": "lip_sync",
            "type": "dub_lipsync",
            "name": {"zh": "让原片的嘴对上配音", "en": "Re-sync the lips to the dub"},
            "position": {"x": 1950, "y": 440},
            "config": {
                "sequence_id": "{{dub_project.sequence_id}}",
                "clip_id": "{{video_on_timeline.clip_id}}",
                "track_id": "{{dubbing.track_id}}",
                "model": "",
                #: 留空:这张脸是谁的、有没有同意,由跑的人确认。
                "consent": "",
            },
        })
        notice = next(node for node in nodes if node["id"] == "done_notice")
        notice["config"]["body"] += text(
            "口型对好的画面在最上面一条视频轨上,盖住原片;删掉那条轨就回到改口型之前。",
            " The lip-synced picture sits on the top video track over the source; delete that track to undo the lip-sync.",
        )
        output = next(node for node in nodes if node["id"] == "output")
        output["config"]["values"].update({
            "lipsync_asset_id": "{{lip_sync.asset_id}}",
            "lipsync_track_id": "{{lip_sync.track_id}}",
        })
    edges = [
        {"id": "start_source", "source": "start", "target": "source_video"},
        {"id": "source_transcript", "source": "source_video", "target": "verbatim_transcript"},
        {"id": "source_project", "source": "source_video", "target": "dub_project"},
        {"id": "project_append", "source": "dub_project", "target": "video_on_timeline"},
        {"id": "source_append", "source": "source_video", "target": "video_on_timeline"},
        {"id": "transcript_translate", "source": "verbatim_transcript", "target": "translate_lines"},
        {"id": "translate_subtitles", "source": "translate_lines", "target": "translated_subtitles"},
        # 字幕要等视频真的落到时间线上才铺 —— 它的落点是 video_on_timeline 算出来的。
        {"id": "append_subtitles", "source": "video_on_timeline", "target": "translated_subtitles"},
        {"id": "subtitles_dub", "source": "translated_subtitles", "target": "dubbing"},
        *([{"id": "dub_lipsync", "source": "dubbing", "target": "lip_sync"},
           {"id": "lipsync_export", "source": "lip_sync", "target": "export_dubbed_video"}]
          if lipsync else [{"id": "dub_export", "source": "dubbing", "target": "export_dubbed_video"}]),
        {"id": "export_notice", "source": "export_dubbed_video", "target": "done_notice"},
        {"id": "notice_output", "source": "done_notice", "target": "output"},
    ]
    graph = {
        "meta": ({"template_id": TRANSLATED_DUB_LIPSYNC, "template_version": 2, "source": "official"} if lipsync
                 else {"template_id": TRANSLATED_DUB, "template_version": 3, "source": "official"}),
        "nodes": nodes,
        "edges": edges,
    }
    return normalize_graph(graph, node_types=NODE_TYPES)
