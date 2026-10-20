/**
 * 一项宿主能力「用在哪」(ADR 0032 §4):宿主界面上的入口、工作流节点的字段、智能体工具。
 * 条目由后端从能力表现算(`used_by`),这里只照着列 —— 设置「能力提供方」和插件页宿主工具共用这一份。
 *
 * 设置页那张卡片里,它**默认收成一行摘要**(`CapabilityUseSummary`):「用在 3 处 · 界面 / 工作流 / 智能体」,
 * 点开才列出那三处。此前是一排安静的标签直接摊在卡片里,和主操作「用哪一家」争注意力 ——
 * 维护者截图里那七组,每组底下都吊着一排小标签,读起来比下拉还显眼。
 */
import React from "react";
import { Bot, LayoutGrid, Workflow } from "lucide-react";

import type { components } from "@/api/generated/schema";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Disclosure } from "@/components/ui/disclosure";
import { Truncate } from "@/components/ui/truncate";

export type CapabilityUse = components["schemas"]["CapabilityUseOut"];

const USE_ICON = { app: LayoutGrid, workflow: Workflow, agent: Bot } as const;

/** 「用在哪」一条的图标:宿主界面上的入口、工作流节点的字段、智能体工具。插件详情里的能力清单也照它画。 */
export function capabilityUseIcon(kind: string) {
  return USE_ICON[kind as keyof typeof USE_ICON] ?? LayoutGrid;
}

/**
 * 摘要里那三个类别的短名 —— 只译 `kind` 这个真实枚举,不猜条目内容。
 * (条目自己的文案太长,收成一行时读不完;具体是哪个入口点开看。)
 */
const USE_KIND_LABEL: Record<string, MessageKey> = {
  app: "capabilityUseKindApp",
  workflow: "capabilityUseKindWorkflow",
  agent: "capabilityUseKindAgent",
};

export function CapabilityUseList({ uses, label }: { uses: CapabilityUse[]; label?: string }) {
  return (
    //: 标签钉在左边一列,标签组在右边自己换行 —— 条目一多,「用在哪」不会被挤到单独一行。
    <div className="flex min-w-0 items-start gap-2.5">
      {label && <span className="shrink-0 text-ui-xs leading-6 text-muted-foreground">{label}</span>}
      <ul data-capability-uses="" className="m-0 flex min-w-0 flex-1 list-none flex-wrap gap-1.5 p-0">
        {uses.map((use) => {
          const Icon = capabilityUseIcon(use.kind);
          return (
            <li
              key={`${use.kind}:${use.label}`}
              data-capability-use={use.kind}
              className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md bg-secondary px-2 py-0.5 text-ui-xs leading-5 text-foreground"
            >
              <Icon size={12} className="shrink-0 text-muted-foreground" aria-hidden />
              <Truncate>{use.label}</Truncate>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * 卡片里的「用在哪」:一行摘要,默认收起。
 *
 * 收起时只留一句「用在 3 处」和类别短名(「界面 / 工作流 / 智能体」),把主操作「用哪一家」让出来;
 * 点开才是真数据 —— 每一条都照接口的 `used_by` 原样列,不在这里编任何条目。
 */
export function CapabilityUseSummary({ uses }: { uses: CapabilityUse[] }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  if (uses.length === 0) return null;
  const kinds = [...new Set(uses.map((use) => use.kind))];
  return (
    <div data-capability-uses-summary="" data-capability-use-count={uses.length} className="min-w-0 py-3">
      <Disclosure
        wide
        label={t("capabilityUsesCount").replace("{n}", String(uses.length))}
        hint={kinds.map((kind) => t(USE_KIND_LABEL[kind] ?? "capabilityUsedBy")).join(" / ")}
        open={open}
        onOpenChange={setOpen}
        contentClassName="pt-2"
      >
        <CapabilityUseList uses={uses} />
      </Disclosure>
    </div>
  );
}
