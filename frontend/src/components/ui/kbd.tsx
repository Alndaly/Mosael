import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * 键帽。全应用只有这一种长相,以顶栏全局搜索按钮上那颗 ⌘K 为准:11px、一圈细边、不填底。
 *
 * 此前每处各写一份:时间线的快捷键表用等宽字体 + 加厚底边,标记旗用等宽 + 底色,搜索按钮用正文
 * 字体。等宽那几处的 ⌘ ⇧ ← → 明显比字母大、还往下沉 —— 打包的字体子集里没有这些符号,等宽栈
 * 回落到 Apple Symbols。字体见 tokens.css 的 `--font-kbd`。
 *
 * 行高钉死在 15px:符号字形的上下伸展比字母大,不钉的话一行里有 ⌘ 的键帽比只有字母的高一截。
 */
const Kbd = React.forwardRef<HTMLElement, React.HTMLAttributes<HTMLElement>>(({ className, ...props }, ref) => (
  <kbd
    ref={ref}
    className={cn(
      "inline-block shrink-0 whitespace-nowrap rounded-sm border border-border px-1 font-kbd text-ui-2xs font-normal leading-[15px] text-muted-foreground",
      className,
    )}
    {...props}
  />
));
Kbd.displayName = "Kbd";

/**
 * 几个键**任选其一**(`A / B`、`⌘Z / ⇧⌘Z`):每个键一颗键帽,中间一道斜杠。
 * 斜杠不进键帽 —— 它不是要按的键,印进去就成了「按 A、斜杠、B」。
 */
function KbdGroup({ keys, className }: { keys: readonly string[]; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap text-ui-2xs text-muted-foreground", className)}>
      {keys.map((key, index) => (
        <React.Fragment key={key}>
          {index > 0 && <span>/</span>}
          <Kbd>{key}</Kbd>
        </React.Fragment>
      ))}
    </span>
  );
}

export { Kbd, KbdGroup };
