/**
 * 删连接、卸载插件时,背后本机服务的安装目录怎么办(ADR 0041 §4「卸载」):
 *
 * - 让 Mosael 装的那一份在 `<数据目录>/local-services/<连接>/` 下:确认框里多两个勾 ——「同时删掉 Mosael 装的这一份(多大)」
 *   和「保留模型(多大)」(挪到 kept-models,以后能在「共用的模型文件夹」里一键加回来)。缺省两个都勾着;不删就留在磁盘上;
 * - 选目录那一种在那里只有 Mosael 写的共用模型配置:不问,跟着连接删掉(你自己的 ComfyUI 目录从来不碰);
 * - 卸载插件:它的连接里还有几份就一起问一次;
 * - 只有部署管理员问得到、删得了(那是这台机器上的东西);别人删连接时安装目录照旧留着。问不到(插件用不了)就说清楚、留着。
 */
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  getLocalServiceFootprint,
  listLocalServiceInstalls,
  removePluginInstance,
  removePluginPackage,
  type LocalServiceFootprint,
} from "@/api/client";
import { useIsDeploymentAdmin } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { ConfirmDialog } from "@/components/app/modals";
import { Checkbox } from "@/components/ui/checkbox";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import { formatBytes } from "@/lib/bytes";

interface Choice {
  remove: boolean;
  keepModels: boolean;
}

/** 两个勾:一起删(多大、在哪)、保留模型(多大、挪到哪)。`installs` 是要处置的那几份(删连接是一份,卸载插件可能几份)。 */
function InstallChoice({ installs, choice, onChange }: { installs: readonly LocalServiceFootprint[]; choice: Choice; onChange: (next: Choice) => void }) {
  const t = useI18n();
  const bytes = installs.reduce((sum, one) => sum + one.bytes, 0);
  const models = installs.reduce((sum, one) => sum + one.models_bytes, 0);
  const withModels = installs.filter((one) => one.has_models);
  const where = installs.length === 1 ? installs[0].directory : installs.map((one) => one.name).join(t("listSeparator"));
  const keepTo = withModels.length === 1 ? withModels[0].keep_to : withModels.map((one) => one.keep_to).join(t("listSeparator"));
  return (
    <div className="grid gap-3 text-ui-sm" data-local-service-removal>
      <label className="flex cursor-pointer items-start gap-2">
        <Checkbox className="mt-0.5" checked={choice.remove} onCheckedChange={(value) => onChange({ ...choice, remove: value === true })} />
        <span className="grid min-w-0 gap-0.5">
          <span className="font-medium">{t("localServiceRemoveInstall").replace("{size}", formatBytes(bytes))}</span>
          <small className="break-all text-ui-xs text-muted-foreground">{t("localServiceRemoveInstallDesc").replace("{where}", where)}</small>
        </span>
      </label>
      {withModels.length > 0 && (
        <label className="ml-6 flex cursor-pointer items-start gap-2">
          <Checkbox
            className="mt-0.5"
            checked={choice.remove && choice.keepModels}
            disabled={!choice.remove}
            onCheckedChange={(value) => onChange({ ...choice, keepModels: value === true })}
          />
          <span className="grid min-w-0 gap-0.5">
            <span className="font-medium">{t("localServiceKeepModels").replace("{size}", formatBytes(models))}</span>
            <small className="break-all text-ui-xs text-muted-foreground">{t("localServiceKeepModelsDesc").replace("{where}", keepTo)}</small>
          </span>
        </label>
      )}
    </div>
  );
}

/** 问不到安装目录里有什么(插件用不了):说清楚,这一次安装目录留着。 */
function FootprintError({ error }: { error: Error }) {
  const t = useI18n();
  return <p role="alert" className="m-0 text-ui-sm text-warning">{t("localServiceFootprintError").replace("{error}", error.message)}</p>;
}

const DEFAULT_CHOICE: Choice = { remove: true, keepModels: true };

/** 删一个连接的确认框。声明了本机服务的插件、部署管理员打开时先问一声它留着什么。 */
export function DeleteConnectionDialog({
  packageId,
  hasServices,
  instance,
  open,
  onCancel,
  onDeleted,
}: {
  packageId: string;
  hasServices: boolean;
  instance: { id: string; name: string };
  open: boolean;
  onCancel: () => void;
  onDeleted: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const admin = useIsDeploymentAdmin();
  const asks = open && admin && hasServices;
  const footprint = useQuery({
    queryKey: ["local-service-footprint", packageId, instance.id],
    queryFn: () => getLocalServiceFootprint(instance.id),
    enabled: asks,
    retry: false,
    staleTime: 0,
  });
  const [choice, setChoice] = React.useState<Choice>(DEFAULT_CHOICE);
  React.useEffect(() => {
    if (open) setChoice(DEFAULT_CHOICE);
  }, [open]);
  const found = asks ? footprint.data ?? null : null;
  const remove = useMutation({
    mutationFn: () =>
      removePluginInstance(
        instance.id,
        // 让 Mosael 装的那一份照人选的;只有共用模型配置的(选目录那一种)跟着连接删
        found ? (found.installed ? { choice: choice.remove ? "remove" : "keep", keepModels: choice.keepModels && found.has_models } : { choice: "remove", keepModels: false }) : undefined,
      ),
    onSuccess: () => {
      onDeleted();
      invalidatePluginDependents(qc);
    },
    onError: (error: Error) => toast.error(error.message),
  });
  return (
    <ConfirmDialog
      open={open}
      title={t("pluginDeleteConnectionTitle").replace("{name}", instance.name)}
      body={t("pluginDeleteConnectionBody")}
      onCancel={onCancel}
      pending={remove.isPending || (asks && footprint.isFetching)}
      onConfirm={() => remove.mutate()}
    >
      {asks && footprint.error ? <FootprintError error={footprint.error as Error} /> : null}
      {found?.installed ? <InstallChoice installs={[found]} choice={choice} onChange={setChoice} /> : null}
    </ConfirmDialog>
  );
}

/** 卸载插件的确认框:它的连接里还留着让 Mosael 装的那几份时,一起问要不要删、要不要保留模型。 */
export function UninstallPluginDialog({
  packageId,
  name,
  open,
  onCancel,
  onDone,
}: {
  packageId: string;
  name: string;
  open: boolean;
  onCancel: () => void;
  onDone: () => void;
}) {
  const t = useI18n();
  const installs = useQuery({
    queryKey: ["local-service-installs", packageId],
    queryFn: () => listLocalServiceInstalls(packageId),
    enabled: open,
    retry: false,
    staleTime: 0,
  });
  const [choice, setChoice] = React.useState<Choice>(DEFAULT_CHOICE);
  React.useEffect(() => {
    if (open) setChoice(DEFAULT_CHOICE);
  }, [open]);
  const found = installs.data ?? [];
  const installed = found.filter((one) => one.installed);
  const uninstall = useMutation({
    mutationFn: () =>
      removePluginPackage(
        packageId,
        // 问不到也得说一声:安装目录留着(删不删、留哪些模型要问插件)
        installs.error
          ? { choice: "keep", keepModels: false }
          : found.length === 0
            ? undefined
            : installed.length === 0 || choice.remove
              ? { choice: "remove", keepModels: choice.keepModels }
              : { choice: "keep", keepModels: false },
      ),
    onSuccess: onDone,
    onError: (error: Error) => toast.error(error.message),
  });
  return (
    <ConfirmDialog
      open={open}
      title={t("pluginUninstallTitle").replace("{name}", name)}
      body={t("pluginUninstallBody")}
      confirmLabel={t("pluginUninstall")}
      pending={uninstall.isPending || installs.isFetching}
      onCancel={onCancel}
      onConfirm={() => uninstall.mutate()}
    >
      {installs.error ? <FootprintError error={installs.error as Error} /> : null}
      {installed.length > 0 && (
        <div className="grid gap-3">
          <p className="m-0 text-ui-sm">{t("pluginUninstallLocalServices").replace("{count}", String(installed.length))}</p>
          <InstallChoice installs={installed} choice={choice} onChange={setChoice} />
        </div>
      )}
    </ConfirmDialog>
  );
}
