import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * 加载占位块。脉冲表示"内容在来的路上";尺寸和形状由 className 给。
 *
 * **底色是相对它所在的那层表面算的,不是一个固定的灰。** 此前用 `bg-muted` —— 那是**页面**的
 * 次级底色,而占位块也出现在弹层上(插件市场就在 ModalShell 里)。弹层的表面比页面**更浅**
 * (浅色 #fafbfd vs #f0f3f8),于是占位块和它踩在的表面几乎同色:实测对比 **1.07**(浅色)/
 * **1.14**(深色)—— 眼睛看不出那儿有东西,再叠上 animate-pulse 的透明度起伏就更没了。
 * 用户报的「加载中没有 Skeleton」其实是有,只是看不见。
 *
 * 用前景色的低透明度叠加就没有这个问题:它合成在**当前这层**上面,不管底下是页面、卡片还是
 * 弹层,拉开的都是同一个相对差。
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("animate-pulse rounded-md bg-foreground/[0.12]", className)} {...props} />;
}

export { Skeleton };
