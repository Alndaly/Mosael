import React from "react";
import { Search } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** 一行里放什么:行首认脸用的一小块(缩略图或图标)、名字、一行说明、行尾一小段附注(版本、时长、日期)。 */
export type PickRow = {
  lead: React.ReactNode;
  title: string;
  /** 一行纯文字 —— 调用方负责去掉 Markdown 这类记号,这里只管截断。 */
  subtitle?: string;
  meta?: string;
};

/**
 * 「从一份清单里挑一个」的弹窗:挑笔记、挑 3D 场景、挑素材都是这一个。
 *
 * 三处此前两个样子:笔记和场景是一张大卡一条(大图标、名字、两行原文、再一行日期),挑到第四条就得滚;
 * 素材是紧凑的一行一个。它们做的是同一件事,版式只有一份:
 *
 * - **搜索钉在头里**(ModalShell 的 header):它作用于下面整份清单,翻到第三十条时它还在原地。
 * - **一行一个**:行首一小块认脸,名字一行,说明一行(截断,不折成两三行把清单撑稀),附注靠右。
 * - **键盘能挑完**:打开就在搜索框里,↑↓ 换一行、回车挑;鼠标悬停和键盘选中是同一种高亮。
 *
 * 加载 / 出错 / 空由这里画,说法由调用方给。
 */
export function PickListDialog<T>({
  open,
  onOpenChange,
  title,
  description,
  searchLabel,
  query,
  onQueryChange,
  items,
  itemKey,
  row,
  onPick,
  pending,
  error,
  onRetry,
  empty,
  notice,
  className,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** 标题下面一句:挑了之后会怎样(「引用正文与来源版本」)。 */
  description?: string;
  searchLabel: string;
  query: string;
  onQueryChange: (query: string) => void;
  items: readonly T[];
  itemKey: (item: T) => string;
  row: (item: T) => PickRow;
  onPick: (item: T) => void;
  pending?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** 清单是空的时候:图标和一句话(没有匹配 / 一个都还没有,由调用方分)。 */
  empty: { icon: React.ReactNode; text: string };
  /** 清单下面一句(「只列了前 200 条,再搜细一点」)。 */
  notice?: string;
  className?: string;
}) {
  const t = useI18n();
  const [active, setActive] = React.useState(0);
  const list = React.useRef<HTMLDivElement | null>(null);
  //: 清单一换(搜了别的),高亮回到第一行 —— 停在第 7 行而清单只剩 3 行时,回车就挑不到东西。
  React.useEffect(() => setActive(0), [items]);
  React.useEffect(() => {
    list.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView?.({ block: "nearest" });
  }, [active]);

  const keys = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (!items.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((current) => (current + step + items.length) % items.length);
    } else if (event.key === "Enter" && !event.nativeEvent.isComposing) {
      event.preventDefault();
      const picked = items[Math.min(active, items.length - 1)];
      if (picked !== undefined) onPick(picked);
    }
  };

  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      className={cn("w-[min(560px,calc(100vw-32px))] h-[min(560px,calc(100dvh-32px))]", className)}
      header={
        <>
          {description ? <p className="m-0 text-ui-xs text-muted-foreground">{description}</p> : null}
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              autoFocus
              size="sm"
              className="pl-8"
              aria-label={searchLabel}
              placeholder={searchLabel}
              value={query}
              maxLength={300}
              onChange={(event) => onQueryChange(event.target.value)}
              onKeyDown={keys}
              aria-controls="pick-list"
            />
          </div>
        </>
      }
    >
      {pending ? (
        <div className="grid gap-1" aria-busy="true">
          {[0, 1, 2, 3, 4].map((n) => (
            <Skeleton key={n} className="h-12 rounded-md" />
          ))}
        </div>
      ) : error ? (
        <div role="alert" className="grid justify-items-center gap-2 py-10 text-center text-ui-sm text-muted-foreground">
          {error}
          {onRetry ? (
            <Button variant="ghost" size="sm" onClick={onRetry}>
              {t("retry")}
            </Button>
          ) : null}
        </div>
      ) : !items.length ? (
        <div className="grid justify-items-center gap-2 py-10 text-center text-ui-sm text-muted-foreground [&_svg]:opacity-70">
          {empty.icon}
          <span>{empty.text}</span>
        </div>
      ) : (
        <div ref={list} id="pick-list" role="listbox" aria-label={title} className="grid content-start gap-0.5">
          {items.map((item, index) => {
            const one = row(item);
            return (
              <button
                key={itemKey(item)}
                type="button"
                role="option"
                aria-selected={index === active}
                data-pick-row=""
                onMouseMove={() => index !== active && setActive(index)}
                onClick={() => onPick(item)}
                className="flex min-w-0 cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1.5 text-left transition-colors aria-selected:bg-secondary"
              >
                <span className="grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded bg-[color-mix(in_srgb,var(--foreground)_6%,transparent)] text-muted-foreground">
                  {one.lead}
                </span>
                <span className="grid min-w-0 flex-1 gap-0.5">
                  <span className="truncate text-ui-sm text-foreground">{one.title}</span>
                  {one.subtitle ? <span className="truncate text-ui-xs text-muted-foreground">{one.subtitle}</span> : null}
                </span>
                {one.meta ? (
                  <span className="shrink-0 self-start pt-0.5 text-ui-2xs tabular-nums text-muted-foreground">{one.meta}</span>
                ) : null}
              </button>
            );
          })}
          {notice ? <p className="m-0 px-1.5 pt-2 text-ui-xs text-muted-foreground">{notice}</p> : null}
        </div>
      )}
    </ModalShell>
  );
}
