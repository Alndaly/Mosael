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
/** 三档动作。顺序固定:允许一次 → 本会话始终允许 → 拒绝,从最小授权到最大再到否。 */
type Choice = "once" | "session" | "reject";

const CHOICES = [
  { choice: "once", icon: Check, label: "confirmAllowOnce", variant: undefined, className: undefined },
  { choice: "session", icon: CheckCheck, label: "confirmAllowSession", variant: "outline", className: undefined },
  { choice: "reject", icon: X, label: "confirmReject", variant: "outline", className: "text-destructive" },
] as const satisfies readonly {
  choice: Choice;
  icon: typeof Check;
  label: "confirmAllowOnce" | "confirmAllowSession" | "confirmReject";
  variant?: "outline";
  className?: string;
}[];

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

  /**
   * 三档动作走**同一个** mutation —— 因为「谁在转」要由它的变量说了算。
   *
   * 此前是两个 mutation、三个按钮共读 `isPending`,于是点任何一个,同屏所有卡的所有按钮一起转。
   * 转圈的意思是"我正在做这件事";六个一起转说的是另一件事,而这张卡正是需要知情同意的地方。
   * 变量里带上卡的 id 和选了哪一档,`decide.variables` 就直接是"此刻在飞的是哪一个"。
   *
   * 「本会话始终允许」的两步(写白名单 → 批准)也收在这里顺序 await:它对用户是一个动作,
   * 就该从头到尾转同一个按钮 —— 拆成两个 mutation 时,第二步一起手,转的会变成隔壁那个。
   */
  const decide = useMutation({
    mutationFn: async ({ id, tool, choice }: { id: string; tool: string; choice: Choice }) => {
      if (choice === "session") {
        // 先写白名单再批准:反过来的话,同一工具的下一张卡可能赶在白名单落库前就被判成手动。
        const session = await api<AgentSession>(`/api/agent/sessions/${allowKey}`);
        const next = Array.from(new Set([...(session.auto_allow_tools ?? []), tool]));
        await api(`/api/agent/sessions/${allowKey}`, {
          method: "PATCH",
          body: JSON.stringify({ auto_allow_tools: next }),
        });
        void qc.invalidateQueries({ queryKey: ["agent-session", allowKey] });
      }
      return api<Confirmation>(`/api/confirmations/${id}/${choice === "reject" ? "reject" : "approve"}`, {
        method: "POST",
      });
    },
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

  // 此刻在飞的是哪一张卡的哪一档。没有就是 null。
  const busy = decide.isPending ? decide.variables : null;

  const items = pending.data ?? [];
  if (items.length === 0) return null;

  return (
    // 与消息内容列同宽(780px 居中):此前裸 grid 吃满整个滚动区,确认卡横跨全屏。
    <div className="mx-auto grid w-full max-w-[780px] gap-2" role="region" aria-label={t("confirmTitle")}>
      {items.map((item) => (
        <div className="grid gap-1.5 rounded-lg border border-border-strong border-l-[3px] border-l-primary bg-panel px-3 py-2.5 text-ui-sm" key={item.id}>
          <div className="flex items-center justify-between gap-2">
            <span className="inline-flex min-w-0 items-center gap-1.5 font-semibold">
              <ShieldAlert size={13} /> {item.summary}
            </span>
            <PermissionBadge permission={item.permission} />
          </div>
          {/* 载荷保持展开:这张卡是智能体写操作与执行之间唯一的闸,摘要不足以构成知情同意
              (例如 add_node 可能藏着一段任意本地 Python)。高度有界,大图滚动而不是把按钮挤走。 */}
          <details open>
            <summary className="cursor-pointer select-none text-ui-xs text-muted-foreground">{t("confirmPayload")}</summary>
            <pre className="mt-1.5 max-h-[220px] overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted p-2 font-mono text-ui-xs leading-[1.5] [word-break:break-word]">{JSON.stringify(item.payload, null, 2)}</pre>
          </details>
          {/* 转的只有被点的那一个;同一张卡的另外两个禁掉(一张卡只能有一个结论),
              别的卡完全不受影响 —— 它等的不是同一件事。 */}
          <div className="flex flex-wrap gap-1.5">
            {CHOICES.map(({ choice, icon: Icon, label, variant, className }) => (
              <Button
                key={choice}
                size="sm"
                variant={variant}
                className={className}
                loading={busy?.id === item.id && busy.choice === choice}
                disabled={busy?.id === item.id}
                onClick={() => decide.mutate({ id: item.id, tool: item.tool, choice })}
              >
                <Icon size={13} /> {t(label)}
              </Button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
