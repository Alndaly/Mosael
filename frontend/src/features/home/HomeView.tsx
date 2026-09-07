import { ACTION_MENU } from "@/components/ui/floating";
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Clapperboard,
  Film,
  FolderPlus,
  Layers,
  MoreHorizontal,
  Search,
  Pencil,
  Scissors,
  Trash2,
} from "lucide-react";

import { api, assetThumbnailUrl, type Asset, deleteProject, renameProject, type Project, type ProjectWithStats, type Workspace } from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { STUDIO_PAGE, CollectionTabs } from "@/components/layout/StudioPage";
import { HomeHero } from "@/features/home/HomeHero";
import { poemOfToday, randomPoem, type Poem } from "@/features/home/poems";
import { relativeTime } from "@/lib/time";
import { formatSeconds, formatShortDate } from "@/features/media/MediaLibraryView";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/layout/EmptyState";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { usePersistentTab } from "@/lib/usePersistentTab";


export function HomeView({
  workspace,
  projects,
  onOpenProject,
  onCreateProject,
  creatingProject,
}: {
  workspace: Workspace;
  projects: ProjectWithStats[];
  onOpenProject: (projectId: string) => void;
  onCreateProject: () => void;
  creatingProject: boolean;
}) {
  const t = useI18n();
  
  const qc = useQueryClient();
  const [renaming, setRenaming] = React.useState<Project | null>(null);
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
    void qc.invalidateQueries({ queryKey: ["projects", workspace.id] });
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
  // Reuse the workspace asset cache. Only project-owned media can illustrate that project.
  const artwork = useQuery({
    queryKey: ["assets", workspace.id],
    queryFn: () => api<Asset[]>(`/api/assets?workspace_id=${workspace.id}`),
    enabled: projects.length > 0,
  });
  const covers = React.useMemo(() => {
    const result = new Map<string, Asset>();
    for (const asset of artwork.data ?? []) {
      if (asset.project_id && (asset.kind === "image" || asset.kind === "video") && !result.has(asset.project_id)) result.set(asset.project_id, asset);
    }
    return result;
  }, [artwork.data]);
  const refresh = () => qc.invalidateQueries({ queryKey: ["projects", workspace.id] });

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



  return (
    <div className={STUDIO_PAGE}>
      <HomeHero
        actions={<Button onClick={onCreateProject} loading={creatingProject}><FolderPlus />{t("createProject")}</Button>}
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
        <CollectionTabs label={t("homeProjectsTitle")} value={collection} onChange={mode => { setCollection(mode); if (mode === "recent") setSortKey("updated"); }} items={[{ value: "recent", label: t("homeRecent") }, { value: "all", label: t("homeAll") }]} />
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <div className="relative"><Search className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" /><Input aria-label={t("searchProjects")} className="w-52 pl-9" value={search} placeholder={t("searchProjects")} onChange={(event) => setSearch(event.target.value)} /></div>
          <Select value={collection === "recent" ? "updated" : sortKey} onValueChange={(value) => { setSortKey(value as "updated" | "created" | "name"); setCollection("all"); }}>
            <SelectTrigger className="w-auto min-w-36" aria-label={t("sortUpdated")}><SelectValue /></SelectTrigger>
            <SelectContent className="max-w-none">
              <SelectItem value="updated">{t("sortUpdated")}</SelectItem><SelectItem value="created">{t("sortCreated")}</SelectItem><SelectItem value="name">{t("sortName")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {projects.length === 0 ? (
        <EmptyState
          icon={<Clapperboard size={22} />}
          title={t("homeEmptyTitle")}
          body={t("homeEmptyBody")}
          action={
            <Button onClick={onCreateProject} disabled={creatingProject}>
              <FolderPlus size={15} /> {t("createProject")}
            </Button>
          }
        />
      ) : (
        <>
          {visible.length === 0 && <p className="py-10 text-center text-muted-foreground">{t("homeNoSearchResults")}</p>}
          {collection === "recent" && !search.trim() && <div className={cn("grid grid-cols-1 gap-6", visible.length >= 3 ? "lg:h-[470px] lg:grid-cols-[1.2fr_1fr] lg:grid-rows-2" : "lg:grid-cols-2")}>
            {visible.slice(0, 3).map((project, index) => <ProjectPresentation key={project.id} project={project} cover={covers.get(project.id)} featured className={index === 0 && visible.length >= 3 ? "lg:row-span-2" : undefined} onOpen={onOpenProject} onRename={setRenaming} onDelete={setDeleting} />)}
          </div>}
          <div className="grid gap-1 empty:hidden">
            {(collection === "recent" && !search.trim() ? visible.slice(3) : visible).map(project => <ProjectPresentation key={project.id} project={project} cover={covers.get(project.id)} onOpen={onOpenProject} onRename={setRenaming} onDelete={setDeleting} />)}
          </div>
        </>
      )}

      <RenameDialog
        open={renaming !== null}
        title={t("renameProject")}
        initialValue={renaming?.name ?? ""}
        onCancel={() => setRenaming(null)}
        onSubmit={(name) => renaming && rename.mutate({ id: renaming.id, name })}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("deleteProjectBody")}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  );
}

/** Every presentation shares the same actions; images always belong to this project. */
function ProjectPresentation({ project, cover, featured = false, className, onOpen, onRename, onDelete }: {
  project: ProjectWithStats; cover?: Asset; featured?: boolean; className?: string;
  onOpen: (id: string) => void; onRename: (project: Project) => void; onDelete: (project: Project) => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => setFailed(false), [cover?.id]);
  const open = () => onOpen(project.id);
  // 列表行的背景向外延伸，抵消自身内边距，让封面和操作按钮对齐上方精选卡片。
  return <ContextMenu>
    <ContextMenuTrigger asChild>
      <article className={cn("group min-h-0 min-w-0", featured ? "flex flex-col gap-3" : "-mx-3 flex items-center gap-4 rounded-lg px-3 py-4 transition-colors hover:bg-panel focus-within:bg-panel", className)}>
        <button type="button" onClick={open} aria-label={`${t("homeOpenEditor")}: ${project.name}`} className={cn("relative flex cursor-pointer items-center justify-center overflow-hidden rounded-lg border border-divider bg-panel-inset focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", featured ? "aspect-video min-h-32 w-full flex-1 lg:aspect-auto" : "h-20 w-32 shrink-0 max-[640px]:w-20")}>
          {cover && !failed ? <img src={assetThumbnailUrl(cover.id)} alt="" loading="lazy" onError={() => setFailed(true)} className="size-full object-cover transition-transform duration-300 motion-safe:group-hover:scale-[1.025]" /> : <span className="flex flex-col items-center gap-3 text-muted-foreground"><Clapperboard size={featured ? 32 : 24} strokeWidth={1.3} />{featured && <span className="text-ui-xs">{t("homeNoCover")}</span>}</span>}
          {(project.timeline_duration ?? 0) > 0 && <span className="absolute bottom-2 right-2 rounded bg-black/75 px-1.5 py-0.5 font-mono text-xs text-white">{formatSeconds(project.timeline_duration!)}</span>}
        </button>
        <div className={cn("flex min-w-0 items-start gap-2", !featured && "flex-1 items-center")}>
          <div className="min-w-0 flex-1">
            <button type="button" onClick={open} className={cn("block max-w-full cursor-pointer truncate rounded text-left font-semibold hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", featured ? "text-lg" : "text-ui-md")} title={project.name}>{project.name}</button>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-ui-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1"><Film size={12} />{t("projectStatAssets").replace("{n}", String(project.asset_count ?? 0))}</span>
              <span className="inline-flex items-center gap-1"><Layers size={12} />{t("projectStatSequences").replace("{n}", String(project.sequence_count ?? 0))}</span>
              {project.updated_at && <span title={project.created_at ? t("projectCreatedAt").replace("{t}", formatShortDate(project.created_at)) : undefined}>{t("projectStatUpdated").replace("{t}", relativeTime(project.updated_at, locale))}</span>}
            </div>
          </div>
          <Popover open={menuOpen} onOpenChange={setMenuOpen}>
            <PopoverTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`${t("projectActions")}: ${project.name}`}><MoreHorizontal /></Button></PopoverTrigger>
            <PopoverContent className={cn(ACTION_MENU, "w-48")} align="end">
              <Button variant="ghost" className="justify-start" onClick={() => { setMenuOpen(false); open(); }}><Scissors />{t("homeOpenEditor")}</Button>
              <Button variant="ghost" className="justify-start" onClick={() => { setMenuOpen(false); onRename(project); }}><Pencil />{t("rename")}</Button>
              <div className="mx-2 my-1 h-px bg-divider" />
              <Button variant="ghost" className="justify-start text-destructive hover:text-destructive" onClick={() => { setMenuOpen(false); onDelete(project); }}><Trash2 />{t("delete")}</Button>
            </PopoverContent>
          </Popover>
        </div>
      </article>
    </ContextMenuTrigger>
    <ContextMenuContent>
      <ContextMenuItem onSelect={open}><Scissors />{t("homeOpenEditor")}</ContextMenuItem>
      <ContextMenuItem onSelect={() => onRename(project)}><Pencil />{t("rename")}</ContextMenuItem>
      <ContextMenuSeparator />
      <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => onDelete(project)}><Trash2 />{t("delete")}</ContextMenuItem>
    </ContextMenuContent>
  </ContextMenu>;
}
