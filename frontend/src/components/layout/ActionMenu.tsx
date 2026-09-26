import { MENU_ITEM, MENU_ITEM_DESTRUCTIVE, MENU_SEPARATOR } from "@/components/ui/floating";
import { Fragment, type KeyboardEvent, type ReactNode } from "react";
import { MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ContextMenuItem, ContextMenuSeparator } from "@/components/ui/context-menu";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export type MenuAction = {
  label: string;
  /** 必填:同一个菜单里有的行有图标、有的没有,文字就对不齐(浏览器池卡片的「重命名」漏过一次)。 */
  icon: ReactNode;
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
export function ActionMenu({
  label,
  actions,
  trigger,
  align = "end",
}: {
  label: string;
  actions: MenuAction[];
  /**
   * 换掉那颗 ⋯(画板操作条上的「生成 ▾」)。得是一个接得住 ref 的按钮,自己带 `aria-label` /
   * `aria-haspopup`;条目、键盘、分组线还是这一份。
   */
  trigger?: ReactNode;
  align?: "start" | "center" | "end";
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        {trigger ?? (
          <Button variant="ghost" size="icon-sm" aria-label={label} title={label} aria-haspopup="menu"><MoreHorizontal /></Button>
        )}
      </PopoverTrigger>
      <PopoverContent
        align={align}
        role="menu"
        aria-label={label}
        className="grid w-auto min-w-48 gap-0.5 p-1.5"
        onKeyDown={moveFocus}
      >
        {actions.map((action, i) => (
          <Fragment key={action.label}>
            {startsDestructiveGroup(actions, i) && <div className={MENU_SEPARATOR} role="separator" />}
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

/** 第一个破坏性条目前面(且前面还有别的)才画分组线 —— ⋯ 菜单和右键菜单同一条规则。 */
function startsDestructiveGroup(actions: MenuAction[], i: number): boolean {
  return Boolean(actions[i].destructive) && i > 0 && !actions[i - 1].destructive;
}

/**
 * 同一份动作清单画成右键菜单的条目,放进调用方自己的 `<ContextMenuContent>`。
 *
 * 卡片的 ⋯ 和右键菜单此前是两份手抄的清单:浏览器池卡片右键的「重命名」漏了图标,
 * 工作流卡片右键的条目不跟着 ⋯ 那边变灰。**清单只写一份**,两个菜单都从它画。
 */
export function ActionContextMenuItems({ actions }: { actions: MenuAction[] }) {
  return (
    <>
      {actions.map((action, i) => (
        <Fragment key={action.label}>
          {startsDestructiveGroup(actions, i) && <ContextMenuSeparator />}
          <ContextMenuItem
            className={cn(action.destructive && MENU_ITEM_DESTRUCTIVE)}
            disabled={action.disabled}
            onSelect={action.onSelect}
          >
            {action.icon}
            <span className="min-w-0 flex-1 truncate">{action.label}</span>
            {action.hint && <span className="shrink-0 pl-4 text-ui-xs tabular-nums text-muted-foreground">{action.hint}</span>}
          </ContextMenuItem>
        </Fragment>
      ))}
    </>
  );
}
