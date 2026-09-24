import { MENU_ITEM, MENU_ITEM_DESTRUCTIVE, MENU_SEPARATOR } from "@/components/ui/floating";
import { Fragment, type KeyboardEvent, type ReactNode } from "react";
import { MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

type Action = {
  label: string;
  icon?: ReactNode;
  /** 行尾一小段弱化的附注(如「版本历史」后面的 `v29`)。不拼进 label:拼进去就和名字抢同一种字重。 */
  hint?: string;
  onSelect: () => void;
  destructive?: boolean;
  disabled?: boolean;
};

/**
 * 卡片 / 画布工具栏右端那颗 ⋯ 的菜单。
 *
 * 条目和右键菜单、笔记页「更多」是**同一套**:MENU_ITEM 的行高、内边距、图标尺寸与悬停底色,
 * 分组线是独立的 MENU_SEPARATOR 元素。此前这里是一排 ghost Button,分组靠给「删除」那一行
 * 补 `border-t` + `rounded-t-none` —— Button 自带一圈透明描边,悬停底色又只圆下面两个角,
 * 看上去「删除」被单独框在一个盒子里,和上面几行不是一种东西。
 *
 * **破坏性操作自动单独成组**:前面有别的条目时,第一个 destructive 条目前一定有分组线。
 * 这件事不交给调用方记 —— 工作流卡片的 ⋯ 就忘过,同一张卡的右键菜单却有线。
 *
 * 键盘:打开后焦点落在第一个可用条目;↑↓ 循环移动、Home/End 到两端,Enter/空格触发;
 * Esc 关闭,焦点回到 ⋯ 按钮(Radix Popover 的默认行为)。
 */
export function ActionMenu({ label, actions }: { label: string; actions: Action[] }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={label} title={label} aria-haspopup="menu"><MoreHorizontal /></Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        role="menu"
        aria-label={label}
        className="grid w-auto min-w-48 gap-0.5 p-1.5"
        onKeyDown={moveFocus}
      >
        {actions.map((action, i) => (
          <Fragment key={action.label}>
            {action.destructive && i > 0 && !actions[i - 1].destructive && <div className={MENU_SEPARATOR} role="separator" />}
            <PopoverClose asChild>
              <button
                type="button"
                role="menuitem"
                className={cn(MENU_ITEM, "w-full text-left", action.destructive && MENU_ITEM_DESTRUCTIVE)}
                disabled={action.disabled}
                onClick={action.onSelect}
              >
                {action.icon}
                <span className="min-w-0 flex-1 truncate">{action.label}</span>
                {action.hint && <span className="shrink-0 pl-4 text-ui-xs tabular-nums text-muted-foreground">{action.hint}</span>}
              </button>
            </PopoverClose>
          </Fragment>
        ))}
      </PopoverContent>
    </Popover>
  );
}

/** 菜单里的方向键:只在可用条目之间走(禁用的原生 button 本来就拿不到焦点),两端循环。 */
function moveFocus(event: KeyboardEvent<HTMLDivElement>) {
  const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')];
  if (items.length === 0) return;
  const at = items.indexOf(document.activeElement as HTMLButtonElement);
  const next =
    event.key === "ArrowDown" ? (at + 1) % items.length
    : event.key === "ArrowUp" ? (at <= 0 ? items.length - 1 : at - 1)
    : event.key === "Home" ? 0
    : event.key === "End" ? items.length - 1
    : null;
  if (next === null) return;
  event.preventDefault();
  items[next].focus();
}
