import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldAlert, X } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useInlineConfirmSurfaceOpen } from "@/components/agent/confirmSurface";

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

  // 聊天面板打开时确认卡走对话内联(InlineConfirmations),这里让位——
  // 否则同一张卡出现两份,而且这层 fixed 卡曾被 z-index 更高的 AI 助手浮窗整块盖住。
  const inlineOpen = useInlineConfirmSurfaceOpen();

  const items = pending.data ?? [];
  if (inlineOpen || items.length === 0) return null;

  return (
    <div className="confirm-stack" role="region" aria-label={t("confirmTitle")}>
      {items.map((item) => (
        <div className="confirm-card" key={item.id}>
          <div className="confirm-head">
            <span className="confirm-source">
              <ShieldAlert size={13} /> {t("confirmTitle")} · {item.requested_by}
            </span>
            <PermissionBadge permission={item.permission} />
          </div>
          <p className="confirm-summary">{item.summary}</p>
          {/* The whole payload, expanded. This card is the only thing standing between an
              agent-proposed mutation and it happening, and the summary alone was not enough to
              consent to: "1 个工作流编辑: add_node" hides a code node whose body is arbitrary
              local Python, which a later run executes unsandboxed. Collapsed-by-default would
              keep the same problem, since nobody expands. Bounded height so a large graph
              scrolls instead of pushing the buttons off screen. */}
          <details className="confirm-payload" open>
            <summary>{t("confirmPayload")}</summary>
            <pre>{JSON.stringify(item.payload, null, 2)}</pre>
          </details>
          <div className="confirm-actions">
            <Button
              size="sm"
              disabled={settle.isPending}
              onClick={() => settle.mutate({ id: item.id, action: "approve" })}
            >
              <Check size={13} /> {t("confirmApprove")}
            </Button>
            <Button
              size="sm"
              variant="outline"
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
