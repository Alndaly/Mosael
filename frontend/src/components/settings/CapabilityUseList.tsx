/**
 * 一项宿主能力「用在哪」(ADR 0032 §4):宿主界面上的入口、工作流节点的字段、智能体工具。
 * 条目由后端从能力表现算(`used_by`),这里只照着列 —— 设置「能力提供方」和插件页宿主工具共用这一份。
 *
 * 画成一排安静的小标签、左对齐换行:它是「这一项的附注」,不是一个要操作的控件。此前放在设置行右边那一格里,
 * 三行小字挤在页面最右、和左边的「用在哪」隔着半屏(用户截图:「能力提供方这个 tab 的界面优化一下」)。
 */
import { Bot, LayoutGrid, Workflow } from "lucide-react";

import type { components } from "@/api/generated/schema";

export type CapabilityUse = components["schemas"]["CapabilityUseOut"];

const USE_ICON = { app: LayoutGrid, workflow: Workflow, agent: Bot } as const;

export function CapabilityUseList({ uses, label }: { uses: CapabilityUse[]; label?: string }) {
  return (
    //: 标签钉在左边一列,标签组在右边自己换行 —— 条目一多,「用在哪」不会被挤到单独一行。
    <div className="flex min-w-0 items-start gap-2.5">
      {label && <span className="shrink-0 text-ui-xs leading-6 text-muted-foreground">{label}</span>}
      <ul data-capability-uses="" className="m-0 flex min-w-0 flex-1 list-none flex-wrap gap-1.5 p-0">
        {uses.map((use) => {
          const Icon = USE_ICON[use.kind as keyof typeof USE_ICON] ?? LayoutGrid;
          return (
            <li
              key={`${use.kind}:${use.label}`}
              data-capability-use={use.kind}
              className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md bg-secondary px-2 py-0.5 text-ui-xs leading-5 text-foreground"
            >
              <Icon size={12} className="shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 truncate">{use.label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
