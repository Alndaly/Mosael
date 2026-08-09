import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, ExternalLink, FolderOutput, Loader2, Plus, Rocket, Sparkles, Trash2, Users } from "lucide-react";
import { toast } from "sonner";

import {
  api,
  createPublishTask,
  deletePublishTask,
  generatePublishCopy,
  listPublishAccounts,
  listPublishPlatforms,
  listPublishTasks,
  type Asset,
  type PublishAccount,
  type PublishTask,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Combobox } from "@/components/app/combobox";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { gotoRecord } from "@/lib/deepLink";
import { usePersistentSelection } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["queued", "running", "pending"]);
// 受阻但可恢复(老版 BLOCKED_STATUSES):人工处理后可重试。
const BLOCKED = new Set(["login_required", "waiting_manual", "permission_required", "blocked"]);

/** 发布页(计划 §6.9 / Phase 13):成片 + 文案 → 发布目标,状态走任务总线。
 *  账号矩阵是一等页签:多平台账号的登录态、启停、复检都在这里管,登录会话
 *  由桌面端 persist: 分区持久化,重启不丢。 */
export function PublishView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();

  // 任务中心深链(openstudio:open-* 事件通道):直接选中那条发布记录。
  React.useEffect(() => {
    const onOpenTask = (event: Event) => {
      const id = (event as CustomEvent<string>).detail;
      if (typeof id === "string" && id) {
        setSelectedId(id);
      }
    };
    window.addEventListener("openstudio:open-publish-task", onOpenTask);
    return () => window.removeEventListener("openstudio:open-publish-task", onOpenTask);
  }, []);
  const [creating, setCreating] = React.useState(false);
  const [deleting, setDeleting] = React.useState<PublishTask | null>(null);

  const tasks = useQuery({
    queryKey: ["publish-tasks", workspace.id],
    queryFn: () => listPublishTasks(workspace.id),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((task) => ACTIVE.has(task.status)) ? 2000 : false,
    refetchOnWindowFocus: true,
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["publish-tasks", workspace.id] });

  const remove = useMutation({
    mutationFn: (id: string) => deletePublishTask(id),
    onSuccess: () => {
      refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setDeleting(null);
    },
  });

  // 选中的那一个**活过导航** —— 切走再回来还停在他刚才看的那条(见 lib/usePersistentTab)。
  // 它被删掉时自动回落到列表第一条,那正是下面这行本来就在做的事。
  const [selectedId, setSelectedId] = usePersistentSelection("publish", (tasks.data ?? []).map((task) => task.id));
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
          gotoRecord("/browser-pool"); // 账号管理归口浏览器池;没账号时引导过去添加
        }}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("publishDeleteBody")}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </>
  );

  // 账号的「增」和「管」都归口「浏览器池」tab;发布页只做发布(记录 + 新建发布)。
  const seg = (
    <div className="flex items-center justify-between">
      <h2 className="m-0 inline-flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
        <Rocket size={13} /> {t("publishTabRecords")}
      </h2>
      <Button variant="outline" size="sm" onClick={() => setCreating(true)}>
        <Plus size={13} /> {t("publishCreate")}
      </Button>
    </div>
  );

  if (tasks.isSuccess && (tasks.data ?? []).length === 0) {
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-3.5 [&>*]:shrink-0">
        <div className="flex h-full min-h-0 flex-col gap-1.5">
          {seg}
          {/* 高度由 flex-1 撑满剩余空间;不能再叠 min-h-full——那是「父容器整高」,
              会把上方分段条的高度顶出去,整页多出一截可滚动。 */}
          <div className="grid min-h-0 flex-1 place-items-center overflow-y-auto">
            <EmptyState
              icon={<Rocket size={22} />}
              title={t("publishEmptyTitle")}
              body={t("publishEmptyBody")}
              action={
                <div className="flex items-center gap-1.5">
                  <Button onClick={() => setCreating(true)}>
                    <Plus size={15} /> {t("publishCreate")}
                  </Button>
                  <Button variant="outline" onClick={() => gotoRecord("/browser-pool")}>
                    <Users size={15} /> {t("publishAccountAdd")}
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
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-3.5 [&>*]:shrink-0">
      <div className="flex h-full min-h-0 flex-col gap-1.5">
      {seg}
      <div className="grid min-h-0 min-w-0 flex-1 grid-cols-[260px_minmax(0,1fr)] gap-2 max-[880px]:grid-cols-[minmax(0,1fr)] max-[880px]:grid-rows-[auto_minmax(0,1fr)] overflow-y-auto">
        <aside className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid grid-rows-[auto_minmax(0,1fr)] max-[880px]:flex max-[880px]:items-center max-[880px]:gap-1.5 max-[880px]:px-1.5 max-[880px]:py-[5px] max-[880px]:[&>div:first-child]:contents">
          <div className="flex min-h-10 items-center justify-between border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-[11px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
            <h2>{t("publishListTitle")}</h2>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)] content-start gap-1 overflow-y-auto overflow-x-hidden p-1.5 [&:has(>.empty-inline:only-child)]:content-stretch max-[880px]:order-1 max-[880px]:flex max-[880px]:min-w-0 max-[880px]:flex-1 max-[880px]:items-center max-[880px]:gap-1.5 max-[880px]:overflow-x-auto max-[880px]:p-0">
            {(tasks.data ?? []).map((task) => (
              <ContextMenu key={task.id}>
                <ContextMenuTrigger asChild>
                  <button
                    type="button"
                    className={cn("flex min-w-0 cursor-pointer items-center gap-[9px] rounded-md border-0 bg-transparent px-2 py-1.5 text-left transition-colors duration-100 hover:bg-muted max-[880px]:w-auto max-[880px]:shrink-0 max-[880px]:py-1", selected?.id === task.id && "bg-accent hover:bg-accent")}
                    onClick={() => setSelectedId(task.id)}
                  >
                    <span className={cn("h-[7px] w-[7px] shrink-0 rounded-full bg-border-strong", ACTIVE.has(task.status) && "bg-[#22c55e]")} />
                    <span className="min-w-0 flex-1 [&_small]:block [&_small]:truncate [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-[12.5px] [&_strong]:font-semibold max-[880px]:[&_small]:hidden">
                      <strong>{task.title || task.asset_name}</strong>
                      <small>
                        {task.account_name} · {t(`batchStatus_${task.status}` as never)}
                      </small>
                    </span>
                  </button>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => setDeleting(task)}>
                    <Trash2 /> {t("delete")}
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            ))}
          </div>
        </aside>
        <div className="grid min-w-0 overflow-y-auto overflow-x-hidden">
          {selected ? (
            <PublishDetail key={selected.id} task={selected} onDelete={() => setDeleting(selected)} />
          ) : (
            <div className="grid min-h-full place-items-center">
              <EmptyState icon={<Rocket size={22} />} title={t("pickDetailTitle")} body={t("pickDetailBody")} />
            </div>
          )}
        </div>
      </div>
      </div>
      {dialogs}
    </div>
  );
}

/** 详情行:标签固定窄列 + 值紧随其右、左对齐填满剩余宽度(读起来是"字段:内容",
 *  而不是设置页那种"标签左、控件甩到最右"、中间一大片空白)。窄屏改成上下堆叠。 */
function InfoRow({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[124px_minmax(0,1fr)] items-start gap-4 px-3.5 py-2.5 max-[520px]:grid-cols-1 max-[520px]:gap-1">
      <dt className="grid content-start gap-0.5 pt-px">
        <span className="text-[12.5px] font-medium text-foreground">{label}</span>
        {description && <span className="text-[11px] leading-[1.4] text-muted-foreground">{description}</span>}
      </dt>
      <dd className="m-0 min-w-0 text-[12.5px] leading-[1.6] text-foreground">{children}</dd>
    </div>
  );
}

function PublishDetail({ task, onDelete }: { task: PublishTask; onDelete: () => void }) {
  const t = useI18n();
  // 不再需要问「这个平台是不是浏览器平台」:发布任务只可能是平台账号发布。
  const ok = task.status === "succeeded" || task.status === "success" || task.status === "prepared";
  return (
    // 标题与下面的字段是同一个对象的两部分,所以共用一张卡:标题当卡头(略深底色 + 分隔线),
    // 而不是浮在卡外面——那样读起来像页面/标签级标题,和表单割裂。
    <div className="grid w-full content-start gap-3 px-0.5 pb-4 pt-0.5">
      <section className="overflow-hidden rounded-lg border border-border bg-panel shadow-[var(--shadow-panel)]">
        <header className="flex items-start justify-between gap-3 border-b border-border bg-panel-subtle px-3 py-2.5">
          <div className="min-w-0">
            <h2 className="m-0 text-[16px] font-[650] leading-[1.35] tracking-[-0.01em] [overflow-wrap:anywhere]">{task.title || task.asset_name}</h2>
            <p className="mb-0 mt-1 text-[12.5px] text-muted-foreground">
              {task.account_name} · {task.platform} · {t(`batchStatus_${task.status}` as never)}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {ACTIVE.has(task.status) ? (
              <Loader2 size={14} className="animate-openstudio-spin" />
            ) : ok ? (
              <CheckCircle2 size={14} className="text-[#16a34a]" />
            ) : BLOCKED.has(task.status) ? (
              <CircleAlert size={14} className="text-[#d97706]" />
            ) : (
              <CircleAlert size={14} className="text-destructive" />
            )}
            {window.openStudioPublish && (
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  window.openStudioPublish
                    ?.openPage(task.account_id, task.platform)
                    .catch((error: Error) => toast.error(error.message))
                }
              >
                <ExternalLink size={13} /> {t("publishOpenPage")}
              </Button>
            )}
            <Button size="sm" variant="outline" className="hover:border-[color-mix(in_oklab,var(--destructive)_45%,var(--border))] hover:text-destructive" onClick={onDelete}>
              <Trash2 size={13} /> {t("delete")}
            </Button>
          </div>
        </header>
        <dl className="m-0 grid [&>*+*]:border-t [&>*+*]:border-border">
          <InfoRow label={t("publishAsset")} description={t("publishAssetDesc")}>
            <code className="timecode text-xs text-muted-foreground [overflow-wrap:anywhere]">{task.asset_name}</code>
          </InfoRow>
          {task.description && (
            <InfoRow label={t("publishDescription")}>
              <p className="m-0 whitespace-pre-wrap [overflow-wrap:anywhere]">{task.description}</p>
            </InfoRow>
          )}
          {task.tags.length > 0 && (
            <InfoRow label={t("publishTags")}>
              <div className="flex flex-wrap gap-1">
                {task.tags.map((tag) => (
                  <span className="inline-flex items-center gap-[3px] rounded-full border border-border bg-panel-subtle px-1.5 py-px text-[11px] text-muted-foreground" key={tag}>
                    {tag}
                  </span>
                ))}
              </div>
            </InfoRow>
          )}
          {task.status === "succeeded" && task.result.target != null && (
            <InfoRow label={t("publishResult")} description={t("publishResultDesc")}>
              <code className="timecode inline-flex items-center gap-[5px] text-xs text-muted-foreground [overflow-wrap:anywhere]" title={String(task.result.target)}>
                <FolderOutput size={12} className="shrink-0" /> {String(task.result.target)}
              </code>
            </InfoRow>
          )}
          {task.status === "failed" && task.error && (
            <InfoRow label={t("publishError")}>
              <p className="m-0 whitespace-pre-wrap text-destructive [overflow-wrap:anywhere]">{task.error}</p>
            </InfoRow>
          )}
        </dl>
      </section>
    </div>
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
      <div className="grid gap-2.5 [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
        <label className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
          <span>{t("publishAsset")}</span>
          <Combobox
            value={assetId ?? ""}
            options={videos.map((asset) => ({ value: asset.id, label: asset.name }))}
            placeholder={t("publishPickAsset")}
            emptyText={t("cmdkEmpty")}
            className="w-full"
            onValueChange={setAssetId}
          />
          {videos.length === 0 && assets.isSuccess && <small>{t("publishNoVideos")}</small>}
        </label>
        <label className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
          <span>{t("publishAccount")}</span>
          <Combobox
            value={accountId ?? ""}
            options={(accounts.data ?? []).map((account: PublishAccount) => ({ value: account.id, label: account.name }))}
            placeholder={t("publishPickAccount")}
            emptyText={t("cmdkEmpty")}
            className="w-full"
            onValueChange={setAccountId}
          />
          {(accounts.data ?? []).length === 0 && accounts.isSuccess && (
            <small>
              {t("publishNoAccounts")}{" "}
              <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-[length:inherit] text-primary underline" onClick={onManageAccounts}>
                {t("publishAccounts")}
              </button>
            </small>
          )}
        </label>
        <label className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
          <span>
            {t("publishTitle")}
            <em className={cn(
              "ml-2 font-normal normal-case not-italic tracking-normal text-muted-foreground",
              title.length > titleMax && "font-semibold text-destructive",
            )}>
              {title.length}/{titleMax}
            </em>
          </span>
          <Input value={title} maxLength={titleMax + 20} onChange={(event) => setTitle(event.target.value)} />
        </label>
        {platformMeta?.short_title && (
          <label className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
            <span>{t("publishShortTitle")}</span>
            <Input value={shortTitle} maxLength={20} onChange={(event) => setShortTitle(event.target.value)} />
          </label>
        )}
        <label className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
          <span>{t("publishDescription")}</span>
          <Textarea
            rows={3}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <label className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-[11px] [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-[12.5px] [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
          <span>{t("publishTags")}</span>
          <Input value={tagsText} placeholder={t("publishTagsPlaceholder")} onChange={(event) => setTagsText(event.target.value)} />
        </label>
        <div className="mt-1 flex items-center justify-end gap-1.5">
          <Button variant="outline" size="sm" disabled={!assetId} loading={aiCopy.isPending} onClick={() => aiCopy.mutate()}>
            <Sparkles size={13} /> {t("publishAiCopy")}
          </Button>
          <span className="flex-1" />
          <Button variant="outline" size="sm" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button size="sm" disabled={!assetId || !accountId} loading={create.isPending} onClick={() => create.mutate()}>
            <Rocket size={13} /> {t("publishStart")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}
