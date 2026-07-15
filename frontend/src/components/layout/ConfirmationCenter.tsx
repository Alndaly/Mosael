import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldAlert, X } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

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
    refetchIntervalInBackground: true,
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

  const items = pending.data ?? [];
  if (items.length === 0) return null;

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
          {item.tool === "edit_timeline" && (
            <ul className="confirm-ops">
              {((item.payload.operations as Array<Record<string, unknown>>) ?? []).slice(0, 5).map((operation, index) => (
                <li key={index} className="timecode">
                  {String(operation.kind)}
                  {operation.timeline_start != null ? ` @ ${Number(operation.timeline_start).toFixed(2)}s` : ""}
                </li>
              ))}
            </ul>
          )}
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
