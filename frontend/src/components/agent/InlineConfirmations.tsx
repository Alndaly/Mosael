import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCheck, ShieldAlert, X } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { registerInlineConfirmSurface } from "@/components/agent/confirmSurface";

type Confirmation = components["schemas"]["ConfirmationOut"];

/**
 * 聊天流里的确认卡(Claude Code / Codex 式):智能体提出的写操作在对话里就地决策,
 * 三档动作——允许一次 / 本会话始终允许(按工具记忆,自动批准后续同工具请求)/ 拒绝。
 *
 * 此前确认只存在于右上角的全局 ConfirmationCenter,而它 z-index 低于 AI 助手浮窗,
 * 会被整块盖住——模型说"等待您的确认",用户却什么都看不到。现在:聊天面板打开时
 * 卡片就在对话里(本组件),全局中心让位(见 confirmSurface.ts);没有聊天面板时
 * 全局中心照常兜底(MCP / 飞书等外部智能体仍走它)。
 *
 * 「本会话始终允许」是客户端策略:按 (allowKey, tool) 记在 localStorage,本组件
 * 挂载期间对匹配的 pending 卡自动批准——与 Claude Code 的 session allowlist 同构,
 * 后端确认内核不感知也不需要感知。
 */
/** `allowKey` 就是**会话 id**:既做「本会话始终允许」的 localStorage 键,也做确认卡的归属筛选键。 */
export function InlineConfirmations({ workspaceId, allowKey }: { workspaceId: string; allowKey: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const storageKey = `openstudio.agent.allow.${allowKey}`;

  const [allowed, setAllowed] = React.useState<string[]>(() => {
    try {
      const parsed = JSON.parse(window.localStorage.getItem(storageKey) ?? "[]");
      return Array.isArray(parsed) ? parsed.map(String) : [];
    } catch {
      return [];
    }
  });
  const allowTool = (tool: string) => {
    setAllowed((current) => {
      const next = current.includes(tool) ? current : [...current, tool];
      window.localStorage.setItem(storageKey, JSON.stringify(next));
      return next;
    });
  };

  // 挂载登记:全局中心据此知道**这个会话**的卡已经有人管了,不再重复显示(其余照常兜底)。
  React.useEffect(() => registerInlineConfirmSurface(allowKey), [allowKey]);

  // **只取本会话的卡**。此前拉的是整个工作区的 pending —— 于是同工作区其它对话、工作流节点、
  // MCP/飞书外部智能体的确认卡都会挤进当前对话;更糟的是下面那段「本会话始终允许」的自动批准
  // 会把它们一并静默批掉,用户以为授的是「这次对话」,实际授的是「这个工作区里所有人的这个工具」。
  const pending = useQuery({
    queryKey: ["confirmations", workspaceId, "pending", allowKey],
    queryFn: () =>
      api<Confirmation[]>(
        `/api/confirmations?workspace_id=${workspaceId}&status=pending&session_id=${encodeURIComponent(allowKey)}`,
      ),
    refetchInterval: 1500,
    refetchOnWindowFocus: true,
  });

  const settle = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "reject" }) =>
      api<Confirmation>(`/api/confirmations/${id}/${action}`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["confirmations", workspaceId, "pending"] });
      void qc.invalidateQueries({ queryKey: ["confirmations", workspaceId, "unowned"] });
      void qc.invalidateQueries({ queryKey: ["sequences"] });
      void qc.invalidateQueries({ queryKey: ["assets"] });
      void qc.invalidateQueries({ queryKey: ["jobs"] });
      void qc.invalidateQueries({ queryKey: ["workflows"] });
      void qc.invalidateQueries({ queryKey: ["generation-jobs"] });
    },
  });

  // 会话允许的工具自动批准。in-flight 集合防止轮询窗口内重复 approve。
  const autoApproving = React.useRef(new Set<string>());
  const items = pending.data ?? [];
  React.useEffect(() => {
    for (const item of items) {
      if (allowed.includes(item.tool) && !autoApproving.current.has(item.id)) {
        autoApproving.current.add(item.id);
        settle.mutate({ id: item.id, action: "approve" });
      }
    }
    // settle 引用稳定性由 useMutation 保证;items/allowed 变化时重扫。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, allowed]);

  const visible = items.filter((item) => !allowed.includes(item.tool));
  if (visible.length === 0) return null;

  return (
    // 与消息内容列同宽(780px 居中):此前裸 grid 吃满整个滚动区,确认卡横跨全屏。
    <div className="mx-auto grid w-full max-w-[780px] gap-2" role="region" aria-label={t("confirmTitle")}>
      {visible.map((item) => (
        <div className="grid gap-1.5 rounded-lg border border-border-strong border-l-[3px] border-l-primary bg-panel px-3 py-2.5 text-[12.5px]" key={item.id}>
          <div className="flex items-center justify-between gap-2">
            <span className="inline-flex min-w-0 items-center gap-1.5 font-semibold">
              <ShieldAlert size={13} /> {item.summary}
            </span>
            <PermissionBadge permission={item.permission} />
          </div>
          {/* 载荷保持展开:这张卡是智能体写操作与执行之间唯一的闸,摘要不足以构成知情同意
              (例如 add_node 可能藏着一段任意本地 Python)。高度有界,大图滚动而不是把按钮挤走。 */}
          <details open>
            <summary className="cursor-pointer select-none text-[11px] text-muted-foreground">{t("confirmPayload")}</summary>
            <pre className="mt-1.5 max-h-[220px] overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted p-2 font-mono text-[11px] leading-[1.5] [word-break:break-word]">{JSON.stringify(item.payload, null, 2)}</pre>
          </details>
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" disabled={settle.isPending} onClick={() => settle.mutate({ id: item.id, action: "approve" })}>
              <Check size={13} /> {t("confirmAllowOnce")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={settle.isPending}
              onClick={() => {
                allowTool(item.tool);
                settle.mutate({ id: item.id, action: "approve" });
              }}
            >
              <CheckCheck size={13} /> {t("confirmAllowSession")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="text-destructive"
              disabled={settle.isPending}
              onClick={() => settle.mutate({ id: item.id, action: "reject" })}
            >
              <X size={13} /> {t("confirmReject")}
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}

function PermissionBadge({ permission }: { permission: string }) {
  const t = useI18n();
  const label =
    permission === "edit" ? t("permEdit") : permission === "ai-cost" ? t("permAiCost") : t("permRenderCost");
  return <Badge variant={permission === "edit" ? "secondary" : "default"}>{label}</Badge>;
}
