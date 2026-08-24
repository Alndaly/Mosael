import React from "react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * 检查器里每一块的外壳 —— **只有这一种**。
 *
 * 此前四块各写各的:一块是键值行,一块是"盒中盒"的数字砖(边框里再套四个边框),另两块是列表行。
 * 三种视觉语言并排,眼睛每换一块就要重新适应一次,而它们说的其实是同一类东西:关于这次对话的
 * 几行事实。统一成"标题行 + 若干行"之后,信息密度反而更高 —— 省下来的是分隔线和内边距,不是内容。
 *
 * 右上角的 `aside` 是可选的次要位:计数(3/3)、次要动作(全部 57 个 ›)都放这里,不再各自发明位置。
 */
export function InspectorCard({
  icon: Icon,
  title,
  aside,
  onToggle,
  className,
  children,
}: {
  icon: LucideIcon;
  title: string;
  aside?: React.ReactNode;
  /** 给可折叠的块用(计划)。传了它标题行才是按钮。 */
  onToggle?: () => void;
  className?: string;
  children?: React.ReactNode;
}) {
  const header = (
    <>
      <span className="flex min-w-0 items-center gap-1.5">
        <Icon size={13} className="shrink-0" />
        {title}
      </span>
      {aside != null && <span className="ml-auto font-normal tabular-nums">{aside}</span>}
    </>
  );
  return (
        // **不描边、圆角比外框小**。此前是 `rounded-lg border border-border` —— 边框色和外面
    // 那层面板一模一样(都是 --border),而卡片本身还有一层填色:填色已经把它从面板背景里
    // 分出来了,再描一道同色的边就是第三重冗余。圆角同理:内卡 10px 比面板的 8px 还大,
    // 嵌套的角应当向内递减,反过来会显得内卡在往外顶。
    <section className={cn("grid gap-2 rounded-sm bg-panel-subtle p-2.5", className)}>
      {/* 排版**只挂在 h3 上**,可折叠时按钮放进去继承它。
          不能把 text-ui-xs font-bold 写在裸 <button> 上:design/tokens.css 里那条
          `button { font: inherit }` 不在任何 layer 内,而 Tailwind 的工具类在 @layer utilities ——
          未分层的规则整体赢过分层的,与选择器特异性无关。于是那两个类静默失效,标题掉回 body 的
          13px/400,和邻座的 11.5px/700 差出一截(这正是「任务计划」比其它两块大一号的原因)。 */}
      <h3 className="m-0 text-ui-xs font-bold text-muted-foreground">
        {onToggle ? (
          <button
            type="button"
            className="flex w-full cursor-pointer items-center gap-1.5 border-0 bg-transparent p-0 text-left"
            onClick={onToggle}
          >
            {header}
          </button>
        ) : (
          <span className="flex items-center gap-1.5">{header}</span>
        )}
      </h3>
      {children}
    </section>
  );
}

/** 一行事实:左标签、右值。检查器里所有"某某是什么"都长这样。 */
export function InspectorRow({ label, value, title }: { label: string; value: React.ReactNode; title?: string }) {
  return (
    <div className="grid grid-cols-[56px_minmax(0,1fr)] items-center gap-2">
      <span className="truncate text-ui-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 truncate text-ui-xs font-[650] text-foreground" title={title}>
        {value}
      </span>
    </div>
  );
}
