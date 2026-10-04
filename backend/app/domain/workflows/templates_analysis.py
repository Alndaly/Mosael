"""**分析类**官方模板:不产出视频,产出一份能照着做的分析笔记。

三张图:账号运营诊断、单条视频爆款拆解、评论区洞察。它们的难处不在分析(那是一次对话),在**取数**:

- **数据来源二选一。** TikHub 插件(按次计费、字段全、不用登录)或者内嵌浏览器(不花钱,但很多平台不登录
  看不到东西)。开始节点的 `data_source` 是一个**选项参数**(`param_options`:browser / tikhub,面板上是下拉),
  条件节点按值直接分两支;值不在选项里运行前就拦,选了 TikHub 而它没备好也当场拦(选项的 `requires`,
  见 engine._check_chosen_options)。没装 TikHub 时浏览器那一支照样能跑 ——
  所以 TikHub 的工具用**通用插件节点**(`plugin_tool`)引用,而不是 `plugin.<包>.<工具>`:后者是动态类型,
  插件不在时整张图校验不过,连浏览器那一支也跑不了。
- **两路交出同一个形状。** TikHub 回的是各平台接口的投影(字段名各异),浏览器回的是页面文字。浏览器那一路先让
  模型把页面文字抄成结构化数据(数字照页面原样抄,「1.2万」也照抄),然后两路都进「整理作品与评论数据」
  (`social_metrics`,见 domain/social_media):按别名取字段、换算单位、算发布频率和互动率。**算术交给代码**,
  写报告的模型拿到的是算好的数和逐条明细。
- **平台差异。** TikHub 按平台分支(抖音 / 小红书 / B 站,一个平台一条连接,工具名各不相同);浏览器不分平台 ——
  不写 CSS 选择器(站点一改版就失效),读页面全部文字(含 B 站评论区那种 shadow DOM 里的)交给模型。

分支汇合靠「任一上游跑过就跑」(Dify 语义,见 engine.incoming_active):汇合节点里把几条分支的同一个输出
写在一起(`{{抖音.summary}}{{小红书.summary}}…`),没走的分支引用出来是空串,所以拼出来的就是走过的那一支。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import pick_text, tr
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.normalization import normalize_graph
from app.domain.workflows.template_requirements import (
    CHAT_MODEL,
    TIKHUB_ACCOUNT,
    TIKHUB_COMMENTS,
    TIKHUB_VIDEO,
    TRANSCRIPTION_ENGINE,
    CheckStatus,
    requirement,
)

ACCOUNT_ANALYSIS = "account_analysis"
VIRAL_VIDEO_BREAKDOWN = "viral_video_breakdown"
COMMENT_INSIGHTS = "comment_insights"

TIKHUB_PLUGIN = "dev.mosael.tikhub"
#: TikHub 那一路接了哪几个平台。浏览器那一路不分平台。
TIKHUB_PLATFORMS = ("douyin", "xiaohongshu", "bilibili")
_PLATFORM_NAMES = {
    "douyin": {"zh": "抖音", "en": "Douyin"},
    "xiaohongshu": {"zh": "小红书", "en": "Xiaohongshu"},
    "bilibili": {"zh": "B站", "en": "Bilibili"},
}
#: 节点 id 的前缀(短一点,画布上好认)。
_SHORT = {"douyin": "dy", "xiaohongshu": "xhs", "bilibili": "bili"}

#: 每个平台、每件事用 TikHub 的哪个工具,入参怎么填。
#:
#: 工具名是 TikHub MCP 从它的 API 路径生成的(`/api/v1/douyin/web/fetch_one_video` → `douyin_web_fetch_one_video`);
#: 用户要在插件页把这几个工具勾上(TikHub 的工具默认不开,见插件清单的 `tools.expose`)。节点上的 `tool_name`
#: 是普通字段,TikHub 改名时在画布上换一个就行。入参的值是模板:编号来自「解析自媒体链接」那一步。
#:
#: 连接留空:一个连接对一个平台,而抖音的工具只在抖音那条连接上 —— 留空时运行时按「这个工具在哪条连接上」
#: 自动挑(plugins.nodes.resolve_instance),前置检查用的也是这一条(见 tikhub_status)。
TIKHUB_CALLS: dict[str, dict[str, tuple[str, dict[str, str]]]] = {
    "douyin": {
        "profile": ("douyin_web_handler_user_profile", {"sec_user_id": "{{link.id}}"}),
        "posts": ("douyin_web_fetch_user_post_videos", {"sec_user_id": "{{link.id}}", "count": "{{start.post_count}}"}),
        "video": ("douyin_web_fetch_one_video", {"aweme_id": "{{link.id}}"}),
        "comments": ("douyin_web_fetch_video_comments", {"aweme_id": "{{link.id}}", "count": "{{start.comment_count}}"}),
    },
    "xiaohongshu": {
        "profile": ("xiaohongshu_app_v2_get_user_info", {"user_id": "{{link.id}}", "share_text": "{{link.url}}"}),
        "posts": ("xiaohongshu_app_v2_get_user_posted_notes", {"user_id": "{{link.id}}", "share_text": "{{link.url}}"}),
        "video": ("xiaohongshu_app_v2_get_video_note_detail", {"note_id": "{{link.id}}", "share_text": "{{link.url}}"}),
        "comments": ("xiaohongshu_app_v2_get_note_comments", {"note_id": "{{link.id}}", "share_text": "{{link.url}}"}),
    },
    "bilibili": {
        "profile": ("bilibili_web_fetch_user_profile", {"uid": "{{link.id}}"}),
        "posts": ("bilibili_web_fetch_user_post_videos", {"uid": "{{link.id}}", "ps": "{{start.post_count}}", "order": "pubdate"}),
        "video": ("bilibili_web_fetch_one_video", {"bv_id": "{{link.id}}"}),
        "comments": ("bilibili_web_fetch_video_comments", {"bv_id": "{{link.id}}", "pn": "1"}),
    },
}
#: 抖音接口的时长是毫秒;另外两家交给「自动」(B 站是秒或「03:21」)。
_DURATION_UNIT = {"douyin": "milliseconds", "xiaohongshu": "auto", "bilibili": "auto"}

#: 每个模板在 TikHub 那一路要用的几件事 —— 前置检查按它查(见 tikhub_status)。
TIKHUB_NEEDS: dict[str, tuple[str, ...]] = {
    TIKHUB_ACCOUNT: ("profile", "posts"),
    TIKHUB_VIDEO: ("video", "comments"),
    TIKHUB_COMMENTS: ("comments",),
}


def tikhub_status(db: Session, user_id: str, check: str) -> CheckStatus:
    """TikHub 那一路**此刻跑得起来吗**:至少有一个平台,它要用的每个工具都恰好落在这个人的一条可用连接上。

    和运行时同一条判据 —— 节点的连接留空,运行时由 `resolve_instance` 按「哪条连接上有这个工具」挑:
    一条都没有(没装、没接、工具没勾)跑不了,两条以上(同一个平台接了两次)它不猜、也跑不了。
    """
    from app.domain.plugins.nodes import instances_for_node, node_type_id

    for platform in TIKHUB_PLATFORMS:
        tools = [TIKHUB_CALLS[platform][need][0] for need in TIKHUB_NEEDS[check]]
        if all(len(instances_for_node(db, node_type_id(TIKHUB_PLUGIN, tool), user_id)) == 1 for tool in tools):
            return "met"
    return "missing"


def tikhub_problem(db: Session, user_id: str, check: str) -> str | None:
    """TikHub 那一路此刻**缺什么**(一句话);跑得起来(tikhub_status 说齐)回 None。

    按要做的那一步说:没装插件 → 去装;没接 → 去接(一个平台一条、填密钥、启用);接了的连接逐条说卡在哪 ——
    停用、缺配置、缺密钥、权限没给(plugins.instances.blocked_reason,插件页同一句),或者这几个工具没勾;
    都好好的却还是不齐,是同一个平台接了两条(运行时不猜)。
    """
    if tikhub_status(db, user_id, check) == "met":
        return None
    from sqlalchemy import select

    from app.db.models import PluginInstance, PluginPackage
    from app.domain.plugins import instances as inst

    if db.get(PluginPackage, TIKHUB_PLUGIN) is None:
        return tr("wfWhy_tikhubNotInstalled")
    connections = list(db.scalars(select(PluginInstance).where(
        PluginInstance.package_id == TIKHUB_PLUGIN, PluginInstance.owner_user_id == user_id,
    )))
    if not connections:
        return tr("wfWhy_tikhubNoConnection")
    reasons: list[str] = []
    for instance in connections:
        blocked = inst.blocked_reason(db, instance)
        if blocked:
            reasons.append(tr("pluginWhy_connection", name=instance.name, reason=blocked))
            continue
        platform = str((instance.config or {}).get("TIKHUB_PLATFORM") or "")
        if platform not in TIKHUB_CALLS:
            continue
        exposed = inst.exposed_tools(db, instance.id)
        off = [TIKHUB_CALLS[platform][need][0] for need in TIKHUB_NEEDS[check] if TIKHUB_CALLS[platform][need][0] not in exposed]
        if off:
            reasons.append(tr("wfWhy_tikhubToolsOff", name=instance.name, tools=tr("punct_listSep").join(off)))
    return tr("punct_listSep").join(reasons) if reasons else tr("wfWhy_tikhubAmbiguous")


def _tool_list(check: str) -> str:
    """前置条件里列出要勾的工具,按平台分组。"""
    return ";".join(
        f"{_PLATFORM_NAMES[platform]['zh']}:" + "、".join(TIKHUB_CALLS[platform][need][0] for need in TIKHUB_NEEDS[check])
        for platform in TIKHUB_PLATFORMS
    )


def _tool_list_en(check: str) -> str:
    return "; ".join(
        f"{_PLATFORM_NAMES[platform]['en']}: " + ", ".join(TIKHUB_CALLS[platform][need][0] for need in TIKHUB_NEEDS[check])
        for platform in TIKHUB_PLATFORMS
    )


# --------------------------------------------------------------------------------------
# 积木
# --------------------------------------------------------------------------------------

#: 引号里放什么。实测(2026-10,k3,409 条评论):报告把归纳出来的话放进「」当成「依据」,读的人以为是评论原文,
#: 可取回的评论里根本没有那句(「都是从COD转过来的兄弟」);长评论则被删改、拼接后仍放在引号里。
_QUOTE_RULE = ("「」里只放评论原文的逐字摘录(太长可以用……删节,不改字、不把两条拼成一句);"
               "归纳、转述、话题名、建议回复的台词都不要加「」。")

#: 浏览器读页面的那段脚本:等页面安定、往下滚几屏(作品列表 / 评论区是滚动加载的),交回页面上的全部文字。
#:
#: **不写选择器。** 各平台的页面结构隔几周就改一次,写死的选择器一改就静悄悄地取到空;页面文字交给模型抄成
#: 结构化数据,改版只影响「文字长什么样」,模型照样读得懂。B 站评论区在 shadow DOM 里,`innerText` 拿不到,
#: 所以另外把每个打开的 shadow root 的文字也收进来。总时长压在执行器的 20 秒脚本上限以内。
#:
#: 实测过的三个坑(2026-10,B 站 310 条评论的页面):
#: 1. shadow root 里的 STYLE/SCRIPT 会被一并抄进来 —— 评论区组件的 `:host` 样式块先吃掉大半字符预算,
#:    页面尾部的评论在截取处被截掉(实测只抄到 13 条),所以采集时跳过这些节点。
#: 2. 滚动轮数写死会两头不靠:滚少了评论区没加载完,直接跳到底则哨兵来不及触发(实测抄到 0 条)。
#:    按步进滚、到底且高度不再长就停,最后留一段收尾等待给最后一次懒加载。
#: 3. max_chars 是抄写的总预算,不是「页面有多大」:评论区模板给到 120k(约 350 条评论的量级),
#:    超过的部分由模型那一步的条数上限收口,而不是在这里截断。
#: 4. 楼中楼默认折叠,不点就不渲染(「共 N 条回复」「展开 N 条回复」)。展开是可选阶段
#:    (`expand_max` 个点开上限,0 = 不展开):按**文字模式**找折叠钮而不是选择器 —— 选择器一改版就
#:    静默失效,而「共 43 条回复」这几个字是给人看的,变了用户先发现。只点顶层评论的折叠钮,
#:    深度展开(「展开更多回复」)不值得那点预算;要全量回复走 TikHub 那一路的回复接口。
#: 5. **已知平台优先走它自己的接口**(2026-10 实测,B 站):页面上下文 fetch 平台 JSON 接口,
#:    带登录态、分页器、楼中楼都在返回里,评论区组件被风控卡住也不受影响(实测组件空转时接口
#:    照常返回 106 条)。接口也是一种会变的契约 —— 所以它只是**优先策略**,落空就落回读 DOM。
#:    抖音/小红书要签名(a_bogus / x-s),不在页面里调,继续走 DOM 那条路。
#: 6. **B 站评论要翻全,取不全要说清**(2026-10,已登录档案逐条对过 69 / 399 / 1374 条三个视频):一级评论逐页
#:    翻到平台不再给(此前只翻 15 页,1374 条的视频只拿到 300 条一级),第 1 页另带置顶;楼中楼按楼逐页翻
#:    reply/reply(此前只用一级里自带的 ≤3 条预览,69 条的视频只拿到 15/50 条回复)。**未登录时 B 站只给 3 条
#:    一级评论、每条下前 20 条回复** —— 这是平台的限制,照实停下,交回平台显示的总数、取到的条数和没取全的原因
#:    (`gap_note`,按界面语言由模板交进来),下游写进结果,不把几条当成全部去分析。
_READ_PAGE_SCRIPT = """(async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const BILI = /bilibili\\.com\\/video\\/(BV[\\w]+)/;
  const bili = location.href.match(BILI) || String(input.video_url || "").match(BILI);
  if (bili) {
    //: B 站:页面上下文直接调它自己的接口 —— 带登录态、结构化 JSON、分页器和楼中楼都在里面,
    //: 评论区组件渲染失败(风控「玩命加载」)也不受影响。接口变了就落空,落回下面读 DOM 那条路。
    try {
      const getJson = async (url) => (await fetch(url, { credentials: "include" })).json();
      const started = Date.now();
      //: 时间预算要落在节点的脚本上限(timeout_ms)之内;页与页之间隔一下,不踩频控。
      const budget = Number(input.budget_ms) || 15000;
      const pause = input.page_pause_ms == null ? 400 : Number(input.page_pause_ms);
      const outOfTime = () => Date.now() - started > budget;
      const view = await getJson("https://api.bilibili.com/x/web-interface/view?bvid=" + bili[1]);
      const v = view && view.data;
      if (v && v.aid) {
        const total = v.stat ? Number(v.stat.reply) || 0 : 0;
        const nav = await getJson("https://api.bilibili.com/x/web-interface/nav").catch(() => null);
        const loggedIn = Boolean(nav && nav.data && nav.data.isLogin);
        //: 评论有多少抓多少,上限 comment_max(最多 2000 条)。
        const wanted = Math.min(Number(input.comment_max) || 1000, 2000);
        const seen = new Set();
        const picked = [];
        let stoppedBy = "";
        //: 同一条评论只算一次(一级里自带的楼中楼预览、置顶,和翻出来的是同一条)。楼中楼拍平、带 ↳ 前缀。
        const take = (c, isReply) => {
          const id = c && (c.rpid_str || (c.rpid ? String(c.rpid) : ""));
          if (!id || seen.has(id)) return;
          seen.add(id);
          picked.push({ isReply, comment: {
            author: c.member ? c.member.uname : "",
            //: 原文照搬:换行是原样的一部分;接口交回的 HTML 转义(&#39;)留给整理节点解一次(unescape_html)。
            text: (isReply ? "↳ " : "") + ((c.content ? c.content.message : "") || "").trim(),
            likes: typeof c.like === "number" ? c.like : "",
            published_at: c.ctime ? new Date(c.ctime * 1000).toISOString().slice(0, 10) : "",
          } });
        };
        const full = () => {
          if (picked.length >= wanted) { stoppedBy = "limit"; return true; }
          if (outOfTime()) { stoppedBy = "time"; return true; }
          return false;
        };
        //: 一级评论逐页翻到平台不再给(第 1 页另带置顶)。未登录时 B 站只给 1 页 3 条 —— 照实停下,下面说清。
        const threads = [];
        for (let pn = 1; !(pn > 1 && full()); pn += 1) {
          const r = await getJson("https://api.bilibili.com/x/v2/reply?type=1&oid=" + v.aid + "&sort=2&ps=20&pn=" + pn);
          const d = (r && r.data) || {};
          const replies = d.replies || [];
          const pinned = pn === 1 ? [...(d.top_replies || []), ...(d.upper && d.upper.top ? [d.upper.top] : [])] : [];
          for (const one of [...pinned, ...replies]) {
            take(one, false);
            for (const sub of one.replies || []) take(sub, true);
            threads.push(one);
          }
          if (replies.length < 20) break;
          await wait(pause);
        }
        //: 楼中楼:一级里只自带前几条预览,回复更多的楼逐页翻 reply/reply,翻到平台不再给。
        for (const one of threads) {
          if (stoppedBy || full()) break;
          if ((one.rcount || 0) <= (one.replies || []).length) continue;
          for (let pn = 1; !full(); pn += 1) {
            const r = await getJson("https://api.bilibili.com/x/v2/reply/reply?type=1&oid=" + v.aid + "&root=" + (one.rpid_str || one.rpid) + "&ps=20&pn=" + pn);
            const subs = (r && r.data && r.data.replies) || [];
            for (const sub of subs) take(sub, true);
            if (subs.length < 20) break;
            await wait(pause);
          }
        }
        const kept = picked.slice(0, wanted);
        if (kept.length) {
          const fetchedReplies = kept.filter((one) => one.isReply).length;
          //: 取到的比平台说的少,说清是哪一种:没登录(平台只给前几条)、到了条数 / 时间上限、或者平台就是没给
          //: (被删除、折叠、仅自己可见)。这几句话由模板按界面语言交进来(input.notes)。
          const notes = input.notes || {};
          const gap = kept.length >= total ? ""
            : stoppedBy === "limit" ? notes.limit
            : stoppedBy === "time" ? notes.time
            : !loggedIn ? notes.login
            : notes.platform;
          //: 视频本身的数据也在 view 接口里(播放、点赞、时长、发布时间……)—— 一并交回,爆款拆解直接整理它。
          //: 只带整理要用的那几格,原样的 view 返回很大,会白占运行记录。
          const video = { bvid: v.bvid, aid: v.aid, title: v.title, pubdate: v.pubdate, duration: v.duration, desc: v.desc,
                          owner: v.owner ? { name: v.owner.name, mid: v.owner.mid } : null, stat: v.stat || {} };
          return { url: location.href, title: document.title, now: new Date().toISOString(), mode: "api", total,
                   fetched: kept.length, fetched_roots: kept.length - fetchedReplies, fetched_replies: fetchedReplies,
                   logged_in: loggedIn, gap_note: gap || "", expanded: -1, video,
                   text: JSON.stringify({ total, comments: kept.map((one) => one.comment) }) };
        }
      }
    } catch (e) { /* 接口这条路不通就落回读 DOM */ }
  }
  await wait(Number(input.settle_ms) || 2500);
  const rounds = Math.min(Number(input.scrolls) || 0, 12);
  let last = -1, stable = 0;
  for (let i = 0; i < rounds; i += 1) {
    window.scrollBy(0, Math.max(window.innerHeight, 800));
    await wait(Number(input.pause_ms) || 1300);
    const h = document.body.scrollHeight;
    const atBottom = window.scrollY + window.innerHeight >= h - 4;
    if (atBottom && h === last) { stable += 1; if (stable >= 2) break; } else { stable = 0; }
    last = h;
  }
  const expandMax = Math.min(Number(input.expand_max) || 0, 20);
  const expanders = [];
  if (expandMax > 0) {
    await wait(Number(input.expand_settle_ms) || 1200);
    //: 目标站点说什么语言不归界面语言管 —— 两种都认。英文站点(YouTube 等)的折叠钮是
    //: 「View 12 replies」「Show more replies」;认不出就这轮不展开,读到的仍是顶层评论。
    const PATTERN = /^(共\\s*\\d+\\s*条回复|展开\\s*\\d*\\s*条回复|展开更多回复|查看回复|view\\s+\\d+\\s+(more\\s+)?repl|show\\s+more\\s+repl)/i;
    //: 折叠钮的文字可能是「共<em>43</em>条回复」这种带子标签的 —— 不要求叶子,
    //: 取**最深的**那个匹配(后代里没有再匹配的),点它才对得上点击处理器。
    const collect = (root) => {
      root.querySelectorAll("*").forEach((el) => {
        if (el.shadowRoot) collect(el.shadowRoot);
        if (expanders.length >= expandMax || el.tagName === "A") return;
        const text = (el.textContent || "").trim();
        if (text.length <= 2 || text.length >= 40 || !PATTERN.test(text)) return;
        const nested = Array.from(el.children).some((c) => PATTERN.test((c.textContent || "").trim()));
        if (!nested) expanders.push(el);
      });
    };
    collect(document);
    //: 说明文字旁边另有一个「点击查看」时点那个:B 站的折叠钮是 <span>共5条回复，</span><bili-text-button>点击查看
    //: </bili-text-button>,点 span 什么也不发生(实测展开报了 8 次、楼中楼一条没出来)。
    const VIEW = /^(点击查看|查看|展开|view|show)/i;
    const clickTarget = (el) => Array.from((el.parentElement && el.parentElement.children) || [])
      .find((one) => one !== el && VIEW.test((one.textContent || "").trim())) || el;
    for (const el of expanders) {
      const target = clickTarget(el);
      target.scrollIntoView({ block: "center" });
      target.click();
      await wait(Number(input.expand_wait_ms) || 600);
    }
  }
  await wait(Number(input.final_ms) || 1500);
  const SKIP = new Set(["STYLE", "SCRIPT", "NOSCRIPT", "LINK", "META"]);
  const parts = [(document.body && document.body.innerText) || ""];
  const visit = (root) => {
    root.querySelectorAll("*").forEach((el) => {
      if (!el.shadowRoot) return;
      const text = Array.from(el.shadowRoot.children)
        .filter((one) => !SKIP.has(one.tagName))
        .map((one) => one.innerText || "").join("\\n").trim();
      if (text) parts.push(text);
      visit(el.shadowRoot);
    });
  };
  visit(document);
  const limit = Number(input.max_chars) || 30000;
  return { url: location.href, title: document.title, now: new Date().toISOString(), expanded: expanders.length, text: parts.join("\\n\\n").slice(0, limit) };
})()"""


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    """严格模式的对象:每个字段都必填,不许多余字段。可空的字段用空字符串表示「页面上没有」。"""
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _string(description: str = "") -> dict[str, Any]:
    return {"type": "string", **({"description": description} if description else {})}


#: 从页面上抄数字时**照原样抄**(「1.2万」「10万+」),换算交给代码 —— 模型做单位换算会错,而且错得看不出来。
_COUNT = _string("照页面原样抄(如 1.2万、3456、10万+);页面上没有就空字符串")


def _post_fields() -> dict[str, Any]:
    return {
        "title": _string("标题或文案的开头"),
        "published_at": _string("发布时间,写成 YYYY-MM-DD 或 YYYY-MM-DD HH:MM;看不出就空字符串"),
        "duration": _string("时长,写成 mm:ss 或秒数;没有就空字符串"),
        "views": _COUNT,
        "likes": _COUNT,
        "comments": _COUNT,
        "collects": _COUNT,
        "shares": _COUNT,
    }


def _comment_schema() -> dict[str, Any]:
    return _object({
        "text": _string("评论原文,一字不改"),
        "likes": _COUNT,
        "author": _string(),
        "published_at": _string("能看出就写 YYYY-MM-DD,否则空字符串"),
    })


#: 页面文字 → 结构化数据那一步共用的规矩。
_TRANSCRIBE_RULES = """规则:
- 只抄页面上真有的,不编、不补、不估;页面上没有的字段写空字符串。
- 数字照页面原样抄(1.2万、3.4w、10万+ 都原样写),不要自己换算。
- 发布时间:能确定就写成 YYYY-MM-DD(有钟点就 YYYY-MM-DD HH:MM);写的是相对时间(3天前、昨天、2小时前)就按
  「读取时间」换算成日期;只写了月-日(09-21)就补上读取时间那一年;实在看不出就空字符串。
- 页面主要是登录框、验证码、「登录后查看更多」时 login_wall = true,并在 notes 里说清看到了什么;
  这时宁可少抄,不要把推荐位、广告、别人的作品当成这个账号的。
只输出符合 JSON Schema 的对象。"""


class _Builder:
    """攒节点和边。位置按「列 × 行」给,画布上一支一行、一步一列。"""

    def __init__(self, chat: Any, locale: str | None) -> None:
        self.chat = chat
        self.locale = locale
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []

    def text(self, zh: str, en: str) -> str:
        """图里给人看的默认值(笔记里的小标题、通知)在建图这一刻定语言(见 templates.localised_names)。"""
        return pick_text({"zh": zh, "en": en}, self.locale)

    def node(self, node_id: str, node_type: str, name: dict[str, str], col: float, row: float, config: dict[str, Any]) -> str:
        self.nodes.append({
            "id": node_id, "type": node_type, "name": name,
            "position": {"x": 40 + int(col * 320), "y": 60 + int(row * 190)}, "config": config,
        })
        return node_id

    def edge(self, source: str, target: str, handle: str | None = None) -> None:
        edge: dict[str, Any] = {"id": f"{source}__{target}", "source": source, "target": target}
        if handle:
            edge["source_handle"] = handle
            edge["id"] += f"__{handle}"
        self.edges.append(edge)

    def llm(self, node_id: str, name: dict[str, str], col: float, row: float, *, system: str, prompt: str,
            schema_name: str, schema: dict[str, Any], max_tokens: int = 8000, temperature: float = 0.3) -> str:
        return self.node(node_id, "llm", name, col, row, {
            "profile_id": getattr(self.chat, "profile_id", ""),
            "model": getattr(self.chat, "model", ""),
            "preset": "precise",
            "system": system,
            "prompt": prompt,
            "response_format": "json_schema",
            "json_schema_name": schema_name,
            "json_schema": schema,
            "json_schema_strict": "true",
            "temperature": temperature,
            "max_tokens": max_tokens,
        })

    def graph(self, template_id: str, *, version: int = 2) -> dict[str, Any]:
        return normalize_graph(
            #: 第 2 版:数据来源从手填的一格(转小写、「包含 tikhub」)改成选项参数,按值直接分支。
            {"meta": {"template_id": template_id, "template_version": version, "source": "official"},
             "nodes": self.nodes, "edges": self.edges},
            node_types=NODE_TYPES,
        )


#: 数据来源的两个选项的值 —— 分支按它直接判。
BROWSER, TIKHUB = "browser", "tikhub"


def _data_source_options(b: _Builder, check: str) -> list[dict[str, str]]:
    """开始节点「数据来源」那一格的选项(`param_options`):面板上是下拉,运行前只认这两个值。TikHub 那一项要什么
    写在 `requires` 上(和模板库前置条件同一个检查键):选了它而它没备好,运行前当场拦、说清缺什么。"""
    return [
        {
            "value": BROWSER,
            "label": b.text("内嵌浏览器", "Built-in browser"),
            "description": b.text(
                "不用配置、不花钱;要登录才看得到的页面(小红书一定要、抖音多半要),在「用内嵌浏览器打开」里换成浏览器池里"
                "已登录的档案。B 站评论不登录只给前 3 条一级评论(每条下前 20 条回复),要取全也换成已登录 B 站的档案。"
                "页面上的数字是约数,发布时间常常缺",
                "Nothing to set up and free; for pages that need a sign-in (Xiaohongshu always, Douyin mostly), switch"
                " “Open in the built-in browser” to a signed-in browser-pool profile. Bilibili shows signed-out visitors only"
                " the first 3 top-level comments (and 20 replies under each); to fetch them all, use a profile signed in to"
                " Bilibili too. Numbers on the page are rounded and publish times are often missing",
            ),
        },
        {
            "value": TIKHUB,
            "label": "TikHub",
            "description": b.text(
                "需安装 TikHub 插件、接好连接并填上 API 密钥(按次计费);数据更全更稳、不用登录",
                "Needs the TikHub plugin with a connection and your API key (billed per call); fuller, steadier data and no"
                " sign-in",
            ),
            "requires": check,
        },
    ]


def _source_switch(b: _Builder, *, link_param: str, expect: str) -> None:
    """认链接 → 按数据来源分两支。`use_tikhub` 的「真」是 TikHub,「假」是浏览器。

    数据来源是选项参数,值只会是 browser / tikhub(别的运行前就拦了),所以按值直接判「等于 tikhub」—— 此前是手填的
    一格,先转小写再判「包含 tikhub」,打错字就静默走了浏览器。"""
    b.node("link", "social_link", {"zh": "认出平台和编号", "en": "Work out the platform and id"}, 1, 2.5, {
        "link": f"{{{{start.{link_param}}}}}", "platform": "{{start.platform}}", "expect": expect,
    })
    b.edge("start", "link")
    b.node("use_tikhub", "condition", {"zh": "用 TikHub 取数吗", "en": "Fetch with TikHub?"}, 3, 2.5, {
        "left": "{{start.data_source}}", "op": "equals", "right": TIKHUB,
    })
    b.edge("link", "use_tikhub")


def _platform_chain(b: _Builder, make_branch, *, col: float) -> list[str]:
    """TikHub 那一支按平台分:抖音?→ 小红书?→ B 站?→ 都不是就说清楚。`make_branch(platform, col, row)`
    造一个平台的那几步,返回这一支的出口(汇合节点从它们接)。"""
    exits: list[str] = []
    previous, handle = "use_tikhub", "true"
    for row, platform in enumerate(TIKHUB_PLATFORMS):
        check = f"tk_is_{_SHORT[platform]}"
        names = _PLATFORM_NAMES[platform]
        b.node(check, "condition", {"zh": f"是{names['zh']}吗", "en": f"Is it {names['en']}?"}, col, row, {
            "left": "{{link.platform}}", "op": "equals", "right": platform,
        })
        b.edge(previous, check, handle)
        exits.extend(make_branch(platform, check, col + 1, row))
        previous, handle = check, "false"
    b.node("tk_unsupported", "notify", {"zh": "TikHub 这一路不认这个平台", "en": "TikHub route can't take this platform"},
           col + 1, len(TIKHUB_PLATFORMS), {
               "title": b.text("没有开始分析:TikHub 这一路不支持这个平台", "Analysis not started: the TikHub route doesn't cover this platform"),
               "body": b.text(
                   "认出的平台是「{{link.platform}}」。TikHub 这一路接了抖音、小红书、B站;别的平台在开始节点的"
                   "数据来源(data_source)里改选「内嵌浏览器」再运行。认错了的话,在开始节点的 platform 里写明平台。",
                   "The platform was read as “{{link.platform}}”. The TikHub route covers Douyin, Xiaohongshu and"
                   " Bilibili; for anything else pick “Built-in browser” as the data source (data_source) on the start node"
                   " and run again. If the platform was misread, name it in the start node's platform.",
               ),
           })
    b.edge(previous, "tk_unsupported", handle)
    return exits


def _tikhub_call(b: _Builder, node_id: str, platform: str, need: str, name: dict[str, str], col: float, row: float) -> str:
    tool, inputs = TIKHUB_CALLS[platform][need]
    return b.node(node_id, "plugin_tool", name, col, row, {
        "plugin_id": TIKHUB_PLUGIN, "tool_name": tool, "instance_id": "", "input": dict(inputs),
    })


#: B 站评论接口那一支取到的比平台显示的少时,说的是哪一种(见读页面脚本的第 6 条)。
def _comment_gap_notes(b: _Builder) -> dict[str, str]:
    return {
        "login": b.text(
            "没登录:B 站对未登录的访问只给前 3 条一级评论、每条下前 20 条回复。要取全,在「用内嵌浏览器打开」上把会话方式"
            "换成浏览器池、选一个已登录 B 站的档案。",
            "Not signed in: Bilibili shows signed-out visitors only the first 3 top-level comments and the first 20 replies"
            " under each. To fetch them all, switch “Open in the built-in browser” to the browser pool and pick a profile"
            " signed in to Bilibili.",
        ),
        "limit": b.text("到了这次最多取的条数,后面的没有再取。", "Stopped at this run's comment limit; the rest weren't fetched."),
        "time": b.text("到了这次取数的时间上限,后面的没有再取。", "Stopped at this run's time limit for fetching; the rest weren't fetched."),
        "platform": b.text("其余的 B 站没有给(被删除、折叠或仅自己可见的评论)。",
                           "Bilibili didn't return the rest (deleted, folded or private comments)."),
    }


#: 评论类模板读页面的脚本上限,以及留给接口那一支翻页的时间(要落在上限之内,余下的给读 DOM 那条路兜底)。
_COMMENT_READ_TIMEOUT_MS = 120000
_COMMENT_FETCH_BUDGET_MS = 90000


def _browser_read(b: _Builder, *, col: float, row: float, scrolls: int, max_chars: int, expand_replies: int = 0,
                  comment_max: int = 0) -> None:
    """打开 → 读页面文字 → 关掉。会话默认是具名的「自媒体分析」(登录跨次保留);要登录的平台在
    「打开浏览器」上改成浏览器池、选一个已登录的档案。

    `comment_max` 给了就是评论类模板:接口那一支最多取这么多条、按时间预算翻页,取不全时用哪几句话说明。"""
    b.node("web_open", "browser_open", {"zh": "用内嵌浏览器打开", "en": "Open in the built-in browser"}, col, row, {
        "url": "{{link.url}}", "session_mode": "named", "session_name": b.text("自媒体分析", "Social analysis"),
    })
    b.edge("use_tikhub", "web_open", "false")
    b.node("web_read", "browser_evaluate", {"zh": "往下滚几屏,读出页面文字", "en": "Scroll and read the page text"},
           col + 1, row, {
               "session": "{{web_open.session}}",
               "expression": _READ_PAGE_SCRIPT,
               "input": {"settle_ms": 2500, "scrolls": scrolls, "pause_ms": 1200, "max_chars": max_chars,
                      "expand_max": expand_replies,
                      **({"comment_max": comment_max, "budget_ms": _COMMENT_FETCH_BUDGET_MS, "page_pause_ms": 400,
                          "notes": _comment_gap_notes(b)} if comment_max else {})},
               **({"timeout_ms": _COMMENT_READ_TIMEOUT_MS} if comment_max else {}),
           })
    b.edge("web_open", "web_read")
    b.node("web_close", "browser_close", {"zh": "关掉浏览器", "en": "Close the browser"}, col + 2, row + 0.8, {
        "session": "{{web_read.session}}",
    })
    b.edge("web_read", "web_close")


def _api_coverage(b: _Builder, col: float, row: float) -> str:
    """B 站评论接口那一支:平台显示多少条、这次取到多少(一级 / 楼中楼)、没取全的原因。写进汇合的数据,
    跟着进报告、进笔记 —— 取到 3 条就别让人以为分析的是全部 396 条。"""
    b.node("web_api_coverage", "template", {"zh": "评论取到多少", "en": "How many comments came back"}, col, row, {
        "template": b.text(
            "评论条数:平台显示 {{web_read.value.total}} 条,这次取到 {{web_read.value.fetched}} 条"
            "(一级 {{web_read.value.fetched_roots}} 条、楼中楼 {{web_read.value.fetched_replies}} 条)。{{web_read.value.gap_note}}",
            "Comment count: the platform shows {{web_read.value.total}}; this run fetched {{web_read.value.fetched}}"
            " ({{web_read.value.fetched_roots}} top-level, {{web_read.value.fetched_replies}} replies). {{web_read.value.gap_note}}",
        ),
    })
    b.edge("web_is_api", "web_api_coverage", "true")
    return "web_api_coverage"


def _escaped_comments(platform: str) -> dict[str, str]:
    """B 站评论接口交回的原文是 HTML 转义过的(实测:「'」写成 &#39;,用户截图里笔记上显示的就是这一串):
    整理它的节点解一次。TikHub 那一路的 B 站评论是同一个接口的原样转发。别的平台的原文没转义,不能解。"""
    return {"unescape_html": "yes"} if platform == "bilibili" else {}


def _merge(b: _Builder, node_id: str, name: dict[str, str], col: float, row: float, template: str, sources: list[str]) -> str:
    """汇合:几支里只有一支跑过,没跑的那几支引用出来是空串。"""
    b.node(node_id, "template", name, col, row, {"template": template})
    for source in sources:
        b.edge(source, node_id)
    return node_id


def _joined(node_ids: list[str], output: str) -> str:
    return "".join(f"{{{{{one}.{output}}}}}" for one in node_ids)


def _report_language(locale: str | None) -> str:
    return pick_text({"zh": "中文", "en": "English"}, locale)


# --------------------------------------------------------------------------------------
# 1 · 账号运营诊断
# --------------------------------------------------------------------------------------


def _account_page_schema() -> dict[str, Any]:
    return _object({
        "account": _object({
            "name": _string(), "handle": _string("平台上的账号 / 号码"), "bio": _string(),
            "followers": _COUNT, "following": _COUNT, "likes_total": _COUNT, "posts_total": _COUNT,
        }),
        "posts": {"type": "array", "items": _object(_post_fields()), "maxItems": 60},
        "login_wall": {"type": "boolean"},
        "notes": _string("页面上异常的地方:登录墙、只显示了一部分、看不出时间……没有就空字符串"),
    })


def _account_report_schema() -> dict[str, Any]:
    return _object({
        "title": _string("笔记标题:带上账号名和「运营诊断」"),
        "verdict": _string("一句话结论"),
        "report_markdown": _string("完整报告,Markdown"),
    })


_ACCOUNT_REPORT_SYSTEM = """你是资深的自媒体运营顾问。你会收到一个账号的资料、最近作品的统计指标和逐条作品数据。
指标是代码算好的(发布频率、时段分布、互动率、头部作品、最近一半对之前一半的变化),直接引用,不要自己重算或改数。

写一份运营诊断:
- verdict:一句话结论(这个号现在处在什么状态、最该做的一件事)。
- report_markdown 用二级标题分成这几节:
  1. 现状概览:粉丝、发布频率与稳定性、发布时段、互动水平;
  2. 内容支柱:把作品按题材聚成 3–6 类,每类写条数、代表作品、表现比平均好还是差;
  3. 做得好的;
  4. 问题(断更、时段、题材分散、钩子弱、互动结构失衡……有数据支撑才写);
  5. 增长 / 衰退信号:结合「最近一半 vs 之前一半」,说清在涨还是在掉、可能为什么;
  6. 可执行建议:5–8 条,每条写清做什么、多久做一次、用哪个指标看效果;
  7. 数据局限:样本多少条、哪些字段取不到、浏览器那一路的数字是页面上的约数。
- 只根据给到的数据下结论;没给的数(粉丝画像、完播率、收入)不要编,缺就说缺。
- 用户写了关心的问题就单独一节回应。
- 用{{start.report_language}}写。
只输出符合 JSON Schema 的对象。"""


def account_analysis_graph(*, chat: Any, locale: str | None = None) -> dict[str, Any]:
    """账号链接 → 认平台 → TikHub(按平台)或浏览器取资料与最近作品 → 统一整理算指标 → 写运营诊断存成笔记。"""
    b = _Builder(chat, locale)
    b.node("start", "start", {"zh": "填账号与数据来源", "en": "Account and data source"}, 0, 2.5, {
        "params": {
            #: 这两格留空:空着运行前就拦(required_params)。要填什么写在模板卡片上。
            "account_link": "",
            "data_source": "",
            "platform": "",
            "post_count": 30,
            "focus": "",
            "report_language": _report_language(locale),
        },
        "required_params": ["account_link", "data_source"],
        #: 数据来源只能从这两项里选(面板上是下拉),默认空着 —— 让用的人自己挑。
        "param_options": {"data_source": _data_source_options(b, TIKHUB_ACCOUNT)},
    })
    _source_switch(b, link_param="account_link", expect="account")

    def branch(platform: str, check: str, col: float, row: float) -> list[str]:
        short, names = _SHORT[platform], _PLATFORM_NAMES[platform]
        profile = _tikhub_call(b, f"{short}_profile", platform, "profile",
                               {"zh": f"TikHub 取{names['zh']}账号资料", "en": f"TikHub: {names['en']} profile"}, col, row)
        b.edge(check, profile, "true")
        posts = _tikhub_call(b, f"{short}_posts", platform, "posts",
                             {"zh": f"TikHub 取{names['zh']}最近作品", "en": f"TikHub: {names['en']} recent posts"}, col + 1, row)
        b.edge(profile, posts)
        metrics = b.node(f"{short}_metrics", "social_metrics", {"zh": f"整理{names['zh']}作品并算指标", "en": f"Tidy {names['en']} posts and metrics"},
                         col + 2, row, {
                             "data": f"{{{{{posts}.output}}}}", "kind": "posts", "profile": f"{{{{{profile}.output}}}}",
                             "limit": "{{start.post_count}}", "duration_unit": _DURATION_UNIT[platform],
                         })
        b.edge(posts, metrics)
        return [metrics]

    tikhub_exits = _platform_chain(b, branch, col=4)

    _browser_read(b, col=4, row=4.2, scrolls=6, max_chars=30000)
    b.llm("web_struct", {"zh": "把页面文字抄成账号资料和作品清单", "en": "Turn the page text into a profile and post list"},
          6, 4.2,
          system="你会收到内嵌浏览器打开一个自媒体账号主页后读到的页面文字,里面可能夹着导航、推荐、登录提示。"
                 "把这个账号的资料和页面上能看到的每一条作品整理出来。\n" + _TRANSCRIBE_RULES,
          prompt="平台(可能为空):{{link.platform}}\n主页:{{link.url}}\n读取时间:{{web_read.value.now}}\n"
                 "页面标题:{{web_read.value.title}}\n\n页面文字:\n{{web_read.value.text}}",
          schema_name="account_page", schema=_account_page_schema(), max_tokens=12000, temperature=0.1)
    b.edge("web_read", "web_struct")
    b.node("web_metrics", "social_metrics", {"zh": "整理页面上的作品并算指标", "en": "Tidy the page's posts and metrics"}, 7, 4.2, {
        "data": "{{web_struct.json.posts}}", "kind": "posts", "profile": "{{web_struct.json.account}}",
        "limit": "{{start.post_count}}",
    })
    b.edge("web_struct", "web_metrics")

    metrics = [*tikhub_exits, "web_metrics"]
    _merge(b, "data_block", {"zh": "汇合这一路的数据", "en": "Collect the data from whichever route ran"}, 8, 2.5,
           _joined(metrics, "summary") + "\n\n### " + b.text("作品明细", "Posts") + "\n\n" + _joined(metrics, "table"),
           metrics)
    #: 几支的条数拼在一起 —— 只有走过的那一支有数(「0」或「27」),没走的是空串。
    b.node("has_posts", "condition", {"zh": "取到作品了吗", "en": "Were any posts fetched?"}, 9, 2.5, {
        "left": _joined(metrics, "count"), "op": "gt", "right": "0",
    })
    b.edge("data_block", "has_posts")
    b.node("no_posts_notice", "notify", {"zh": "没取到作品", "en": "No posts fetched"}, 10, 4, {
        "title": b.text("账号分析没有完成:一条作品都没取到", "Account analysis stopped: no posts were fetched"),
        "body": b.text(
            "{{link.url}} 没取到作品。常见原因:要登录才看得到(小红书一定要、抖音多半要 —— 在「用内嵌浏览器打开」上改用"
            "浏览器池里已登录的档案);链接不是主页;账号没有公开作品;TikHub 的工具没勾选或额度用完。{{web_struct.json.notes}}",
            "No posts came back for {{link.url}}. Usual causes: the page needs a sign-in (Xiaohongshu always, Douyin mostly"
            " — switch “Open in the built-in browser” to a signed-in browser-pool profile); the link isn't a profile;"
            " the account has no public posts; the TikHub tools aren't enabled or the quota ran out. {{web_struct.json.notes}}",
        ),
    })
    b.edge("has_posts", "no_posts_notice", "false")
    b.llm("report", {"zh": "写运营诊断", "en": "Write the diagnosis"}, 10, 2.5,
          system=_ACCOUNT_REPORT_SYSTEM,
          prompt="平台:{{link.platform}}\n账号主页:{{link.url}}\n数据来源:{{start.data_source}}\n"
                 "用户关心的问题(可能为空):{{start.focus}}\n\n{{data_block.text}}",
          schema_name="account_diagnosis", schema=_account_report_schema(), max_tokens=10000)
    b.edge("has_posts", "report", "true")
    b.node("save_note", "note_create", {"zh": "存成笔记", "en": "Save as a note"}, 11, 2.5, {
        "title": "{{report.json.title}}",
        "markdown": "> {{report.json.verdict}}\n\n{{report.json.report_markdown}}\n\n---\n\n## "
                    + b.text("附:关键数据", "Appendix: the numbers") + "\n\n{{data_block.text}}",
        "tags": b.text("账号分析", "account analysis"),
    })
    b.edge("report", "save_note")
    b.node("done_notice", "notify", {"zh": "诊断完成通知", "en": "Diagnosis ready"}, 12, 2.5, {
        "title": b.text("账号运营诊断已存成笔记", "The account diagnosis is saved as a note"),
        "body": "{{report.json.verdict}}",
    })
    b.edge("save_note", "done_notice")
    b.node("output", "output", {"zh": "交付诊断与数据", "en": "Hand over the diagnosis and data"}, 13, 2.5, {
        "values": {
            "note_id": "{{save_note.note_id}}",
            "verdict": "{{report.json.verdict}}",
            "report": "{{report.json.report_markdown}}",
            "platform": "{{link.platform}}",
            "data": "{{data_block.text}}",
        },
    })
    b.edge("done_notice", "output")
    return b.graph(ACCOUNT_ANALYSIS)


# --------------------------------------------------------------------------------------
# 2 · 单条视频爆款拆解
# --------------------------------------------------------------------------------------


def _video_page_schema() -> dict[str, Any]:
    return _object({
        "video": _object({**_post_fields(), "author": _string(), "description": _string("简介 / 文案 / 话题标签")}),
        "comments": {"type": "array", "items": _comment_schema(), "maxItems": 80},
        "login_wall": {"type": "boolean"},
        "notes": _string("页面上异常的地方;没有就空字符串"),
    })


def _breakdown_schema() -> dict[str, Any]:
    return _object({
        "title": _string("笔记标题:带上视频标题和「爆款拆解」"),
        "verdict": _string("一句话:它火的核心原因"),
        "report_markdown": _string("完整拆解,Markdown"),
        "script_outline_markdown": _string("照这个套路做一条的脚本提纲,Markdown"),
    })


_BREAKDOWN_SYSTEM = """你是短视频爆款拆解专家。你会收到一条视频的数据(代码算好的)、赞最多的评论,以及带时间码的口播逐字稿
(下载或转写不成功时为空)。拆解它为什么火,再给一份照这个套路做一条的脚本提纲。

- verdict:一句话说清它火的核心原因。
- report_markdown 用二级标题分成这几节:
  1. 数据表现:互动率、收藏 / 转发 / 评论各占多少,说明了什么(收藏多 = 有用,转发多 = 社交货币,评论多 = 争议或共鸣);
  2. 选题:为什么这个题有人看,击中了谁的什么需求;
  3. 钩子(前 3 秒):引用逐字稿开头的原话分析;没有逐字稿就根据标题、简介和评论推断,并写明是推断;
  4. 结构与节奏:按时间段拆,每段起什么作用、在哪里转折;
  5. 情绪点:哪些地方让人想点赞、评论、转发,用评论原文佐证(""" + _QUOTE_RULE.rstrip("。") + """);
  6. 标题与封面文案:用了什么手法;
  7. 评论区反馈:大家在夸什么、问什么、争什么;
  8. 可复用的套路:3–5 条,写成可以照做的规则;
  9. 不能照搬的部分与风险(账号势能、时效、平台规则)。
- script_outline_markdown:照这个套路做一条新的,主题围绕「{{start.my_topic}}」(为空就挑同领域的一个题):
  3 个标题备选、前 3 秒钩子台词、分段脚本(时间 / 画面 / 台词)、结尾引导。
- 只根据给到的材料下结论;没给的数据不要编。数据里「评论条数」那句说了评论取到多少、平台显示多少:只取到一部分时,
  评论区反馈那一节写明是从取到的这些里看的。
- 用{{start.report_language}}写。
只输出符合 JSON Schema 的对象。"""


def viral_video_breakdown_graph(*, chat: Any, locale: str | None = None) -> dict[str, Any]:
    """视频链接 → 认平台 → TikHub(按平台)或浏览器取详情和评论 → 整理 →(可选)下载 → 转写口播 → 拆解 → 笔记。

    关键帧没有抽:工作流里还没有「看画面」的节点。拆解按标题、简介、评论和带时间码的逐字稿做,报告里会写明。
    """
    b = _Builder(chat, locale)
    b.node("start", "start", {"zh": "填视频与数据来源", "en": "Video and data source"}, 0, 2.5, {
        "params": {
            "video_link": "",
            "data_source": "",
            "platform": "",
            "comment_count": 30,
            "download_video": "yes",
            "my_topic": "",
            "report_language": _report_language(locale),
        },
        "required_params": ["video_link", "data_source"],
        "param_options": {"data_source": _data_source_options(b, TIKHUB_VIDEO)},
    })
    _source_switch(b, link_param="video_link", expect="video")

    def branch(platform: str, check: str, col: float, row: float) -> list[str]:
        short, names = _SHORT[platform], _PLATFORM_NAMES[platform]
        video = _tikhub_call(b, f"{short}_video", platform, "video",
                             {"zh": f"TikHub 取{names['zh']}视频详情", "en": f"TikHub: {names['en']} video details"}, col, row)
        b.edge(check, video, "true")
        comments = _tikhub_call(b, f"{short}_comments", platform, "comments",
                                {"zh": f"TikHub 取{names['zh']}评论", "en": f"TikHub: {names['en']} comments"}, col, row + 0.45)
        b.edge(check, comments, "true")
        video_m = b.node(f"{short}_video_m", "social_metrics", {"zh": "整理视频数据", "en": "Tidy the video's numbers"}, col + 1, row, {
            "data": f"{{{{{video}.output}}}}", "kind": "posts", "limit": 1, "duration_unit": _DURATION_UNIT[platform],
        })
        b.edge(video, video_m)
        comments_m = b.node(f"{short}_comments_m", "social_metrics", {"zh": "按赞排好评论", "en": "Rank the comments"},
                            col + 1, row + 0.45, {
                                "data": f"{{{{{comments}.output}}}}", "kind": "comments", "limit": "{{start.comment_count}}",
                                **_escaped_comments(platform),
                            })
        b.edge(comments, comments_m)
        return [video_m, comments_m]

    tikhub_exits = _platform_chain(b, branch, col=4)

    _browser_read(b, col=4, row=4.2, scrolls=8, max_chars=40000, expand_replies=6, comment_max=1000)
    #: 读页面那段脚本在 B 站视频页上优先调它自己的接口(mode=api),交回的是视频数据和评论清单,不是页面文字 ——
    #: 直连整理;只有 DOM 读来的页面文字才需要模型抄写(和评论区洞察同一个分法)。
    b.node("web_is_api", "condition", {"zh": "是接口取的吗", "en": "Came from the site API?"}, 5.6, 4.2, {
        "left": "{{web_read.value.mode}}", "op": "equals", "right": "api",
    })
    b.edge("web_read", "web_is_api")
    b.node("web_api_video_m", "social_metrics", {"zh": "整理接口取回的视频数据", "en": "Tidy the API video numbers"}, 6.6, 3.6, {
        "data": "{{web_read.value.video}}", "kind": "posts", "limit": 1, "duration_unit": "seconds",
    })
    b.edge("web_is_api", "web_api_video_m", "true")
    b.node("web_api_comments_m", "social_metrics", {"zh": "整理接口取回的评论", "en": "Tidy the API comments"}, 6.6, 4.0, {
        "data": "{{web_read.value.text}}", "kind": "comments", "limit": "{{start.comment_count}}", **_escaped_comments("bilibili"),
    })
    b.edge("web_is_api", "web_api_comments_m", "true")
    coverage = _api_coverage(b, 6.6, 4.3)
    b.llm("web_struct", {"zh": "把页面文字抄成视频数据和评论", "en": "Turn the page text into video data and comments"},
          6, 4.6,
          system="你会收到内嵌浏览器打开一条自媒体视频 / 笔记后读到的页面文字(往下滚过,评论区可能在里面)。"
                 "把这条视频的数据和页面上能看到的评论整理出来(评论原文一字不改,最多 80 条,赞多的优先)。\n" + _TRANSCRIBE_RULES,
          prompt="平台(可能为空):{{link.platform}}\n视频:{{link.url}}\n读取时间:{{web_read.value.now}}\n"
                 "页面标题:{{web_read.value.title}}\n\n页面文字:\n{{web_read.value.text}}",
          schema_name="video_page", schema=_video_page_schema(), max_tokens=12000, temperature=0.1)
    b.edge("web_is_api", "web_struct", "false")
    b.node("web_video_m", "social_metrics", {"zh": "整理视频数据", "en": "Tidy the video's numbers"}, 7, 4.6, {
        "data": "{{web_struct.json.video}}", "kind": "posts", "limit": 1,
    })
    b.edge("web_struct", "web_video_m")
    b.node("web_comments_m", "social_metrics", {"zh": "按赞排好评论", "en": "Rank the comments"}, 7, 5.05, {
        "data": "{{web_struct.json.comments}}", "kind": "comments", "limit": "{{start.comment_count}}",
    })
    b.edge("web_struct", "web_comments_m")

    video_ids = [one for one in tikhub_exits if one.endswith("_video_m")] + ["web_api_video_m", "web_video_m"]
    comment_ids = [one for one in tikhub_exits if one.endswith("_comments_m")] + ["web_api_comments_m", "web_comments_m"]
    _merge(b, "data_block", {"zh": "汇合这一路的数据", "en": "Collect the data from whichever route ran"}, 8, 2.5,
           _joined(video_ids, "summary") + "\n\n### " + b.text("视频明细", "Video") + "\n\n" + _joined(video_ids, "table")
           + "\n\n" + _joined(comment_ids, "summary") + "\n" + _joined([coverage], "text") + "\n\n"
           + _joined(comment_ids, "table"),
           video_ids + comment_ids + [coverage])
    b.node("has_video", "condition", {"zh": "取到这条视频了吗", "en": "Was the video found?"}, 9, 2.5, {
        "left": _joined(video_ids, "count"), "op": "gt", "right": "0",
    })
    b.edge("data_block", "has_video")
    b.node("no_video_notice", "notify", {"zh": "没取到这条视频", "en": "Video not found"}, 10, 4.2, {
        "title": b.text("爆款拆解没有完成:没取到这条视频的数据", "Breakdown stopped: the video's data couldn't be fetched"),
        "body": b.text(
            "{{link.url}} 没取到数据。常见原因:要登录才看得到(在「用内嵌浏览器打开」上改用浏览器池里已登录的档案);"
            "链接不是单条作品;TikHub 的工具没勾选或额度用完。{{web_struct.json.notes}}",
            "No data came back for {{link.url}}. Usual causes: it needs a sign-in (switch “Open in the built-in browser”"
            " to a signed-in browser-pool profile); the link isn't a single post; the TikHub tools aren't enabled or the quota"
            " ran out. {{web_struct.json.notes}}",
        ),
    })
    b.edge("has_video", "no_video_notice", "false")

    #: 下载 → 转写是**可选**的一段:下不到(要登录、被限流)时数据和评论照样拆,报告里说明少了口播。
    b.node("want_download", "condition", {"zh": "要下载视频转写口播吗", "en": "Download and transcribe?"}, 10, 1.3, {
        "left": "{{start.download_video}}", "op": "not_equals", "right": "no",
    })
    b.edge("has_video", "want_download", "true")
    b.node("download", "import_url", {"zh": "下载视频进素材库", "en": "Download the video"}, 11, 1.3, {
        "url": "{{link.url}}", "kind": "video", "profile_id": "", "max_height": 720, "fail_on_error": "no",
    })
    b.edge("want_download", "download", "true")
    b.node("got_video", "condition", {"zh": "下到了吗", "en": "Downloaded?"}, 12, 1.3, {
        "left": "{{download.asset_id}}", "op": "not_empty",
    })
    b.edge("download", "got_video")
    b.node("transcript", "transcribe_asset", {"zh": "转写口播(带时间码)", "en": "Transcribe the speech with timecodes"}, 13, 1.3, {
        "asset_id": "{{download.asset_id}}",
    })
    b.edge("got_video", "transcript", "true")
    b.node("transcript_section", "template", {"zh": "逐字稿附在笔记后", "en": "Attach the transcript"}, 14, 1.3, {
        "template": "## " + b.text("口播逐字稿", "Transcript") + "\n\n{{transcript.text}}",
    })
    b.edge("transcript", "transcript_section")

    b.llm("breakdown", {"zh": "拆解爆款原因并写脚本提纲", "en": "Break down why it worked and outline a script"}, 14, 2.5,
          system=_BREAKDOWN_SYSTEM,
          prompt="视频:{{link.url}}\n平台:{{link.platform}}\n数据来源:{{start.data_source}}\n\n{{data_block.text}}\n\n"
                 "口播逐字稿(带时间码 JSON,可能为空):\n{{transcript.timed_text}}\n\n"
                 "没有逐字稿的原因(可能为空):{{download.error}}",
          schema_name="viral_breakdown", schema=_breakdown_schema(), max_tokens=12000, temperature=0.4)
    b.edge("has_video", "breakdown", "true")
    b.node("save_note", "note_create", {"zh": "存成笔记", "en": "Save as a note"}, 15, 2.5, {
        "title": "{{breakdown.json.title}}",
        "markdown": "> {{breakdown.json.verdict}}\n\n{{breakdown.json.report_markdown}}\n\n## "
                    + b.text("照这个套路做一条", "Make one the same way") + "\n\n{{breakdown.json.script_outline_markdown}}"
                    + "\n\n---\n\n## " + b.text("附:关键数据", "Appendix: the numbers") + "\n\n{{data_block.text}}"
                    + "\n\n{{transcript_section.text}}",
        "tags": b.text("爆款拆解", "viral breakdown"),
    })
    b.edge("breakdown", "save_note")
    b.node("done_notice", "notify", {"zh": "拆解完成通知", "en": "Breakdown ready"}, 16, 2.5, {
        "title": b.text("爆款拆解已存成笔记", "The breakdown is saved as a note"),
        "body": "{{breakdown.json.verdict}}",
    })
    b.edge("save_note", "done_notice")
    b.node("output", "output", {"zh": "交付拆解与脚本提纲", "en": "Hand over the breakdown and outline"}, 17, 2.5, {
        "values": {
            "note_id": "{{save_note.note_id}}",
            "verdict": "{{breakdown.json.verdict}}",
            "report": "{{breakdown.json.report_markdown}}",
            "script_outline": "{{breakdown.json.script_outline_markdown}}",
            "video_asset_id": "{{download.asset_id}}",
            "transcript": "{{transcript.text}}",
        },
    })
    b.edge("done_notice", "output")
    #: 第 3 版:浏览器那一路在 B 站上走接口(mode=api)时直接整理接口交回的视频数据和评论,不再交给模型当页面文字抄。
    #: 第 4 版:B 站评论接口翻全一级和楼中楼,汇合的数据里写明取到多少 / 平台显示多少(旧图的脚本只翻 15 页、不翻楼中楼)。
    return b.graph(VIRAL_VIDEO_BREAKDOWN, version=4)


# --------------------------------------------------------------------------------------
# 3 · 评论区洞察
# --------------------------------------------------------------------------------------


def _comments_page_schema() -> dict[str, Any]:
    return _object({
        "title": _string("这条作品的标题"),
        "comment_total": _string("页面上显示的评论总数,照页面原样抄(「1.2万」也照抄);页面上没有就空字符串"),
        "comments": {"type": "array", "items": _comment_schema(), "maxItems": 150},
        "login_wall": {"type": "boolean"},
        "notes": _string("页面上异常的地方;没有就空字符串"),
    })


#: 分批分析的提示词:每一批只做「观察」,不下结论 —— 结论是综合那一步的事。
_BATCH_SYSTEM = (
    "你是用户研究助手,负责读完一批评论并留下紧凑的观察笔记。只根据给到的这批评论说话:\n"
    "- 这批在聊什么(话题 + 条数);\n"
    "- 大家在问什么、哪里不满、哪里惊喜;\n"
    "- 值得回复的评论(高赞的问题、误解、负面),写出建议回复;\n"
    "- 值得原样引用的金句(抄原文)。\n"
    + _QUOTE_RULE + "\n"
    "用户写了关心的问题就优先回应它。只输出符合 JSON Schema 的对象。"
)


def _batch_schema() -> dict[str, Any]:
    return _object({
        "notes_markdown": _string("这一批的观察笔记,紧凑 markdown"),
        "standout_comments": {"type": "array", "items": _string("值得原样引用的评论原文"),
                              "description": "最多 8 条"},
    })


def _insight_schema() -> dict[str, Any]:
    return _object({
        "title": _string("笔记标题:带上作品标题和「评论区洞察」"),
        "verdict": _string("一句话:评论区最值得注意的事"),
        "report_markdown": _string("完整洞察,Markdown"),
        "reply_suggestions_markdown": _string("值得回复的评论与建议回复,Markdown"),
    })


_INSIGHT_SYSTEM = """你是用户研究和社区运营专家。你会收到:一份按赞排的整体统计,以及**分批覆盖这次取到的全部评论**的
分析笔记(评论太多装不下一次读完时,分批读过再交给你综合)。以分批笔记为准,统计用来校准比例。
数据开头「评论条数」那句写着这次取到多少、平台显示多少:取到的比平台少时,在 report_markdown 开头如实写明只分析了
取到的这些、为什么没取全,结论按这批评论下,不要说成全部评论;取全了就不必提。做评论区洞察。

- verdict:一句话,评论区最值得注意的事。
- report_markdown 用二级标题分成这几节:
  1. 大家在聊什么:按话题聚类,每类写条数和 1–2 条代表评论原文;
  2. 观众画像:从用词、关心的事推断年龄段、身份、所处阶段,每一条写明依据,并注明是推断;
  3. 需求与痛点;
  4. 疑问清单:大家在问什么,哪些值得单独做一条内容回答(用自己的话概括成问题时不加「」,要引原话就逐字摘);
  5. 异议与负面:说了什么、有多少、建议怎么回应;
  6. 情绪分布:正面 / 中性 / 负面的大致比例(注明是估计);
  7. 下一条可以做什么:3–5 个选题,每个写清依据的是哪几条评论。
- reply_suggestions_markdown:挑 5–10 条最值得回复的评论(高赞的问题、误解、负面),写出建议回复,语气真诚、不抬杠。
- 只引用给到的评论原文,不要编评论;样本少就明说结论的把握有限。
- """ + _QUOTE_RULE + """
- 用户写了关心的问题就单独一节回应。
- 用{{start.report_language}}写。
只输出符合 JSON Schema 的对象。"""


def comment_insights_graph(*, chat: Any, locale: str | None = None) -> dict[str, Any]:
    """作品链接 → 认平台 → TikHub(按平台)或浏览器取评论 → 按赞排好 → 评论区洞察 → 笔记。"""
    b = _Builder(chat, locale)
    b.node("start", "start", {"zh": "填作品与数据来源", "en": "Post and data source"}, 0, 2.5, {
        "params": {
            "video_link": "",
            "data_source": "",
            "platform": "",
            #: 附表按赞给前这么几条;分析覆盖抓到的**全部**(分批喂模型)。TikHub 一路一次一页,
            #: 浏览器一路已知平台直接翻它的接口。
            "comment_count": 50,
            "focus": "",
            "report_language": _report_language(locale),
        },
        "required_params": ["video_link", "data_source"],
        "param_options": {"data_source": _data_source_options(b, TIKHUB_COMMENTS)},
    })
    _source_switch(b, link_param="video_link", expect="video")

    def branch(platform: str, check: str, col: float, row: float) -> list[str]:
        short, names = _SHORT[platform], _PLATFORM_NAMES[platform]
        comments = _tikhub_call(b, f"{short}_comments", platform, "comments",
                                {"zh": f"TikHub 取{names['zh']}评论", "en": f"TikHub: {names['en']} comments"}, col, row)
        b.edge(check, comments, "true")
        ranked = b.node(f"{short}_comments_m", "social_metrics", {"zh": "按赞排好评论", "en": "Rank the comments"}, col + 1, row, {
            "data": f"{{{{{comments}.output}}}}", "kind": "comments",
            "limit": "2000", "table_limit": "{{start.comment_count}}", **_escaped_comments(platform),
        })
        b.edge(comments, ranked)
        return [ranked]

    tikhub_exits = _platform_chain(b, branch, col=4)

    #: 评论区的预算给足:310 条评论的页面正文约 5 万字符,楼中楼展开后更多;条数上限由模型那步收口。
    #: 接口那一路一次要翻几十页、再逐楼翻楼中楼,带着自己的脚本上限和翻页时间预算(见 _browser_read)。
    _browser_read(b, col=4, row=4.2, scrolls=7, max_chars=120000, expand_replies=8, comment_max=2000)
    #: 接口回来的已经是结构化清单,再让模型抄一遍只会丢条(实测 106 条抄丢成 71)——
    #: 接口路直连整理;只有 DOM 读来的页面文字才需要模型抄写。
    b.node("web_is_api", "condition", {"zh": "是接口取的吗", "en": "Came from the site API?"}, 5.6, 4.2, {
        "left": "{{web_read.value.mode}}", "op": "equals", "right": "api",
    })
    b.edge("web_read", "web_is_api")
    b.node("web_api_m", "social_metrics", {"zh": "整理接口取回的评论", "en": "Tidy the API comments"}, 6.6, 4.0, {
        "data": "{{web_read.value.text}}", "kind": "comments",
        "limit": "2000", "table_limit": "{{start.comment_count}}", **_escaped_comments("bilibili"),
    })
    b.edge("web_is_api", "web_api_m", "true")
    api_coverage = _api_coverage(b, 6.6, 4.3)
    b.llm("web_struct", {"zh": "把页面文字抄成评论清单", "en": "Turn the page text into a comment list"}, 6.6, 4.6,
          system="你会收到内嵌浏览器打开一条自媒体作品、往下滚过评论区之后读到的页面文字。"
                 "把这条作品的标题和页面上能看到的每一条评论整理出来(原文一字不改,赞多的优先;"
                 "回复楼里的也算,但不要把推荐视频的标题当成评论)。\n" + _TRANSCRIBE_RULES,
          prompt="平台(可能为空):{{link.platform}}\n作品:{{link.url}}\n读取时间:{{web_read.value.now}}\n"
                 "页面标题:{{web_read.value.title}}\n\n页面文字:\n{{web_read.value.text}}",
          schema_name="comments_page", schema=_comments_page_schema(), max_tokens=16000, temperature=0.1)
    b.edge("web_is_api", "web_struct", "false")
    b.node("web_comments_m", "social_metrics", {"zh": "按赞排好评论", "en": "Rank the comments"}, 7.6, 4.6, {
        "data": "{{web_struct.json.comments}}", "kind": "comments",
        "limit": "2000", "table_limit": "{{start.comment_count}}",
    })
    b.edge("web_struct", "web_comments_m")
    #: 读页面那一路只看得到页面上已经加载出来的评论:说清读到几条、页面显示的总数是多少。
    b.node("web_dom_coverage", "template", {"zh": "评论读到多少", "en": "How many comments were read"}, 8.2, 4.6, {
        "template": b.text(
            "评论条数:这次从页面上读到 {{web_comments_m.count}} 条,只包括页面上已经加载出来的那些,不是全部"
            "(页面上显示的总数:{{web_struct.json.comment_total}})。",
            "Comment count: this run read {{web_comments_m.count}} from the page, only the ones the page had loaded, not all"
            " of them (total shown on the page: {{web_struct.json.comment_total}}).",
        ),
    })
    b.edge("web_comments_m", "web_dom_coverage")

    ranked = [*tikhub_exits, "web_api_m", "web_comments_m"]
    coverage = _joined([api_coverage, "web_dom_coverage"], "text")
    _merge(b, "data_block", {"zh": "汇合这一路的评论", "en": "Collect the comments from whichever route ran"}, 8, 2.5,
           coverage + "\n\n" + _joined(ranked, "summary") + "\n\n### " + b.text("全部评论(按赞排)", "All comments (by likes)")
           + "\n\n" + _joined(ranked, "table"), [*ranked, api_coverage, "web_dom_coverage"])
    b.node("has_comments", "condition", {"zh": "取到评论了吗", "en": "Were any comments fetched?"}, 9, 2.5, {
        "left": _joined(ranked, "count"), "op": "gt", "right": "0",
    })
    b.edge("data_block", "has_comments")
    b.node("no_comments_notice", "notify", {"zh": "没取到评论", "en": "No comments fetched"}, 10, 4.2, {
        "title": b.text("评论区洞察没有完成:一条评论都没取到", "Comment insights stopped: no comments were fetched"),
        "body": b.text(
            "{{link.url}} 没取到评论。常见原因:要登录才看得到评论(小红书一定要 —— 在「用内嵌浏览器打开」上改用浏览器池里已登录的档案);"
            "作品关了评论或还没有评论;TikHub 的工具没勾选或额度用完。{{web_struct.json.notes}}",
            "No comments came back for {{link.url}}. Usual causes: comments need a sign-in (always on Xiaohongshu — switch"
            " “Open in the built-in browser” to a signed-in browser-pool profile); comments are off or there are none"
            " yet; the TikHub tools aren't enabled or the quota ran out. {{web_struct.json.notes}}",
        ),
    })
    b.edge("has_comments", "no_comments_notice", "false")

    #: 分析覆盖抓到的**全部**评论:五个来源只跑一支,items 引用出来其余四支是空串,拼起来就是那一支的
    #: JSON(as_text 把列表写成 JSON;见 graph_rules)。拆批 → 逐批出笔记 → 综合,模型上下文装不下时也不丢评论。
    b.node("all_items", "template", {"zh": "汇合全部评论", "en": "Collect every comment"}, 9, 2.5, {
        "template": _joined(ranked, "items"),
    })
    b.edge("has_comments", "all_items", "true")
    b.node("chunks", "list_chunk", {"zh": "拆成几批", "en": "Split into batches"}, 9, 3.1, {
        "items": "{{all_items.text}}", "size": 80,
    })
    b.edge("all_items", "chunks")
    b.node("batch_analyze", "loop_foreach", {"zh": "逐批分析", "en": "Analyse batch by batch"}, 9, 3.7, {
        "items": "{{chunks.batches}}",
        "concurrency": 2,
        #: 循环体的作用域只有 loop / item / input —— 作品链接和用户关心的问题经 inputs 带进去。
        "inputs": {"url": "{{link.url}}", "focus": "{{start.focus}}"},
        "body": {"nodes": [{
            "id": "batch_notes",
            "type": "llm",
            "name": {"zh": "分析这一批", "en": "Analyse this batch"},
            "position": {"x": 80, "y": 120},
            "config": {
                "profile_id": getattr(chat, "profile_id", ""),
                "model": getattr(chat, "model", ""),
                "preset": "precise",
                "system": _BATCH_SYSTEM,
                "prompt": "作品:{{input.url}}\n用户关心的问题(可能为空):{{input.focus}}\n\n这一批评论(JSON):\n{{loop.item}}",
                "response_format": "json_schema",
                "json_schema_name": "comment_insights_batch",
                "json_schema": _batch_schema(),
                "json_schema_strict": "true",
                "temperature": 0.3,
                "max_tokens": 6000,
            },
        }], "edges": []},
        "output": "{{batch_notes.json.notes_markdown}}",
    })
    b.edge("chunks", "batch_analyze")
    b.llm("insight", {"zh": "综合各批,做评论区洞察", "en": "Synthesize the batch notes"}, 10, 2.5,
          system=_INSIGHT_SYSTEM,
          prompt="作品:{{link.url}}\n平台:{{link.platform}}\n标题(可能为空):{{web_struct.json.title}}{{web_read.value.title}}\n"
                 "用户关心的问题(可能为空):{{start.focus}}\n\n按赞排的整体情况:\n{{data_block.text}}\n\n"
                 "分批分析笔记(覆盖了全部评论,JSON 数组,逐条是一份笔记):\n{{batch_analyze.results}}",
          schema_name="comment_insights", schema=_insight_schema(), max_tokens=12000, temperature=0.3)
    b.edge("batch_analyze", "insight")
    b.node("save_note", "note_create", {"zh": "存成笔记", "en": "Save as a note"}, 11, 2.5, {
        "title": "{{insight.json.title}}",
        "markdown": "> {{insight.json.verdict}}\n\n" + coverage + "\n\n{{insight.json.report_markdown}}\n\n## "
                    + b.text("建议回复", "Suggested replies") + "\n\n{{insight.json.reply_suggestions_markdown}}"
                    + "\n\n---\n\n## " + b.text("附:评论数据", "Appendix: the comments") + "\n\n{{data_block.text}}",
        "tags": b.text("评论区洞察", "comment insights"),
    })
    b.edge("insight", "save_note")
    b.node("done_notice", "notify", {"zh": "洞察完成通知", "en": "Insights ready"}, 12, 2.5, {
        "title": b.text("评论区洞察已存成笔记", "The comment insights are saved as a note"),
        "body": "{{insight.json.verdict}}\n" + coverage,
    })
    b.edge("save_note", "done_notice")
    b.node("output", "output", {"zh": "交付洞察与建议回复", "en": "Hand over the insights and replies"}, 13, 2.5, {
        "values": {
            "note_id": "{{save_note.note_id}}",
            "verdict": "{{insight.json.verdict}}",
            "report": "{{insight.json.report_markdown}}",
            "replies": "{{insight.json.reply_suggestions_markdown}}",
        },
    })
    b.edge("done_notice", "output")
    #: 第 3 版:B 站评论接口翻全一级和楼中楼,结果里写明取到多少 / 平台显示多少(旧图的脚本只翻 15 页、不翻楼中楼,
    #: 洞察的提示词还说「所有评论都被读过了」)。
    return b.graph(COMMENT_INSIGHTS, version=3)


# --------------------------------------------------------------------------------------
# 模板库卡片
# --------------------------------------------------------------------------------------

#: 数据来源两条里满足一条就够 —— 前置检查按组判(见 template_requirements.requirement 的 group)。
_SOURCE = "data_source"


def _browser_requirement(*, comments: bool) -> dict[str, Any]:
    if comments:
        return requirement(
            None, group=_SOURCE,
            zh="或者用内嵌浏览器取数(不花钱,不用连接):小红书看评论一定要登录、抖音多半要 —— 在「用内嵌浏览器打开」"
               "上把会话方式改成浏览器池、选一个已登录的档案;B站不登录只给前 3 条一级评论(每条下前 20 条回复),"
               "要取全评论同样换成已登录 B 站的档案。结果里会写明取到多少、平台显示多少",
            en="Or fetch with the built-in browser (free, no connection): Xiaohongshu comments always need a sign-in and"
               " Douyin's mostly do — switch “Open in the built-in browser” to the browser pool and pick a signed-in"
               " profile; signed out, Bilibili gives only the first 3 top-level comments (and 20 replies under each), so"
               " use a profile signed in to Bilibili to fetch them all. The result says how many came back and how many"
               " the platform shows",
        )
    return requirement(
        None, group=_SOURCE,
        zh="或者用内嵌浏览器取数(不花钱,不用连接):小红书一定要登录、抖音多半要 —— 在「用内嵌浏览器打开」上把会话方式"
           "改成浏览器池、选一个已登录的档案;B站不用登录。页面上的数字是约数,发布时间常常缺",
        en="Or fetch with the built-in browser (free, no connection): Xiaohongshu always needs a sign-in and Douyin mostly"
           " does — switch “Open in the built-in browser” to the browser pool and pick a signed-in profile; Bilibili"
           " needs none. Numbers on the page are rounded and publish times are often missing",
    )


def _tikhub_requirement(check: str) -> dict[str, Any]:
    return requirement(
        check, group=_SOURCE,
        zh="TikHub 取数(按次计费、字段全、不用登录):TikHub 插件的连接(一个平台一条),并在插件页勾选这些工具 —— "
           + _tool_list(check),
        en="Fetch with TikHub (billed per call, complete fields, no sign-in): a TikHub plugin connection (one per platform)"
           " with these tools enabled on the plugins page — " + _tool_list_en(check),
    )


ANALYSIS_TEMPLATE_CATALOG: list[dict[str, Any]] = [
    {
        "id": ACCOUNT_ANALYSIS,
        "name": {"zh": "自媒体账号运营诊断", "en": "Social account health check"},
        "summary": {
            "zh": "贴一个抖音、小红书或 B站账号的主页链接,取账号资料和最近 30 条作品(发布时间、文案、时长、播放 / 点赞 / 评论 / 收藏 / 转发),"
                  "由代码算出发布频率、发布时段分布、互动率、头部作品和「最近一半对之前一半」的增长 / 衰退信号,再写一份运营诊断"
                  "(现状、内容支柱、做得好的、问题、可执行建议)存成笔记,附关键数据表。数据来源在开始节点的下拉里二选一:"
                  "内嵌浏览器(不用配置、不花钱,小红书 / 抖音要换成已登录的浏览器档案,其他平台也能用,数字是页面上的约数)"
                  "或 TikHub(要装插件、填密钥,每次运行 2 次请求、每次约 0.001 美元起,以 TikHub 账单为准;字段全、更稳、不用登录)。"
                  "另有 1–2 次 AI 对话(浏览器那一路多一次整理页面)。",
            "en": "Paste a Douyin, Xiaohongshu or Bilibili profile link to fetch the profile and the latest 30 posts (publish time,"
                  " caption, length, views / likes / comments / saves / shares). Code works out posting frequency, posting-time"
                  " distribution, engagement rate, top posts and a recent-half-vs-earlier-half growth or decline signal, then a"
                  " diagnosis (where it stands, content pillars, what works, problems, concrete next steps) is saved as a note with"
                  " the key numbers attached. Pick the data source from the start node's drop-down: the built-in browser (nothing to"
                  " set up and free; Xiaohongshu / Douyin need a signed-in browser profile, other platforms work too, and the"
                  " numbers are the page's rounded ones) or TikHub (needs the plugin and an API key; 2 calls per run, from about"
                  " $0.001 each — see your TikHub bill; complete fields, steadier, no sign-in)."
                  " Plus one or two AI chat calls (one more on the browser route to read the page).",
        },
        "requires": [
            requirement(CHAT_MODEL, zh="AI 对话模型", en="Chat model"),
            _tikhub_requirement(TIKHUB_ACCOUNT),
            _browser_requirement(comments=False),
            requirement(None, zh="一个账号主页链接(或账号编号 + 平台)", en="A profile link (or an account id plus the platform)"),
        ],
        "stages": {
            "zh": ["填主页链接、选数据来源(内嵌浏览器或 TikHub),可选平台和关心的问题", "认出平台和账号编号",
                   "TikHub 按平台取资料与作品,或浏览器打开主页、滚动读出页面", "整理作品、算频率 / 时段 / 互动率 / 趋势",
                   "写运营诊断", "存成笔记(附数据表)"],
            "en": ["Profile link and the data source (built-in browser or TikHub), optionally the platform and your question",
                   "Work out the platform and account id", "TikHub fetches profile and posts per platform, or the browser reads the page",
                   "Tidy the posts; frequency, timing, engagement and trend", "Write the diagnosis", "Save as a note with the numbers"],
        },
    },
    {
        "id": VIRAL_VIDEO_BREAKDOWN,
        "name": {"zh": "自媒体视频爆款拆解", "en": "Why a video went viral"},
        "summary": {
            "zh": "贴一条抖音、小红书或 B站视频的链接,取视频数据和赞最多的评论,下载视频、转写带时间码的口播,拆解它为什么火"
                  "(选题、前 3 秒钩子、结构节奏、情绪点、标题封面、评论区反馈、可复用的套路),并给一份「照这个套路做一条」的脚本提纲,"
                  "存成笔记。数据来源在开始节点的下拉里二选一:内嵌浏览器(不用配置、不花钱,要登录的平台换成已登录的浏览器档案)"
                  "或 TikHub(要装插件、填密钥,每次运行 2 次请求、每次约 0.001 美元起;字段全、更稳、不用登录)。"
                  "下载用的是素材库的「从链接导入」(抖音一般要在「下载视频进素材库」上选已登录的浏览器档案),下不到时照样按数据和评论拆;"
                  "转写在本机跑;另有 1–2 次 AI 对话。暂不看画面(没有抽关键帧)。",
            "en": "Paste a Douyin, Xiaohongshu or Bilibili video link to fetch its numbers and most-liked comments, download it and"
                  " transcribe the speech with timecodes, then break down why it worked (topic, the first-three-second hook,"
                  " structure and pacing, emotional beats, title and cover, comment feedback, reusable patterns) and outline a"
                  " script to make one the same way, saved as a note. Pick the data source from the start node's drop-down: the"
                  " built-in browser (nothing to set up and free; switch to a signed-in browser profile where needed) or TikHub"
                  " (needs the plugin and an API key; 2 calls per run, from about $0.001 each; complete fields, steadier, no"
                  " sign-in). The download uses the"
                  " library's Import from link (Douyin usually needs a signed-in browser profile on the download step); if it"
                  " fails, the breakdown still runs on the numbers and comments. Transcription runs locally; plus one or two AI"
                  " chat calls. Frames are not looked at yet.",
        },
        "requires": [
            requirement(CHAT_MODEL, zh="AI 对话模型", en="Chat model"),
            _tikhub_requirement(TIKHUB_VIDEO),
            _browser_requirement(comments=True),
            requirement(TRANSCRIPTION_ENGINE, zh="拆口播可选:转写引擎", en="Optional for the speech: a transcription engine", optional=True),
            requirement(None, zh="一条视频链接(或作品编号 + 平台)", en="A video link (or a post id plus the platform)"),
        ],
        "stages": {
            "zh": ["填视频链接、选数据来源(内嵌浏览器或 TikHub),可选你想做的主题", "认出平台和作品编号",
                   "TikHub 按平台取详情与评论,或浏览器打开、滚到评论区读出页面", "整理视频数据、评论按赞排好",
                   "可选:下载视频、转写口播", "拆解爆款原因、写脚本提纲", "存成笔记"],
            "en": ["Video link and the data source (built-in browser or TikHub), optionally a topic of your own", "Work out the platform and post id",
                   "TikHub fetches details and comments per platform, or the browser reads the page down to the comments",
                   "Tidy the numbers, rank the comments", "Optional: download and transcribe", "Break it down and outline a script",
                   "Save as a note"],
        },
    },
    {
        "id": COMMENT_INSIGHTS,
        "name": {"zh": "评论区洞察与观众画像", "en": "Comment insights and audience"},
        "summary": {
            "zh": "贴一条作品链接,取赞最多的一批评论(默认 50 条:TikHub 一次取一页,约 20–50 条;浏览器往下滚着读评论区),按话题聚类,"
                  "推断观众画像、需求与痛点、疑问清单、异议与情绪分布,给出下一条可以做的选题和值得回复的评论的建议回复,存成笔记。"
                  "数据来源在开始节点的下拉里二选一:内嵌浏览器(不用配置、不花钱,小红书评论要换成已登录的浏览器档案)"
                  "或 TikHub(要装插件、填密钥,每次运行 1 次请求;字段全、更稳、不用登录)。另有 1–2 次 AI 对话。",
            "en": "Paste a post link to fetch its most-liked comments (50 by default: one page via TikHub, about 20–50; the"
                  " browser scrolls through the comment section), group them by topic, infer the audience, needs and pain points, open questions, objections and"
                  " sentiment, suggest next topics and replies to the comments worth answering, saved as a note. Pick the data"
                  " source from the start node's drop-down: the built-in browser (nothing to set up and free; Xiaohongshu"
                  " comments need a signed-in browser profile) or TikHub (needs the plugin and an API key; 1 call per run;"
                  " complete fields, steadier, no sign-in). Plus one or two AI chat calls.",
        },
        "requires": [
            requirement(CHAT_MODEL, zh="AI 对话模型", en="Chat model"),
            _tikhub_requirement(TIKHUB_COMMENTS),
            _browser_requirement(comments=True),
            requirement(None, zh="一条作品链接(或作品编号 + 平台)", en="A post link (or a post id plus the platform)"),
        ],
        "stages": {
            "zh": ["填作品链接、选数据来源(内嵌浏览器或 TikHub),可选关心的问题", "认出平台和作品编号",
                   "TikHub 按平台取评论,或浏览器滚动读出评论区", "评论按赞排好", "做评论区洞察、写建议回复", "存成笔记"],
            "en": ["Post link and the data source (built-in browser or TikHub), optionally your question", "Work out the platform and post id",
                   "TikHub fetches comments per platform, or the browser reads the comment section", "Rank the comments by likes",
                   "Analyse the comments, draft replies", "Save as a note"],
        },
    },
]
