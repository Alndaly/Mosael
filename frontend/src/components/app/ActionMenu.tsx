import { Fragment, type ReactNode } from "react";
import { MoreHorizontal } from "lucide-react";
import { ContextMenuItem, ContextMenuSeparator } from "@/components/ui/context-menu";
import { MENU_ITEM_DESTRUCTIVE } from "@/components/ui/floating";
import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem, MenuItemBody, MenuSeparator } from "@/components/ui/menu";
import { Popover, PopoverClose, PopoverTrigger } from "@/components/ui/popover";
import type { HintShortcut } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type MenuAction = {
  label: string;
  /** 必填:同一个菜单里有的行有图标、有的没有,文字就对不齐(浏览器池卡片的「重命名」漏过一次)。 */
  icon: ReactNode;
  /** 名字下面一行淡色的补充说明(见 MenuItemBody 的 description)。 */
  description?: string;
  /** 名字是动态的长值(文件名、工作流名):单行截断、悬停看全文。 */
  truncate?: boolean;
  /** 行尾一小段弱化的附注(如「版本历史」后面的 `v29`)。不拼进 label:拼进去就和名字抢同一种字重。 */
  hint?: string;
  shortcut?: HintShortcut;
  onSelect: () => void;
  destructive?: boolean;
  /** 点不了。为什么点不了写在 `description` 里(菜单里没有悬停说明可看)。 */
  disabled?: boolean;
  /**
   * 点不了,而且原因就是这一句(如只读成员碰写操作,见 components/layout/useWriteBlocked):给了就当 `disabled`,
   * 这一句顶替 `description` 画在名字下面。调用方不必自己同时设两格 —— 漏设 `disabled` 就成了「说点不了却点得了」。
   */
  disabledReason?: string | null;
  /**
   * 分组名:和前一个条目的组不同,中间就画一条分组线(工作流卡片的「打开 | 应用 | 文件 | 路径 | 补齐 | 删除」)。
   * 不给就和以前一样只有破坏性条目自动单独成组。
   */
  group?: string;
};

/**
 * 卡片 / 画布工具栏右端那颗 ⋯ 的菜单。
 *
 * 条目和右键菜单、笔记页「更多」是**同一套**:MenuContent / MenuItem / MenuItemBody(宽度、行高、
 * 内边距、图标尺寸、悬停底色、折行与截断),分组线是独立的 MenuSeparator 元素。此前这里是一排 ghost Button,分组靠给「删除」那一行
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
          <IconButton variant="ghost" size="icon-sm" label={label} aria-haspopup="menu"><MoreHorizontal /></IconButton>
        )}
      </PopoverTrigger>
      <MenuContent align={align} label={label}>
        {actions.map((action, i) => (
          <Fragment key={action.label}>
            {startsGroup(actions, i) && <MenuSeparator />}
            <PopoverClose asChild>
              <MenuItem
                icon={action.icon}
                label={action.label}
                description={action.disabledReason || action.description}
                truncate={action.truncate}
                hint={action.hint}
                shortcut={action.shortcut}
                destructive={action.destructive}
                disabled={isDisabled(action)}
                onClick={action.onSelect}
              />
            </PopoverClose>
          </Fragment>
        ))}
      </MenuContent>
    </Popover>
  );
}

function isDisabled(action: MenuAction): boolean {
  return Boolean(action.disabled || action.disabledReason);
}

/**
 * 这一条前面要不要画分组线 —— ⋯ 菜单和右键菜单同一条规则:第一个破坏性条目前面(且前面还有别的),或者分组名换了。
 */
function startsGroup(actions: MenuAction[], i: number): boolean {
  if (i === 0) return false;
  const destructive = Boolean(actions[i].destructive) && !actions[i - 1].destructive;
  return destructive || (actions[i].group ?? "") !== (actions[i - 1].group ?? "");
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
          {startsGroup(actions, i) && <ContextMenuSeparator />}
          <ContextMenuItem
            className={cn(action.destructive && MENU_ITEM_DESTRUCTIVE)}
            disabled={isDisabled(action)}
            onSelect={action.onSelect}
          >
            <MenuItemBody
              icon={action.icon}
              label={action.label}
              description={action.disabledReason || action.description}
              truncate={action.truncate}
              hint={action.hint}
              shortcut={action.shortcut}
            />
          </ContextMenuItem>
        </Fragment>
      ))}
    </>
  );
}
