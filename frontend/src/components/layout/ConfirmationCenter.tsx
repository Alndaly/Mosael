import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldAlert, X } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { useInlineConfirmSessions } from "@/components/agent/confirmSurface";
import { PermissionBadge } from "@/components/agent/PermissionBadge";

type Confirmation = components["schemas"]["ConfirmationOut"];

/**
 * Global confirmation cards (plan §16.2): external agents propose mutations,
 * nothing runs until the user approves here.
 */
export function ConfirmationCenter({ workspaceId }: { workspaceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const pending = useQuery({
    queryKey: ["confirmations", workspaceId, "pending"],
    queryFn: () => api<Confirmation[]>(`/api/confirmations?workspace_id=${workspaceId}&status=pending`),
    refetchInterval: 2500,
    refetchOnWindowFocus: true,
  });

  const settle = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "reject" }) =>
      api<Confirmation>(`/api/confirmations/${id}/${action}`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["confirmations", workspaceId, "pending"] });
      void qc.invalidateQueries({ queryKey: ["sequences"] });
      void qc.invalidateQueries({ queryKey: ["assets"] });
      void qc.invalidateQueries({ queryKey: ["jobs"] });
      void qc.invalidateQueries({ queryKey: ["generation-jobs"] });
    },
  });

  // 按**归属**分工,而不是「有内联面就整体让位」:
  //  - 卡属于某个正开着的对话 → 那边内联显示,这里跳过(否则同一张卡出现两份);
  //  - 卡没有会话(MCP / 飞书等外部智能体)或它那次对话没开着 → 这里兜底,否则没人显示,
  //    智能体会一直干等。
  // 旧写法是「只要有任何内联面就整体返回 null」,于是一开聊天面板,外部智能体的卡也跟着被藏掉。
  const handledSessions = useInlineConfirmSessions();

  // 此刻在飞的是哪一张卡的哪一档 —— 同 InlineConfirmations。直接读 `settle.isPending` 的话,
  // 屏上每张卡的每个按钮会一起转:转圈的意思是"我正在做这件事",而它们没有。
  const busy = settle.isPending ? settle.variables : null;

  const items = (pending.data ?? []).filter(
    (item) => !item.session_id || !handledSessions.includes(item.session_id),
  );
  if (items.length === 0) return null;

  return (
    <div className="fixed right-4 top-14 z-[60] grid w-[340px] gap-2" role="region" aria-label={t("confirmTitle")}>
      {items.map((item) => (
        <div className="animate-confirm-in rounded-lg border border-border-strong bg-popover px-3 py-2.5 shadow-[var(--shadow-raised)]" key={item.id}>
          <div className="mb-1.5 flex items-center justify-between gap-1.5">
            <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
              <ShieldAlert size={13} /> {t("confirmTitle")} · {item.requested_by}
            </span>
            <PermissionBadge permission={item.permission} />
          </div>
          <p className="mb-2 mt-0 text-[13px] font-semibold leading-[1.45]">{item.summary}</p>
          {/* The whole payload, expanded. This card is the only thing standing between an
              agent-proposed mutation and it happening, and the summary alone was not enough to
              consent to: "1 个工作流编辑: add_node" hides a code node whose body is arbitrary
              local Python, which a later run executes unsandboxed. Collapsed-by-default would
              keep the same problem, since nobody expands. Bounded height so a large graph
              scrolls instead of pushing the buttons off screen. */}
          <details open>
            <summary className="cursor-pointer select-none text-[11px] text-muted-foreground">{t("confirmPayload")}</summary>
            <pre className="mt-1.5 max-h-[220px] overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted p-2 font-mono text-[11px] leading-[1.5] [word-break:break-word]">{JSON.stringify(item.payload, null, 2)}</pre>
          </details>
          <div className="flex gap-1.5">
            {/* 转的只有被点的那一个;同一张卡的另一个禁掉 —— 一张卡只能有一个结论。 */}
            <Button
              size="sm"
              loading={busy?.id === item.id && busy.action === "approve"}
              disabled={busy?.id === item.id}
              onClick={() => settle.mutate({ id: item.id, action: "approve" })}
            >
              <Check size={13} /> {t("confirmApprove")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              loading={busy?.id === item.id && busy.action === "reject"}
              disabled={busy?.id === item.id}
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

