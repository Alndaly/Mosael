"""首页与管理台那两屏统计的响应体(聚合在 domain/dashboard 与 domain/usage)。"""

from __future__ import annotations

from pydantic import Field
from app.api.schemas.base import ApiModel

class DaySeriesPoint(ApiModel):
    day: str
    total: int = 0
    failed: int = 0


class UserSpendPoint(ApiModel):
    user_id: str = ""
    username: str = ""
    cost_micros: int = 0
    calls: int = 0


class AdminOverviewOut(ApiModel):
    users: int = 0
    active_users_7d: int = 0
    workspaces: int = 0
    assets: int = 0
    jobs_by_day: list[DaySeriesPoint] = Field(default_factory=list)
    spend_by_user: list[UserSpendPoint] = Field(default_factory=list)
    #: 金额的币种。此前没有这一栏,界面只好硬写 ¥ —— 一个按 USD 计价的部署会看到人民币符号。
    currency: str = "USD"
    window_days: int = 30


class DailyActivityOut(ApiModel):
    """一天的任务活动(首页活动图的一根柱)。date 为 YYYY-MM-DD(UTC)。"""

    date: str
    succeeded: int
    failed: int


class DailyPublishOut(ApiModel):
    """一天的发布活动(首页发布图的一根柱)。date 为 YYYY-MM-DD(UTC)。"""

    date: str
    succeeded: int
    failed: int
    active: int
    blocked: int


class DailyUsageOut(ApiModel):
    """一天的供应商费用/用量。cost_micros 是已知估算费用,unknown 是未定价事件数。"""

    date: str
    cost_micros: int
    events: int
    unknown: int


class DailyUsageTokensOut(ApiModel):
    """一天的 AI token 用量。total_tokens 允许供应商只返回总量,不拆输入/输出。"""

    date: str
    input_tokens: int
    output_tokens: int
    #: 缓存读/写单列 —— 它们与 input 不相交,单价也差一个数量级。并进"其他"的话,
    #: "这个月省下多少"在界面上就看不见了。
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int


class WorkspaceSummaryOut(ApiModel):
    """首页仪表数字。一次请求给全一屏,避免首页发 N 个列表请求做 .length 聚合。

    **这句话要一直是真的。** 它曾经附了八个界面从不读的字段 —— 于是没人知道这个回包里哪些是
    界面需要的、哪些是历史残留,下一个改统计页的人既不敢删也不敢信。而按供应商/能力分组的
    聚合在后端是有成本的(近 14 天的用量事件 join 价格规则),每次打开首页都算一遍扔掉。

    两个方向都修了:费用磁贴改显示**钱**(此前显示调用次数,而同一个回包里躺着金额,
    配套的 `usage_currency` 反倒被读了)、费用图下面补一行按供应商的分摊;剩下五个没人要的
    连算带发一起删。棘轮:`tests/test_api_fields_reach_the_screen.py`。
    """

    project_count: int
    asset_count: int
    sequence_count: int
    workflow_count: int
    running_jobs: int
    week_jobs_succeeded: int
    week_jobs_failed: int
    week_published: int
    # 图表数据:近 14 天逐日任务活动(旧→新,缺日补零)与素材类型构成
    daily: list[DailyActivityOut]
    asset_kinds: dict[str, int]
    # 发布图表:近 14 天发布任务状态(旧→新,缺日补零)与按平台聚合的发布任务数
    publish_daily: list[DailyPublishOut]
    publish_platforms: dict[str, int]
    # 供应商费用/用量:近 14 天聚合;没有价格规则时 cost 为 0,unknown 计数仍保留审计线索
    usage_cost_micros: int = 0
    usage_currency: str = "USD"
    usage_event_count: int = 0
    usage_unknown_cost_events: int = 0
    #: 没能定价的「供应商 + 模型 + 能力」及其次数。界面据此说清**缺哪个模型的价**,
    #: 而不是笼统一句「暂无价格规则」——后者在用户配了规则、只是没配这个模型时是错的。
    usage_unpriced: list[dict] = Field(default_factory=list)
    #: cacheRead / 提示词总量(input + cacheRead + cacheWrite)。0..1。
    usage_cache_hit_ratio: float = 0.0
    usage_daily: list[DailyUsageOut] = Field(default_factory=list)
    usage_token_daily: list[DailyUsageTokensOut] = Field(default_factory=list)
    usage_by_capability: dict[str, int] = Field(default_factory=dict)
    usage_by_provider: dict[str, int] = Field(default_factory=dict)
