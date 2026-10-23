import { LoadingState } from "@/components/layout/LoadingState";
import React from "react";
import { PageHeading, STUDIO_PAGE, CollectionTabs } from "@/components/layout/StudioPage";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, CircleAlert, ExternalLink, ListChecks, Loader2, Plus, Rocket, Sparkles, Trash2, Users, X } from "lucide-react";
import { toast } from "sonner";

import { deleteWarningKey } from "@/features/publish/publishDeleteWarning";
import {
  createPublishTask,
  deletePublishTask,
  generatePublishCopy,
  listPublishAccounts,
  listPublishPlatforms,
  listPublishTasks,
  publishWorkerOnline,
  type PublishAccount,
  type PublishTask,
  type Workspace,
} from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import type { MessageKey } from "@/app/messages";
import { DIALOG_FIELD } from "@/components/app/modals";
import { platformLabel } from "@/lib/platformLabel";
import { AssetGridField } from "@/features/nodeForms/AssetGridField";
import { AssetPickerField } from "@/features/publish/AssetPickerField";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Combobox } from "@/components/app/combobox";
import { useAssetSearch } from "@/lib/assetQueries";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { SearchInput } from "@/components/ui/search-input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { MenuItemBody } from "@/components/ui/menu";
import { Truncate } from "@/components/ui/truncate";
import { Hint } from "@/components/ui/tooltip";
import { useWriteBlocked } from "@/components/layout/useWriteBlocked";
import { SelectionCheck } from "@/components/app/SelectionCheck";
import { useAssetPreviewModal } from "@/features/media/AssetPreviewModalById";
import { dayGroupOf, groupByLocalDay } from "@/lib/dayGroups";
import { useMultiSelect } from "@/lib/useMultiSelect";
import { gotoRecord, useOpenRequest, useSectionEntry } from "@/lib/deepLink";
import { parseServerTime, useNow } from "@/lib/time";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["queued", "running", "pending"]);
// 受阻但可恢复(老版 BLOCKED_STATUSES):人工处理后可重试。
const BLOCKED = new Set(["login_required", "waiting_manual", "permission_required", "blocked"]);
// 记录列表的状态筛选。「从起点进来」可以指定其中一个(统计页「近 N 天发布」→ 已成功)。
const STATUS_FILTERS: readonly string[] = ["all", "active", "succeeded", "attention"];

/** 发布页(计划 §6.9 / Phase 13):成片 + 文案 → 发布目标,状态走任务总线。
 *  账号矩阵是一等页签:多平台账号的登录态、启停、复检都在这里管,登录会话
 *  由桌面端 persist: 分区持久化,重启不丢。 */
/**
 * **内容形状 → 文案 key**。一张表,不用三元判断。
 *
 * 形状名带连字符(`image-text`)不能直接拼成 key,所以以前写成「是 image-text 就用 A、否则拼 B」;
 * 加第三种形状时那句要再改。表里没有的形状就不出标签 —— 不认识就别硬编一个。
 */
const KIND_LABEL_KEY: Partial<Record<string, MessageKey>> = {
  video: "publishKind_video",
  "image-text": "publishKind_imageText",
  article: "publishKind_article",
};

const kindLabel = (kind: string | undefined): string | null =>
  kind ? (KIND_LABEL_KEY[kind] ?? null) : null;

export function PublishView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const writeBlocked = useWriteBlocked(workspace.role);
  const { locale } = usePreferences();
  const qc = useQueryClient();

  // 任务中心深链(mosael:open-* 事件通道):直接选中那条发布记录。
  useOpenRequest("mosael:open-publish-task", (id) => {
    setStatusFilter("all");
    setSearch("");
    setFocusedId(id);
  });
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

  // 有活儿排着的时候才问「执行器在不在」—— 它是**另一个进程**(Electron 主进程里的发布
  // 执行器),后端只负责排队。执行器没起来,任务就停在 queued 上不动,而界面此前对此一个字
  // 都不说:用户看到的是"点了发布,然后什么都没发生"。没有待办时不问,省得每 10 秒一次空轮询。
  const waiting = (tasks.data ?? []).some((task) => ACTIVE.has(task.status));
  const worker = useQuery({
    queryKey: ["publish-worker-status"],
    queryFn: publishWorkerOnline,
    enabled: waiting,
    refetchInterval: waiting ? 10_000 : false,
  });
  // 只在**确知离线**时说话:还没问到答案不等于离线,那会在刚进页面的一瞬闪一条假警报。
  const executorOffline = waiting && worker.isSuccess && !worker.data.online;

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
  //: 素材预览:列表里点成片名直接看素材(按 id 补全完整素材再开详情弹窗,见 useAssetPreviewModal)。
  const { openAsset, modal: assetModal } = useAssetPreviewModal();
  //: 深链(mosael:open-publish-task)只把那条滚进视野、短暂高亮 —— 详情弹窗已按维护者要求删掉,
  //: 信息与动作都在行内。
  const [focusedId, setFocusedId] = React.useState<string | null>(null);
  const listRef = React.useRef<HTMLDivElement | null>(null);
  // 按天分栏。时间是无时区标记的 UTC 串,分组必须按本地日历天算(见 lib/dayGroups)。
  const [statusFilter, setStatusFilter] = React.useState("all");
  //: 搜索:标题 / 简介 / 标签 / 成片名 / 账号都对。数据都在手上(分页由列表整取),本地筛。
  const [search, setSearch] = React.useState("");
  //: 排序是**怎么看**的一部分,不是这一刻的临时值 —— 切走再回来照旧(和素材库同一个做法)。
  const [sortKey, setSortKey] = usePersistentTab<"newest" | "oldest" | "name">("publish-sort", "newest", ["newest", "oldest", "name"]);
  useSectionEntry("publish", (entry) => {
    setFocusedId(null);
    setStatusFilter(STATUS_FILTERS.includes(entry) ? entry : "all");
  });
  //: 深链过来的那一条:滚进视野、亮 2 秒。
  React.useEffect(() => {
    if (!focusedId) return;
    const row = listRef.current?.querySelector(`[data-publish-task="${focusedId}"]`);
    row?.scrollIntoView({ block: "center", behavior: "smooth" });
    const timer = window.setTimeout(() => setFocusedId(null), 2_000);
    return () => window.clearTimeout(timer);
  }, [focusedId]);

  const filteredTasks = React.useMemo(() => {
    const needle = search.trim().toLowerCase();
    const kept = (tasks.data ?? []).filter((task) => {
      const byStatus =
        statusFilter === "all" ||
        (statusFilter === "active"
          ? ACTIVE.has(task.status)
          : statusFilter === "succeeded"
            ? ["succeeded", "success"].includes(task.status)
            : !ACTIVE.has(task.status) && !["succeeded", "success"].includes(task.status));
      if (!byStatus) return false;
      if (!needle) return true;
      return [task.title, task.description, task.asset_name, task.account_name, ...task.tags]
        .some((field) => field?.toLowerCase().includes(needle));
    });
    //: 按发布(记录创建)时间排;「最新发布」在前是默认。按名称排时用界面语言比(中文按拼音、英文按字母)。
    const nameOf = (task: PublishTask) => task.title || task.asset_name;
    return [...kept].sort((a, b) => {
      if (sortKey === "name") return nameOf(a).localeCompare(nameOf(b), locale);
      const delta = parseServerTime(a.created_at).getTime() - parseServerTime(b.created_at).getTime();
      return sortKey === "newest" ? -delta : delta;
    });
  }, [tasks.data, statusFilter, search, sortKey, locale]);
  const groups = React.useMemo(
    () => groupByLocalDay(filteredTasks, (task) => task.created_at),
    [filteredTasks],
  );
  const now = useNow(60_000);
  // 多选与素材页同一份状态机(见 lib/useMultiSelect)。
  const { selectMode, enter: enterSelectMode, selectedIds, toggle, selectAll, allSelected, clear, exit } =
    useMultiSelect(filteredTasks, (task) => task.id);
  const [batchDeleting, setBatchDeleting] = React.useState(false);

  const dialogs = (
    <>
      <CreatePublishDialog
        open={creating}
        workspace={workspace}
        onClose={() => setCreating(false)}
        onCreated={() => {
          //: **不自动打开详情弹窗**(维护者:提交后那个"进度弹窗"不要了)。进度就在列表项里看:
          //: 状态列(运行中 → 成功/失败,定时轮询)、失败原因、时间都在那一行;要细节再点开这一条。
          setCreating(false);
          refresh();
        }}
        onManageAccounts={() => {
          setCreating(false);
          gotoRecord("/browser-pool"); // 账号管理归口浏览器池;没账号时引导过去添加
        }}
      />
      {assetModal}
      <ConfirmDialog
        open={batchDeleting}
        title={t("deleteConfirmTitle")}
        // 选中的里面只要有一条已经发出去了,就按"发过"的说法警告 —— 批量删最容易顺手把
        // 成功记录一起带走,而那本账没了之后,"我发过什么"就只剩记忆了。
        body={t(
          deleteWarningKey((tasks.data ?? []).filter((task) => selectedIds.has(task.id)).map((task) => task.status)) as never,
        )}
        onCancel={() => setBatchDeleting(false)}
        pending={batchRemove.isPending}
        onConfirm={() => batchRemove.mutate()}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={t("deleteConfirmTitle")}
        body={t(deleteWarningKey(deleting ? [deleting.status] : []) as never)}
        onCancel={() => setDeleting(null)}
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </>
  );

  // 账号的「增」和「管」都归口「浏览器池」tab;发布页只做发布(记录 + 新建发布)。
  const seg = (
    <PageHeading title={t("navPublish")} description={t("studioPublishDesc")} count={tasks.data?.length} actions={
      <span className="flex flex-wrap items-center gap-1.5">
        {selectMode ? (
          <>
            <span className="whitespace-nowrap text-xs text-muted-foreground">
              {t("mediaSelectedCount").replace("{n}", String(selectedIds.size))}
            </span>
            <Button variant="outline" size="default" onClick={() => selectAll(filteredTasks)}>
              <ListChecks size={13} /> {allSelected(filteredTasks) ? t("mediaDeselectAll") : t("mediaSelectAll")}
            </Button>
            <Hint disabledReason={writeBlocked?.reason}>
              <Button
                variant="outline"
                size="default"
                className="hover:border-destructive/50 hover:text-destructive"
                disabled={selectedIds.size === 0 || Boolean(writeBlocked)}
                onClick={() => setBatchDeleting(true)}
              >
                <Trash2 size={13} /> {t("delete")}
              </Button>
            </Hint>
            <Button variant="outline" size="default" onClick={exit}>
              <X size={13} /> {t("cancel")}
            </Button>
          </>
        ) : (
          <>
            <Button variant="outline" size="default" onClick={() => enterSelectMode()}>
              <Check size={13} /> {t("mediaSelectMode")}
            </Button>
            <Hint disabledReason={writeBlocked?.reason}>
              <Button disabled={Boolean(writeBlocked)} onClick={() => setCreating(true)}>
                <Plus size={13} /> {t("publishCreate")}
              </Button>
            </Hint>
          </>
        )}
      </span>
    } />
  );

  if (tasks.isSuccess && (tasks.data ?? []).length === 0) {
    return (
      <div className={STUDIO_PAGE}>
        <PageHeading title={t("navPublish")} description={t("studioPublishDesc")} />
        <EmptyState
          icon={<Rocket size={22} />}
          title={t("publishEmptyTitle")}
          body={t("publishEmptyBody")}
          action={
            <div className="flex items-center gap-1.5">
              <Hint disabledReason={writeBlocked?.reason}>
                <Button disabled={Boolean(writeBlocked)} onClick={() => setCreating(true)}>
                  <Plus size={15} /> {t("publishCreate")}
                </Button>
              </Hint>
              <Hint disabledReason={writeBlocked?.reason}>
                <Button variant="outline" disabled={Boolean(writeBlocked)} onClick={() => gotoRecord("/browser-pool")}>
                  <Users size={15} /> {t("publishAccountAdd")}
                </Button>
              </Hint>
            </div>
          }
        />
        {dialogs}
      </div>
    );
  }

  return (
    <div className={STUDIO_PAGE}>
      <div className="flex h-full min-h-0 flex-col gap-7">
      {seg}
      {executorOffline && (
        <div className="flex items-center gap-2 rounded-lg border border-warning/40 bg-[color-mix(in_srgb,var(--warning)_10%,transparent)] px-3 py-2 text-ui-sm text-warning">
          <CircleAlert size={15} className="shrink-0" />
          <span>{t("publishExecutorOffline")}</span>
        </div>
      )}
      {/* 一行:状态页签(看哪些)→ 搜索 + 排序(在这刀之内再筛再排,搜索吃满余量)。
          段与段之间 16(和素材库工具条的 gap-x-4 同一档);搜索与排序是一段,内部 8。 */}
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
        <CollectionTabs label={t("publishTabRecords")} value={statusFilter} onChange={setStatusFilter} items={[{value:"all", label:t("studioAll")}, {value:"active", label:t("batchStatus_running")}, {value:"succeeded", label:t("batchStatus_succeeded")}, {value:"attention", label:t("studioNeedsAttention")}]} />
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <SearchInput className="min-w-40 flex-1" aria-label={t("publishSearchPlaceholder")} value={search} placeholder={t("publishSearchPlaceholder")} onChange={(event) => setSearch(event.target.value)} />
          <Select value={sortKey} onValueChange={(value) => setSortKey(value as "newest" | "oldest" | "name")}>
            <SelectTrigger className="w-auto min-w-28" aria-label={t("publishSortNewest")}><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="newest">{t("publishSortNewest")}</SelectItem>
              <SelectItem value="oldest">{t("publishSortOldest")}</SelectItem>
              <SelectItem value="name">{t("publishSortName")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
      {/* 每天一张**圆角白卡**(维护者给的图):日期栏头在卡外,记录落在卡里;卡片内的分割线内缩。 */}
      <div ref={listRef} className="flex min-h-0 flex-1 flex-col overflow-y-auto [&>*]:shrink-0">
        {tasks.isPending ? <LoadingState className="h-auto flex-1" /> : tasks.isError ? <EmptyState icon={<Rocket />} title={t("pageLoadError")} body={tasks.error.message} action={<Button variant="secondary" onClick={() => void tasks.refetch()}>{t("retry")}</Button>} /> : filteredTasks.length === 0 && <EmptyState icon={<Rocket />} title={t("studioNoMatches")} body={t("studioNoMatchesHint")} />}
        {groups.map((group) => {
          const day = dayGroupOf(group.key, now, locale);
          return (
            <section key={group.key || "unknown"} className="grid gap-2 pb-4">
              {/*: 日期栏头**自己一行、贴顶**;滚很长时也知道现在看的是哪一天。
                  底色必须是**实底**:`bg-background` 在磨砂外观下是半透明的,记录滚到它底下会透出来,
                  于是"今天"和第一条记录的成片名、时间叠在同一行(维护者 2026-10-23 截图)。
                  这里照 TraceView 的分组标题用 `bg-panel`(卡片同一层实底),并让它横向铺满卡片宽度。 */}
              <h3 className="workspace-sticky sticky top-0 z-[2] -mx-px m-0 flex items-baseline gap-1.5 rounded-lg bg-panel px-3 py-2 text-ui-sm font-medium text-muted-foreground">
                {day.kind === "today" ? t("dateToday") : day.kind === "yesterday" ? t("dateYesterday") : day.text}
                <span className="font-normal tabular-nums text-muted-foreground/70">{group.items.length}</span>
              </h3>
              <div className="grid overflow-hidden rounded-lg bg-panel">
                {group.items.map((task, index) => (
                  <React.Fragment key={task.id}>
                  {/*: 行与行之间的分割线**内缩 12px**(不顶到卡片左右边):线从正文起点开始,
                      卡片圆角因此不被切断。 */}
                  {index > 0 && <div aria-hidden className="mx-3 border-t border-divider" />}
                  <ContextMenu>
                    <ContextMenuTrigger asChild>
                      <div
                        //: 行容器。**点整行什么都不做**(维护者:整行点击不应该有反应)—— 动作都在行内:
                        //: 成片名开预览、右侧两颗钮查看页面/删除。只在多选模式下整行可点(勾选)。
                        //: 行容器不是 button:里面还要放「点开预览素材」那颗按钮,按钮套按钮是非法结构。
                        //: **这一层不留圆角**(它是 divide-y 的直接子元素,分割线以 border-top 画在它身上,
                        //: 圆角会让分割线两端弯起来)。
                        className={cn(
                          "group relative rounded-lg",
                          //: 深链定位到的那一条亮一下 —— 详情弹窗删掉之后,这是"从通知点进来"唯一的位置感。
                          focusedId === task.id && "ring-2 ring-primary/50",
                        )}
                        data-publish-task={task.id}
                        onClick={selectMode ? () => toggle(task.id) : undefined}
                      >
                        {/*: 多选模式下整行可点 = 勾选;此时才铺那颗铺满整行的无障碍按钮。 */}
                        {selectMode && (
                          <button
                            type="button"
                            className="absolute inset-0 z-[1] rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            aria-label={`${task.title || task.asset_name} · ${t(`batchStatus_${task.status}` as never)}`}
                          />
                        )}
                        <PublishCard
                          task={task}
                          selecting={selectMode}
                          onPreviewAsset={openAsset}
                          onOpenPage={
                            window.mosaelPublish
                              ? () =>
                                  void window.mosaelPublish
                                    ?.openPage(task.account_id, task.platform)
                                    .catch((error: Error) => toast.error(error.message))
                              : undefined
                          }
                          onDelete={() => setDeleting(task)}
                          deleteReason={writeBlocked?.reason}
                        />
                        {selectMode && <SelectionCheck selected={selectedIds.has(task.id)} />}
                      </div>
                    </ContextMenuTrigger>
                    <ContextMenuContent>
                      <ContextMenuItem className="text-destructive focus:text-destructive" disabled={Boolean(writeBlocked)} onSelect={() => setDeleting(task)}>
                        <MenuItemBody icon={<Trash2 />} label={t("delete")} description={writeBlocked?.brief} />
                      </ContextMenuItem>
                    </ContextMenuContent>
                  </ContextMenu>
                  </React.Fragment>
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
    return { Icon: CheckCircle2, tone: "text-success", spin: false };
  }
  if (BLOCKED.has(status)) return { Icon: CircleAlert, tone: "text-warning", spin: false };
  return { Icon: CircleAlert, tone: "text-destructive", spin: false };
}

/** 按本地时区显示后端时间。 */
function localTime(iso: string, locale: string): string {
  const date = parseServerTime(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
}

/**
 * 记录卡片。**卡面上要能判断"这条要不要点开"** —— 所以给的是状态、什么时候、发到哪个号、
 * 发的哪条成片;失败时把原因头一行也带出来,那通常就是他要找的东西。
 */
function PublishCard({
  task,
  selecting = false,
  onPreviewAsset,
  onOpenPage,
  onDelete,
  deleteReason,
}: {
  task: PublishTask;
  selecting?: boolean;
  /** 点成片名直接预览这条素材(id 可能为空:素材已删,那就只显示名字)。 */
  onPreviewAsset?: (assetId: string) => void;
  /** 打开这条发布在平台上的页面(桌面版才有)。 */
  onOpenPage?: () => void;
  /** 删除这条记录(写权限不足时给 deleteReason,按钮禁掉并说明原因)。 */
  onDelete?: () => void;
  deleteReason?: string | false | null;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const { Icon, tone, spin } = statusTone(task.status);
  return (
    // 一条记录一行,信息**都在行里**(维护者:此前只有标题/账号/成片,信息量太少,详情要靠弹窗):
    // 标题、平台 · 账号 · 成片、简介、标签、作品状态/失败原因、状态与时间。
    // 间距只走 12/8/4:行上下 12(py-3)、行内各段 4(gap-1)、标签 chip 之间 4、日期栏头 8。
    // hover 底色与圆角在**外层行容器**上(它才是接收点击与悬停的那一层);这里只管排布。
    // 左侧 12(和别页内容对齐);右侧 20(状态列右对齐,12 会贴住圆角的边)。
    <article className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-5 py-3 pl-3 pr-5">
      {/*: 首行是标题(ui-md),图标跟着首行对齐而不是整段居中。 */}
      {/*: 图标只当**行的锚**,不染状态色 —— 状态由标题旁那枚徽标说(此前红圈「!」+ 红字「失败」+
          红字失败原因,同一件事三遍)。 */}
      <span className="mt-0.5 grid size-10 shrink-0 place-items-center rounded-lg bg-panel-subtle text-muted-foreground">
        <Icon size={18} className={spin ? "animate-mosael-spin" : undefined} />
      </span>
      {/*: 左列分**三层**:① 标题 + 元信息 ② 正文(简介 + 标签)③ 结果(失败原因 / 作品)。
          层间 8、层内 4(间距只走 12/8/4)。此前五样东西全是 4px,标题、成片、正文、标签、报错
          挤成一片,读起来"浮着"、没有主次(维护者 2026-10-23)。 */}
      <div className="grid min-w-0 gap-2">
        <div className="grid gap-1">
          <div className="flex min-w-0 items-center gap-2">
            <Truncate as="strong" className="text-ui-md font-semibold">{task.title || task.asset_name}</Truncate>
            {/*: 状态徽标跟着标题:一条记录"是什么、现在怎样"在一处读。 */}
            <span className={cn("shrink-0 rounded-full bg-panel-subtle px-1.5 py-0.5 text-ui-xs font-medium", tone)}>
              {t(`batchStatus_${task.status}` as never)}
            </span>
            {/*: 这条发的是什么形状(ADR 0076):视频是老形状,不必占位;其余形状要一眼看得出来。 */}
            {task.content_kind !== "video" && kindLabel(task.content_kind) && (
              <span className="shrink-0 rounded-full bg-panel-subtle px-1.5 py-0.5 text-ui-xs text-muted-foreground">
                {t(kindLabel(task.content_kind) as MessageKey)}
              </span>
            )}
          </div>
          <div className="flex min-w-0 items-center gap-1 text-ui-sm text-muted-foreground">
            {/*: **只写平台的中文名**,不写 `xiaohongshu` 这种技术 id ——
                此前是「xiaohongshu · 小红书」,同一个东西写了两遍,而其中一遍是给程序看的。 */}
            {/*: 账号名常常就叫「小红书」——和平台名一样时只写一次,否则读起来是「小红书 · 小红书」。 */}
            <span className="shrink-0">
              {task.account_name && task.account_name !== platformLabel(task.platform, t)
                ? `${platformLabel(task.platform, t)} · ${task.account_name}`
                : platformLabel(task.platform, t)}
            </span>
            {/*: 只有**标题和成片不是同一个名字**时才把成片名再写一遍 —— 没有标题的记录里,
                标题位置摆的就是成片名,再写一次就是两条边在说同一件事。 */}
            {task.title && <span className="shrink-0">·</span>}
            {task.title && (onPreviewAsset && task.asset_id ? (
              <Button
                variant="inline"
                size="xs"
                //: 悬停**只出下划线**,不要那层底色(维护者:"hover 后有下划线的那种 button")——
                //: 成片名是一段值里的链接感,不是一颗带底色的按钮。
                className="relative z-10 min-w-0 hover:bg-transparent hover:underline underline-offset-2"
                onClick={(event) => {
                  event.stopPropagation();
                  onPreviewAsset(task.asset_id!);
                }}
              >
                <Truncate>{task.asset_name}</Truncate>
              </Button>
            ) : (
              <Truncate>{task.asset_name}</Truncate>
            ))}
          </div>
        </div>
        {(task.description || task.tags.length > 0) && (
          <div className="grid gap-1" data-publish-row-body="">
            {/*: 正文:这条发出去的是什么。用的是正文色(不是灰的)—— 它仅次于标题,
                灰掉之后和「平台 · 账号」那条元信息混成一层。 */}
            {task.description && (
              <Truncate as="p" lines={2} className="text-ui-sm text-foreground" data-publish-row-description="">
                {task.description}
              </Truncate>
            )}
            {/*: 标签:一行 chip,和详情弹窗里同一个形状。 */}
            {task.tags.length > 0 && (
              <div className="flex flex-wrap gap-1" data-publish-row-tags="">
                {task.tags.map((tag) => (
                  <span className="inline-flex items-center rounded-full border border-border bg-panel-subtle px-1.5 py-px text-ui-xs text-muted-foreground" key={tag}>
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
        {task.status === "failed" && task.error && (
          //: 失败原因带**提示色**(和状态列同一个语义色):灰色读起来像补充说明,可这一句正是
          //: "要不要点开这条"的判断依据(维护者截图指出)。
          <Truncate as="p" lines={2} className="text-ui-sm text-destructive" data-publish-failed-summary="">
            {task.error_summary || task.error}
          </Truncate>
        )}
        {["succeeded", "success"].includes(task.status) && (
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-ui-xs text-muted-foreground" data-publish-row-post="">
            <Truncate>{task.post?.post_id ? `${t("publishPost")} ${task.post.post_id}` : t("publishPostMissing")}</Truncate>
            {/*: 作品**真正发出去的时刻**(published_at,服务端记的),和右上角那颗记录创建时间不是同一个。 */}
            {task.post?.published_at && (
              <span data-publish-row-published="" className="shrink-0">
                {t("publishPostAt")} {new Date(task.post.published_at).toLocaleString(locale)}
              </span>
            )}
            {task.post?.url && (
              <a
                href={task.post.url}
                target="_blank"
                rel="noreferrer noopener"
                className="relative z-10 inline-flex shrink-0 items-center gap-1 text-primary hover:underline"
                onClick={(event) => event.stopPropagation()}
              >
                <ExternalLink size={11} /> {t("publishPostOpen")}
              </a>
            )}
          </div>
        )}
      </div>
      {/*: 右列是**一整块**,贴着行顶:状态 → 时间 → 动作。此前状态贴顶、动作 `mt-auto` 钉在行底,
          一条内容多的记录（简介 + 标签 + 失败原因）中间被撑开,右列就分成上下两座孤岛 ——
          维护者截图指出的「右侧内容层级不对」就是这个(2026-10-23)。现在三样排在一起、都右对齐。 */}
      <div className={cn("relative z-10 flex shrink-0 flex-col items-end gap-1 text-right", selecting && "pr-7")}>
        {/*: 右列只放**记录本身**的时间与动作。状态词搬去标题旁(见上)—— 同一件事(really? this one)
            不要一处红字、一处彩标。 */}
        <span className="text-ui-xs tabular-nums text-muted-foreground">{localTime(task.created_at, locale)}</span>
        {/*: 行内动作紧跟其后(空一格):文字 + 图标,正常的按钮。
            写权限不足时删除禁掉并说明原因 —— 和详情弹窗里那一颗同一条判据。 */}
        {(onOpenPage || onDelete) && !selecting && (
          <div className="mt-1 flex items-center gap-1">
            {onOpenPage && (
              <Button
                variant="outline"
                size="sm"
                onClick={(event) => {
                  event.stopPropagation();
                  onOpenPage();
                }}
              >
                <ExternalLink size={13} /> {t("publishOpenPage")}
              </Button>
            )}
            {onDelete && (
              <Hint disabledReason={deleteReason ?? undefined}>
                <Button
                  variant="outline"
                  size="sm"
                  className="hover:border-[color-mix(in_oklab,var(--destructive)_45%,var(--border))] hover:text-destructive"
                  disabled={Boolean(deleteReason)}
                  onClick={(event) => {
                    event.stopPropagation();
                    onDelete();
                  }}
                >
                  <Trash2 size={13} /> {t("delete")}
                </Button>
              </Hint>
            )}
          </div>
        )}
      </div>
    </article>
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
  //: 内容形状(ADR 0076):平台认哪几种由 /publish/platforms 的 `kinds` 决定,这里不写死。
  const [kind, setKind] = React.useState("video");
  //: 图文 / 文章的多份图片(顺序就是发布顺序)。
  const [imageIds, setImageIds] = React.useState<string[]>([]);
  const [body, setBody] = React.useState("");
  const [accountId, setAccountId] = React.useState<string | null>(null);
  const [title, setTitle] = React.useState("");
  const [shortTitle, setShortTitle] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [tagsText, setTagsText] = React.useState("");
  // 平台自己的发布选项(可见性等)。**不在这里写死任何平台的选项** —— 有哪些、什么类型、默认是什么,
  // 全部来自 /api/publish/platforms 的声明(后端 PLATFORM_OPTIONS)。加一个平台属性不需要动这里。
  const [options, setOptions] = React.useState<Record<string, unknown>>({});

  //: 能发的是视频:按种类在服务端筛、敲字在服务端搜,不把整个素材库拉回来。选中的那一份记下名字 ——
  //: 再搜别的字时它不一定还在清单里,触发器上照样写着它。
  const videos = useAssetSearch({ workspace_id: workspace.id, kind: ["video"] }, { enabled: open });
  const [assetName, setAssetName] = React.useState("");
  const accounts = useQuery({
    queryKey: ["publish-accounts", workspace.id],
    queryFn: () => listPublishAccounts(workspace.id),
    enabled: open,
  });
  const platforms = useQuery({ queryKey: ["publish-platforms"], queryFn: listPublishPlatforms, enabled: open, staleTime: Infinity });
  // 停用的账号发不出去(后端报 publishErr_accountDisabled):不列进可选项,只说一句它们去哪儿启用。
  const allAccounts = accounts.data ?? [];
  const usableAccounts = allAccounts.filter((account) => account.enabled);
  const disabledAccounts = allAccounts.length - usableAccounts.length;
  //: 存着的设置解不开了(主密钥换了或丢了):照样列出来,但说清要重新登录一次(体检 UM-22)。
  const unreadableAccounts = usableAccounts.filter((account) => account.config_unreadable);
  const selectedAccount = usableAccounts.find((account) => account.id === accountId) ?? null;
  const platformMeta =
    (platforms.data ?? []).find((item) => item.platform === selectedAccount?.platform) ?? null;
  //: 只列**我们已经会发**的形状(后端按适配器进度声明)。平台能发、但适配器还没接的(比如小红书的
  //: 「文章」)不摆出来 —— 摆了就是让用户点一下,再在真实页面上失败。
  const platformKinds = React.useMemo(
    () => platformMeta?.implemented_kinds ?? ["video"],
    [platformMeta?.implemented_kinds],
  );
  //: 换了账号(平台),当前形状要是人家不认,回落到它认的第一档。
  React.useEffect(() => {
    if (!platformKinds.includes(kind)) setKind(platformKinds[0] ?? "video");
  }, [kind, platformKinds]);
  const kindLimits = (platformMeta?.content_limits?.[kind] ?? {}) as {
    title_max?: number;
    body_max?: number | null;
    max_items?: number | null;
  };
  const titleMax = kindLimits.title_max ?? platformMeta?.title_max ?? 300;
  const bodyMax = kindLimits.body_max ?? null;
  const maxItems = kindLimits.max_items ?? null;
  const needsImages = kind !== "video";
  //: 这一条能不能提交:视频要一份素材;图文 / 文章要 1..max 张图;正文不超上限。
  const assetCount = needsImages ? imageIds.length : assetId ? 1 : 0;
  const tooManyImages = maxItems !== null && imageIds.length > maxItems;
  const bodyTooLong = bodyMax !== null && [...body].length > bodyMax;
  const assetsReady = assetCount > 0 && !tooManyImages;
  // 超长的标题后端会拒(publishErr_titleTooLong):计数变红的同时就不让提交,别等点了再报错。
  // 按码点数,和后端的 len() 同一把尺 —— `.length` 数的是 UTF-16 单元,一个 emoji 算两个,会提前拦下。
  const titleLength = [...title.trim()].length;
  const titleTooLong = titleLength > titleMax;
  const optionSpecs = platformMeta?.options ?? [];
  // 换平台就按新平台的声明重置:选项的键是平台专属的,带着上一个平台的键提交会被后端拒掉
  // (那是对的 —— 静默丢掉才会让人以为自己设了公开)。
  React.useEffect(() => {
    setOptions(Object.fromEntries(optionSpecs.map((spec) => [spec.key, spec.default])));
  }, [platformMeta?.platform]);

  //: 换形状:把不适用的选择清掉 —— 带着上一次的素材提交,发出去的和看到的不一样。
  React.useEffect(() => {
    if (kind === "video") {
      setImageIds([]);
      setBody("");
    } else {
      setAssetId(null);
      setAssetName("");
    }
  }, [kind]);

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
        content_kind: kind,
        ...(needsImages
          ? {
              asset_ids: imageIds,
              body: body.trim(),
              //: 图文 / 文章的正文就是 body:简介那一栏是**视频档**的东西,不能把同一段文字再发一遍,
              //: 否则适配器会把它当第二段填进编辑器(真机:正文被打了两遍)。
              description: "",
            }
          : { asset_id: assetId! }),
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
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={t("publishCreate")}
      //: 发布表单字段多(内容类型、素材网格、标题、正文、标签、平台选项),360 的默认宽度会让人
      //: 一行一行往下滚;给到 720,网格一次能摆下几张缩略图。窄窗口仍然收在视口内。
      className="w-[min(720px,calc(100vw-32px))]"
      footer={
        <>
          <Button
            className="mr-auto"
            variant="outline"
            size="sm"
            disabled={kind !== "video" || !assetId}
            loading={aiCopy.isPending}
            onClick={() => aiCopy.mutate()}
          >
            <Sparkles size={13} /> {t("publishAiCopy")}
          </Button>
          <Button variant="outline" size="sm" onClick={onClose}>{t("cancel")}</Button>
          <Button
            size="sm"
            disabled={!assetsReady || !selectedAccount || titleTooLong || bodyTooLong}
            loading={create.isPending}
            onClick={() => create.mutate()}
          >
            <Rocket size={13} /> {t("publishStart")}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <label className={DIALOG_FIELD}>
          <span>{t("publishAccount")}</span>
          <Combobox
            value={accountId ?? ""}
            options={usableAccounts.map((account: PublishAccount) => ({ value: account.id, label: account.name }))}
            placeholder={t("publishPickAccount")}
            emptyText={t("cmdkEmpty")}
            className="w-full"
            onValueChange={setAccountId}
          />
          {/* 取不回来不是「没有账号」:此前下拉里只写「没有匹配的结果」,没有一句错误也没有下一步(体检 UM-22)。 */}
          {accounts.isError && (
            <small data-publish-accounts-error="" className="text-destructive">
              {t("publishAccountsLoadFailed")}{" "}
              <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-[length:inherit] text-primary underline" onClick={() => void accounts.refetch()}>
                {t("retry")}
              </button>
            </small>
          )}
          
          {/* 「存着的设置解不开了」是**要人去处理**的警告(重新登录一次),不是普通说明:
              用警告色 + 一枚图标,和旁边的灰色小字区分开。 */}
          {unreadableAccounts.length > 0 && (
            <p
              data-publish-accounts-unreadable=""
              role="note"
              className="m-0 flex items-start gap-1.5 text-ui-xs leading-[1.45] text-warning"
            >
              <CircleAlert size={13} className="mt-[1px] shrink-0" />
              <span>
                {t("publishAccountConfigUnreadable").replace("{names}", unreadableAccounts.map((account) => account.name).join(t("listSeparator")))}
              </span>
            </p>
          )}
          {accounts.isSuccess && (allAccounts.length === 0 || disabledAccounts > 0) && (
            <small>
              {allAccounts.length === 0
                ? t("publishNoAccounts")
                : t("publishAccountsDisabledHidden").replace("{n}", String(disabledAccounts))}{" "}
              <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-[length:inherit] text-primary underline" onClick={onManageAccounts}>
                {t("publishAccounts")}
              </button>
            </small>
          )}
        </label>
        {/* 内容形状(ADR 0076):**排在发布目标之后** —— 先选发到哪,再选发什么形状,
            素材那一格才跟着换(视频是一份、图文是多张)。平台只认一种形状时不摆选择器。 */}
        {selectedAccount && platformKinds.length > 1 && (
          <div className="grid gap-2">
            {/*: 标题字号/字重跟着 DIALOG_FIELD 走(ui-sm / medium),不再自己写一套 12px 半粗。 */}
            <span className="text-ui-sm font-medium text-foreground">{t("publishContentKind")}</span>
            <Segmented
              //: **铺满这一行**(`fill`):同 `ExportControl` / `MaskFromAssetDialog` 里那种
              //: 「一整行的分段」—— 弹窗里一条只有两三档的选择,居中一小撮会显得没排满。
              fill
              //: **md**(40px),和这个弹窗里其余字段同高:分段原来用的是 sm(32),
              //: 比上面的下拉矮一截,一行里两种高度看着就是没对齐。
              size="md"
              aria-label={t("publishContentKind")}
              value={kind}
              onValueChange={(next) => setKind(next)}
              options={platformKinds.map((one) => ({
                value: one,
                //: 表里没有的形状不硬编名字(见 `KIND_LABEL_KEY`);真到那一步该先补表。
                label: kindLabel(one) ? t(kindLabel(one) as MessageKey) : one,
              }))}
            />
          </div>
        )}
        <div className="grid gap-2">
          <span className="text-ui-sm font-medium text-foreground">{t("publishAsset")}</span>
          {!needsImages && (
            //: **点开弹窗挑一份**(和图文那格的素材弹窗同一个控件):就地展开的下拉会把几十份成片
            //: 的名字排成一列,既难认也和应用里"挑素材"的样子不一样(维护者 2026-10-23)。
            <AssetPickerField
              workspaceId={workspace.id}
              value={assetId ?? ""}
              label={assetName}
              placeholder={t("publishPickAsset")}
              onChange={(id, name) => {
                setAssetId(id);
                setAssetName(name);
              }}
            />
          )}
          {/* 图文 / 文章:和工作流节点表单**同一个控件**(上传瓦片 + 「+」从素材库挑 + 缩略图 + 拖拽排序)。 */}
          {needsImages && (
            //: **撑满这一栏**,和别字段同宽(维护者 2026-10-23)。控件自己按「一排占满」排版,
            //: 挑到四张以上就回到四列;少于四枚时每枚各占一等份 —— 那是它本来的意思。
            <AssetGridField
              value={imageIds.join(",")}
              workspaceId={workspace.id}
              media={["image"]}
              max={maxItems ?? 18}
              onChange={(next) => {
                setImageIds(
                  String(next ?? "")
                    .split(",")
                    .map((one) => one.trim())
                    .filter(Boolean),
                );
              }}
            />
          )}
          {!needsImages && videos.isSuccess && videos.total === 0 && !videos.query && (
            <small className="text-ui-xs leading-[1.4] text-muted-foreground">{t("publishNoVideos")}</small>
          )}
        </div>
        <label className={DIALOG_FIELD}>
          <span>
            {t("publishTitle")}
            <em className={cn(
              "ml-2 font-normal normal-case not-italic tracking-normal text-muted-foreground",
              titleTooLong && "font-semibold text-destructive",
            )}>
              {titleLength}/{titleMax}
            </em>
          </span>
          <Input value={title} maxLength={titleMax + 20} onChange={(event) => setTitle(event.target.value)} />
        </label>
        {platformMeta?.short_title && (
          <label className={DIALOG_FIELD}>
            <span>{t("publishShortTitle")}</span>
            <Input value={shortTitle} maxLength={20} onChange={(event) => setShortTitle(event.target.value)} />
          </label>
        )}
        {/* 图文 / 文章的正文:平台的上限由后端声明(`content_limits.body_max`),这里只计数。 */}
        {needsImages && (
          <label className={DIALOG_FIELD}>
            <span>
              {t("publishBody")}
              <small className={bodyTooLong ? "text-destructive" : undefined}>
                {[...body].length}
                {bodyMax === null ? "" : ` / ${bodyMax}`}
              </small>
            </span>
            <Textarea rows={6} value={body} onChange={(event) => setBody(event.target.value)} />
          </label>
        )}
        {!needsImages && (
        <label className={DIALOG_FIELD}>
          <span>{t("publishDescription")}</span>
          <Textarea
            rows={3}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        )}
        <label className={DIALOG_FIELD}>
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
              //: **和别的字段同一种皮肤**:同样的 `rounded-md`(4px 的 `rounded` 会明显比方圆)、
              //: 同样的 `border-field-border` 与 `bg-field`、同样的标签字号与字重 ——
              //: 此前这里自己写了一套,维护者一眼看出「圆角、边框和别处不一致」(2026-10-23)。
              className="flex items-center justify-between gap-4 rounded-md border border-field-border bg-field px-2.5 py-2"
            >
              <span className="grid min-w-0 gap-0.5">
                <span className="text-ui-sm font-medium text-foreground">{spec.label}</span>
                {spec.description && (
                  <small className="text-ui-xs leading-[1.4] text-muted-foreground">
                    <InlineMarkdown text={spec.description} />
                  </small>
                )}
              </span>
              <Switch
                checked={Boolean(options[spec.key] ?? spec.default)}
                onCheckedChange={(next: boolean) => setOptions((prev) => ({ ...prev, [spec.key]: next }))}
              />
            </label>
          ) : (
            <label key={spec.key} className={DIALOG_FIELD}>
              <span>{spec.label}</span>
              <Combobox
                value={String(options[spec.key] ?? spec.default)}
                options={(spec.choices ?? []).map((choice) => ({ value: choice.value, label: choice.label }))}
                emptyText={t("cmdkEmpty")}
                className="w-full"
                onValueChange={(next) => setOptions((prev) => ({ ...prev, [spec.key]: next }))}
              />
              {spec.description && (
                <small>
                  <InlineMarkdown text={spec.description} />
                </small>
              )}
            </label>
          ),
        )}
      </div>
    </ModalShell>
  );
}
