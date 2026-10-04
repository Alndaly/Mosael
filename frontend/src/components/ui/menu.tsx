import * as React from "react"
import { Check } from "lucide-react"

import { cn } from "@/lib/utils"

import { MENU_ITEM, MENU_ITEM_DESTRUCTIVE, MENU_SEPARATOR, MENU_WIDTH } from "./floating"
import { Kbd, KbdGroup } from "./kbd"
import { PopoverContent } from "./popover"
import type { HintShortcut } from "./tooltip"
import { Truncate } from "./truncate"

/**
 * 点按钮弹出的动作菜单(「插入▾」、卡片的 ⋯、「生成▾」)的浮层。右键菜单是 ContextMenuContent,
 * 两者的条目长得一样 —— 都用 MenuItemBody 排一行。
 *
 * 宽度由 MENU_WIDTH 定,调用方不写宽度(棘轮:design/menuWidths.test.ts);条目之间用方向键走,
 * 两端循环,跳过禁用的。
 */
const MenuContent = React.forwardRef<
  React.ElementRef<typeof PopoverContent>,
  Omit<React.ComponentPropsWithoutRef<typeof PopoverContent>, "role" | "aria-label"> & {
    /** 菜单叫什么(读屏念的)。通常就是触发按钮上的字或它的 aria-label。 */
    label?: string
  }
>(({ className, label, onKeyDown, ...props }, ref) => (
  <PopoverContent
    ref={ref}
    role="menu"
    aria-label={label}
    className={cn(MENU_WIDTH, "grid content-start gap-0.5 p-1.5", className)}
    onKeyDown={(event) => {
      onKeyDown?.(event)
      if (!event.defaultPrevented) moveMenuFocus(event)
    }}
    {...props}
  />
))
MenuContent.displayName = "MenuContent"

/** 菜单里的方向键:只在可用条目之间走(禁用的原生 button 本来就拿不到焦点),两端循环。 */
function moveMenuFocus(event: React.KeyboardEvent<HTMLElement>) {
  const items = [...event.currentTarget.querySelectorAll<HTMLElement>('[role^="menuitem"]:not(:disabled)')]
  if (items.length === 0) return
  const at = items.indexOf(document.activeElement as HTMLElement)
  const next =
    event.key === "ArrowDown" ? (at + 1) % items.length
    : event.key === "ArrowUp" ? (at <= 0 ? items.length - 1 : at - 1)
    : event.key === "Home" ? 0
    : event.key === "End" ? items.length - 1
    : null
  if (next === null) return
  event.preventDefault()
  items[next].focus()
}

export type MenuItemBodyProps = {
  /** 行首图标。同一张菜单里有的行有图标、有的没有,字就对不齐 —— 没有图标的行给 `inset`。 */
  icon?: React.ReactNode
  /** 没有图标时空出图标那一格,和有图标的行对齐。 */
  inset?: boolean
  /** 名字。**静态文案放不下就折行**,不截断。 */
  label: React.ReactNode
  /**
   * 名字下面一行淡色的补充说明 —— 和悬停说明(Hint)同一种层次。括号里的补充别拼进名字:
   * 「插入图片」下面写「也可粘贴或拖入」,而不是「插入图片(也可粘贴或拖入)」。
   */
  description?: React.ReactNode
  /**
   * 名字是**动态的长值**(文件名、网址、工作流名、模型名、用户输入):单行截断,悬停看全文。
   * 它们的长度不由我们定,折行会把一行撑成好几行,不截又会把菜单撑开。
   */
  truncate?: boolean
  /** 行尾一小段弱化的附注(版本号 `v29`、数量)。不拼进名字:拼进去就和名字抢同一种字重。 */
  hint?: React.ReactNode
  /** 快捷键,用键帽画在行尾。 */
  shortcut?: HintShortcut | null
  /** 单选 / 多选菜单:选中的行在行尾打勾。不是勾选型的菜单别传。 */
  checked?: boolean
  /**
   * 说明那一行的 id。给了的话说明不进这一行的名字(读屏念名字,再把说明当描述念),由外面那颗
   * 按钮用 `aria-describedby` 指过来 —— MenuItem 自己会给;右键菜单里不给,说明就跟着名字一起念。
   */
  descriptionId?: string
}

/**
 * 菜单一行里面怎么排:图标 | 名字(+ 下面一行说明)| 附注 / 快捷键 / 勾。
 *
 * 动作菜单(MenuItem)、右键菜单(ContextMenuItem 里放它)、卡片的 ⋯(ActionMenu)都用这一份,
 * 所以对齐、折行、截断在所有菜单里是同一条规矩。行尾那几样和图标都贴着**第一行**(self-start),
 * 名字折成两行或者带说明时,图标不会漂到两行中间去。
 */
function MenuItemBody({ icon, inset, label, description, truncate, hint, shortcut, checked, descriptionId }: MenuItemBodyProps) {
  return (
    <>
      {icon || inset ? (
        <span data-menu-icon="" aria-hidden className="mt-0.5 grid size-4 shrink-0 place-items-center self-start">
          {icon}
        </span>
      ) : null}
      <span className="grid min-w-0 flex-1 gap-px">
        {truncate ? <Truncate>{label}</Truncate> : <span className="min-w-0 break-words">{label}</span>}
        {description ? (
          <span id={descriptionId} aria-hidden={descriptionId ? true : undefined} className="min-w-0 break-words text-ui-xs leading-4 text-muted-foreground">
            {description}
          </span>
        ) : null}
      </span>
      {hint ? <span className="mt-0.5 shrink-0 self-start pl-2 text-ui-xs tabular-nums text-muted-foreground">{hint}</span> : null}
      {shortcut && shortcut.length > 0 ? (
        // 键帽只给眼睛看:进了名字,读屏会把「撤销」念成「撤销 Ctrl+Z」,按名字找条目的地方也对不上。
        <span aria-hidden className="mt-0.5 shrink-0 self-start pl-2">
          {typeof shortcut === "string" ? <Kbd>{shortcut}</Kbd> : <KbdGroup keys={shortcut} />}
        </span>
      ) : null}
      {checked ? <Check className="mt-0.5 shrink-0 self-start" aria-hidden /> : null}
    </>
  )
}

/**
 * 动作菜单里的一项(原生按钮)。外观是 MENU_ITEM,里面用 MenuItemBody 排。点完要关菜单的话,
 * 调用方用 `PopoverClose asChild` 包它,或者自己收起受控的 open。
 */
const MenuItem = React.forwardRef<
  HTMLButtonElement,
  Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children"> &
    MenuItemBodyProps & {
      /** 删除、移除这类:红字,其余(行高、悬停底色)和别的条目一样。 */
      destructive?: boolean
    }
>(({ icon, inset, label, description, truncate, hint, shortcut, checked, destructive, className, role = "menuitem", type = "button", ...props }, ref) => {
  const descriptionId = React.useId()
  return (
    <button
      ref={ref}
      type={type}
      role={role}
      aria-checked={role === "menuitemradio" || role === "menuitemcheckbox" ? Boolean(checked) : undefined}
      aria-describedby={description ? descriptionId : undefined}
      className={cn(MENU_ITEM, "w-full text-left", destructive && MENU_ITEM_DESTRUCTIVE, className)}
      {...props}
    >
      <MenuItemBody
        icon={icon}
        inset={inset}
        label={label}
        description={description}
        descriptionId={description ? descriptionId : undefined}
        truncate={truncate}
        hint={hint}
        shortcut={shortcut}
        checked={checked}
      />
    </button>
  )
})
MenuItem.displayName = "MenuItem"

/** 分组线。一个独立的元素,不是哪一行的 border(见 floating.ts 的 MENU_SEPARATOR)。 */
function MenuSeparator({ className }: { className?: string }) {
  return <div role="separator" className={cn(MENU_SEPARATOR, className)} />
}

/** 一组条目的小标题:小一号、次要色,一眼看得出「这不是能点的那一行」。 */
function MenuLabel({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-2.5 pb-1 pt-1.5 text-ui-xs font-medium text-muted-foreground", className)} {...props} />
}

export { MenuContent, MenuItem, MenuItemBody, MenuSeparator, MenuLabel, moveMenuFocus }
