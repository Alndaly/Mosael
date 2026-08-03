import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type VendorPreset = components["schemas"]["VendorPresetOut"];

/**
 * 「我在这条连接上的钥匙」。
 *
 * 和编辑连接是两件事,所以是两个入口:连接(端点、模型目录、定价)是部署的配置,只有部署管理员
 * 能改;钥匙是谁在花钱、以谁的身份调用,每个人配自己的。共享那一档是例外 —— 那把钥匙是整个
 * 部署在花钱,只有部署管理员能置位(后端同样把关)。
 */
export function MyKeyDialog({
  profile,
  preset,
  canShare,
  onClose,
}: {
  profile: ProviderProfile;
  preset: VendorPreset | undefined;
  canShare: boolean;
  onClose: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const secretFields = (preset?.fields ?? []).filter((f) => f.secret && f.storage !== "api_key");
  const [apiKey, setApiKey] = React.useState("");
  const [secrets, setSecrets] = React.useState<Record<string, string>>({});
  const [shared, setShared] = React.useState(profile.my_key_shared);

  const save = useMutation({
    mutationFn: () =>
      api(`/api/settings/providers/${profile.id}/credential`, {
        method: "PUT",
        body: JSON.stringify({ api_key: apiKey || null, secrets, shared }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["provider-profiles"] });
      onClose();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const forget = useMutation({
    mutationFn: () => api(`/api/settings/providers/${profile.id}/credential`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["provider-profiles"] });
      onClose();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && onClose()}
      title={t("providerMyKey").replace("{name}", profile.name)}
    >
      <small className="block pb-1 text-[11px] text-muted-foreground">{t("providerMyKeyHint")}</small>
      <div className={DIALOG_FIELD}>
        <label>API Key</label>
        {/* 存着的那把从不回传浏览器,只回尾四位 —— 留空即「不改」。 */}
        <Input
          type="password"
          value={apiKey}
          placeholder={profile.key_hint || t("providerKeyKeepHint")}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </div>
      {secretFields.map((field) => (
        <div className={DIALOG_FIELD} key={field.key}>
          <label>{field.label}</label>
          <Input
            type="password"
            value={secrets[field.key] ?? ""}
            placeholder={t("providerKeyKeepHint")}
            onChange={(e) => setSecrets((prev) => ({ ...prev, [field.key]: e.target.value }))}
          />
        </div>
      ))}
      {canShare && (
        <div className="flex items-start gap-2.5 pt-1">
          <Switch checked={shared} onCheckedChange={setShared} aria-label={t("providerShareKey")} />
          <div className="grid gap-0.5">
            <span className="text-xs font-medium">{t("providerShareKey")}</span>
            <small className="text-[11px] text-muted-foreground">{t("providerShareKeyHint")}</small>
          </div>
        </div>
      )}
      <div className="flex items-center gap-2 pt-2">
        {profile.is_mine && (
          <Button variant="ghost" className="mr-auto text-destructive" loading={forget.isPending} onClick={() => forget.mutate()}>
            {t("providerForgetKey")}
          </Button>
        )}
        <span className="flex-1" />
        <Button variant="outline" onClick={onClose}>
          {t("cancel")}
        </Button>
        <Button loading={save.isPending} onClick={() => save.mutate()}>
          {t("save")}
        </Button>
      </div>
    </ModalShell>
  );
}
