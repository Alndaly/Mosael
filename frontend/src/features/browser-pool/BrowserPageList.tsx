import React from "react";
import { Globe, PanelLeftClose, PanelLeftOpen, Plus, X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { HintRegion } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { APP_CHROME } from "@/components/ui/appChrome";
import { isImeKeystroke } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

import { moveBefore } from "./pageListState";
import { usePageListMotion } from "./usePageListMotion";

type Page = NonNullable<PublishViewState["pages"]>[number];

/** 展开时多宽、收起成图标条时多宽(像素)。原生网页视图从这个位置往右铺。 */
export const PAGE_LIST_WIDTH = 220;
export const PAGE_LIST_COLLAPSED_WIDTH = 48;
const NOTICE_MS = 6_000;

/**
 * 浏览器会话左侧的**页面列表**(像 Arc 左边那一列):这个会话开着的每一页 —— 网站图标、标题,悬停看网址;
 * 当前页高亮,点哪页切哪页;单页可关(只剩一页时不关),拖动排顺序;可以收起成一条图标;顶上「新建页面」。
 * 收起时鼠标停上去、键盘切进来,列表临时展开盖在网页上,移开就收回;「收起」本身记在本机。展开、收起、临时展开
 * 都带过渡,原生网页视图在过渡期间由一张画面替着(见 usePageListMotion)。
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
  const [adding, setAdding] = React.useState(false);
  const [address, setAddress] = React.useState("");
  const [dragging, setDragging] = React.useState<string | null>(null);
  // 拖的是哪一页也记在 ref 里:放下那一刻 state 可能还没轮到重渲染。
  const draggingRef = React.useRef<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const motion = usePageListMotion(bridge, adding);
  const { collapsed, shape, compact, snapshot } = motion;
  //: 网页左侧让出多宽:临时展开时也只让图标条那么宽 —— 列表盖在网页上,不推挤它。
  const inset = shape.collapsed ? PAGE_LIST_COLLAPSED_WIDTH : PAGE_LIST_WIDTH;
  const width = shape.collapsed && !shape.peek ? PAGE_LIST_COLLAPSED_WIDTH : PAGE_LIST_WIDTH;
  //: 画面盖着的时候,它的右沿钉在网页原来的右沿,左沿跟着网页该在的位置滑。
  const backdropRight = snapshot ? snapshot.bounds.x + snapshot.bounds.width : 0;
  const edge = useEdgeColor(snapshot?.frame ?? null);
  //: 列表右边就是原生网页视图(临时展开时是那张画面):说明夹在这一列里往下出,伸出去会被网页盖住。
  const hintRegion = React.useMemo(() => ({ area: { top, left: 0, width }, side: "bottom" as const }), [top, width]);

  React.useEffect(() => {
    void bridge.setPagesInset(inset);
  }, [bridge, inset]);
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

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const value = address.trim();
    if (!value) return;
    void bridge.newPage(value);
    setAddress("");
    setAdding(false);
    if (collapsed) motion.dismiss({ instant: true }); // 收回,让人看到新开的那一页
  };

  const drop = (movedId: string, targetId: string) => {
    const moved = movedId || draggingRef.current;
    draggingRef.current = null;
    setDragging(null);
    if (!moved || moved === targetId) return;
    void bridge.reorderPages(moveBefore(pages.map((page) => page.id), moved, targetId));
  };

  return (
    <>
      <nav
        {...APP_CHROME}
        ref={motion.ref}
        data-page-list={!shape.collapsed ? "expanded" : shape.peek ? "peek" : "collapsed"}
        aria-label={t("browserPagesTitle")}
        className={cn(
          "fixed bottom-0 left-0 z-[190] flex flex-col overflow-hidden border-r border-border bg-panel",
          shape.peek && "shadow-[var(--shadow-raised)]",
        )}
        style={{ top, width, transition: motion.transition("width") }}
        {...motion.handlers}
        onBlur={(event) => {
          motion.handlers.onBlur(event);
          // 临时展开时地址框也让它开着;焦点离开了列表,地址框就收起(不然列表收不回去)。
          if (collapsed && !event.currentTarget.contains(event.relatedTarget as Node | null)) setAdding(false);
        }}
        onKeyDown={(event) => {
          if (event.key !== "Escape" || !shape.peek || isImeKeystroke(event)) return;
          if ((event.target as HTMLElement).closest("[data-page-list-address]")) return; // 地址框自己处理 Esc
          motion.dismiss();
        }}
      >
        <HintRegion.Provider value={hintRegion}>
          <div className={cn("flex items-center gap-1 p-1.5", compact && "flex-col")}>
            {/* 收起时只剩一个加号;要看名字,鼠标停上去列表就展开了。展开时字就写在按钮上。 */}
            <button
              type="button"
              data-page-list-new
              className={cn(
                "inline-flex h-7 cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-2 text-ui-sm text-foreground hover:bg-secondary",
                compact ? "w-7 justify-center px-0" : "min-w-0 flex-1",
              )}
              aria-label={t("browserPagesNew")}
              aria-expanded={adding}
              onClick={() => setAdding((was) => !was)}
            >
              <Plus size={14} className="shrink-0" />
              {!compact && <Truncate>{t("browserPagesNew")}</Truncate>}
            </button>
            <IconButton
              unstyled
              type="button"
              data-page-list-toggle
              className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-muted-foreground hover:bg-secondary hover:text-foreground"
              label={t(!collapsed ? "browserPagesCollapse" : shape.peek ? "browserPagesPin" : "browserPagesExpand")}
              hint={collapsed && shape.peek ? t("browserPagesPinHint") : undefined}
              onClick={motion.toggle}
            >
              {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
            </IconButton>
          </div>

          {adding && !compact && (
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
                compact={compact}
                closable={pages.length > 1}
                dragging={dragging === page.id}
                untitled={t("browserPagesUntitled")}
                closeLabel={t("browserPagesClose")}
                onSelect={() => {
                  void bridge.switchPage(page.id);
                  if (collapsed) motion.dismiss({ instant: true }); // 收回,让人看到切过去的那一页
                }}
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
        </HintRegion.Provider>
      </nav>
      {/* 过渡和临时展开期间替着原生网页视图的那张画面:裁切框的右沿钉在网页原来的右沿,左沿跟着网页该在的位置滑;
          画面贴着左沿走,收起时右边空出来的那一截用画面边上的颜色补上。 */}
      {snapshot && (
        <div
          data-page-backdrop=""
          className="fixed z-[189] overflow-hidden select-none"
          style={{
            top: snapshot.bounds.y,
            height: snapshot.bounds.height,
            left: inset,
            width: Math.max(0, backdropRight - inset),
            background: edge ?? undefined,
            transition: motion.transition("left") === "none" ? "none" : `${motion.transition("left")}, ${motion.transition("width")}`,
          }}
        >
          <img
            key={snapshot.take}
            alt=""
            src={snapshot.frame}
            draggable={false}
            onLoad={motion.backdropReady}
            className="block max-w-none"
            style={{ width: snapshot.bounds.width, height: snapshot.bounds.height }}
          />
        </div>
      )}
    </>
  );
}

function PageRow({
  page,
  compact,
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
  compact: boolean;
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
      {/* 悬停、聚焦这一行时网址在标题下面露出来;只剩图标条时标题和网址都看不到 —— 停上去列表就展开了。 */}
      <button
        type="button"
        aria-current={page.current ? "page" : undefined}
        aria-label={compact ? title : undefined}
        className={cn(
          "flex min-w-0 flex-1 cursor-pointer items-center gap-2 border-0 bg-transparent py-1.5 text-left text-ui-sm",
          compact ? "justify-center px-0" : "px-2",
          page.current ? "font-medium text-foreground" : "text-muted-foreground group-hover:text-foreground",
        )}
        onClick={onSelect}
      >
        <Favicon src={page.favicon} />
        {!compact && (
          <span className="flex min-w-0 flex-col">
            <Truncate>{title}</Truncate>
            <Truncate className="hidden text-ui-xs text-muted-foreground group-focus-within:block group-hover:block">
              {page.url}
            </Truncate>
          </span>
        )}
      </button>
      {closable && !compact && (
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

/**
 * 画面右沿最常见的颜色(多数网页右边是底色)。收起时画面往左滑,右边空出来的那一截用它补上,看上去像网页本来的
 * 底色在延伸,而不是一条白边。取不到(没有 canvas)就不补。
 */
function useEdgeColor(frame: string | null): string | null {
  const [color, setColor] = React.useState<string | null>(null);
  React.useEffect(() => {
    setColor(null);
    if (!frame) return;
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = 1;
      canvas.height = 24;
      const context = canvas.getContext("2d");
      if (!context || !image.naturalWidth) return;
      context.drawImage(image, image.naturalWidth - 2, 0, 1, image.naturalHeight, 0, 0, 1, 24);
      const pixels = context.getImageData(0, 0, 1, 24).data;
      const counts = new Map<string, number>();
      for (let i = 0; i < pixels.length; i += 4) {
        const key = `rgb(${pixels[i]}, ${pixels[i + 1]}, ${pixels[i + 2]})`;
        counts.set(key, (counts.get(key) ?? 0) + 1);
      }
      setColor([...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null);
    };
    image.src = frame;
  }, [frame]);
  return color;
}

/** 网站图标;没有或取不到就画一个地球。 */
function Favicon({ src }: { src: string }) {
  const [broken, setBroken] = React.useState(false);
  if (!src || broken) return <Globe size={14} className="shrink-0 text-muted-foreground" />;
  return <img src={src} alt="" className="h-3.5 w-3.5 shrink-0 rounded-sm" onError={() => setBroken(true)} />;
}
