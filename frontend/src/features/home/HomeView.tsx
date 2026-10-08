import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Clapperboard,
  Film,
  ListChecks,
  FolderPlus,
  Layers,
  MoreHorizontal,
  Pencil,
  Scissors,
  Trash2,
  X,
} from "lucide-react";

import { api, assetThumbnailUrl, deleteProject, renameProject, type Project, type ProjectWithStats, type Workspace } from "@/api/client";
import { projectKeys } from "@/api/queryKeys";
import { useI18n, usePreferences } from "@/app/preferences";
import { STUDIO_PAGE, CollectionTabs } from "@/components/layout/StudioPage";
import { useWriteBlocked, type WriteBlock } from "@/components/layout/useWriteBlocked";
import { HomeHero } from "@/features/home/HomeHero";
import { poemOfToday, randomPoem, type Poem } from "@/features/home/poems";
import { formatShortDate, formatTimecode, relativeTime } from "@/lib/time";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem, MenuItemBody, MenuSeparator } from "@/components/ui/menu";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState, PageLoadError } from "@/components/layout/EmptyState";
import { LoadingState } from "@/components/layout/LoadingState";
import { cn } from "@/lib/utils";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { SearchInput } from "@/components/ui/search-input";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { useMultiSelect } from "@/lib/useMultiSelect";
import { nextProjectName, useCreateProject } from "@/lib/useCreateProject";
import { SelectionCheck } from "@/components/app/SelectionCheck";
import { toast } from "sonner";


/** 项目列表取得怎样。列表在 App 里取(侧栏切项目也要它),首页只读这份状态。 */
export type ProjectsLoad = { pending: boolean; error: unknown; retrying: boolean; retry: () => void };

export function HomeView({
  workspace,
  projects,
  load,
  onOpenProject,
}: {
  workspace: Workspace;
  projects: ProjectWithStats[];
  load: ProjectsLoad;
  onOpenProject: (projectId: string) => void;
}) {
  const t = useI18n();
  //: 只读成员建不了、改不了、删不了项目:这几处灰掉并说为什么(体检 D62,和定时任务页同一个做法)。
  const writeBlocked = useWriteBlocked(workspace.role);
  const qc = useQueryClient();
  const [renaming, setRenaming] = React.useState<Project | null>(null);
  //: 新建:先弹窗起名,建好**留在首页**,新项目滚到看得见的地方、高亮一下 —— 此前一点就建了个
  //: 「未命名项目 N」并直接跳进剪辑页,看起来像只是跳了个页面,根本没意识到建了东西。
  const [naming, setNaming] = React.useState(false);
  const [justCreated, setJustCreated] = React.useState<string | null>(null);
  const create = useCreateProject(workspace.id, (id) => {
    setNaming(false);
    setSearch("");
    setJustCreated(id);
  });
  React.useEffect(() => {
    if (!justCreated) return;
    document.querySelector(`[data-project-id="${justCreated}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    const timer = window.setTimeout(() => setJustCreated(null), 2400);
    return () => window.clearTimeout(timer);
  }, [justCreated, projects]);
  const [deleting, setDeleting] = React.useState<Project | null>(null);
  const [search, setSearch] = React.useState("");
  const [collection, setCollection] = usePersistentTab<"recent" | "all">("home-collection", "recent", ["recent", "all"]);
  // 排序方式跟着人走 —— 切走再回来不该重置成默认(见 lib/usePersistentTab)。
  const [sortKey, setSortKey] = usePersistentTab<"updated" | "created" | "name">(
    "home-sort", "updated", ["updated", "created", "name"],
  );

  // 诗从后端取(今日诗词,几十万句);取不到就用本地精选那份 —— 断网不该让首页空一格。
  // 首屏先给本地那句,网络回来了再换,避免开屏闪一下空白。
  const [poem, setPoem] = React.useState<Poem>(poemOfToday);
  const [poemSpins, setPoemSpins] = React.useState(0);
  const [poemLoading, setPoemLoading] = React.useState(false);
  const spinPoem = React.useCallback(async () => {
    setPoemSpins((n) => n + 1);
    setPoemLoading(true);
    try {
      const remote = await api<{ text: string; author: string; source: string; dynasty: string }>("/api/home/poem");
      if (remote?.text) {
        setPoem({ text: remote.text, author: remote.author || remote.dynasty, source: remote.source });
        return;
      }
      setPoem((current) => randomPoem(current));
    } catch {
      setPoem((current) => randomPoem(current));
    } finally {
      setPoemLoading(false);
    }
  }, []);
  React.useEffect(() => {
    void spinPoem();
  }, [spinPoem]);

  // 走字的钟。它不解决任何问题 —— 但盯着首页等渲染/发布跑完的时候,一个还在动的东西
  // 让这一页看起来是活的。每秒一跳,只在首页挂载期间。
  // ?holiday=christmas 之类:节日效果一年只有几天能看到,没有预览入口等于写完没法验。
  // 跟着 hashchange 走 —— 只在挂载时读一次的话,改了地址栏没反应,这个知道也用不了。
  const readHolidayOverride = () =>
    new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("holiday");
  const [holidayOverride, setHolidayOverride] = React.useState(readHolidayOverride);
  React.useEffect(() => {
    const sync = () => setHolidayOverride(readHolidayOverride());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const [now, setNow] = React.useState(() => new Date());
  React.useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const greetingKey = React.useMemo(() => {
    const hour = new Date().getHours();
    if (hour < 5) return "homeGreetingDawn" as const;
    if (hour < 11) return "homeGreetingMorning" as const;
    if (hour < 13) return "homeGreetingNoon" as const;
    if (hour < 18) return "homeGreetingAfternoon" as const;
    return "homeGreetingEvening" as const;
  }, []);


  React.useEffect(() => {
    void qc.invalidateQueries({ queryKey: projectKeys.list(workspace.id) });
  }, [qc, workspace.id]);

  const visible = React.useMemo(() => {
    const query = search.trim().toLowerCase();
    const matched = projects.filter((project) => query === "" || project.name.toLowerCase().includes(query));
    return [...matched].sort((a, b) => {
      if (collection === "all" && sortKey === "name") return a.name.localeCompare(b.name, "zh-CN");
      if (collection === "all" && sortKey === "created") return (b.created_at ?? "").localeCompare(a.created_at ?? "");
      return (b.updated_at ?? "").localeCompare(a.updated_at ?? "");
    });
  }, [projects, search, sortKey, collection]);
  const refresh = () => qc.invalidateQueries({ queryKey: projectKeys.list(workspace.id) });

  // 多选与素材、工作流、发布同一份状态机(见 lib/useMultiSelect):退出即清空、全选只作用于
  // 当前看得见的那些(搜索之后)、被删掉的自动剔除。
  const { selectMode, enter: enterSelectMode, selectedIds, toggle, selectAll, allSelected, clear, exit, menuTargets } =
    useMultiSelect(visible, (project) => project.id);
  const [batchDeleting, setBatchDeleting] = React.useState(false);
  const batchRemove = useMutation({
    mutationFn: async () => {
      // 没有批量接口:逐条删,失败的报出去(和工作流、素材页同一种做法)。
      const failures: string[] = [];
      for (const id of selectedIds) {
        try {
          await deleteProject(id);
        } catch (error) {
          failures.push(String((error as Error).message));
        }
      }
      return failures;
    },
    onSuccess: (failures) => {
      clear();
      if (failures.length > 0) toast.error(failures.join("\n"));
      void refresh();
    },
    onSettled: () => setBatchDeleting(false),
  });

  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameProject(id, name),
    onSuccess: () => {
      void refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setRenaming(null);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteProject(id),
    onSuccess: () => {
      void refresh();
    },
    // Closed in onSettled, not onSuccess: a failed request used to leave the dialog
    // open with its confirm button re-enabled, so repeated clicks fired repeated
    // requests. The global fallback still reports the error.
    onSettled: () => {
      setDeleting(null);
    },
  });



  //: 真取回来一个空列表时,「新建项目」只在正中的空状态里摆一颗:页头再留一颗同一件事的实心按钮,一屏两个主动作,
  //: 空状态的视觉中心也被拽到右上角(画板、工作流、发布空页同一个做法)。取的途中照旧摆着 —— 大多数工作区不是空的,不让它晚一拍才冒出来。
  const empty = projects.length === 0 && !load.error && !load.pending;

  return (
    <div className={STUDIO_PAGE}>
      <HomeHero
        actions={empty ? undefined : (
          <Hint disabledReason={writeBlocked?.reason}>
            <Button disabled={Boolean(writeBlocked)} onClick={() => setNaming(true)}><FolderPlus />{t("createProject")}</Button>
          </Hint>
        )}
        greeting={t(greetingKey)}
        workspaceName={workspace.name}
        now={now}
        poem={poem}
        poemLoading={poemLoading}
        poemEgg={poemSpins > 0 && poemSpins % 10 === 0 ? t("homePoemEgg") : undefined}
        onRefreshPoem={() => void spinPoem()}
        holidayOverride={holidayOverride}
      />
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <CollectionTabs label={t("homeProjectsTitle")} value={collection} onChange={setCollection} items={[{ value: "recent", label: t("homeRecent") }, { value: "all", label: t("homeAll") }]} />
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {projects.length > 0 && (selectMode ? (
            <>
              <span className="whitespace-nowrap text-xs text-muted-foreground">
                {t("mediaSelectedCount").replace("{n}", String(selectedIds.size))}
              </span>
              <Button variant="outline" onClick={() => selectAll(visible)}>
                <ListChecks size={13} /> {allSelected(visible) ? t("mediaDeselectAll") : t("mediaSelectAll")}
              </Button>
              <Hint disabledReason={writeBlocked?.reason}>
                <Button
                  variant="outline"
                  className="hover:border-destructive/50 hover:text-destructive"
                  disabled={selectedIds.size === 0 || Boolean(writeBlocked)}
                  onClick={() => setBatchDeleting(true)}
                >
                  <Trash2 size={13} /> {t("delete")}
                </Button>
              </Hint>
              <Button variant="outline" onClick={exit}>
                <X size={13} /> {t("cancel")}
              </Button>
            </>
          ) : (
            <Button variant="outline" onClick={() => enterSelectMode()}>
              <Check size={13} /> {t("mediaSelectMode")}
            </Button>
          ))}
          <SearchInput className="w-52" aria-label={t("searchProjects")} value={search} placeholder={t("searchProjects")} onChange={(event) => setSearch(event.target.value)} />
          {/* 「最近」这一栏本身就是按更新时间排的,这里只是**显示**成它;人选的那种排序原样留着,回到「全部」
              还是他选的那一种 —— 切到「最近」时不去改写它(那等于替人把排序改了)。 */}
          <Select value={collection === "recent" ? "updated" : sortKey} onValueChange={(value) => { setSortKey(value as "updated" | "created" | "name"); setCollection("all"); }}>
            <SelectTrigger className="w-auto min-w-36" aria-label={t("sortUpdated")}><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="updated">{t("sortUpdated")}</SelectItem><SelectItem value="created">{t("sortCreated")}</SelectItem><SelectItem value="name">{t("sortName")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* 「还没有项目」只在真取回来一个空列表时说:后端瞬断、升级重启时取不回来,此前也是这一句 + 「新建一个项目」,
          看着像项目全丢了(体检 UM-21)。轮询中途失败、手上还有上一份的,照旧显示上一份。 */}
      {projects.length === 0 && load.error ? (
        <PageLoadError icon={<Clapperboard size={22} />} error={load.error} retrying={load.retrying} onRetry={load.retry} />
      ) : projects.length === 0 && load.pending ? (
        <LoadingState />
      ) : projects.length === 0 ? (
        <EmptyState
          icon={<Clapperboard size={22} />}
          title={t("homeEmptyTitle")}
          body={t("homeEmptyBody")}
          action={
            <Hint disabledReason={writeBlocked?.reason}>
              <Button disabled={Boolean(writeBlocked)} onClick={() => setNaming(true)}>
                <FolderPlus size={15} /> {t("createProject")}
              </Button>
            </Hint>
          }
        />
      ) : (
        <>
          {visible.length === 0 && <p className="py-10 text-center text-muted-foreground">{t("homeNoSearchResults")}</p>}
          {collection === "recent" && !search.trim() && <div className={cn("grid grid-cols-1 gap-6", visible.length >= 3 ? "lg:h-[470px] lg:grid-cols-[1.2fr_1fr] lg:grid-rows-2" : "lg:grid-cols-2")}>
            {visible.slice(0, 3).map((project, index) => <ProjectPresentation key={project.id} project={project} featured className={index === 0 && visible.length >= 3 ? "lg:row-span-2" : undefined} onOpen={onOpenProject} onRename={setRenaming} onDelete={setDeleting} selecting={selectMode} selected={selectedIds.has(project.id)} onToggle={toggle} menuSelection={menuTargets(project.id).length} onDeleteSelection={() => setBatchDeleting(true)} highlighted={justCreated === project.id} writeBlocked={writeBlocked} />)}
          </div>}
          <div className="grid gap-1 empty:hidden">
            {(collection === "recent" && !search.trim() ? visible.slice(3) : visible).map(project => <ProjectPresentation key={project.id} project={project} onOpen={onOpenProject} onRename={setRenaming} onDelete={setDeleting} selecting={selectMode} selected={selectedIds.has(project.id)} onToggle={toggle} menuSelection={menuTargets(project.id).length} onDeleteSelection={() => setBatchDeleting(true)} highlighted={justCreated === project.id} writeBlocked={writeBlocked} />)}
          </div>
        </>
      )}

      <RenameDialog
        open={naming}
        title={t("createProject")}
        initialValue={nextProjectName(t("projectDefault"), projects)}
        confirmLabel={t("createProjectConfirm")}
        pending={create.isPending}
        onCancel={() => setNaming(false)}
        onSubmit={(name) => create.mutate(name)}
      />
      <RenameDialog
        open={renaming !== null}
        title={t("renameProject")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        pending={rename.isPending}
        onSubmit={(name) => renaming && rename.mutate({ id: renaming.id, name })}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("deleteProjectBody")}
        onCancel={() => setDeleting(null)}
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
      <ConfirmDialog
        open={batchDeleting}
        title={t("deleteConfirmTitle")}
        body={t("deleteProjectsBody").replace("{n}", String(selectedIds.size))}
        onCancel={() => setBatchDeleting(false)}
        pending={batchRemove.isPending}
        onConfirm={() => batchRemove.mutate()}
      />
    </div>
  );
}

/** Every presentation shares the same actions; images always belong to this project. */
function ProjectPresentation({ project, featured = false, className, onOpen, onRename, onDelete, selecting = false, selected = false, onToggle, menuSelection = 1, onDeleteSelection, highlighted = false, writeBlocked = null }: {
  project: ProjectWithStats; featured?: boolean; className?: string;
  onOpen: (id: string) => void; onRename: (project: Project) => void; onDelete: (project: Project) => void;
  /** 选择模式下点卡片是勾选,不是打开;单条的操作菜单收起来(批量动作在工具条上)。 */
  selecting?: boolean; selected?: boolean; onToggle?: (id: string) => void;
  /** 右键菜单作用于几项(useMultiSelect.menuTargets):大于 1 = 右键的这一项在选区里,菜单作用于整个选区,
   *  只给能对一批做的动作;和时间线同一条规则。 */
  menuSelection?: number; onDeleteSelection?: () => void;
  /** 刚建好的那一个:亮一下,让人一眼看到它在哪儿。 */
  highlighted?: boolean;
  /** 改不了(只读成员)的原因;改名、删除灰掉,原因写在条目下面。 */
  writeBlocked?: WriteBlock | null;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  // 封面由后端给:时间线上最早出现的画面,没有时是项目自己的第一张图(见 routes/projects._covers)。
  const cover = project.cover_asset_id;
  React.useEffect(() => setFailed(false), [cover]);
  //: **整行 / 整张卡**都是可点区域(点空白处也算),由外层 article 统一接:平时是打开,选择模式下
  //: 是勾选。里面的封面和标题只是给键盘用的按钮,点击冒泡上去 —— 各处理一次的话,选择模式下点
  //: 封面会勾上又立刻取消,平时会打开两次。
  //: 刚建好的那个和选中的长得一样(卡片是封面一圈主色,列表行是一层主色底),只是过两秒自己褪掉 ——
  //: 另起一套「整张卡外面再套一圈」的样式,把标题也圈进去,和选中态不是一个语言。
  const marked = (selecting && selected) || highlighted;
  const activate = () => (selecting ? onToggle?.(project.id) : onOpen(project.id));
  const open = () => onOpen(project.id);
  // 列表行的背景向外延伸，抵消自身内边距，让封面和操作按钮对齐上方精选卡片。
  return <ContextMenu>
    <ContextMenuTrigger asChild>
      <article
        data-project-id={project.id}
        aria-selected={selecting ? selected : undefined}
        onClick={activate}
        className={cn(
          "group min-h-0 min-w-0 cursor-pointer",
          featured ? "flex flex-col gap-3" : "-mx-3 flex items-center gap-4 rounded-lg px-3 py-4 transition-colors hover:bg-panel focus-within:bg-panel",
          //: 列表行选中:整行一层淡淡的主色底,不给每行各套一圈边框 —— 连着选几行时,一圈圈边框摞在一起很乱。
          marked && !featured && "bg-[color-mix(in_srgb,var(--primary)_8%,transparent)] hover:bg-[color-mix(in_srgb,var(--primary)_11%,transparent)]",
          className,
        )}
      >
        <button type="button" aria-label={`${selecting ? t("mediaSelectMode") : t("homeOpenEditor")}: ${project.name}`} aria-pressed={selecting ? selected : undefined} className={cn("relative flex cursor-pointer items-center justify-center overflow-hidden rounded-lg border border-divider bg-panel-inset focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", featured ? "aspect-video min-h-32 w-full flex-1 lg:aspect-auto" : "h-20 w-32 shrink-0 max-[640px]:w-20", featured && "transition-shadow", marked && featured && "ring-2 ring-primary")}>
          {cover && !failed ? <img src={assetThumbnailUrl(cover)} alt="" loading="lazy" onError={() => setFailed(true)} className="size-full object-cover transition-transform duration-240 motion-safe:group-hover:scale-[1.025]" /> : <span className="flex flex-col items-center gap-3 text-muted-foreground"><Clapperboard size={featured ? 32 : 24} strokeWidth={1.3} />{featured && <span className="text-ui-xs">{t("homeNoCover")}</span>}</span>}
          {(project.timeline_duration ?? 0) > 0 && <span className="absolute bottom-2 right-2 rounded bg-black/75 px-1.5 py-0.5 font-mono text-xs text-white">{formatTimecode(project.timeline_duration!)}</span>}
          {selecting && <SelectionCheck selected={selected} />}
        </button>
        <div className={cn("flex min-w-0 items-start gap-2", !featured && "flex-1 items-center")}>
          <div className="min-w-0 flex-1">
            <button type="button" className={cn("block max-w-full cursor-pointer rounded text-left font-semibold hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", featured ? "text-lg" : "text-ui-md")}><Truncate>{project.name}</Truncate></button>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-ui-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1"><Film size={12} />{t((project.asset_count ?? 0) === 1 ? "projectStatAsset" : "projectStatAssets").replace("{n}", String(project.asset_count ?? 0))}</span>
              <span className="inline-flex items-center gap-1"><Layers size={12} />{t((project.sequence_count ?? 0) === 1 ? "projectStatSequence" : "projectStatSequences").replace("{n}", String(project.sequence_count ?? 0))}</span>
              {project.updated_at && <Hint label={project.created_at ? t("projectCreatedAt").replace("{t}", formatShortDate(project.created_at)) : undefined}><span>{t("projectStatUpdated").replace("{t}", relativeTime(project.updated_at, locale))}</span></Hint>}
            </div>
          </div>
          {/* 菜单里的点击不能冒泡到整行 —— 否则点「…」或菜单里的「重命名」会顺带把项目打开。
              Popover 的内容虽然渲染在 portal 里,React 的事件仍按组件树冒泡。 */}
          {!selecting && <span className="contents" onClick={(event) => event.stopPropagation()}><Popover open={menuOpen} onOpenChange={setMenuOpen}>
            <PopoverTrigger asChild><IconButton label={`${t("projectActions")}: ${project.name}`} aria-haspopup="menu"><MoreHorizontal /></IconButton></PopoverTrigger>
            <MenuContent label={`${t("projectActions")}: ${project.name}`} align="end">
              <MenuItem icon={<Scissors />} label={t("homeOpenEditor")} onClick={() => { setMenuOpen(false); open(); }} />
              <MenuItem icon={<Pencil />} label={t("rename")} disabled={Boolean(writeBlocked)} description={writeBlocked?.brief} onClick={() => { setMenuOpen(false); onRename(project); }} />
              <MenuSeparator />
              <MenuItem icon={<Trash2 />} label={t("delete")} destructive disabled={Boolean(writeBlocked)} description={writeBlocked?.brief} onClick={() => { setMenuOpen(false); onDelete(project); }} />
            </MenuContent>
          </Popover></span>}
        </div>
      </article>
    </ContextMenuTrigger>
    <ContextMenuContent>
      {menuSelection > 1 && onDeleteSelection ? (
        <ContextMenuItem className="text-destructive focus:text-destructive" disabled={Boolean(writeBlocked)} onSelect={onDeleteSelection}><MenuItemBody icon={<Trash2 />} label={t("deleteSelectedN").replace("{n}", String(menuSelection))} description={writeBlocked?.brief} /></ContextMenuItem>
      ) : (
        <>
          <ContextMenuItem onSelect={open}><MenuItemBody icon={<Scissors />} label={t("homeOpenEditor")} /></ContextMenuItem>
          <ContextMenuItem disabled={Boolean(writeBlocked)} onSelect={() => onRename(project)}><MenuItemBody icon={<Pencil />} label={t("rename")} description={writeBlocked?.brief} /></ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem className="text-destructive focus:text-destructive" disabled={Boolean(writeBlocked)} onSelect={() => onDelete(project)}><MenuItemBody icon={<Trash2 />} label={t("delete")} description={writeBlocked?.brief} /></ContextMenuItem>
        </>
      )}
    </ContextMenuContent>
  </ContextMenu>;
}
