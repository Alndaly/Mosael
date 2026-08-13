import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import { createPublishAccount, listPublishPlatforms, type PublishPlatform, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

/** 添加发布账号(= 挂平台的浏览器池档案):选平台 + 配置 + 代理。归口「浏览器池」——账号的「增」和
 *  「管」都在池里,发布页专心做发布。建成后同时刷新 publish-accounts 与 browser-profiles 两处列表。 */
export function AddAccountDialog({
  open,
  workspace,
  onClose,
}: {
  open: boolean;
  workspace: Workspace;
  onClose: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [platform, setPlatform] = React.useState("douyin");
  const [name, setName] = React.useState("");
  const [config, setConfig] = React.useState<Record<string, string>>({});
  const [proxy, setProxy] = React.useState("");

  const platforms = useQuery({ queryKey: ["publish-platforms"], queryFn: listPublishPlatforms, enabled: open, staleTime: Infinity });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["publish-accounts", workspace.id] });
    void qc.invalidateQueries({ queryKey: ["browser-profiles", workspace.id] });
  };

  const meta = (platforms.data ?? []).find((item) => item.platform === platform) ?? null;
  const configSpecs = Object.entries((meta?.config ?? {}) as Record<string, { description?: string; required?: boolean }>);

  const create = useMutation({
    mutationFn: () =>
      createPublishAccount({
        workspace_id: workspace.id,
        platform,
        name: name.trim() || meta?.label || platform,
        config,
        proxy: proxy.trim() || null,
      }),
    onSuccess: () => {
      setName("");
      setConfig({});
      setProxy("");
      refresh();
      toast.success(t("publishAccountAdded"));
      onClose();
    },
    onError: (error: Error) => toast.error(t("publishAccountFailed"), { description: error.message }),
  });

  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onClose()} title={t("publishAccountAdd")}>
      <div className="grid gap-2.5 [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
        <label className={DIALOG_FIELD}>
          <span>{t("publishPlatform")}</span>
          <Select
            value={platform}
            onValueChange={(value) => {
              setPlatform(value);
              setConfig({});
            }}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(platforms.data ?? []).map((item: PublishPlatform) => (
                <SelectItem key={item.platform} value={item.platform}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {meta && <small>{meta.description}</small>}
        </label>
        <label className={DIALOG_FIELD}>
          <span>{t("publishAccountName")}</span>
          <Input value={name} placeholder={meta?.label} onChange={(event) => setName(event.target.value)} />
        </label>
        {configSpecs.map(([key, spec]) => (
          <label className={DIALOG_FIELD} key={key}>
            <span>
              {key}
              {spec?.required ? " *" : ""}
            </span>
            <Input
              value={config[key] ?? ""}
              onChange={(event) => setConfig((current) => ({ ...current, [key]: event.target.value }))}
            />
            {spec?.description && <small>{spec.description}</small>}
          </label>
        ))}
        <label className={DIALOG_FIELD}>
          <span>{t("publishProxy")}</span>
          <Input
            value={proxy}
            placeholder="http://user:pass@host:port"
            spellCheck={false}
            onChange={(event) => setProxy(event.target.value)}
          />
          <small>{t("publishProxyHint")}</small>
        </label>
        <div className="mt-1 flex justify-end gap-1.5">
          <Button variant="outline" size="sm" onClick={onClose}>
            {t("close")}
          </Button>
          <Button size="sm" loading={create.isPending} onClick={() => create.mutate()}>
            <Plus size={13} /> {t("publishAccountAdd")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}
