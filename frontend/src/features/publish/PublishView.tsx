import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, FolderOutput, Loader2, Plus, Rocket, Settings2, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  api,
  createPublishAccount,
  createPublishTask,
  deletePublishAccount,
  deletePublishTask,
  generatePublishCopy,
  listPublishAccounts,
  listPublishPlatforms,
  listPublishTasks,
  type Asset,
  type PublishAccount,
  type PublishPlatform,
  type PublishTask,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, ModalShell } from "@/components/ui/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SettingsGroup, SettingsRow } from "@/features/settings/ui";

const ACTIVE = new Set(["queued", "running"]);

/** 发布页(计划 §6.9 / Phase 13):成片 + 文案 → 发布目标,状态走任务总线。 */
export function PublishView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);
  const [managingAccounts, setManagingAccounts] = React.useState(false);
  const [deleting, setDeleting] = React.useState<PublishTask | null>(null);

  const tasks = useQuery({
    queryKey: ["publish-tasks", workspace.id],
    queryFn: () => listPublishTasks(workspace.id),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((task) => ACTIVE.has(task.status)) ? 2000 : false,
    refetchIntervalInBackground: true,
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["publish-tasks", workspace.id] });

  const remove = useMutation({
    mutationFn: (id: string) => deletePublishTask(id),
    onSuccess: () => {
      setDeleting(null);
      refresh();
    },
  });

  const selected = (tasks.data ?? []).find((task) => task.id === selectedId) ?? (tasks.data ?? [])[0] ?? null;

  const dialogs = (
    <>
      <CreatePublishDialog
        open={creating}
        workspace={workspace}
        onClose={() => setCreating(false)}
        onCreated={(task) => {
          setCreating(false);
          setSelectedId(task.id);
          refresh();
        }}
        onManageAccounts={() => {
          setCreating(false);
          setManagingAccounts(true);
        }}
      />
      <AccountsDialog open={managingAccounts} workspace={workspace} onClose={() => setManagingAccounts(false)} />
      <ConfirmDialog
        open={deleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("publishDeleteBody")}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </>
  );

  if (tasks.isSuccess && (tasks.data ?? []).length === 0) {
    return (
      <div className="feature-view">
        <EmptyState
          icon={<Rocket size={22} />}
          title={t("publishEmptyTitle")}
          body={t("publishEmptyBody")}
          action={
            <div className="kb-empty-actions">
              <Button onClick={() => setCreating(true)}>
                <Plus size={15} /> {t("publishCreate")}
              </Button>
              <Button variant="outline" onClick={() => setManagingAccounts(true)}>
                <Settings2 size={15} /> {t("publishAccounts")}
              </Button>
            </div>
          }
        />
        {dialogs}
      </div>
    );
  }

  return (
    <div className="feature-view">
      <div className="plugins-shell">
        <aside className="plugins-list panel">
          <div className="panel-head">
            <h2>{t("navPublish")}</h2>
            <div className="kb-list-actions">
              <Button size="icon-sm" variant="ghost" title={t("publishAccounts")} onClick={() => setManagingAccounts(true)}>
                <Settings2 size={14} />
              </Button>
              <Button variant="outline" size="sm" onClick={() => setCreating(true)}>
                <Plus size={13} /> {t("publishCreate")}
              </Button>
            </div>
          </div>
          <div className="plugins-list-body">
            {(tasks.data ?? []).map((task) => (
              <ContextMenu key={task.id}>
                <ContextMenuTrigger asChild>
                  <button
                    type="button"
                    className={selected?.id === task.id ? "plugins-item active" : "plugins-item"}
                    onClick={() => setSelectedId(task.id)}
                  >
                    <span className={ACTIVE.has(task.status) ? "plugins-dot on" : "plugins-dot"} />
                    <span className="plugins-item-text">
                      <strong>{task.title || task.asset_name}</strong>
                      <small>
                        {task.account_name} · {t(`batchStatus_${task.status}` as never)}
                      </small>
                    </span>
                  </button>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem destructive onSelect={() => setDeleting(task)}>
                    <Trash2 /> {t("delete")}
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            ))}
          </div>
        </aside>
        <div className="plugins-detail">
          {selected ? (
            <PublishDetail key={selected.id} task={selected} onDelete={() => setDeleting(selected)} />
          ) : (
            <EmptyState icon={<Rocket size={22} />} title={t("publishEmptyTitle")} body={t("publishEmptyBody")} />
          )}
        </div>
      </div>
      {dialogs}
    </div>
  );
}

function PublishDetail({ task, onDelete }: { task: PublishTask; onDelete: () => void }) {
  const t = useI18n();
  return (
    <div className="plugins-detail-body">
      <SettingsGroup
        title={task.title || task.asset_name}
        description={`${task.account_name} · ${task.platform}`}
        actions={
          <div className="sched-actions">
            {ACTIVE.has(task.status) ? (
              <Loader2 size={14} className="spin" />
            ) : task.status === "succeeded" ? (
              <CheckCircle2 size={14} className="inv-ok" />
            ) : (
              <CircleAlert size={14} className="inv-bad" />
            )}
            <Button size="sm" variant="outline" className="sched-delete" onClick={onDelete}>
              <Trash2 size={13} /> {t("delete")}
            </Button>
          </div>
        }
      >
        <SettingsRow label={t("publishAsset")} description={t("publishAssetDesc")}>
          <code className="timecode sg-value">{task.asset_name}</code>
        </SettingsRow>
        {task.description && (
          <SettingsRow label={t("publishDescription")}>
            <span className="publish-desc">{task.description}</span>
          </SettingsRow>
        )}
        {task.tags.length > 0 && (
          <SettingsRow label={t("publishTags")}>
            <span className="publish-tags">
              {task.tags.map((tag) => (
                <span className="tag-chip readonly" key={tag}>
                  {tag}
                </span>
              ))}
            </span>
          </SettingsRow>
        )}
        {task.status === "succeeded" && task.result.target != null && (
          <SettingsRow label={t("publishResult")} description={t("publishResultDesc")}>
            <code className="timecode sg-value publish-target" title={String(task.result.target)}>
              <FolderOutput size={12} /> {String(task.result.target)}
            </code>
          </SettingsRow>
        )}
        {task.status === "failed" && task.error && (
          <SettingsRow label={t("publishError")}>
            <span className="publish-error">{task.error}</span>
          </SettingsRow>
        )}
      </SettingsGroup>
    </div>
  );
}

/** 账号管理:平台注册表驱动的添加表单 + 现有账号列表。 */
function AccountsDialog({ open, workspace, onClose }: { open: boolean; workspace: Workspace; onClose: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [platform, setPlatform] = React.useState("folder");
  const [name, setName] = React.useState("");
  const [config, setConfig] = React.useState<Record<string, string>>({});

  const platforms = useQuery({ queryKey: ["publish-platforms"], queryFn: listPublishPlatforms, enabled: open, staleTime: Infinity });
  const accounts = useQuery({
    queryKey: ["publish-accounts", workspace.id],
    queryFn: () => listPublishAccounts(workspace.id),
    enabled: open,
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["publish-accounts", workspace.id] });

  const meta = (platforms.data ?? []).find((item) => item.platform === platform) ?? null;
  const configSpecs = Object.entries((meta?.config ?? {}) as Record<string, { description?: string; required?: boolean }>);

  const create = useMutation({
    mutationFn: () =>
      createPublishAccount({
        workspace_id: workspace.id,
        platform,
        name: name.trim() || meta?.label || platform,
        config,
      }),
    onSuccess: () => {
      setName("");
      setConfig({});
      refresh();
      toast.success(t("publishAccountAdded"));
    },
    onError: (error: Error) => toast.error(t("publishAccountFailed"), { description: error.message }),
  });
  const remove = useMutation({ mutationFn: (id: string) => deletePublishAccount(id), onSuccess: refresh });

  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onClose()} title={t("publishAccounts")}>
      <div className="task-create-form">
        {(accounts.data ?? []).length > 0 && (
          <div className="publish-account-list">
            {(accounts.data ?? []).map((account: PublishAccount) => (
              <div className="publish-account" key={account.id}>
                <span className="publish-account-text">
                  <strong>{account.name}</strong>
                  <small>{(platforms.data ?? []).find((p: PublishPlatform) => p.platform === account.platform)?.label ?? account.platform}</small>
                </span>
                <Button size="icon-sm" variant="ghost" aria-label={t("delete")} onClick={() => remove.mutate(account.id)}>
                  <Trash2 size={13} />
                </Button>
              </div>
            ))}
          </div>
        )}
        <label className="wf-field">
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
        <label className="wf-field">
          <span>{t("publishAccountName")}</span>
          <Input value={name} placeholder={meta?.label} onChange={(event) => setName(event.target.value)} />
        </label>
        {configSpecs.map(([key, spec]) => (
          <label className="wf-field" key={key}>
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
        <div className="task-create-actions">
          <Button variant="outline" size="sm" onClick={onClose}>
            {t("close")}
          </Button>
          <Button size="sm" disabled={create.isPending} onClick={() => create.mutate()}>
            <Plus size={13} /> {t("publishAccountAdd")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}

/** 新建发布:成片 + 账号 + 文案(可 AI 生成)。 */
function CreatePublishDialog({
  open,
  workspace,
  onClose,
  onCreated,
  onManageAccounts,
}: {
  open: boolean;
  workspace: Workspace;
  onClose: () => void;
  onCreated: (task: PublishTask) => void;
  onManageAccounts: () => void;
}) {
  const t = useI18n();
  const [assetId, setAssetId] = React.useState<string | null>(null);
  const [accountId, setAccountId] = React.useState<string | null>(null);
  const [title, setTitle] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [tagsText, setTagsText] = React.useState("");

  const assets = useQuery({
    queryKey: ["assets", workspace.id],
    queryFn: () => api<Asset[]>(`/api/assets?workspace_id=${workspace.id}`),
    enabled: open,
  });
  const accounts = useQuery({
    queryKey: ["publish-accounts", workspace.id],
    queryFn: () => listPublishAccounts(workspace.id),
    enabled: open,
  });
  const videos = (assets.data ?? []).filter((asset) => asset.kind === "video");

  const aiCopy = useMutation({
    mutationFn: () => generatePublishCopy({ workspace_id: workspace.id, asset_id: assetId }),
    onSuccess: (copy) => {
      setTitle(copy.title);
      setDescription(copy.description);
      setTagsText(copy.tags.join(", "));
      toast.success(t("publishCopyDone"));
    },
    onError: (error: Error) => toast.error(t("publishCopyFailed"), { description: error.message }),
  });
  const create = useMutation({
    mutationFn: () =>
      createPublishTask({
        workspace_id: workspace.id,
        account_id: accountId!,
        asset_id: assetId!,
        title: title.trim(),
        description: description.trim(),
        tags: tagsText
          .split(/[,，\s]+/)
          .map((tag) => tag.trim())
          .filter(Boolean),
      }),
    onSuccess: (task) => {
      setTitle("");
      setDescription("");
      setTagsText("");
      onCreated(task);
    },
    onError: (error: Error) => toast.error(t("publishFailedToast"), { description: error.message }),
  });

  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onClose()} title={t("publishCreate")}>
      <div className="task-create-form">
        <label className="wf-field">
          <span>{t("publishAsset")}</span>
          <Select value={assetId ?? ""} onValueChange={setAssetId}>
            <SelectTrigger>
              <SelectValue placeholder={t("publishPickAsset")} />
            </SelectTrigger>
            <SelectContent>
              {videos.map((asset) => (
                <SelectItem key={asset.id} value={asset.id}>
                  {asset.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {videos.length === 0 && assets.isSuccess && <small>{t("publishNoVideos")}</small>}
        </label>
        <label className="wf-field">
          <span>{t("publishAccount")}</span>
          <Select value={accountId ?? ""} onValueChange={setAccountId}>
            <SelectTrigger>
              <SelectValue placeholder={t("publishPickAccount")} />
            </SelectTrigger>
            <SelectContent>
              {(accounts.data ?? []).map((account: PublishAccount) => (
                <SelectItem key={account.id} value={account.id}>
                  {account.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {(accounts.data ?? []).length === 0 && accounts.isSuccess && (
            <small>
              {t("publishNoAccounts")}{" "}
              <button type="button" className="publish-inline-link" onClick={onManageAccounts}>
                {t("publishAccounts")}
              </button>
            </small>
          )}
        </label>
        <label className="wf-field">
          <span>{t("publishTitle")}</span>
          <Input value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label className="wf-field">
          <span>{t("publishDescription")}</span>
          <textarea
            rows={3}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <label className="wf-field">
          <span>{t("publishTags")}</span>
          <Input value={tagsText} placeholder={t("publishTagsPlaceholder")} onChange={(event) => setTagsText(event.target.value)} />
        </label>
        <div className="task-create-actions publish-create-actions">
          <Button variant="outline" size="sm" disabled={aiCopy.isPending || !assetId} onClick={() => aiCopy.mutate()}>
            {aiCopy.isPending ? <Loader2 size={13} className="spin" /> : <Sparkles size={13} />} {t("publishAiCopy")}
          </Button>
          <span className="publish-actions-spacer" />
          <Button variant="outline" size="sm" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button size="sm" disabled={!assetId || !accountId || create.isPending} onClick={() => create.mutate()}>
            <Rocket size={13} /> {t("publishStart")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}
