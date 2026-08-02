import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCheck, ShieldAlert, X } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { registerInlineConfirmSurface } from "@/components/agent/confirmSurface";
import { PermissionBadge } from "@/components/agent/PermissionBadge";

type Confirmation = components["schemas"]["ConfirmationOut"];
type AgentSession = components["schemas"]["AgentSessionOut"];

/**
 * 聊天流里的确认卡(Claude Code / Codex 式):智能体提出的写操作在对话里就地决策,
 * 三档动作——允许一次 / 本会话始终允许(按工具记忆)/ 拒绝。
 *
 * 此前确认只存在于右上角的全局 ConfirmationCenter,而它 z-index 低于 AI 助手浮窗,
 * 会被整块盖住——模型说"等待您的确认",用户却什么都看不到。现在:聊天面板打开时
 * 卡片就在对话里(本组件),全局中心让位(见 confirmSurface.ts);没有聊天面板时
 * 全局中心照常兜底(MCP / 飞书等外部智能体仍走它)。
 *
 * **「本会话始终允许」是服务端策略**,不是这里的一段自动批准。它此前记在 localStorage 里、
 * 由本组件挂载期间轮询自动批 —— 于是聊天面板一关组件就卸载,而 turn 还在跑:同一个"授权"的
 * 行为取决于某个 React 组件在不在,飞书和 MCP 那两条入口更是完全够不着。现在点它只是把工具名
 * 写进会话的白名单,放行由后端在开卡的那一刻判定(domain/agent/autopilot)。
 */
/** `allowKey` 就是**会话 id**:既是白名单挂靠的会话,也是确认卡的归属筛选键。 */
export function InlineConfirmations({ workspaceId, allowKey }: { workspaceId: string; allowKey: string }) {
  const t = useI18n();
  const qc = useQueryClient();

  // 挂载登记:全局中心据此知道**这个会话**的卡已经有人管了,不再重复显示(其余照常兜底)。
  React.useEffect(() => registerInlineConfirmSurface(allowKey), [allowKey]);

  // **只取本会话的卡**。此前拉的是整个工作区的 pending —— 于是同工作区其它对话、工作流节点、
  // MCP/飞书外部智能体的确认卡都会挤进当前对话,用户以为授的是「这次对话」,实际授的是别人的。
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

  /** 把这个工具加进会话白名单 —— 后端从此在开卡那一刻就放行它,不必等某个组件挂着。 */
  const allowTool = useMutation({
    mutationFn: async (tool: string) => {
      const session = await api<AgentSession>(`/api/agent/sessions/${allowKey}`);
      const next = Array.from(new Set([...(session.auto_allow_tools ?? []), tool]));
      return api(`/api/agent/sessions/${allowKey}`, {
        method: "PATCH",
        body: JSON.stringify({ auto_allow_tools: next }),
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["agent-session", allowKey] });
    },
  });

  const items = pending.data ?? [];
  if (items.length === 0) return null;

  return (
    // 与消息内容列同宽(780px 居中):此前裸 grid 吃满整个滚动区,确认卡横跨全屏。
    <div className="mx-auto grid w-full max-w-[780px] gap-2" role="region" aria-label={t("confirmTitle")}>
      {items.map((item) => (
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
            <Button size="sm" loading={settle.isPending} onClick={() => settle.mutate({ id: item.id, action: "approve" })}>
              <Check size={13} /> {t("confirmAllowOnce")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              loading={settle.isPending || allowTool.isPending}
              onClick={() => {
                // 先写白名单再批准:反过来的话,同一工具的下一张卡可能赶在白名单落库前就被判成手动。
                allowTool.mutate(item.tool, {
                  onSuccess: () => settle.mutate({ id: item.id, action: "approve" }),
                });
              }}
            >
              <CheckCheck size={13} /> {t("confirmAllowSession")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="text-destructive"
              loading={settle.isPending}
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
