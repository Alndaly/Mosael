"""自媒体分析节点:认链接、把取回来的作品 / 评论整理成同一个形状并算指标(见 domain/social_media)。

两个节点都不碰付费接口,取数是别的节点的事(TikHub 插件节点、浏览器节点)。它们存在,是因为分析类模板的两条
取数路交回来的东西形状各异,而写报告的那一步只该面对一种形状、一份算好的数。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain import social_media
from app.domain.workflows import WorkflowDomainError, as_text
from app.domain.workflows.executors.registry import RunScope, register

#: 一次最多整理多少条。作品列表一页几十条,评论能翻出几百条 —— 交给模型读的那份要有个头。
#: 一次进分析的上限。评论区全量分析(下游分批喂模型)要装得下几千条;人看的那张表
#: 另有 table_limit 收口 —— 它从来不是为了读完,是为了抽查。
MAX_ITEMS = 2000


@register("social_link")
def social_link(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    text = as_text(config.get("link")).strip()
    if not text:
        raise WorkflowDomainError("wfErr_socialLinkEmpty")
    found = social_media.parse_link(
        text, platform=as_text(config.get("platform")), expect=str(config.get("expect") or "")
    )
    if not found.url:
        #: 只给了一个编号却没说平台(或者说了平台、编号却不是那个平台的样子):拼不出链接,浏览器打不开,
        #: TikHub 也不知道该去哪个平台查。当场说清,不让下游拿着空链接去开浏览器。
        raise WorkflowDomainError("wfErr_socialLinkUnreadable", params={"text": text[:80]})
    return {"platform": found.platform, "kind": found.kind, "id": found.id, "url": found.url}


def _offset_hours(config: dict[str, Any]) -> float:
    raw = config.get("utc_offset")
    value = 8.0 if raw in (None, "") else float(raw)
    if not -12 <= value <= 14:
        raise WorkflowDomainError("wfErr_socialOffset", params={"value": as_text(raw)})
    return value


def _newest_first(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每一条都有发布时间才按时间排;缺的时候保留平台给的顺序(主页列表本来就是新的在前)。"""
    if posts and all(post.get("published_at") for post in posts):
        return sorted(posts, key=lambda post: post["published_at"], reverse=True)
    return posts


@register("social_metrics")
def social_metrics(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    kind = str(config.get("kind") or "posts")
    if kind not in ("posts", "comments"):
        raise WorkflowDomainError("wfErr_socialMetricsKind", params={"kind": kind})
    #: 数字格在进执行体之前已经按声明查过是数(binding.check_number_fields)。
    limit = max(1, min(int(float(config.get("limit") or 30)), MAX_ITEMS))
    #: 附表给人看,默认跟着 limit 走;分析要全量、附表要精选时,单独给 table_limit。
    table_limit_raw = config.get("table_limit")
    table_limit = max(1, min(int(float(table_limit_raw)), limit)) if table_limit_raw not in (None, "") else limit
    offset = _offset_hours(config)
    raw = social_media.find_items(config.get("data"), kind=kind)

    if kind == "comments":
        comments = [social_media.normalize_comment(one, offset_hours=offset) for one in raw]
        comments = sorted((one for one in comments if one["text"]), key=lambda one: -(one["likes"] or 0))[:limit]
        stats = social_media.comment_stats(comments)
        return {
            "items": comments,
            "count": len(comments),
            "account": {},
            "stats": stats,
            "summary": social_media.comments_summary(stats),
            "table": social_media.comments_table(comments[:table_limit]),
        }

    unit = str(config.get("duration_unit") or "auto")
    posts = [social_media.normalize_post(one, duration_unit=unit, offset_hours=offset) for one in raw]
    #: 什么都没认出来的一项(没有标题、编号,也没有一个数)不是作品,是混进列表里的别的东西(广告位、分隔卡片)。
    posts = [one for one in posts if one["id"] or one["title"] or one["interactions"] is not None]
    posts = _newest_first(posts)[:limit]
    account = social_media.normalize_account(config.get("profile"))
    stats = social_media.post_stats(posts, account=account)
    return {
        "items": posts,
        "count": len(posts),
        "account": account,
        "stats": stats,
        "summary": social_media.posts_summary(stats, account),
        "table": social_media.posts_table(posts),
    }
