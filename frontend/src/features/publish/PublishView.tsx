import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bug, CheckCircle2, CircleAlert, ExternalLink, FolderOutput, Loader2, LogIn, Plus, RefreshCcw, Rocket, Settings2, Sparkles, Trash2, Users } from "lucide-react";
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
  patchPublishAccount,
  recheckPublishAccount,
  type Asset,
  type PublishAccount,
  type PublishPlatform,
  type PublishTask,
  type Workspace,
} from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, ModalShell, RenameDialog } from "@/components/ui/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { relativeTime } from "@/lib/time";

const ACTIVE = new Set(["queued", "running", "pending"]);
// 受阻但可恢复(老版 BLOCKED_STATUSES):人工处理后可重试。
const BLOCKED = new Set(["login_required", "waiting_manual", "permission_required", "blocked"]);

/** 发布页(计划 §6.9 / Phase 13):成片 + 文案 → 发布目标,状态走任务总线。
 *  账号矩阵是一等页签:多平台账号的登录态、启停、复检都在这里管,登录会话
 *  由桌面端 persist: 分区持久化,重启不丢。 */
export function PublishView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [tab, setTab] = React.useState<"records" | "accounts">("records");
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  // 任务中心深链(mibu:open-* 事件通道):直接选中那条发布记录。
  React.useEffect(() => {
    const onOpenTask = (event: Event) => {
      const id = (event as CustomEvent<string>).detail;
      if (typeof id === "string" && id) {
        setSelectedId(id);
        setTab("records");
      }
    };
    window.addEventListener("mibu:open-publish-task", onOpenTask);
    return () => window.removeEventListener("mibu:open-publish-task", onOpenTask);
  }, []);
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
          setTab("accounts");
        }}
      />
      <AddAccountDialog open={managingAccounts} workspace={workspace} onClose={() => setManagingAccounts(false)} />
      <ConfirmDialog
        open={deleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("publishDeleteBody")}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </>
  );

  const seg = (
    <div className="publish-head">
      <div className="seg">
        <button
          type="button"
          className={tab === "records" ? "seg-btn active" : "seg-btn"}
          onClick={() => setTab("records")}
        >
          <Rocket size={13} /> {t("publishTabRecords")}
        </button>
        <button
          type="button"
          className={tab === "accounts" ? "seg-btn active" : "seg-btn"}
          onClick={() => setTab("accounts")}
        >
          <Users size={13} /> {t("publishTabAccounts")}
        </button>
      </div>
      {tab === "records" ? (
        <Button variant="outline" size="sm" onClick={() => setCreating(true)}>
          <Plus size={13} /> {t("publishCreate")}
        </Button>
      ) : (
        <Button variant="outline" size="sm" onClick={() => setManagingAccounts(true)}>
          <Plus size={13} /> {t("publishAccountAdd")}
        </Button>
      )}
    </div>
  );

  if (tab === "accounts") {
    return (
      <div className="feature-view">
        <div className="publish-col">
          {seg}
          <div className="publish-body">
            <AccountsPanel workspace={workspace} onAdd={() => setManagingAccounts(true)} />
          </div>
        </div>
        {dialogs}
      </div>
    );
  }

  if (tasks.isSuccess && (tasks.data ?? []).length === 0) {
    return (
      <div className="feature-view">
        <div className="publish-col">
          {seg}
          <div className="publish-body">
            <EmptyState
              icon={<Rocket size={22} />}
              title={t("publishEmptyTitle")}
              body={t("publishEmptyBody")}
              action={
                <div className="kb-empty-actions">
                  <Button onClick={() => setCreating(true)}>
                    <Plus size={15} /> {t("publishCreate")}
                  </Button>
                  <Button variant="outline" onClick={() => setTab("accounts")}>
                    <Settings2 size={15} /> {t("publishTabAccounts")}
                  </Button>
                </div>
              }
            />
          </div>
        </div>
        {dialogs}
      </div>
    );
  }

  return (
    <div className="feature-view">
      <div className="publish-col">
      {seg}
      <div className="publish-body plugins-shell">
        <aside className="plugins-list panel">
          <div className="panel-head">
            <h2>{t("navPublish")}</h2>
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
      </div>
      {dialogs}
    </div>
  );
}

/** 账号矩阵:多平台账号卡片墙。登录态、上次检测、启停、复检一屏看全。 */
function AccountsPanel({ workspace, onAdd }: { workspace: Workspace; onAdd: () => void }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const [renaming, setRenaming] = React.useState<PublishAccount | null>(null);
  const [removing, setRemoving] = React.useState<PublishAccount | null>(null);

  const platforms = useQuery({ queryKey: ["publish-platforms"], queryFn: listPublishPlatforms, staleTime: Infinity });
  const accounts = useQuery({
    queryKey: ["publish-accounts", workspace.id],
    queryFn: () => listPublishAccounts(workspace.id),
    // 复检/登录会在后台改登录态,轮询把徽标拉回真实状态。
    refetchInterval: 10000,
    refetchIntervalInBackground: true,
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["publish-accounts", workspace.id] });

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { name?: string; enabled?: boolean } }) =>
      patchPublishAccount(id, body),
    onSuccess: () => {
      setRenaming(null);
      refresh();
    },
  });
  const recheck = useMutation({
    mutationFn: (id: string) => recheckPublishAccount(id),
    onSuccess: () => {
      toast.success(t("publishRecheckQueued"));
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deletePublishAccount(id),
    onSuccess: () => {
      setRemoving(null);
      refresh();
    },
  });

  const items = accounts.data ?? [];
  if (accounts.isSuccess && items.length === 0) {
    return (
      <EmptyState
        icon={<Users size={22} />}
        title={t("publishNoAccountsTitle")}
        body={t("publishNoAccountsBody")}
        action={
          <Button onClick={onAdd}>
            <Plus size={15} /> {t("publishAccountAdd")}
          </Button>
        }
      />
    );
  }

  return (
    <div className="acct-grid">
      {items.map((account) => {
        const meta = (platforms.data ?? []).find((p) => p.platform === account.platform);
        const isBrowser = meta?.executor === "browser";
        return (
          <ContextMenu key={account.id}>
            <ContextMenuTrigger asChild>
              <div className={account.enabled ? "acct-card panel" : "acct-card panel disabled"}>
                <div className="acct-head">
                  <span className="acct-platform">{meta?.label ?? account.platform}</span>
                  {isBrowser ? (
                    <em className={`publish-binding b-${account.binding_status}`}>
                      {t(`binding_${account.binding_status}` as never)}
                    </em>
                  ) : (
                    <em className="publish-binding b-bound">{t("publishLocalExecutor")}</em>
                  )}
                </div>
                <strong className="acct-name">{account.name}</strong>
                <small className="acct-meta">
                  {isBrowser
                    ? `${account.profile_name ? `${account.profile_name} · ` : ""}${
                        account.last_checked_at
                          ? t("publishLastChecked").replace("{t}", relativeTime(account.last_checked_at, locale))
                          : t("publishNeverChecked")
                      }`
                    : t("publishLocalHint")}
                </small>
                {/* 状态行恒占位:有错误显示错误,否则空占位,保证同排卡片行数一致。 */}
                <small className={account.last_error ? "acct-error" : "acct-error placeholder"}>
                  {account.last_error ?? " "}
                </small>
                <div className="acct-actions">
                  {isBrowser && (
                    <Button
                      size="sm"
                      variant="outline"
                      title={window.mibuPublish ? undefined : t("publishNeedDesktop")}
                      disabled={!window.mibuPublish}
                      onClick={() => {
                        window.mibuPublish
                          ?.login(account.id, account.platform)
                          .then(() => toast.success(t("publishLoginOpened")))
                          .catch((error: Error) => toast.error(error.message));
                      }}
                    >
                      <LogIn size={13} /> {t("publishLogin")}
                    </Button>
                  )}
                  {isBrowser && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={recheck.isPending}
                      onClick={() => recheck.mutate(account.id)}
                    >
                      <RefreshCcw size={13} /> {t("publishRecheck")}
                    </Button>
                  )}
                  <span className="acct-spacer" />
                  <Switch
                    checked={account.enabled}
                    onCheckedChange={(next) => patch.mutate({ id: account.id, body: { enabled: next } })}
                    aria-label={t("publishAccountEnabled")}
                  />
                </div>
              </div>
            </ContextMenuTrigger>
            <ContextMenuContent>
              <ContextMenuItem onSelect={() => setRenaming(account)}>{t("rename")}</ContextMenuItem>
              {isBrowser && window.mibuPublish && (
                <ContextMenuItem
                  onSelect={() => {
                    window.mibuPublish
                      ?.inspect(account.id, account.platform)
                      .then((ok) => (ok ? undefined : toast.error(t("publishInspectFailed"))))
                      .catch((error: Error) => toast.error(error.message));
                  }}
                >
                  <Bug /> {t("publishInspect")}
                </ContextMenuItem>
              )}
              <ContextMenuItem destructive onSelect={() => setRemoving(account)}>
                <Trash2 /> {t("delete")}
              </ContextMenuItem>
            </ContextMenuContent>
          </ContextMenu>
        );
      })}
      <RenameDialog
        open={renaming !== null}
        title={t("rename")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        onSubmit={(value) => renaming && patch.mutate({ id: renaming.id, body: { name: value } })}
      />
      <ConfirmDialog
        open={removing !== null}
        title={t("deleteConfirmTitle")}
        body={t("publishAccountDeleteBody")}
        onCancel={() => setRemoving(null)}
        onConfirm={() => removing && remove.mutate(removing.id)}
      />
    </div>
  );
}

function PublishDetail({ task, onDelete }: { task: PublishTask; onDelete: () => void }) {
  const t = useI18n();
  const platforms = useQuery({ queryKey: ["publish-platforms"], queryFn: listPublishPlatforms, staleTime: Infinity });
  const isBrowser =
    (platforms.data ?? []).find((item) => item.platform === task.platform)?.executor === "browser";
  const ok = task.status === "succeeded" || task.status === "success" || task.status === "prepared";
  return (
    <div className="plugins-detail-body">
      <SettingsGroup
        title={task.title || task.asset_name}
        description={`${task.account_name} · ${task.platform} · ${t(`batchStatus_${task.status}` as never)}`}
        actions={
          <div className="sched-actions">
            {ACTIVE.has(task.status) ? (
              <Loader2 size={14} className="spin" />
            ) : ok ? (
              <CheckCircle2 size={14} className="inv-ok" />
            ) : BLOCKED.has(task.status) ? (
              <CircleAlert size={14} className="publish-blocked-icon" />
            ) : (
              <CircleAlert size={14} className="inv-bad" />
            )}
            {isBrowser && window.mibuPublish && (
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  window.mibuPublish
                    ?.openPage(task.account_id, task.platform)
                    .catch((error: Error) => toast.error(error.message))
                }
              >
                <ExternalLink size={13} /> {t("publishOpenPage")}
              </Button>
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

/** 添加发布账号(纯创建弹窗;列表/管理在账号矩阵页签)。 */
function AddAccountDialog({ open, workspace, onClose }: { open: boolean; workspace: Workspace; onClose: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [platform, setPlatform] = React.useState("folder");
  const [name, setName] = React.useState("");
  const [config, setConfig] = React.useState<Record<string, string>>({});

  const platforms = useQuery({ queryKey: ["publish-platforms"], queryFn: listPublishPlatforms, enabled: open, staleTime: Infinity });
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
      onClose();
    },
    onError: (error: Error) => toast.error(t("publishAccountFailed"), { description: error.message }),
  });

  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onClose()} title={t("publishAccountAdd")}>
      <div className="task-create-form">
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
  const [shortTitle, setShortTitle] = React.useState("");
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
  const platforms = useQuery({ queryKey: ["publish-platforms"], queryFn: listPublishPlatforms, enabled: open, staleTime: Infinity });
  const videos = (assets.data ?? []).filter((asset) => asset.kind === "video");
  const selectedAccount = (accounts.data ?? []).find((account) => account.id === accountId) ?? null;
  const platformMeta =
    (platforms.data ?? []).find((item) => item.platform === selectedAccount?.platform) ?? null;
  const titleMax = platformMeta?.title_max ?? 300;

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
        short_title: shortTitle.trim(),
      }),
    onSuccess: (task) => {
      setTitle("");
      setShortTitle("");
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
          <span>
            {t("publishTitle")}
            <em className={title.length > titleMax ? "publish-title-count over" : "publish-title-count"}>
              {title.length}/{titleMax}
            </em>
          </span>
          <Input value={title} maxLength={titleMax + 20} onChange={(event) => setTitle(event.target.value)} />
        </label>
        {platformMeta?.short_title && (
          <label className="wf-field">
            <span>{t("publishShortTitle")}</span>
            <Input value={shortTitle} maxLength={20} onChange={(event) => setShortTitle(event.target.value)} />
          </label>
        )}
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
