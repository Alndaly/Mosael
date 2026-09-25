import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * 加载占位块:一块底色 + 一道从左到右扫过的光,表示"内容在来的路上";尺寸和形状由 className 给。
 *
 * **这是全项目唯一的加载占位实现。** 样子写在 design/tokens.css 的 `.skeleton` 里(components 层,
 * 使用方的工具类照常压得过它),颜色是 `--skeleton-base` / `--skeleton-highlight` 两个主题 token,
 * 要求减少动态时只剩底色。别在调用处再挂 `animate-pulse` / `animate-none` —— 此前画板生成中的
 * 那一格就是挂了 `animate-none`,于是整张卡是一块死灰,只剩中间一个小圈在转。
 * 棘轮见 design/skeletons.test.ts。
 *
 * **底色是相对它所在的那层表面算的,不是一个固定的灰。** 更早用的是 `bg-muted` —— 那是**页面**的
 * 次级底色,而占位块也出现在弹层上(插件市场就在 ModalShell 里)。弹层的表面比页面**更浅**
 * (浅色 #fafbfd vs #f0f3f8),于是占位块和它踩在的表面几乎同色:实测对比 **1.07**(浅色)/
 * **1.14**(深色)—— 眼睛看不出那儿有东西。用户报的「加载中没有 Skeleton」其实是有,只是看不见。
 * 前景色的低透明度叠加没有这个问题:它合成在**当前这层**上面,拉开的都是同一个相对差。
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="skeleton" className={cn("skeleton rounded-md", className)} {...props} />;
}

export { Skeleton };
