import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { KeyRound, MessageSquare, QrCode, RefreshCcw, Trash2 } from "lucide-react";

import { api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { ModalShell } from "@/components/ui/modals";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

type FeishuBot = components["schemas"]["FeishuBotOut"];
type Onboarding = components["schemas"]["FeishuOnboardingOut"];

const CAPABILITIES = ["readonly", "editor", "full"] as const;

export function FeishuSection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [manualOpen, setManualOpen] = React.useState(false);
  const [appId, setAppId] = React.useState("");
  const [appSecret, setAppSecret] = React.useState("");
  const [scanning, setScanning] = React.useState(false);
  const [qrDataUrl, setQrDataUrl] = React.useState<string | null>(null);

  const bots = useQuery({
    queryKey: ["feishu-bots", workspace.id],
    queryFn: () => api<FeishuBot[]>(`/api/feishu/bots?workspace_id=${workspace.id}`),
    refetchInterval: 4000,
    refetchIntervalInBackground: true,
  });

  const onboarding = useQuery({
    queryKey: ["feishu-onboarding", workspace.id],
    enabled: scanning,
    queryFn: () => api<Onboarding>(`/api/feishu/onboarding/${workspace.id}`),
    refetchInterval: 2000,
    refetchIntervalInBackground: true,
  });

  React.useEffect(() => {
    const url = onboarding.data?.qr_url;
    if (url) {
      void QRCode.toDataURL(url, { width: 180, margin: 1 }).then(setQrDataUrl);
    }
    if (onboarding.data?.phase === "done") {
      setScanning(false);
      setQrDataUrl(null);
      void qc.invalidateQueries({ queryKey: ["feishu-bots", workspace.id] });
    }
  }, [onboarding.data?.qr_url, onboarding.data?.phase, qc, workspace.id]);

  const beginScan = useMutation({
    mutationFn: () => api<Onboarding>(`/api/feishu/onboarding/${workspace.id}`, { method: "POST" }),
    onSuccess: (state) => {
      setScanning(true);
      if (state.qr_url) void QRCode.toDataURL(state.qr_url, { width: 180, margin: 1 }).then(setQrDataUrl);
    },
  });

  const addBot = useMutation({
    mutationFn: () =>
      api<FeishuBot>("/api/feishu/bots", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, app_id: appId.trim(), app_secret: appSecret.trim() }),
      }),
    onSuccess: () => {
      setAppId("");
      setAppSecret("");
      setManualOpen(false);
      void qc.invalidateQueries({ queryKey: ["feishu-bots", workspace.id] });
    },
  });

  const patchBot = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api<FeishuBot>(`/api/feishu/bots/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["feishu-bots", workspace.id] }),
  });
  const restartBot = useMutation({
    mutationFn: (id: string) => api<FeishuBot>(`/api/feishu/bots/${id}/restart`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["feishu-bots", workspace.id] }),
  });
  const removeBot = useMutation({
    mutationFn: (id: string) => api(`/api/feishu/bots/${id}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["feishu-bots", workspace.id] }),
  });

  const hasBots = (bots.data ?? []).length > 0;

  return (
    <SettingsGroup
      title={t("feishuTitle")}
      description={t("feishuDesc")}
      actions={
        <>
          <Button size="sm" onClick={() => beginScan.mutate()} disabled={beginScan.isPending || scanning}>
            <QrCode size={13} /> {t("feishuScanCreate")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setManualOpen(true)}>
            <KeyRound size={13} /> {t("feishuManualToggle")}
          </Button>
        </>
      }
    >
      <SettingsBlock>
        {beginScan.isError && <p className="login-error">{String((beginScan.error as Error).message)}</p>}

        {scanning && (
          <div className="feishu-qr">
            {qrDataUrl ? <img src={qrDataUrl} alt="Feishu QR" /> : null}
            <div>
              <p>{t("feishuScanHint")}</p>
              <p className="feishu-qr-status">
                {onboarding.data?.phase === "error" ? onboarding.data.error : t("feishuWaitingScan")}
                {onboarding.data?.user_code ? ` · ${onboarding.data.user_code}` : ""}
              </p>
            </div>
          </div>
        )}

        {hasBots && (
          <div className="feishu-bots">
            {(bots.data ?? []).map((bot) => (
              <div className="feishu-bot" key={bot.id}>
                <span className="feishu-bot-icon">
                  <MessageSquare size={14} />
                </span>
                <div className="feishu-bot-body">
                  <strong>{bot.name}</strong>
                  <small>
                    {bot.app_id}
                    {bot.status_detail ? ` · ${bot.status_detail}` : ""}
                  </small>
                </div>
                <StatusBadge status={bot.status} />
                <div className="feishu-bot-actions">
                  <select
                    value={bot.capability}
                    onChange={(event) => patchBot.mutate({ id: bot.id, body: { capability: event.target.value } })}
                  >
                    {CAPABILITIES.map((capability) => (
                      <option key={capability} value={capability}>
                        {capability === "readonly"
                          ? t("feishuCapReadonly")
                          : capability === "editor"
                            ? t("feishuCapEditor")
                            : t("feishuCapFull")}
                      </option>
                    ))}
                  </select>
                  <Button variant="ghost" size="icon-sm" onClick={() => restartBot.mutate(bot.id)} aria-label={t("feishuRestart")}>
                    <RefreshCcw size={13} />
                  </Button>
                  <Button variant="ghost" size="icon-sm" onClick={() => removeBot.mutate(bot.id)} aria-label={t("feishuRemove")}>
                    <Trash2 size={13} />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

        {!hasBots && !scanning && (
          <EmptyState icon={<MessageSquare size={22} />} title={t("feishuNoBots")} body={t("feishuEmptyBody")} />
        )}
      </SettingsBlock>

      <ModalShell open={manualOpen} onOpenChange={(next) => !next && setManualOpen(false)} title={t("feishuManualToggle")}>
        <div className="grid gap-3">
          <p className="text-[13px] text-muted-foreground">{t("feishuManualBody")}</p>
          <Input placeholder={t("feishuAppId")} value={appId} onChange={(event) => setAppId(event.target.value)} autoFocus />
          <Input
            type="password"
            placeholder={t("feishuAppSecret")}
            value={appSecret}
            onChange={(event) => setAppSecret(event.target.value)}
          />
          {addBot.isError && <p className="login-error">{String((addBot.error as Error).message)}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setManualOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              size="sm"
              disabled={!appId.trim() || !appSecret.trim() || addBot.isPending}
              onClick={() => addBot.mutate()}
            >
              {t("feishuAdd")}
            </Button>
          </div>
        </div>
      </ModalShell>
    </SettingsGroup>
  );
}

function StatusBadge({ status }: { status: string }) {
  const t = useI18n();
  const label =
    status === "online"
      ? t("feishuStatusOnline")
      : status === "connecting"
        ? t("feishuStatusConnecting")
        : status === "error"
          ? t("feishuStatusError")
          : t("feishuStatusOffline");
  return <Badge variant={status === "online" ? "default" : "secondary"}>{label}</Badge>;
}
