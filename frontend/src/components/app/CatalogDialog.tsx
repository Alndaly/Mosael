import React from "react";
import { ArrowLeft, Search } from "lucide-react";

import { ModalShell } from "@/components/app/modals";
import { CollectionTabs } from "@/components/layout/StudioPage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * 「逛一份目录、点开一条看清楚、再决定要不要」的弹窗 —— 插件市场和工作流社区共用这一个。
 *
 * 两边此前各长各的:市场是一列挤着的长条(说明整段铺开、权限码一排排),社区是左边一条窄列表
 * + 右边一块详情(详情大半空着,主操作在底栏,和选中的那一条隔着整个弹窗)。它们做的是同一件事,
 * 所以版式只有一份:
 *
 * 1. **卡片网格**。一张卡只回答「这是什么、我有没有、要不要」:图标、名字、一行来历、三行摘要、
 *    状态、主操作。列数跟着弹窗宽度走(auto-fill),不写断点。
 * 2. **点开是一页详情**,不是侧栏。侧栏要和网格分宽度,两边都窄;详情页拿到整个弹窗宽,
 *    宽时自己分成「正文 + 侧栏信息」两栏(容器查询,不看视口)。返回键和 Esc 都退回网格,
 *    并且**回到刚才那张卡**:滚动位置和键盘焦点都还原,不从头翻。
 *
 * 状态(加载 / 出错 / 空)由调用方给 —— 两份目录各有各的说法。
 */

/** 弹窗的尺寸:宽到能排三四列卡,高度固定 —— 网格和详情来回切时弹窗不跳。 */
const CATALOG_DIALOG =
  "w-[min(1120px,calc(100vw-32px))] max-w-none h-[min(820px,calc(100dvh-32px))] max-h-[calc(100dvh-32px)]";

export type CatalogFilter<F extends string> = { value: F; label: string; count?: number };

export function CatalogDialog<T, F extends string = string>({
  open,
  onOpenChange,
  title,
  description,
  searchLabel,
  query,
  onQueryChange,
  headerActions,
  filters,
  notice,
  items,
  itemKey,
  renderCard,
  placeholder,
  detail,
  onDetailChange,
  renderDetail,
  backLabel,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** 标题下面一句说明:这份目录是什么、从这里拿走的是什么。 */
  description?: string;
  searchLabel: string;
  query: string;
  onQueryChange: (query: string) => void;
  /** 搜索框右边的按钮(插件市场的「从链接安装」)。 */
  headerActions?: React.ReactNode;
  filters?: { label: string; value: F; onChange: (value: F) => void; items: CatalogFilter<F>[] };
  /** 网格上方的一条提示(插件市场:远端索引拉不到,下面只列出内置的)。详情页上不显示。 */
  notice?: React.ReactNode;
  /** 已经按搜索和筛选过滤好的条目。 */
  items: T[];
  itemKey: (item: T) => string;
  /** 一张卡。`open` 打开它的详情 —— 交给 CatalogCard 的 onOpen。 */
  renderCard: (item: T, open: () => void) => React.ReactNode;
  /** 没有卡可排时占住正文的那一块(加载、出错、空、搜不到)。有卡时不显示。 */
  placeholder?: React.ReactNode;
  /** 正在看的那一条;null = 在网格上。 */
  detail: T | null;
  onDetailChange: (id: string | null) => void;
  renderDetail: (item: T) => React.ReactNode;
  backLabel: string;
  /** 挂在弹窗里的二级弹窗(安装确认、卸载确认)。 */
  children?: React.ReactNode;
}) {
  const rootRef = React.useRef<HTMLDivElement>(null);
  const backRef = React.useRef<HTMLButtonElement>(null);
  //: 离开网格时它滚到哪儿、从哪张卡点进去的 —— 回来时原样还原。
  const gridScroll = React.useRef(0);
  const cameFrom = React.useRef<string | null>(null);
  const detailId = detail ? itemKey(detail) : null;

  const scroller = () => rootRef.current?.closest<HTMLElement>("[data-slot='modal-body']") ?? null;

  const openDetail = (id: string) => {
    gridScroll.current = scroller()?.scrollTop ?? 0;
    cameFrom.current = id;
    onDetailChange(id);
  };
  const back = () => onDetailChange(null);

  //: 切页之后:进详情 → 滚回顶、焦点给返回键(读屏从这一页的开头读起);回网格 → 还原滚动,
  //: 焦点回到刚才那张卡。**用 layout effect**:换页和还原滚动要在同一帧,不然先闪一下顶部。
  React.useLayoutEffect(() => {
    const body = scroller();
    if (detailId) {
      if (body) body.scrollTop = 0;
      backRef.current?.focus({ preventScroll: true });
      return;
    }
    if (body) body.scrollTop = gridScroll.current;
    const id = cameFrom.current;
    if (!id) return;
    const card = Array.from(rootRef.current?.querySelectorAll<HTMLElement>("[data-catalog-card]") ?? []).find(
      (one) => one.dataset.catalogCard === id,
    );
    card?.querySelector<HTMLElement>("[data-catalog-open]")?.focus({ preventScroll: true });
    // 只在换页时跑:详情里的内容变了(装好了、状态刷新了)不该把焦点拽回返回键。
  }, [detailId]);

  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      className={CATALOG_DIALOG}
      onEscapeKeyDown={(event) => {
        if (!detailId) return;
        event.preventDefault();
        back();
      }}
      header={
        detail ? (
          // 详情页的头只有一颗返回键:搜索和筛选作用于网格,在这一页上它们什么都不做。
          <div className="flex min-w-0 items-center">
            <Button ref={backRef} variant="ghost" className="-ml-3" onClick={back}>
              <ArrowLeft />
              {backLabel}
            </Button>
          </div>
        ) : (
          <div className="grid min-w-0 gap-3">
            {description && <p className="m-0 text-ui-sm font-normal leading-relaxed text-muted-foreground">{description}</p>}
            <div className="flex min-w-0 items-center gap-2">
              <label className="relative min-w-0 flex-1">
                <Search
                  size={14}
                  aria-hidden
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
                />
                <Input
                  className="pl-9"
                  placeholder={searchLabel}
                  aria-label={searchLabel}
                  value={query}
                  onChange={(event) => onQueryChange(event.target.value)}
                />
              </label>
              {headerActions}
            </div>
            {filters && (
              <CollectionTabs label={filters.label} value={filters.value} onChange={filters.onChange} items={filters.items} />
            )}
          </div>
        )
      }
    >
      <div ref={rootRef} className="min-h-full min-w-0">
        {!detail && notice && <div className="mb-3">{notice}</div>}
        {detail ? (
          renderDetail(detail)
        ) : items.length > 0 ? (
          <ul
            role="list"
            aria-label={title}
            className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(min(100%,264px),1fr))] gap-3 p-0 pb-1"
          >
            {items.map((item) => (
              <li key={itemKey(item)} className="grid min-w-0">
                {renderCard(item, () => openDetail(itemKey(item)))}
              </li>
            ))}
          </ul>
        ) : (
          <div className="grid min-h-[320px] place-items-center">{placeholder}</div>
        )}
      </div>
      {children}
    </ModalShell>
  );
}

/** 状态标记的几种语气。颜色只是第二信号 —— 每一种都带字。 */
export type CatalogTone = "success" | "warning" | "primary" | "muted";

const TONE: Record<CatalogTone, string> = {
  success: "bg-[color-mix(in_srgb,var(--success)_14%,transparent)] text-success",
  warning: "bg-[color-mix(in_srgb,var(--warning)_16%,transparent)] text-warning",
  primary: "bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary",
  muted: "bg-secondary text-muted-foreground",
};

export function CatalogBadge({
  tone,
  icon,
  children,
}: {
  tone: CatalogTone;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1 rounded-full px-2 text-ui-2xs font-semibold [&_svg]:size-3 [&_svg]:shrink-0",
        TONE[tone],
      )}
    >
      {icon}
      {children}
    </span>
  );
}

/** 卡片和详情页左上角那块图标底。 */
export function CatalogIcon({ children, size = "md" }: { children: React.ReactNode; size?: "md" | "lg" }) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] font-semibold text-primary",
        size === "lg" ? "size-14 rounded-xl text-ui-lg [&_svg]:size-6" : "size-10 rounded-lg text-ui-md [&_svg]:size-[18px]",
      )}
    >
      {children}
    </span>
  );
}

/**
 * 一张卡。**整张可点**(打开详情),而主操作是卡上另一颗独立的按钮。
 *
 * 按钮里不能再套按钮,所以「整张可点」是名字那颗按钮用一层 `after:` 盖满整张卡;主操作按钮
 * 抬到这层之上(`relative z-10`)。键盘上是两站:先到名字(回车看详情),再到主操作。
 */
export function CatalogCard({
  id,
  icon,
  title,
  meta,
  badge,
  summary,
  facts,
  action,
  onOpen,
}: {
  id: string;
  icon: React.ReactNode;
  title: string;
  /** 名字下面那一行小字:版本、作者、来源。 */
  meta?: React.ReactNode;
  /** 右上角的状态(已安装 / 有新版 / 已添加)。 */
  badge?: React.ReactNode;
  /** 纯文本摘要,截成三行 —— markdown 由调用方先摊平(`toPlainText`,见 components/markdown/inlineSyntax)。 */
  summary: string;
  /** 左下角一两条事实(几项权限、几个步骤、缺几样)。 */
  facts?: React.ReactNode;
  /** 右下角的主操作。 */
  action?: React.ReactNode;
  onOpen: () => void;
}) {
  return (
    <article
      data-catalog-card={id}
      className={cn(
        "relative grid min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_1fr_auto] gap-3 rounded-xl border border-border bg-panel p-4 transition-colors",
        "hover:border-border-strong hover:bg-panel-subtle",
        "has-[[data-catalog-open]:focus-visible]:border-primary has-[[data-catalog-open]:focus-visible]:ring-2 has-[[data-catalog-open]:focus-visible]:ring-ring",
      )}
    >
      <div className="flex min-w-0 items-start gap-3">
        <CatalogIcon>{icon}</CatalogIcon>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <h3 className="m-0 min-w-0 text-ui-sm font-semibold leading-snug text-foreground">
            <button
              type="button"
              data-catalog-open
              className="block max-w-full cursor-pointer truncate text-left after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none"
              onClick={onOpen}
            >
              {title}
            </button>
          </h3>
          {meta && <p className="m-0 min-w-0 truncate text-ui-xs text-muted-foreground">{meta}</p>}
        </div>
        {badge}
      </div>
      {/* 不能再加 `block`:line-clamp 靠的是 -webkit-box,block 会把它覆盖掉,摘要就整段铺开。 */}
      <p className="m-0 line-clamp-3 min-w-0 text-ui-xs leading-relaxed text-muted-foreground">{summary}</p>
      <div className="flex min-h-8 min-w-0 items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-3 text-ui-xs text-muted-foreground [&_svg]:size-3.5 [&_svg]:shrink-0">
          {facts}
        </span>
        {action && <span className="relative z-10 flex shrink-0 items-center gap-2">{action}</span>}
      </div>
    </article>
  );
}

/** 卡片左下角的一条事实:图标 + 一句短话。 */
export function CatalogFact({ icon, children, tone }: { icon: React.ReactNode; children: React.ReactNode; tone?: "warning" | "success" }) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1 truncate", tone === "warning" && "text-warning", tone === "success" && "text-success")}>
      {icon}
      <span className="truncate">{children}</span>
    </span>
  );
}

/**
 * 详情页。头部是这一条的身份 + **它的主操作**(操作贴着它作用的那个东西,不放到底栏),
 * 下面是正文;宽的时候右边另起一栏放「信息」类的东西(版本、作者、权限、前置条件)。
 */
export function CatalogDetail({
  icon,
  title,
  badges,
  meta,
  actions,
  aside,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  badges?: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <article className="@container/catalog-detail grid min-w-0 gap-6 pb-2">
      <header className="flex min-w-0 flex-wrap items-start gap-x-4 gap-y-3">
        <CatalogIcon size="lg">{icon}</CatalogIcon>
        <div className="grid min-w-0 flex-1 basis-[240px] gap-1">
          {badges && <div className="flex min-w-0 flex-wrap items-center gap-1.5">{badges}</div>}
          <h3 className="m-0 min-w-0 break-words text-ui-lg font-semibold leading-snug tracking-tight text-foreground">{title}</h3>
          {meta && <p className="m-0 min-w-0 text-ui-xs text-muted-foreground">{meta}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </header>
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-8 @3xl/catalog-detail:grid-cols-[minmax(0,1fr)_280px]">
        <div className="grid min-w-0 content-start gap-7">{children}</div>
        {aside && (
          <aside className="grid min-w-0 content-start gap-6 border-t border-divider pt-6 @3xl/catalog-detail:border-l @3xl/catalog-detail:border-t-0 @3xl/catalog-detail:pl-6 @3xl/catalog-detail:pt-0">
            {aside}
          </aside>
        )}
      </div>
    </article>
  );
}

/** 详情页里的一节:小标题 + 内容。 */
export function CatalogSection({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="grid min-w-0 gap-3">
      <h4 className="m-0 flex items-center gap-1.5 text-ui-sm font-semibold text-foreground">
        {title}
        {count !== undefined && <span className="text-ui-xs font-normal tabular-nums text-muted-foreground">{count}</span>}
      </h4>
      {children}
    </section>
  );
}
