import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { KeyRound, Link2, Loader2, MessageSquare, QrCode, RefreshCcw, Trash2 } from "lucide-react";

import { api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { ModalShell } from "@/components/app/modals";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

type FeishuBot = components["schemas"]["FeishuBotOut"];
type Onboarding = components["schemas"]["FeishuOnboardingOut"];
type BindCode = components["schemas"]["FeishuBindCodeOut"];
type Binding = components["schemas"]["FeishuBindingOut"];

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
    refetchOnWindowFocus: true,
  });

  const onboarding = useQuery({
    queryKey: ["feishu-onboarding", workspace.id],
    enabled: scanning,
    queryFn: () => api<Onboarding>(`/api/feishu/onboarding/${workspace.id}`),
    refetchInterval: 2000,
    refetchOnWindowFocus: true,
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
      if (state.qr_url) void QRCode.toDataURL(state.qr_url, { width: 180, margin: 1 }).then(setQrDataUrl);
    },
    onError: () => {
      setScanning(false); // request failed → close the just-opened dialog
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

  // Account binding: the bot acts with the bound member's permissions, so a Feishu user
  // must bind first. Member issues a code, then DMs it to the bot.
  const [bindBotId, setBindBotId] = React.useState<string | null>(null);
  const [bindCode, setBindCode] = React.useState<BindCode | null>(null);
  const issueCode = useMutation({
    mutationFn: (botId: string) => api<BindCode>(`/api/feishu/bots/${botId}/bind-code`, { method: "POST" }),
    onSuccess: (code, botId) => {
      setBindBotId(botId);
      setBindCode(code);
    },
  });
  const bindings = useQuery({
    queryKey: ["feishu-bindings", bindBotId],
    enabled: Boolean(bindBotId),
    queryFn: () => api<Binding[]>(`/api/feishu/bots/${bindBotId}/bindings`),
    // 弹窗开着就轮询:用户在飞书里发绑定码,回来这里应当实时看到绑定成功,不用手动刷新。
    refetchInterval: 2000,
    refetchOnWindowFocus: true,
  });
  const removeBinding = useMutation({
    mutationFn: (openId: string) => api(`/api/feishu/bots/${bindBotId}/bindings/${openId}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["feishu-bindings", bindBotId] }),
  });

  const hasBots = (bots.data ?? []).length > 0;

  return (
    <SettingsGroup
      title={t("feishuTitle")}
      description={t("feishuDesc")}
      actions={
        <>
          {/* 两种绑定方式是平级选择,同一视觉重量,不做主次 */}
          {/* 先弹窗再发请求:点击即开弹层(展示加载态),二维码随请求返回再填,避免"卡一下才弹"。 */}
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setScanning(true);
              beginScan.mutate();
            }}
            disabled={scanning}
          >
            <QrCode size={13} /> {t("feishuScanCreate")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setManualOpen(true)}>
            <KeyRound size={13} /> {t("feishuManualToggle")}
          </Button>
        </>
      }
    >
      <SettingsBlock>
        {beginScan.isError && <p className="m-0 text-xs text-destructive">{String((beginScan.error as Error).message)}</p>}

        {hasBots && (
          <div className="grid gap-1.5">
            {(bots.data ?? []).map((bot) => (
              <div className="grid grid-cols-[32px_minmax(0,1fr)_auto] items-center gap-2.5 rounded-lg border border-border bg-panel px-3 py-2" key={bot.id}>
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary">
                  <MessageSquare size={15} />
                </span>
                <div className="min-w-0 [&_small]:block [&_small]:truncate [&_small]:font-mono [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-[13px] [&_strong]:font-semibold">
                  <div className="flex min-w-0 items-center gap-2">
                    <strong>{bot.name}</strong>
                    <StatusBadge status={bot.status} />
                  </div>
                  <small title={bot.status_detail || undefined}>
                    {bot.app_id}
                    {bot.status_detail ? ` · ${bot.status_detail}` : ""}
                  </small>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Select
                    value={bot.capability}
                    onValueChange={(capability) => patchBot.mutate({ id: bot.id, body: { capability } })}
                  >
                    <SelectTrigger className="h-8 w-[104px]" title={t("feishuCapability")} aria-label={t("feishuCapability")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CAPABILITIES.map((capability) => (
                        <SelectItem key={capability} value={capability}>
                          {capability === "readonly"
                            ? t("feishuCapReadonly")
                            : capability === "editor"
                              ? t("feishuCapEditor")
                              : t("feishuCapFull")}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
                  <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => issueCode.mutate(bot.id)} title={t("feishuBind")} aria-label={t("feishuBind")}>
                    <Link2 size={14} />
                  </Button>
                  <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => restartBot.mutate(bot.id)} title={t("feishuRestart")} aria-label={t("feishuRestart")}>
                    <RefreshCcw size={14} />
                  </Button>
                  <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive" onClick={() => removeBot.mutate(bot.id)} title={t("feishuRemove")} aria-label={t("feishuRemove")}>
                    <Trash2 size={14} />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

        {!hasBots && (
          <EmptyState icon={<MessageSquare size={22} />} title={t("feishuNoBots")} body={t("feishuEmptyBody")} />
        )}
      </SettingsBlock>

      <ModalShell
        open={scanning}
        onOpenChange={(next) => {
          if (!next) {
            setScanning(false);
            setQrDataUrl(null);
          }
        }}
        title={t("feishuScanCreate")}
      >
        <div className="flex items-center gap-3.5 [&_img]:rounded [&_img]:bg-white [&_img]:p-1 [&_p]:mb-1 [&_p]:mt-0 [&_p]:text-xs">
          {qrDataUrl ? (
            <img src={qrDataUrl} alt="Feishu QR" />
          ) : (
            <div className="flex h-[188px] w-[188px] shrink-0 items-center justify-center rounded-md bg-panel-inset text-muted-foreground" aria-hidden>
              <Loader2 size={20} className="animate-mibu-spin" />
            </div>
          )}
          <div>
            <p>{t("feishuScanHint")}</p>
            <p className="text-muted-foreground">
              {beginScan.isError
                ? String((beginScan.error as Error).message)
                : onboarding.data?.phase === "error"
                  ? onboarding.data.error
                  : qrDataUrl
                    ? t("feishuWaitingScan")
                    : t("feishuQrLoading")}
              {onboarding.data?.user_code ? ` · ${onboarding.data.user_code}` : ""}
            </p>
          </div>
        </div>
      </ModalShell>

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
          {addBot.isError && <p className="m-0 text-xs text-destructive">{String((addBot.error as Error).message)}</p>}
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

      <ModalShell
        open={Boolean(bindCode)}
        onOpenChange={(next) => {
          if (!next) {
            setBindCode(null);
            setBindBotId(null);
          }
        }}
        title={t("feishuBindTitle")}
      >
        <div className="grid gap-3">
          <p className="text-[13px] text-muted-foreground">{t("feishuBindHint")}</p>
          <code className="block rounded-lg border border-border bg-background p-2.5 text-center text-[22px] font-semibold tracking-[0.22em] tabular-nums">{bindCode?.code}</code>
          <div className="grid gap-1.5">
            <small className="text-[12px] text-muted-foreground">{t("feishuBindMembers")}</small>
            {(bindings.data ?? []).length === 0 ? (
              <small className="text-[12px] text-muted-foreground">{t("feishuBindNobody")}</small>
            ) : (
              (bindings.data ?? []).map((binding) => (
                <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-background px-2 py-1 text-[13px]" key={binding.open_id}>
                  <span className="truncate">{binding.username}</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-muted-foreground hover:text-destructive"
                    onClick={() => removeBinding.mutate(binding.open_id)}
                    title={t("feishuUnbind")}
                    aria-label={t("feishuUnbind")}
                  >
                    <Trash2 size={13} />
                  </Button>
                </div>
              ))
            )}
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
  // 状态点 + 语义色淡底:在线绿 / 连接中主色 / 出错红 / 离线灰,不再用重色实心徽章。
  const tone =
    status === "online"
      ? "bg-[color-mix(in_srgb,var(--success)_14%,transparent)] text-[var(--success)]"
      : status === "connecting"
        ? "bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary"
        : status === "error"
          ? "bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-destructive"
          : "bg-secondary text-muted-foreground";
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-px text-[10.5px] font-semibold ${tone}`}>
      <i className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      {label}
    </span>
  );
}
