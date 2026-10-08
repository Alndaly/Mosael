import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { Loader2 } from "lucide-react"

import { CONTROL_HEIGHT, CONTROL_ICON, CONTROL_SQUARE, INLINE_ACTION_SIZE, PRESSED, PRESSED_BORDER } from "@/components/ui/control-size"
import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex cursor-pointer items-center justify-center gap-2 whitespace-nowrap rounded-md border border-transparent text-ui-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-action text-action-foreground  hover:bg-action/90",
        destructive:
          "bg-destructive text-destructive-foreground  hover:bg-destructive/90",
        //: 描边和输入框、下拉框是**同一种描边**(field-border):一行里的输入框、下拉框、描边按钮
        //: 外轮廓一样清楚。此前用的是分隔线色,在弹窗里几乎看不见,按钮的可见轮廓比旁边的
        //: 实心按钮小一圈 —— 两个 40px 的按钮看起来不一样高。
        //: 按下(aria-pressed)的样子三种一样:强调底色 + 强调色前景(control-size 的 PRESSED)。别在调用处另写「开着」的颜色,
        //: 也别用 `variant={on ? "secondary" : "ghost"}` 切变体 —— 写 aria-pressed 就够了(棘轮 design/pressedState.test.ts)。
        outline:
          `border border-field-border bg-control hover:bg-secondary hover:text-foreground ${PRESSED} ${PRESSED_BORDER}`,
        secondary:
          `bg-secondary text-secondary-foreground  hover:bg-secondary/80 ${PRESSED}`,
        ghost: `hover:bg-accent hover:text-accent-foreground ${PRESSED}`,
        link: "text-primary underline-offset-4 hover:underline",
        //: **行内动作**:放在一个值旁边、一行说明里的次要动作 ——「在 Civitai 上找」「标为 NSFW」「改回自动判断」「显示全部」。
        //: 比正文小一档(text-ui-xs)、次要色、不加粗,悬停才显出底色;图标跟着缩成 14px;高 24px、上下各收 2px,
        //: 不撑高所在的那一行。尺寸由这一档自己定(见下面的 compoundVariants),调用处不写 size。
        //:
        //: 什么时候**不**用它:一页 / 一个弹窗的主动作用 default(实心);和主动作并排的次要动作用 outline / secondary;
        //: 工具栏、卡片角上不带边框的文字按钮用 ghost;只有图标的用 IconButton。判据是「它挨着的是一段值或说明,而不是
        //: 别的按钮」—— 挨着值的按钮用正文字号,就比值本身还醒目,一行里视觉最重的反倒成了次要动作。
        //: 棘轮:`design/inlineActions.test.ts`。
        inline: "font-normal text-muted-foreground hover:bg-secondary hover:text-foreground",
      },
      size: {
        default: `${CONTROL_HEIGHT.md} rounded-md px-4 py-2`,
        // 28px 的带文字按钮(密集工具条)。高度压到 28 之后 text-ui-sm 会把它顶满,所以这一档自带 text-ui-xs,
        // 图标跟着缩到 14(16 的图标配 12 的字,图标比字重)—— 字号、图标跟着高度走,不必每个调用点再补一遍。
        xs: `${CONTROL_HEIGHT.xs} rounded-md px-2.5 text-ui-xs ${CONTROL_ICON.text.xs}`,
        sm: `${CONTROL_HEIGHT.sm} rounded-md px-3`,
        lg: `${CONTROL_HEIGHT.lg} rounded-md px-6`,
        // 方钮和同档文字控件一样高:icon 40 和 md 的输入框、按钮并排,icon-sm 32、icon-xs 28 同理。图标在哪一档都是 16。
        // 此前 icon 是 36,比同档 40 矮一截;挨着字段的试听键只好另起一档 icon-lg(40)—— 定稿后合成一个名字。
        // 这几档以前没有 token 时,几十处各自写 `h-7 w-7` 盖在 size="icon" 上 —— 盖漏一处就是一颗大圆钮杵在一排小控件中间。
        // 棘轮:`components/ui/buttonScale.test.ts` 拦下一处再手搓。
        icon: `${CONTROL_SQUARE.md} rounded-md ${CONTROL_ICON.square}`,
        "icon-sm": `${CONTROL_SQUARE.sm} rounded-md ${CONTROL_ICON.square}`,
        "icon-xs": `${CONTROL_SQUARE.xs} rounded-md ${CONTROL_ICON.square}`,
      },
      //: 形状:默认圆角 8px;`round` 是全圆 —— 胶囊形的浮动工具条(画板格子上方那一条)里的按钮、输入框底栏的发送键、
      //: 播放键。挑这一项,别在 className 里写 rounded-full(棘轮 design/controlOverrides.test.ts)。
      shape: {
        square: "",
        round: "rounded-full",
      },
    },
    compoundVariants: [
      //: 行内动作自带尺寸:不论调用处写没写 size,都是这一套(写在最后,cn 合并时盖过 size 那一档的高度、留白和字号)。
      { variant: "inline", class: INLINE_ACTION_SIZE },
    ],
    defaultVariants: {
      variant: "default",
      size: "default",
      shape: "square",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
  /**
   * 正在跑:禁用点击,并把**第一个图标**换成转圈。
   *
   * 换掉而不是插一个:按钮宽度不变,行不会跳。没有图标的按钮就在文字前面加一个。
   *
   * 判据是「点下去会发请求,而且没有别的即时反馈」—— 那种按钮不接这个标就等于骗人:
   * 它看起来点了没反应,于是用户再点一次。纯前端的开合/筛选、以及乐观更新的开关不必接,
   * 界面本来就当场变了。
   */
  loading?: boolean
}

/**
 * **不写 `type` 就是 `type="button"`**:点了只做 onClick 里写的那件事。要提交表单的那一颗显式写 `type="submit"`
 * (表单外面的用 `form={id}` 指过去)。HTML 的默认是 submit —— 那时 `<form>` 里任何一颗没写 type 的按钮(展开、清空、
 * 换一个选项)点了都会顺带把整张表单交出去,换基础件时踩到过(模型设置里点「自己描述这个端点」把整张表单存了)。
 * 棘轮:`design/buttonTypes.test.ts`。`asChild` 时不加:那时它把样子借给别的元素(`<a>`、`<label>`),type 由那个元素自己定。
 */
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, shape, asChild = false, loading = false, disabled, children, type, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    // asChild 时不动 children:那时候 Button 只是把样式借给别人(<label>、<a>),
    // 塞一个 spinner 进去会破坏调用方自己的结构。
    const content =
      loading && !asChild ? <BusyChildren>{children}</BusyChildren> : children
    return (
      <Comp
        type={asChild ? type : (type ?? "button")}
        className={cn(buttonVariants({ variant, size, shape, className }))}
        ref={ref}
        disabled={disabled || (loading && !asChild)}
        aria-busy={loading || undefined}
        {...props}
      >
        {content}
      </Comp>
    )
  }
)

/**
 * 把第一个图标替换成转圈,大小沿用它的 `size`(不带 Button 外观的按钮里,图标的大小多半就靠它)。
 * 一个图标都没有时,`prepend` 就在最前面补一个;不补的(IconButton unstyled 的头像、整块自绘的内容)
 * 由调用方自己在里面画转圈。
 */
function BusyChildren({ children, prepend = true }: { children?: React.ReactNode; prepend?: boolean }) {
  const nodes = React.Children.toArray(children)
  const iconAt = nodes.findIndex(
    (node) => React.isValidElement(node) && typeof node.type !== "string",
  )
  if (iconAt < 0) {
    return prepend ? <><Loader2 key="__busy" className="animate-mosael-spin" />{children}</> : <>{children}</>
  }
  const icon = nodes[iconAt] as React.ReactElement<{ size?: number | string }>
  const spinner = <Loader2 key="__busy" size={icon.props.size} className="animate-mosael-spin" />
  return <>{nodes.map((node, index) => (index === iconAt ? spinner : node))}</>
}
Button.displayName = "Button"

export { BusyChildren, Button, buttonVariants }
