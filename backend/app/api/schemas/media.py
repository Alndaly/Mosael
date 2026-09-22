"""素材库:素材、LUT、字体,以及导入、分析、转码这几类请求。"""

from __future__ import annotations

from datetime import datetime
from pydantic import Field, computed_field
from app.api.schemas.base import ApiModel, OrmModel

class AssetCreate(ApiModel):
    workspace_id: str
    project_id: str | None = None
    kind: str
    name: str
    original_filename: str = ""
    file_key: str = ""
    media_info: dict = Field(default_factory=dict)


class AssetOut(OrmModel):
    id: str
    workspace_id: str
    project_id: str | None
    kind: str
    source: str
    name: str
    original_filename: str
    file_key: str
    media_info: dict
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def proxy_expected(self) -> bool:
        """这份素材会不会有代理。**前端不该用缺省值去猜后端的配置。**

        预览只走 WebCodecs + 代理这一条路(ADR-0004),画不出来时必须给一个说得清的状态。
        而 `generate_proxies` 关掉时后端既不建任务也不写 `proxy_status` —— 素材上**什么都
        没说**,于是前端读到空串,落进「未知一律当作还在转」那一档:遮罩写「转码中,等一会儿
        就好」,一件永远不会发生的事,外加每 2 秒轮询一次。

        算出来而不是存进 `media_info`:这是一个服务端配置,存进去的话开关一翻就得带迁移,
        而且每份素材里存的都是同一句话。
        """
        from app.domain.assets.proxies import proxies_possible

        return proxies_possible(self)


class AssetUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    tags: list[str] | None = Field(default=None, max_length=24)
    #: 归入某个项目;空串 = 移出项目(回到"未归档")。工作流的「素材整理」节点一直能做这件事,
    #: 而这个接口收不了 —— 于是同一个能力在两个界面上不一样。
    project_id: str | None = Field(default=None, max_length=64)


class LutOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    original_filename: str
    size: int
    created_at: datetime | None = None


class FontOut(OrmModel):
    id: str
    workspace_id: str
    family: str
    original_filename: str
    size: int
    created_at: datetime | None = None


class LutUpdate(ApiModel):
    name: str = Field(min_length=1, max_length=200)


class LocalImportRequest(ApiModel):
    """按本机绝对路径导入素材(仅桌面端自带后端可用,见 routes/assets.import_local_asset)。"""

    workspace_id: str
    path: str
    project_id: str | None = None


class AnalyzeAssetRequest(ApiModel):
    question: str = Field(default="", max_length=2000)
    profile_id: str | None = None
    #: 视频分析方式:auto(有原生能力就走原生,否则抽帧)/ native(强制原生)/ frames(强制抽帧+转写)。
    mode: str = "auto"


class AnalyzeAssetResponse(ApiModel):
    answer: str
    provider: str
    model: str
    #: 实际走的方式:image / native / frames。
    mode: str = "frames"
    #: 抽帧数(原生模式为 0)。
    frames: int = 0
    used_transcript: bool = False


class UrlProbeRequest(ApiModel):
    workspace_id: str
    url: str = Field(min_length=4, max_length=2000)
    #: 探测也可能需要登录态:私享列表不登录就是"不可用"。
    profile_id: str | None = None
    #: 从列表的第几条开始(1 起)。频道能有上万条,一次探 200 条,往后翻靠它。
    start: int = Field(default=1, ge=1)


class RemoteEntryOut(ApiModel):
    id: str
    url: str
    title: str
    duration: float | None = None
    uploader: str = ""
    thumbnail: str = ""
    #: 这一条实际拿得到的画质高度(从高到低)。空 = 未知(播放列表只做浅层探测),不是"没有"。
    heights: list[int] = Field(default_factory=list)


class UrlProbeResponse(ApiModel):
    title: str
    is_playlist: bool
    entries: list[RemoteEntryOut]
    #: 这一批从第几条开始(1 起)。界面据此说「第 201–400 条」,而不是让人以为总共这么多。
    start: int = 1
    #: 清单被截断了吗。**要如实说** —— 否则用户以为这就是全部,勾完发现少了一半。
    truncated: bool = False


class UrlSupportResponse(ApiModel):
    """Cheap URL classification backed by yt-dlp's installed extractor registry."""

    supported: bool
    extractor: str = ""


class UrlImportItem(ApiModel):
    url: str = Field(min_length=4, max_length=2000)
    title: str = Field(default="", max_length=300)


class UrlImportRequest(ApiModel):
    workspace_id: str
    project_id: str | None = None
    items: list[UrlImportItem] = Field(min_length=1, max_length=50)
    #: 下画面还是只下声轨。**不是下完再抽** —— 只要声音的人不该为此付几百 MB 和一次转码。
    kind: str = Field(default="video", pattern="^(video|audio)$")
    #: 借哪个浏览器池档案的登录态(会员视频、私享列表需要)。空 = 按公开内容下载。
    profile_id: str | None = None
    #: 画质上限(0 = 不限)。**上限而不是精确值**:同一批里每条能给的画质不一样。
    max_height: int = Field(default=0, ge=0, le=4320)


class VideoToGifRequest(ApiModel):
    """Options for creating a new GIF asset from a video asset."""

    fps: int = Field(default=12, ge=1, le=30)
    width: int = Field(default=720, ge=64, le=1920)
    start: float = Field(default=0, ge=0)
    duration: float | None = Field(default=None, gt=0)


class DenoiseAssetRequest(ApiModel):
    """给一份素材降噪。空 engine = 内置引擎;档位的合法值由契约判(领域层报 422)。"""

    engine: str = Field(default="", max_length=40)
    strength: str = Field(default="medium", max_length=20)


class AssetFrameRequest(ApiModel):
    """从一段视频里取某一时刻的一帧,存成一份新素材。"""

    at: float = 0
    #: 落到哪个项目下。留空跟随原素材。
    project_id: str | None = None


class SequenceFrameRequest(ApiModel):
    """把时间线在某一时刻的合成画面存成一份新素材。"""

    at: float = 0
