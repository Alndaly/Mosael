import type React from "react";
import { ChevronDown, ChevronRight, Terminal } from "lucide-react";

import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { Truncate } from "@/components/ui/truncate";

/**
 * 插件工具的一行:左边一格(开放的勾,或宿主工具的锁)、名字 + 一行说明、徽标、展开箭头;点开是这一行的内容。
 *
 * 插件页上的两种工具 —— 给智能体和工作流开放的(ToolRow)、只给 Mosael 调的(HostTools)—— **共用这一个外壳**。
 * 此前各画各的:开放的是一行可展开的条目,宿主工具是一张常开的卡片,内边距、标题字号、说明的位置都不一样,
 * 还多露一个裸的工具键名(用户截图:「mineru 插件的这个工具的样式为何和别的插件的工具不一样」)。两者真正的差别
 * 只在左边那一格和展开后的内容。
 */
export function ToolRowFrame({
  lead,
  label,
  description,
  badges,
  open,
  onOpenChange,
  children,
  ...data
}: {
  lead: React.ReactNode;
  label: string;
  description: string;
  badges?: React.ReactNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
} & { [attribute: `data-${string}`]: string }) {
  return (
    <div {...data} className="overflow-hidden rounded-lg border border-border bg-panel">
      <div className="flex items-center gap-3 px-4">
        <span className="grid size-7 shrink-0 place-items-center">{lead}</span>
        <button
          type="button"
          aria-expanded={open}
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 border-0 bg-transparent py-4 text-left"
          onClick={() => onOpenChange(!open)}
        >
          <Terminal size={14} className="shrink-0" />
          <div className="min-w-0 flex-1">
            <Truncate as="strong" className="text-ui-sm font-semibold">{label}</Truncate>
            {/* 在展开按钮里:链接只留文字。 */}
            <Truncate as="small" className="text-ui-xs text-muted-foreground">
              <InlineMarkdown text={description} links={false} />
            </Truncate>
          </div>
          {badges}
          {open ? (
            <ChevronDown size={13} className="shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight size={13} className="shrink-0 text-muted-foreground" />
          )}
        </button>
      </div>
      {open && <div className="grid gap-5 border-t border-divider bg-panel-subtle/40 p-5">{children}</div>}
    </div>
  );
}
