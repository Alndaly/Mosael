import React from "react";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert, ShieldCheck, Sparkles } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n, usePreferences } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { relativeTime } from "@/lib/time";

type Confirmation = components["schemas"]["ConfirmationOut"];

/**
 * 这次对话里,**哪些操作是被自动放行的、被哪一档放的**。
 *
 * 后端为"这次写操作是谁批的、怎么批的"记了完整的一套(`decision_mode` 分 manual /
 * session-allow / auto / bypass,`resolved_at` 记时间,注释里写明了为什么要分开留痕)——
 * 而这条链的最后一环没接上:前端对 `/api/confirmations` 的两个调用点**都写死
 * `status=pending`**,于是"决策之后"的那一半在界面上根本不存在。
 *
 * 后果是:用户在某次对话里开了 auto 档之后,智能体每做一次本该问他的写操作,卡片开出来即被
 * 判定放行 —— 他看到的只是"它做了这件事",看不到"这件事本来要问你,是你之前那个开关替你答的"。
 * **一个知情同意的机制,只在"问"的那一刻可见、不在"已经发生"的时候可见,它就只是一个弹窗。**
 *
 * 手动批的那些不列:那是他自己一张一张点过的,他知道。这里只回答"我没被问到的那些是什么"。
 */
const GATE_ICON = {
  auto: ShieldCheck,
  bypass: ShieldAlert,
  "session-allow": Sparkles,
} as const;

const GATE_LABEL = {
  auto: "permTraceGateAuto",
  bypass: "permTraceGateBypass",
  "session-allow": "permTraceGateSessionAllow",
} as const;

export function AutoApprovalTrace({ workspaceId, sessionId }: { workspaceId: string; sessionId: string }) {
  const t = useI18n();
  const { locale } = usePreferences();

  const approved = useQuery({
    queryKey: ["confirmations", workspaceId, "approved", sessionId],
    queryFn: () =>
      api<Confirmation[]>(
        `/api/confirmations?workspace_id=${workspaceId}&status=approved&session_id=${encodeURIComponent(sessionId)}&limit=20`,
      ),
    // 这一栏只在设置弹层打开时看得到,不需要轮询 —— 打开时取一次即可。
    staleTime: 5_000,
  });

  const automatic = (approved.data ?? []).filter(
    (card): card is Confirmation & { decision_mode: keyof typeof GATE_ICON } =>
      card.decision_mode !== "manual" && card.decision_mode in GATE_ICON,
  );
  // 一条都没有就整块不出现 —— 常驻一句"暂无"只是噪音,而这一栏本来就是"有事才说话"。
  if (automatic.length === 0) return null;

  return (
    <div className="grid gap-1.5 border-t border-border pt-2.5">
      <span className="text-ui-xs font-medium text-muted-foreground">
        {t("permTraceTitle").replace("{n}", String(automatic.length))}
      </span>
      <ul className="m-0 grid max-h-[168px] list-none gap-1 overflow-y-auto p-0">
        {automatic.map((card) => {
          const Icon = GATE_ICON[card.decision_mode];
          return (
            <li key={card.id} className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-1.5 text-ui-2xs">
              <Icon
                size={12}
                className={card.decision_mode === "bypass" ? "mt-[3px] text-destructive" : "mt-[3px] text-primary"}
              />
              <span className="grid gap-0.5">
                <span className="truncate text-foreground" title={toPlainText(card.summary)}>
                  {card.summary ? <InlineMarkdown text={card.summary} links={false} /> : card.tool}
                </span>
                <span className="text-muted-foreground">
                  {t(GATE_LABEL[card.decision_mode])}
                  {card.resolved_at ? ` · ${relativeTime(card.resolved_at, locale)}` : ""}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
