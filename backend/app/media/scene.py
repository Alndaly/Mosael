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
    #: 每条字幕画在第几「道」(clip id → 道)。见 subtitle_lanes。
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
    """每条字幕画在第几「道」:显示着、有字幕的字幕轨按 position 从下往上排,第几条就是第几道。

    **两条字幕轨要各占一处。** 双语分两条轨(原文一条、译文一条)时,此前预览只画找到的第一条、导出把两条
    叠在同一个位置 —— 预览看着少一种语言,成片里两行字压成一团。道的位置怎么摆见 render_plan.lane_style。
    空轨不占道:一条没字的字幕轨不该把另一条挤到画面另一头。
    """
    lanes: dict[str, int] = {}
    occupied = sorted((track for track in shown if track.get("clips")), key=lambda track: int(track.get("position") or 0))
    for lane, track in enumerate(occupied):
        for clip in track.get("clips") or []:
            lanes[str(clip["id"])] = lane
    return lanes
