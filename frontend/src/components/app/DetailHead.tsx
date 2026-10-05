import React from "react";
import { ArrowLeft } from "lucide-react";

import { IconButton } from "@/components/ui/icon-button";
import { cn } from "@/lib/utils";

/**
 * 弹窗里「点开一条看详情」那一页的骨架零件 —— 模型库 / 工作流库(LibraryDetail)、插件市场 / 工作流社区(CatalogDialog)
 * 用的是同一套:
 *
 * - **返回键在固定头的最前面**,和名字、操作同一行。此前目录弹窗的返回是名字上面单独一行「← 全部插件」,
 *   一整行只放一颗按钮,把页头往下推,读起来像两层标题(用户截图:「这个返回按钮所在位置设计很不舒服」)。
 * - **固定头不跟着滚**,下面一条分隔线;正文在它下面自己滚 —— 往下翻多长,名字和操作都在。
 */

/** 固定头的外框:不跟着滚、下面一条分隔线;左右内边距和弹窗正文对齐,上边距由弹窗标题那一条给。 */
export const DETAIL_HEAD = "shrink-0 border-b border-divider px-6 pb-3";

/** 固定头下面自己滚的那一块。 */
export const DETAIL_SCROLL = "min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 pb-6 pt-5";

/**
 * 固定头最前面的返回键:只有一个箭头,名字(「返回全部插件」)在悬停说明和读屏里。往左探出半格,箭头和下面正文的左边对齐。
 * 进详情时焦点给它(读屏从这一页的开头读起)—— 谁打开的详情谁负责(见 LibraryDetail、CatalogDialog)。
 */
export const DetailBackButton = React.forwardRef<HTMLButtonElement, { label: string; onClick: () => void; className?: string }>(
  ({ label, onClick, className }, ref) => (
    <IconButton ref={ref} variant="ghost" size="icon" className={cn("-ml-2 shrink-0", className)} label={label} onClick={onClick}>
      <ArrowLeft />
    </IconButton>
  ),
);
DetailBackButton.displayName = "DetailBackButton";
