import * as React from "react"

import { Button, type ButtonProps } from "./button"
import { Hint, type HintShortcut } from "./tooltip"

export type IconButtonProps = Omit<ButtonProps, "aria-label" | "title"> & {
  /** 按钮叫什么。**只写这一次**:它既是读屏念的 `aria-label`,也是悬停说明的第一行。 */
  label: string
  /** 名字下面一行淡色的补充说明(「撤回上一步编辑」)。名字已经说清楚了就别写。 */
  hint?: string | null
  /** 快捷键,用键帽画在名字那一行。 */
  shortcut?: HintShortcut | null
  /** 点不了的原因。只在 `disabled` 时显示;禁用了却说不出为什么,就别给。 */
  disabledReason?: string | false | null
  tooltipSide?: "top" | "bottom" | "left" | "right"
  tooltipAlign?: "start" | "center" | "end"
  /**
   * 不要 Button 的外观:渲染原生 `<button>`,样式全由 className(或外层 CSS,如笔记工具栏的
   * `.note-format button`)给。名字、说明、禁用原因照旧。
   */
  unstyled?: boolean
}

/**
 * 只有图标的按钮。
 *
 * 图标按钮最常见的两种坏法:没有 `aria-label`(读屏只念「按钮」),或者靠原生 `title` 给人看名字
 * (停一秒多才出、样式是系统的、深色下不跟主题)。这里两样都给,而且名字只写一次。
 * 棘轮:`design/iconButtons.test.ts` —— 功能代码里只有图标的按钮都走这里。
 *
 * 默认 `variant="ghost" size="icon-sm"`(工具栏、卡片里最常见的那一档);其余属性原样给 Button。
 */
const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(
  (
    { label, hint, shortcut, disabledReason, tooltipSide, tooltipAlign, unstyled, variant = "ghost", size = "icon-sm", ...props },
    ref,
  ) => {
    let button: React.ReactNode
    if (unstyled) {
      const { loading, asChild: _asChild, disabled, ...rest } = props
      button = <button ref={ref} aria-label={label} aria-busy={loading || undefined} disabled={disabled || loading} {...rest} />
    } else {
      button = <Button ref={ref} variant={variant} size={size} aria-label={label} {...props} />
    }
    return (
      <Hint
        label={label}
        hint={hint}
        shortcut={shortcut}
        disabledReason={props.disabled ? disabledReason : undefined}
        side={tooltipSide}
        align={tooltipAlign}
      >
        {button}
      </Hint>
    )
  },
)
IconButton.displayName = "IconButton"

export { IconButton }
