"""场景模型:t 时刻画面上有哪些层、按什么 z 序、谁是 base。

**这是预览与导出唯一的共同语义**,也是唯一必须两侧字面一致的东西。前端有一份等价实现
(`frontend/src/features/editor/playback/sceneModel.ts`)——因为预览要在本地同步跑到 60fps、
还要处理尚未提交的拖拽草稿,而导出要无头、在后端、可外派给 worker(见 ADR-0002)。这两个
约束决定了模型必然存在于两种语言里,「只有一份实现」做不到。

所以一致性靠**契约 + 语料**而不是靠共用代码:`tests/parity/scene-cases.json` 是语言中立的
用例集,后端 `tests/test_scene_parity.py` 与前端 `sceneModel.parity.test.ts` 跑同一份语料。
任一侧改了语义而另一侧没跟上,两边的 CI 都会红——漂移不再靠用户发现。

历史教训:这个模块诞生前,两侧各自手写、各自有绿测试、断言却相反——
- 上层 video 轨静音:预览显示画面,导出整层丢失(轨道头是**喇叭**图标,语义是音频,预览对);
- 最底 video 轨为空:预览把上层片段当 overlay(cover 取景),导出把它提为 base(遵 fill_mode)。
两条都是用户可见的成片不一致,而两侧测试全绿。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 画面层只认这两种素材;音频素材不进画面,文本片段(无 asset_id)是独立的一层。
VISUAL_ASSET_KINDS = frozenset({"video", "image"})


@dataclass(frozen=True)
class SceneLayer:
    """t 时刻的一个画面层。"""

    clip: dict[str, Any]
    track_id: str
    #: 最底「有媒体片段」的 video 轨上的片段:按序列 fill_mode 取景(cover/contain/blur)。
    #: 其余层一律 cover。**显式携带而不是靠数组位置推断**——base 缺媒体时不能让 overlay 继承 base 取景。
    is_base: bool


def clip_duration(clip: dict[str, Any]) -> float:
    """时间线上的时长 = 源区间 / 速度。与前端 geometry.clipDuration 逐字对应。"""
    speed = float(clip.get("speed") or 1.0) or 1.0
    return (float(clip["src_out"]) - float(clip["src_in"])) / speed


def clip_end(clip: dict[str, Any]) -> float:
    return float(clip["timeline_start"]) + clip_duration(clip)


def is_visual_clip(clip: dict[str, Any], assets: dict[str, dict[str, Any]]) -> bool:
    """带素材、且素材是视频/图片的片段才进画面。无 asset_id 的是文本片段(花字/字幕)。"""
    asset_id = clip.get("asset_id")
    if not asset_id:
        return False
    asset = assets.get(str(asset_id))
    return bool(asset) and str(asset.get("kind")) in VISUAL_ASSET_KINDS


def video_tracks_sorted(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """video 轨按 position 升序 = 时间线上从上到下。最上面的轨盖在最上层(PR/DaVinci 语义)。"""
    return sorted((t for t in tracks if str(t.get("kind")) == "video"), key=lambda t: int(t.get("position") or 0))


def assign_base_and_overlays(
    tracks: list[dict[str, Any]], assets: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """(base 轨, overlay 轨列表 bottom→top)。

    base = **最底「有画面片段」的 video 轨**。跳过空轨是有意的:把一条空的底轨当 base 会让整个
    渲染变成「没有片段可渲染」,而预览那边则会把上层片段降级成 overlay、丢掉 fill_mode 取景。

    overlay 里**不排除静音轨**:轨道头的静音是喇叭图标,语义是音频。静音一条画中画轨应当只让它
    闭嘴,不该让画面消失(音频侧的排除见 `audible_tracks`)。
    """
    with_media = [t for t in video_tracks_sorted(tracks) if any(is_visual_clip(c, assets) for c in t.get("clips") or [])]
    if not with_media:
        return None, []
    base = with_media[-1]
    # [:-1] 是 base 之上的轨(升序=上面的在前);reversed 换成 bottom→top,即绘制/叠加顺序。
    return base, list(reversed(with_media[:-1]))


def active_clip_on_track(
    track: dict[str, Any], assets: dict[str, dict[str, Any]], t: float
) -> dict[str, Any] | None:
    """同一轨上的片段不重叠,所以 t 时刻至多一个。排序让乱序输入也有确定结果。

    区间取 [start, end):相邻片段的交界处只有后一个命中,否则切换帧会画两层。
    """
    for clip in sorted((track.get("clips") or []), key=lambda c: float(c.get("timeline_start") or 0.0)):
        if not is_visual_clip(clip, assets):
            continue
        if float(clip["timeline_start"]) <= t < clip_end(clip):
            return clip
    return None


def scene_layers_at(
    tracks: list[dict[str, Any]], assets: dict[str, dict[str, Any]], t: float
) -> list[SceneLayer]:
    """t 时刻的可见画面层,bottom→top。前端 sceneLayersAt 的等价实现,由一致性语料钉死。"""
    base_track, overlay_tracks = assign_base_and_overlays(tracks, assets)
    if base_track is None:
        return []
    layers: list[SceneLayer] = []
    base_clip = active_clip_on_track(base_track, assets, t)
    if base_clip is not None:
        layers.append(SceneLayer(clip=base_clip, track_id=str(base_track.get("id") or ""), is_base=True))
    for track in overlay_tracks:
        clip = active_clip_on_track(track, assets, t)
        if clip is not None:
            layers.append(SceneLayer(clip=clip, track_id=str(track.get("id") or ""), is_base=False))
    return layers


def audible_tracks(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """会出声的轨:静音轨不出声——**任何 kind 都一样**,video 轨也不例外。

    与画面分开是刻意的:静音只关音频,画面照旧(见 assign_base_and_overlays)。
    """
    return [t for t in tracks if not bool(t.get("muted"))]


@dataclass(frozen=True)
class TextLayers:
    """画面上的文字层:字幕和花字。它们不进 scene_layers_at(那里只有素材画面),单独一层画在最上面。"""

    #: 没隐藏的字幕轨上的全部片段。
    subtitles: list[dict[str, Any]]
    #: video 轨上的花字(没有素材、有文字的片段)。**不看静音** —— 静音只管声音。
    titles: list[dict[str, Any]]
    #: 每条字幕在字幕框里排第几「道」(clip id → 道)。见 subtitle_lanes。
    subtitle_lanes: dict[str, int]


def is_text_clip(clip: dict[str, Any]) -> bool:
    """文本片段:没有素材、有文字。放在 video 轨上就是花字。"""
    return not clip.get("asset_id") and bool(clip.get("text_override"))


def text_layers(tracks: list[dict[str, Any]]) -> TextLayers:
    """要画出来的字幕与花字。前端 textLayers 的等价实现,由 contracts/text-layer-cases.json 钉死。

    轨道上两个开关各管一件事:`hidden` 只管字幕显示,`muted` 只管声音。此前字幕轨借 muted 表示
    「不显示」,视频轨的 muted 又顺带把花字藏掉 —— 给一条画中画轨关声音,字从成片里没了。
    """
    shown = [track for track in tracks if str(track.get("kind")) == "subtitle" and not bool(track.get("hidden"))]
    subtitles = [clip for track in shown for clip in track.get("clips") or []]
    titles = [clip for track in video_tracks_sorted(tracks) for clip in track.get("clips") or [] if is_text_clip(clip)]
    return TextLayers(subtitles=subtitles, titles=titles, subtitle_lanes=subtitle_lanes(shown))


def subtitle_lanes(shown: list[dict[str, Any]]) -> dict[str, int]:
    """每条字幕在字幕框里排第几「道」:显示着、有字幕的字幕轨按 position 升序(= 时间线上从上到下)排,
    第几条就是第几道,道 0 在框的最上面。

    **为什么按时间线顺序,而不是认「原文 / 译文」**:字幕轨上没有这种标记 —— role 只给配音轨用,翻译功能
    把译文写回同一条字幕(「原文\\n译文」),不另建轨;轨名是给人看的、随便改。时间线顺序是用户看得见、
    也挪得动的那一个。新建的字幕轨缺省放在最下面(tracks.add_track 只有视频轨缺省放最上面),所以先有的
    原文轨默认在上、后导入的译文轨在下;要换就在时间线上把轨道上移 / 下移。

    空轨不占道。各道怎么合成一框见 subtitle_frames。
    """
    lanes: dict[str, int] = {}
    occupied = sorted((track for track in shown if track.get("clips")), key=lambda track: int(track.get("position") or 0))
    for lane, track in enumerate(occupied):
        for clip in track.get("clips") or []:
            lanes[str(clip["id"])] = lane
    return lanes


def subtitle_text(clip: dict[str, Any]) -> str:
    """一条字幕要画的字:去掉首尾空白。只剩空白就是不画。"""
    return str(clip.get("text_override") or "").strip()


def stacked_subtitle_text(present: list[dict[str, Any]], lanes: dict[str, int]) -> str:
    """此刻在场的几条字幕合成**一框**:按道从上到下一道一行(一条字幕自己有几行就占几行),空白的不占行。

    **为什么合成一框而不是各道分开摆**:双语分两条轨时用户要两行都在字幕样式指定的位置(通常底部),原文在上、
    译文在下。合成一框之后,框整体按字幕样式定位 —— 底部时下沿不动、往上长,顶部时上沿不动、往下长 ——
    每道此刻几行高由排版自己决定,预览(一个 DOM 元素)和导出(同一套 CSS 渲染的一张 PNG、或一条 libass
    Dialogue)不用各算一遍高度。也因此「分两条轨」和「同一条轨里写两行」是同一框字、同一个画面。

    同一道上不该同时有两条(一条轨上的片段不重叠);真有的话按开始时间、再按 id 排,结果仍是确定的。
    前端 textLayers.stackedSubtitleText 是同一条规则,contracts/text-layer-cases.json 钉住。
    """
    drawn = sorted(
        (clip for clip in present if subtitle_text(clip)),
        key=lambda clip: (lanes.get(str(clip["id"]), 0), float(clip["timeline_start"]), str(clip["id"])),
    )
    return "\n".join(subtitle_text(clip) for clip in drawn)


@dataclass(frozen=True)
class SubtitleFrame:
    """[start, end) 这段时间里画面上的那一框字幕。"""

    start: float
    end: float
    text: str


def subtitle_frames(subtitles: list[dict[str, Any]], lanes: dict[str, int]) -> list[SubtitleFrame]:
    """把字幕切成「画面上那一框字不变」的几段 —— 导出按段烧(渲染计划的 subtitles 就是它)。

    在场取左闭右开 [start, end),和预览(Monitor 的场景键)、画面层(active_clip_on_track)同一个区间:
    同一道上首尾相接的两条,交界处只算后一条。切点是各条字幕的起止,按微秒取整 —— 浮点误差切出来的
    几纳秒小段会在成片里闪一帧两道都在的画面。相邻两段的字一样就并成一段。

    预览不切段,逐时刻用 stacked_subtitle_text 合成;两者按同一个在场区间、同一个合成规则,所以每一刻一致。

    扫一遍切点、维护「此刻在场」的集合:一部两小时的片子几千条字幕,逐段再扫全部字幕是平方级的。
    """
    spans = [
        (clip, round(float(clip["timeline_start"]), 6), round(clip_end(clip), 6))
        for clip in subtitles
        if subtitle_text(clip)
    ]
    spans = [(clip, start, end) for clip, start, end in spans if start < end]
    entering: dict[float, list[int]] = {}
    leaving: dict[float, list[int]] = {}
    for index, (_clip, start, end) in enumerate(spans):
        entering.setdefault(start, []).append(index)
        leaving.setdefault(end, []).append(index)
    cuts = sorted({*entering, *leaving})
    present: dict[int, dict[str, Any]] = {}
    frames: list[SubtitleFrame] = []
    for lo, hi in zip(cuts, cuts[1:]):
        for index in leaving.get(lo, ()):
            present.pop(index, None)
        for index in entering.get(lo, ()):
            present[index] = spans[index][0]
        text = stacked_subtitle_text(list(present.values()), lanes)
        if not text:
            continue
        if frames and frames[-1].end == lo and frames[-1].text == text:
            frames[-1] = SubtitleFrame(start=frames[-1].start, end=hi, text=text)
        else:
            frames.append(SubtitleFrame(start=lo, end=hi, text=text))
    return frames
