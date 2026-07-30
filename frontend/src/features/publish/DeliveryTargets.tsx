import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderInput, Plus, Trash2, Webhook } from "lucide-react";
import { toast } from "sonner";

import {
  createDeliveryTarget,
  deleteDeliveryTarget,
  listDeliveryKinds,
  listDeliveryTargets,
  type DeliveryKind,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

/**
 * 交付目标:把成片送到本地目录 / POST 给外部自动化。
 *
 * 和「发布账号」分开陈列,不是分类洁癖 —— 它们在数据上就是两种东西:交付没有登录身份、
 * 没有平台、没有需要人介入的中间态。以前 folder/webhook 伪装成两个「发布平台」躺在浏览器池的
 * 添加账号弹窗里(而且是默认选项),建一个就在池子里多一个永远不会有登录态的空壳档案。
 */

const KIND_ICONS: Record<string, React.ReactNode> = {
  folder: <FolderInput size={14} />,
  webhook: <Webhook size={14} />,
};

export function DeliveryTargets({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [creating, setCreating] = React.useState(false);

  const targets = useQuery({
    queryKey: ["delivery-targets", workspace.id],
    queryFn: () => listDeliveryTargets(workspace.id),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["delivery-targets", workspace.id] });

  const remove = useMutation({
    mutationFn: (id: string) => deleteDeliveryTarget(id),
    onSuccess: refresh,
  });

  const list = targets.data ?? [];

  return (
    <div className="grid content-start gap-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-semibold tracking-[0.02em] text-muted-foreground">
          {t("deliveryTargets")}
        </div>
        <Button size="sm" variant="outline" className="h-7" onClick={() => setCreating(true)}>
          <Plus size={13} /> {t("deliveryTargetAdd")}
        </Button>
      </div>

      {list.length === 0 && targets.isSuccess ? (
        <EmptyState icon={<FolderInput size={22} />} title={t("deliveryEmpty")} body={t("deliveryEmptyBody")} />
      ) : (
        <ul className="grid list-none gap-1 p-0">
          {list.map((target) => (
            <li
              key={target.id}
              className="flex items-center gap-2 rounded-md border border-border bg-panel px-2.5 py-2 text-[12.5px]"
            >
              <span className="text-muted-foreground">{KIND_ICONS[target.kind]}</span>
              <span className="min-w-0 flex-1 truncate font-medium">{target.name}</span>
              <code className="timecode max-w-[280px] truncate text-[11px] text-muted-foreground">
                {target.config.directory ?? target.config.url ?? ""}
              </code>
              <button
                type="button"
                className="inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded border-0 bg-transparent text-muted-foreground hover:bg-secondary hover:text-destructive"
                aria-label={t("delete")}
                onClick={() => remove.mutate(target.id)}
              >
                <Trash2 size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <CreateTargetDialog open={creating} workspace={workspace} onClose={() => setCreating(false)} onCreated={refresh} />
    </div>
  );
}

function CreateTargetDialog({
  open,
  workspace,
  onClose,
  onCreated,
}: {
  open: boolean;
  workspace: Workspace;
  onClose: () => void;
  onCreated: () => void;
}) {
  const t = useI18n();
  const [kind, setKind] = React.useState("folder");
  const [name, setName] = React.useState("");
  const [config, setConfig] = React.useState<Record<string, string>>({});

  const kinds = useQuery({
    queryKey: ["delivery-kinds"],
    queryFn: listDeliveryKinds,
    enabled: open,
    staleTime: Infinity,
  });
  const meta = (kinds.data ?? []).find((item: DeliveryKind) => item.kind === kind) ?? null;
  const specs = Object.entries(meta?.config ?? {});

  const create = useMutation({
    mutationFn: () =>
      createDeliveryTarget({ workspace_id: workspace.id, kind, name: name.trim() || meta?.label || kind, config }),
    onSuccess: () => {
      setName("");
      setConfig({});
      onCreated();
      toast.success(t("deliveryTargetAdded"));
      onClose();
    },
    onError: (error: Error) => toast.error(t("deliveryTargetFailed"), { description: error.message }),
  });

  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onClose()} title={t("deliveryTargetAdd")}>
      <div className="grid gap-2.5">
        <label className={DIALOG_FIELD}>
          <span>{t("deliveryKind")}</span>
          <Select
            value={kind}
            onValueChange={(value) => {
              setKind(value);
              setConfig({});
            }}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(kinds.data ?? []).map((item: DeliveryKind) => (
                <SelectItem key={item.kind} value={item.kind}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {meta && <small>{meta.description}</small>}
        </label>
        <label className={DIALOG_FIELD}>
          <span>{t("deliveryTargetName")}</span>
          <Input value={name} placeholder={meta?.label} onChange={(event) => setName(event.target.value)} />
        </label>
        {specs.map(([key, spec]) => (
          <label className={DIALOG_FIELD} key={key}>
            <span>
              {key}
              {spec?.required ? " *" : ""}
            </span>
            <Input
              value={config[key] ?? ""}
              spellCheck={false}
              onChange={(event) => setConfig((current) => ({ ...current, [key]: event.target.value }))}
            />
            {spec?.description && <small>{spec.description}</small>}
          </label>
        ))}
        <div className="mt-1 flex justify-end gap-1.5">
          <Button variant="outline" size="sm" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button size="sm" disabled={create.isPending} onClick={() => create.mutate()}>
            <Plus size={13} /> {t("deliveryTargetAdd")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}
