import React from "react";
import { Globe, PanelLeftClose, PanelLeftOpen, Plus, X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { isImeKeystroke } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

import { moveBefore, readCollapsed, writeCollapsed } from "./pageListState";

type Page = NonNullable<PublishViewState["pages"]>[number];

/** 展开时多宽、收起成图标条时多宽(像素)。原生网页视图从这个位置往右铺。 */
export const PAGE_LIST_WIDTH = 220;
export const PAGE_LIST_COLLAPSED_WIDTH = 48;
const NOTICE_MS = 6_000;

/**
 * 浏览器会话左侧的**页面列表**(像 Arc 左边那一列):这个会话开着的每一页 —— 网站图标、标题,悬停看网址;
 * 当前页高亮,点哪页切哪页;单页可关(只剩一页时不关),拖动排顺序;可以收起成一条图标;顶上「新建页面」。
 *
 * 页面在新窗口打开(target=_blank、window.open)时会进这个列表并切过去,不再弹一个独立小窗(见
 * electron/publish/accountViews.openWindow)。列表是渲染层的 DOM,原生网页视图盖不住它 —— 所以挂着时
 * 告诉主进程左侧让出多宽(setPagesInset),卸载时还回去。
 */
export function BrowserPageList({ state, top }: { state: PublishViewState; top: number }) {
  const bridge = window.mosaelPublish;
  if (!bridge?.switchPage || !state.pages?.length) return null;
  return <PageList bridge={bridge} state={state} top={top} />;
}

function PageList({
  bridge,
  state,
  top,
}: {
  bridge: NonNullable<Window["mosaelPublish"]>;
  state: PublishViewState;
  top: number;
}) {
  const t = useI18n();
  const pages = React.useMemo(() => state.pages ?? [], [state.pages]);
  const [collapsed, setCollapsed] = React.useState(readCollapsed);
  const [adding, setAdding] = React.useState(false);
  const [address, setAddress] = React.useState("");
  const [dragging, setDragging] = React.useState<string | null>(null);
  // 拖的是哪一页也记在 ref 里:放下那一刻 state 可能还没轮到重渲染。
  const draggingRef = React.useRef<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const width = collapsed ? PAGE_LIST_COLLAPSED_WIDTH : PAGE_LIST_WIDTH;

  React.useEffect(() => {
    void bridge.setPagesInset(width);
  }, [bridge, width]);
  React.useEffect(() => () => void bridge.setPagesInset(0), [bridge]);

  // 开满了被拦下(新窗口、新建页面):说一句。挂上时已有的那次不算。
  const seenLimit = React.useRef(state.pageLimitHitAt ?? 0);
  React.useEffect(() => {
    const at = state.pageLimitHitAt ?? 0;
    if (at <= seenLimit.current) return;
    seenLimit.current = at;
    setNotice(t("browserPagesLimit").replace("{n}", String(state.pageLimit ?? 10)));
  }, [state.pageLimitHitAt, state.pageLimit, t]);
  React.useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const toggle = () => {
    setCollapsed((was) => {
      writeCollapsed(!was);
      return !was;
    });
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const value = address.trim();
    if (!value) return;
    void bridge.newPage(value);
    setAddress("");
    setAdding(false);
  };

  const drop = (movedId: string, targetId: string) => {
    const moved = movedId || draggingRef.current;
    draggingRef.current = null;
    setDragging(null);
    if (!moved || moved === targetId) return;
    void bridge.reorderPages(moveBefore(pages.map((page) => page.id), moved, targetId));
  };

  return (
    <nav
      data-page-list={collapsed ? "collapsed" : "expanded"}
      aria-label={t("browserPagesTitle")}
      className="fixed bottom-0 left-0 z-[190] flex flex-col border-r border-border bg-panel"
      style={{ top, width }}
    >
      <div className={cn("flex items-center gap-1 p-1.5", collapsed && "flex-col")}>
        {/* 收起时只剩一个加号,名字靠悬停说;展开时字就写在按钮上,不再重复。 */}
        <Hint label={collapsed ? t("browserPagesNew") : undefined} side="right">
          <button
            type="button"
            data-page-list-new
            className={cn(
              "inline-flex h-7 cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-2 text-ui-sm text-foreground hover:bg-secondary",
              collapsed ? "w-7 justify-center px-0" : "min-w-0 flex-1",
            )}
            aria-label={t("browserPagesNew")}
            aria-expanded={adding}
            onClick={() => {
              if (collapsed) toggle();
              setAdding((was) => !was);
            }}
          >
            <Plus size={14} className="shrink-0" />
            {!collapsed && <Truncate>{t("browserPagesNew")}</Truncate>}
          </button>
        </Hint>
        <IconButton
          unstyled
          type="button"
          data-page-list-toggle
          className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-muted-foreground hover:bg-secondary hover:text-foreground"
          label={t(collapsed ? "browserPagesExpand" : "browserPagesCollapse")}
          onClick={toggle}
        >
          {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
        </IconButton>
      </div>

      {adding && !collapsed && (
        <form className="px-1.5 pb-1.5" onSubmit={submit}>
          <Input
            autoFocus
            data-page-list-address
            value={address}
            spellCheck={false}
            placeholder={t("browserPagesNewPlaceholder")}
            onChange={(event) => setAddress(event.target.value)}
            onKeyDown={(event) => {
              if (isImeKeystroke(event)) return; // 输入法选词时的 Esc 是给输入法的
              if (event.key === "Escape") {
                setAdding(false);
                setAddress("");
              }
            }}
          />
        </form>
      )}

      <ul className="m-0 flex min-h-0 flex-1 list-none flex-col gap-0.5 overflow-y-auto p-1.5 pt-0">
        {pages.map((page) => (
          <PageRow
            key={page.id}
            page={page}
            collapsed={collapsed}
            closable={pages.length > 1}
            dragging={dragging === page.id}
            untitled={t("browserPagesUntitled")}
            closeLabel={t("browserPagesClose")}
            onSelect={() => void bridge.switchPage(page.id)}
            onClose={() => void bridge.closePage(page.id)}
            onDragStart={() => {
              draggingRef.current = page.id;
              setDragging(page.id);
            }}
            onDragEnd={() => {
              draggingRef.current = null;
              setDragging(null);
            }}
            onDrop={(movedId) => drop(movedId, page.id)}
          />
        ))}
      </ul>

      {notice && (
        <p role="status" data-page-list-notice className="m-1.5 rounded-md bg-secondary p-2 text-ui-xs text-foreground">
          {notice}
        </p>
      )}
    </nav>
  );
}

function PageRow({
  page,
  collapsed,
  closable,
  dragging,
  untitled,
  closeLabel,
  onSelect,
  onClose,
  onDragStart,
  onDragEnd,
  onDrop,
}: {
  page: Page;
  collapsed: boolean;
  closable: boolean;
  dragging: boolean;
  untitled: string;
  closeLabel: string;
  onSelect: () => void;
  onClose: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDrop: (movedId: string) => void;
}) {
  const title = page.title.trim() || untitled;
  return (
    <li
      data-page-row={page.id}
      data-current={page.current || undefined}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", page.id);
        onDragStart();
      }}
      onDragEnd={onDragEnd}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        onDrop(event.dataTransfer?.getData("text/plain") ?? "");
      }}
      className={cn(
        "group relative flex items-center rounded-md",
        page.current ? "bg-secondary" : "hover:bg-secondary",
        dragging && "opacity-50",
      )}
    >
      {/* 展开时悬停这一行,网址在标题下面露出来;收起时只剩网站图标,标题和网址都靠悬停说明。 */}
      <Hint label={collapsed ? title : undefined} hint={collapsed ? page.url : undefined} side="right">
      <button
        type="button"
        aria-current={page.current ? "page" : undefined}
        aria-label={collapsed ? title : undefined}
        className={cn(
          "flex min-w-0 flex-1 cursor-pointer items-center gap-2 border-0 bg-transparent py-1.5 text-left text-ui-sm",
          collapsed ? "justify-center px-0" : "px-2",
          page.current ? "font-medium text-foreground" : "text-muted-foreground group-hover:text-foreground",
        )}
        onClick={onSelect}
      >
        <Favicon src={page.favicon} />
        {!collapsed && (
          <span className="flex min-w-0 flex-col">
            <Truncate>{title}</Truncate>
            <Truncate className="hidden text-ui-xs text-muted-foreground group-hover:block">{page.url}</Truncate>
          </span>
        )}
      </button>
      </Hint>
      {closable && !collapsed && (
        <IconButton
          unstyled
          type="button"
          data-page-close
          label={closeLabel}
          className="mr-1 inline-flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded border-0 bg-transparent text-muted-foreground opacity-0 hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
          onClick={onClose}
        >
          <X size={12} />
        </IconButton>
      )}
    </li>
  );
}

/** 网站图标;没有或取不到就画一个地球。 */
function Favicon({ src }: { src: string }) {
  const [broken, setBroken] = React.useState(false);
  if (!src || broken) return <Globe size={14} className="shrink-0 text-muted-foreground" />;
  return <img src={src} alt="" className="h-3.5 w-3.5 shrink-0 rounded-sm" onError={() => setBroken(true)} />;
}
