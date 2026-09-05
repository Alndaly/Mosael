import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { Loader2 } from "lucide-react"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-ui-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground  hover:bg-primary/90",
        destructive:
          "bg-destructive text-destructive-foreground  hover:bg-destructive/90",
        outline:
          "border border-border bg-transparent hover:bg-secondary hover:text-foreground",
        secondary:
          "bg-secondary text-secondary-foreground  hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 rounded-full px-4 py-2",
        // 28px 的带文字胶囊。工具栏那一行放的都是次要动作,sm(32px)在里面偏高、px-3 偏宽;
        // 高度压到 28 之后 text-ui-sm 会把胶囊顶满,所以这一档自带 text-ui-xs —— 字号跟着
        // 高度走,不必每个调用点再补一遍。
        xs: "h-7 rounded-full px-2.5 text-ui-xs",
        sm: "h-8 rounded-full px-3",
        lg: "h-10 rounded-full px-8",
        icon: "h-9 w-9 rounded-full",
        // 与 sm 同高的方形图标按钮。卡片、工具栏这类窄容器里,次要动作放不下文字标签,
        // 而 icon(36px)在一排 sm(32px)按钮中间会高出一截。
        "icon-sm": "size-8 rounded-full",
        // 28px:全应用工具栏的**实际**刻度(时间线、编辑器、设置页、智能体输入框都是这一档)。
        // 这一档以前没有 token,于是几十处各自写 `h-7 w-7` 盖在 size="icon" 上 —— 盖漏一处
        // 就是一个 36px 的圆按钮杵在一排 28px 控件中间,智能体输入框刚栽过这一下。
        // 棘轮:`components/ui/buttonScale.test.ts` 拦下一处再手搓。
        "icon-xs": "size-7 rounded-full",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
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

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading = false, disabled, children, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    // asChild 时不动 children:那时候 Button 只是把样式借给别人(<label>、<a>),
    // 塞一个 spinner 进去会破坏调用方自己的结构。
    const content =
      loading && !asChild ? <BusyChildren>{children}</BusyChildren> : children
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
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

/** 把第一个 svg 图标替换成转圈;一个图标都没有就在最前面补一个。 */
function BusyChildren({ children }: { children?: React.ReactNode }) {
  const spinner = <Loader2 key="__busy" className="animate-mosael-spin" />
  const nodes = React.Children.toArray(children)
  const iconAt = nodes.findIndex(
    (node) => React.isValidElement(node) && typeof node.type !== "string",
  )
  if (iconAt < 0) return <>{spinner}{children}</>
  return <>{nodes.map((node, index) => (index === iconAt ? spinner : node))}</>
}
Button.displayName = "Button"

export { Button, buttonVariants }
