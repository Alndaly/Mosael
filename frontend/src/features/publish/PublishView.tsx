import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, CircleAlert, ExternalLink, FolderOutput, ListChecks, Loader2, Plus, Rocket, Sparkles, Trash2, Users, X } from "lucide-react";
import { toast } from "sonner";

import { deleteWarningKey } from "@/features/publish/publishDeleteWarning";
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
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Combobox } from "@/components/app/combobox";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { SelectionCheck } from "@/components/app/SelectionCheck";
import { dayGroupOf, groupByLocalDay } from "@/lib/dayGroups";
import { useMultiSelect } from "@/lib/useMultiSelect";
import { gotoRecord } from "@/lib/deepLink";
import { useNow } from "@/lib/time";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["queued", "running", "pending"]);
// 受阻但可恢复(老版 BLOCKED_STATUSES):人工处理后可重试。
const BLOCKED = new Set(["login_required", "waiting_manual", "permission_required", "blocked"]);

/** 发布页(计划 §6.9 / Phase 13):成片 + 文案 → 发布目标,状态走任务总线。
 *  账号矩阵是一等页签:多平台账号的登录态、启停、复检都在这里管,登录会话
 *  由桌面端 persist: 分区持久化,重启不丢。 */
export function PublishView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();

  // 任务中心深链(openstudio:open-* 事件通道):直接选中那条发布记录。
  React.useEffect(() => {
    const onOpenTask = (event: Event) => {
      const id = (event as CustomEvent<string>).detail;
      if (typeof id === "string" && id) {
        setOpenId(id);
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

  const batchRemove = useMutation({
    mutationFn: async () => {
      // 没有批量接口:逐条删,失败的留下来报出去(和素材页同一种做法)。
      const failures: string[] = [];
      for (const id of selectedIds) {
        try {
          await deletePublishTask(id);
        } catch (error) {
          failures.push(String((error as Error).message));
        }
      }
      return failures;
    },
    onSuccess: (failures) => {
      setBatchDeleting(false);
      clear();
      if (failures.length > 0) toast.error(failures.join("\n"));
      refresh();
    },
  });

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

  // 详情走弹窗:记录本身是一条条独立的东西,列表 + 常驻右栏会把整页宽度让给"当前这一条",
  // 而多数时候人是在**扫一遍**,不是在盯着一条看。
  const [openId, setOpenId] = React.useState<string | null>(null);
  const opened = (tasks.data ?? []).find((task) => task.id === openId) ?? null;
  // 按天分栏。时间是无时区标记的 UTC 串,分组必须按本地日历天算(见 lib/dayGroups)。
  const groups = React.useMemo(
    () => groupByLocalDay(tasks.data ?? [], (task) => task.created_at),
    [tasks.data],
  );
  const now = useNow(60_000);
  // 多选与素材页同一份状态机(见 lib/useMultiSelect)。
  const { selectMode, setSelectMode, selectedIds, toggle, selectAll, allSelected, clear, exit } =
    useMultiSelect(tasks.data ?? [], (task) => task.id);
  const [batchDeleting, setBatchDeleting] = React.useState(false);

  const dialogs = (
    <>
      <CreatePublishDialog
        open={creating}
        workspace={workspace}
        onClose={() => setCreating(false)}
        onCreated={(task) => {
          setCreating(false);
          setOpenId(task.id);
          refresh();
        }}
        onManageAccounts={() => {
          setCreating(false);
          gotoRecord("/browser-pool"); // 账号管理归口浏览器池;没账号时引导过去添加
        }}
      />
      <PublishDetailDialog
        task={opened}
        onClose={() => setOpenId(null)}
        onDelete={() => {
          if (opened) setDeleting(opened);
        }}
      />
      <ConfirmDialog
        open={batchDeleting}
        title={t("deleteConfirmTitle")}
        // 选中的里面只要有一条已经发出去了,就按"发过"的说法警告 —— 批量删最容易顺手把
        // 成功记录一起带走,而那本账没了之后,"我发过什么"就只剩记忆了。
        body={t(
          deleteWarningKey((tasks.data ?? []).filter((task) => selectedIds.has(task.id)).map((task) => task.status)) as never,
        )}
        onCancel={() => setBatchDeleting(false)}
        onConfirm={() => batchRemove.mutate()}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={t("deleteConfirmTitle")}
        body={t(deleteWarningKey(deleting ? [deleting.status] : []) as never)}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </>
  );

  // 账号的「增」和「管」都归口「浏览器池」tab;发布页只做发布(记录 + 新建发布)。
  const seg = (
    <div className="flex items-center justify-between">
      <h2 className="m-0 inline-flex items-center gap-1.5 text-ui-md font-semibold text-foreground">
        <Rocket size={13} /> {t("publishTabRecords")}
      </h2>
      <span className="flex flex-wrap items-center gap-1.5">
        {selectMode ? (
          <>
            <span className="whitespace-nowrap text-xs text-muted-foreground">
              {t("mediaSelectedCount").replace("{n}", String(selectedIds.size))}
            </span>
            <Button variant="outline" size="sm" onClick={() => selectAll(tasks.data ?? [])}>
              <ListChecks size={13} /> {allSelected(tasks.data ?? []) ? t("mediaDeselectAll") : t("mediaSelectAll")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="hover:border-destructive/50 hover:text-destructive"
              disabled={selectedIds.size === 0}
              onClick={() => setBatchDeleting(true)}
            >
              <Trash2 size={13} /> {t("delete")}
            </Button>
            <Button variant="ghost" size="sm" onClick={exit}>
              <X size={13} /> {t("cancel")}
            </Button>
          </>
        ) : (
          <>
            <Button variant="outline" size="sm" onClick={() => setSelectMode(true)}>
              <Check size={13} /> {t("mediaSelectMode")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setCreating(true)}>
              <Plus size={13} /> {t("publishCreate")}
            </Button>
          </>
        )}
      </span>
    </div>
  );

  if (tasks.isSuccess && (tasks.data ?? []).length === 0) {
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2 [&>*]:shrink-0">
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
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2 [&>*]:shrink-0">
      <div className="flex h-full min-h-0 flex-col gap-1.5">
      {seg}
      <div className="min-h-0 flex-1 overflow-y-auto pt-1">
        {groups.map((group) => {
          const day = dayGroupOf(group.key, now, locale);
          return (
            <section key={group.key || "unknown"} className="grid gap-2 pb-4">
              {/* 日期栏头贴顶:滚很长时也知道现在看的是哪一天。 */}
              <h3 className="sticky top-0 z-[1] m-0 bg-background/92 py-1 text-ui-xs font-semibold text-muted-foreground backdrop-blur-sm">
                {day.kind === "today" ? t("dateToday") : day.kind === "yesterday" ? t("dateYesterday") : day.text}
                <span className="ml-1.5 font-normal tabular-nums text-muted-foreground/70">{group.items.length}</span>
              </h3>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(232px,1fr))] gap-2">
                {group.items.map((task) => (
                  <ContextMenu key={task.id}>
                    <ContextMenuTrigger asChild>
                      <button
                        type="button"
                        className="relative h-full text-left"
                        onClick={() => (selectMode ? toggle(task.id) : setOpenId(task.id))}
                      >
                        <PublishCard task={task} selecting={selectMode} />
                        {selectMode && <SelectionCheck selected={selectedIds.has(task.id)} />}
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
            </section>
          );
        })}
      </div>
      </div>
      {dialogs}
    </div>
  );
}


/** 一条记录的状态归成四档:进行中 / 成了 / 卡住了(可人工恢复)/ 没成。
 *  颜色和图标只在这里定一次 —— 卡片和详情弹窗都读它,免得两处各挑一套。 */
function statusTone(status: string) {
  if (ACTIVE.has(status)) return { Icon: Loader2, tone: "text-muted-foreground", spin: true };
  if (status === "succeeded" || status === "success") {
    return { Icon: CheckCircle2, tone: "text-[#16a34a]", spin: false };
  }
  if (BLOCKED.has(status)) return { Icon: CircleAlert, tone: "text-[#d97706]", spin: false };
  return { Icon: CircleAlert, tone: "text-destructive", spin: false };
}

function StatusIcon({ status }: { status: string }) {
  const { Icon, tone, spin } = statusTone(status);
  return <Icon size={13} className={cn("shrink-0", tone, spin && "animate-openstudio-spin")} aria-hidden />;
}

/** 后端时间无时区标记,补 Z 再按本地时区显示(与 lib/time、lib/dayGroups 同一约定)。 */
function localTime(iso: string, locale: string): string {
  const normalized = /Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
}

/**
 * 记录卡片。**卡面上要能判断"这条要不要点开"** —— 所以给的是状态、什么时候、发到哪个号、
 * 发的哪条成片;失败时把原因头一行也带出来,那通常就是他要找的东西。
 */
function PublishCard({ task, selecting = false }: { task: PublishTask; selecting?: boolean }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const { Icon, tone, spin } = statusTone(task.status);
  return (
    // **同一种信息落在同一个位置**:状态行贴顶、元信息贴底(mt-auto),中间留给长短不一的标题。
    // 此前全部顺排,于是标题一行和两行的卡片里,"发到哪个号""哪条成片"各自落在不同高度 ——
    // 同一排卡片横着看过去像三种模板。
    <article className="flex h-full flex-col gap-1.5 rounded-lg border border-border bg-panel p-2.5 shadow-[var(--shadow-panel)] transition-colors hover:border-border-strong">
      <div className="flex items-center gap-1.5">
        <Icon size={13} className={cn("shrink-0", tone, spin && "animate-openstudio-spin")} />
        <span className={cn("text-ui-xs font-semibold", tone)}>{t(`batchStatus_${task.status}` as never)}</span>
        {/* 选择态下右上角让给勾选圈 —— 两者叠在一起时间会被盖掉一半,不如干脆不显示。 */}
        {!selecting && (
          <span className="ml-auto shrink-0 tabular-nums text-ui-xs text-muted-foreground">
            {localTime(task.created_at, locale)}
          </span>
        )}
      </div>
      <strong className="line-clamp-2 text-ui-md font-[650] leading-[1.4] text-foreground [overflow-wrap:anywhere]">
        {task.title || task.asset_name}
      </strong>
      <div className="mt-auto grid gap-1.5 pt-0.5">
        <p className="m-0 truncate text-ui-xs text-muted-foreground">
          {task.platform} · {task.account_name}
        </p>
        <code className="truncate font-mono text-ui-xs text-muted-foreground/80">{task.asset_name}</code>
        {task.status === "failed" && task.error && (
          <p className="m-0 line-clamp-2 text-ui-xs leading-[1.45] text-destructive [overflow-wrap:anywhere]">{task.error}</p>
        )}
      </div>
    </article>
  );
}

/** 详情弹窗。点开一条才看细节 —— 常驻右栏会把整页宽度让给"当前这一条",而多数时候人是在扫一遍。 */
function PublishDetailDialog({ task, onClose, onDelete }: { task: PublishTask | null; onClose: () => void; onDelete: () => void }) {
  const t = useI18n();
  return (
    <ModalShell
      open={task !== null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={task ? task.title || task.asset_name : t("publishListTitle")}
      className="w-[min(620px,calc(100vw-32px))]"
    >
      {task && <PublishDetail task={task} onDelete={onDelete} onLeave={onClose} />}
    </ModalShell>
  );
}

/** 详情行:标签固定窄列 + 值紧随其右、左对齐填满剩余宽度(读起来是"字段:内容",
 *  而不是设置页那种"标签左、控件甩到最右"、中间一大片空白)。窄屏改成上下堆叠。 */
/** 详情里的一行事实。**没有边框、没有底色、不画横线** —— 弹窗本身已经是一张卡,里面再套一张
 *  带框的表就是盒中盒,而行与行之间靠间距分开就够了(素材预览弹窗里的同类就是这么排的,
 *  两处保持一致)。 */
function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[76px_minmax(0,1fr)] items-baseline gap-3 max-[520px]:grid-cols-1 max-[520px]:gap-1">
      <dt className="text-ui-xs text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0 text-ui-sm leading-[1.6] text-foreground [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

function PublishDetail({
  task,
  onDelete,
  onLeave,
}: {
  task: PublishTask;
  onDelete: () => void;
  /** 跳去内嵌浏览器之后调用 —— 弹窗留在原地的话,从平台页返回 Open Studio 还要再点一次关闭。 */
  onLeave: () => void;
}) {
  const t = useI18n();
  // 不再需要问「这个平台是不是浏览器平台」:发布任务只可能是平台账号发布。
  const ok = task.status === "succeeded" || task.status === "success";
  return (
    // 外框和标题由弹窗提供 —— 这里再套一张卡就是盒中盒,标题也会重复一遍。
    <div className="grid w-full content-start gap-2.5">
      <section>
        <header className="flex items-start justify-between gap-3 pb-2.5">
          {/* 状态只说一次:此前这一行写着「失败」,右边还浮着一个同义的红色图标。 */}
          <p className="m-0 flex min-w-0 items-center gap-1.5 text-ui-sm text-muted-foreground">
            <StatusIcon status={task.status} />
            <span className="truncate">
              {task.account_name} · {task.platform} ·{" "}
              <span className={statusTone(task.status).tone}>{t(`batchStatus_${task.status}` as never)}</span>
            </span>
          </p>
          <div className="flex shrink-0 items-center gap-1.5">
            {window.openStudioPublish && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  // 先关弹窗再跳:跳过去之后这个弹窗就在内嵌视图**背后**,用户从平台页
                  // 返回时会撞见一个自己没打开过的东西,还得多点一次。
                  onLeave();
                  window.openStudioPublish
                    ?.openPage(task.account_id, task.platform)
                    .catch((error: Error) => toast.error(error.message));
                }}
              >
                <ExternalLink size={13} /> {t("publishOpenPage")}
              </Button>
            )}
            <Button size="sm" variant="outline" className="hover:border-[color-mix(in_oklab,var(--destructive)_45%,var(--border))] hover:text-destructive" onClick={onDelete}>
              <Trash2 size={13} /> {t("delete")}
            </Button>
          </div>
        </header>
        <dl className="m-0 grid gap-2.5">
          <InfoRow label={t("publishAsset")}>
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
                  <span className="inline-flex items-center gap-[3px] rounded-full border border-border bg-panel-subtle px-1.5 py-px text-ui-xs text-muted-foreground" key={tag}>
                    {tag}
                  </span>
                ))}
              </div>
            </InfoRow>
          )}
          {task.status === "succeeded" && task.result.target != null && (
            <InfoRow label={t("publishResult")}>
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
  // 平台自己的发布选项(可见性等)。**不在这里写死任何平台的选项** —— 有哪些、什么类型、默认是什么,
  // 全部来自 /api/publish/platforms 的声明(后端 PLATFORM_OPTIONS)。加一个平台属性不需要动这里。
  const [options, setOptions] = React.useState<Record<string, unknown>>({});

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
  const optionSpecs = platformMeta?.options ?? [];
  // 换平台就按新平台的声明重置:选项的键是平台专属的,带着上一个平台的键提交会被后端拒掉
  // (那是对的 —— 静默丢掉才会让人以为自己设了公开)。
  React.useEffect(() => {
    setOptions(Object.fromEntries(optionSpecs.map((spec) => [spec.key, spec.default])));
  }, [platformMeta?.platform]);

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
        options,
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
      <div className="grid gap-2.5 [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
        <label className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-ui-sm [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
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
        <label className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-ui-sm [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
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
        <label className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-ui-sm [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
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
          <label className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-ui-sm [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
            <span>{t("publishShortTitle")}</span>
            <Input value={shortTitle} maxLength={20} onChange={(event) => setShortTitle(event.target.value)} />
          </label>
        )}
        <label className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-ui-sm [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
          <span>{t("publishDescription")}</span>
          <Textarea
            rows={3}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <label className="grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-ui-sm [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none">
          <span>{t("publishTags")}</span>
          <Input value={tagsText} placeholder={t("publishTagsPlaceholder")} onChange={(event) => setTagsText(event.target.value)} />
        </label>
        {/*
          * 平台专属选项。**和上面几栏长一个样**:同样的 label + 控件,不套边框、不加小标题 ——
          * 它们本来就是这次发布的字段("发到哪、谁能看"),不是附属于别处的一组设置。框起来反而
          * 像是从别的地方嵌进来的东西。
          *
          * 控件用应用自己的 Combobox / Switch,不用原生 <select>:原生控件的弹层由系统绘制,
          * 配色、圆角、字体都和应用对不上,深色模式下尤其突兀。
          */}
        {optionSpecs.map((spec) =>
          spec.type === "bool" ? (
            /*
             * 开关型选项**不走「标签在上、控件在下」**那套:那是给输入框/下拉用的,它们占满整行,
             * 标签放上面才对得齐。开关只有 36px 宽,单独占一行会孤零零吊在标签底下,而且旁边留一
             * 大片空白 —— 应用里设置页早就用的是另一种形状(SettingsRow:标签与说明在左、控件在右),
             * 这里照它,只是按对话框的字号与行距收紧。
             *
             * 加边框是为了让它看起来**也是一栏表单**:同一个对话框里其它控件(输入框、下拉)都有边框,
             * 光秃秃一个开关会像是漏在表单外面的东西。
             */
            <label
              key={spec.key}
              className="flex items-center justify-between gap-4 rounded border border-border bg-field px-2.5 py-2"
            >
              <span className="grid min-w-0 gap-0.5">
                <span className="text-xs font-semibold text-foreground">{spec.label}</span>
                {spec.description && (
                  <small className="text-ui-xs leading-[1.4] text-muted-foreground">{spec.description}</small>
                )}
              </span>
              <Switch
                checked={Boolean(options[spec.key] ?? spec.default)}
                onCheckedChange={(next: boolean) => setOptions((prev) => ({ ...prev, [spec.key]: next }))}
              />
            </label>
          ) : (
            <label key={spec.key} className={"grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground"}>
              <span>{spec.label}</span>
              <Combobox
                value={String(options[spec.key] ?? spec.default)}
                options={(spec.choices ?? []).map((choice) => ({ value: choice.value, label: choice.label }))}
                emptyText={t("cmdkEmpty")}
                className="w-full"
                onValueChange={(next) => setOptions((prev) => ({ ...prev, [spec.key]: next }))}
              />
              {spec.description && <small>{spec.description}</small>}
            </label>
          ),
        )}
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
