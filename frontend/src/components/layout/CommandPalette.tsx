import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BookOpen,
  Bot,
  Boxes,
  CalendarClock,
  Clapperboard,
  FileAudio,
  FileImage,
  FileText,
  FileVideo,
  FolderOpen,
  FolderPlus,
  Home,
  Moon,
  Plug,
  Rocket,
  Scissors,
  SearchX,
  Settings,
  Sun,
  Workflow,
} from "lucide-react";

import { api, listPublishTasks, listWorkflows, type Asset, type ProjectWithStats, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n, usePreferences } from "@/app/preferences";
import { Highlight } from "@/components/app/Highlight";
import type { StudioView } from "@/components/layout/AppShell";
import {
  CommandDialog,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { emitOpenEvent } from "@/lib/deepLink";


/** 页面导航项:label 走 i18n,keywords 供英文/拼音前缀匹配。 */
const NAV_ENTRIES: Array<{ view: StudioView; labelKey: string; keywords: string[]; icon: React.ReactNode }> = [
  { view: "home", labelKey: "navHome", keywords: ["home", "shouye"], icon: <Home size={14} /> },
  { view: "media", labelKey: "navMedia", keywords: ["media", "assets", "sucai"], icon: <FolderOpen size={14} /> },
  { view: "editor", labelKey: "navEditor", keywords: ["editor", "cut", "jianji"], icon: <Scissors size={14} /> },
  { view: "ai", labelKey: "navAi", keywords: ["ai", "chat", "agent"], icon: <Bot size={14} /> },
  { view: "publish", labelKey: "navPublish", keywords: ["publish", "fabu"], icon: <Rocket size={14} /> },
  { view: "workflows", labelKey: "navWorkflows", keywords: ["workflow", "flow", "gongzuoliu"], icon: <Workflow size={14} /> },
  { view: "browser-pool", labelKey: "navBrowserPool", keywords: ["browser", "pool", "account", "liulanqi", "zhanghao"], icon: <Boxes size={14} /> },
  { view: "settings", labelKey: "navSettings", keywords: ["settings", "shezhi"], icon: <Settings size={14} /> },
  { view: "scheduler", labelKey: "schedulerTitle", keywords: ["schedule", "cron", "dingshi"], icon: <CalendarClock size={14} /> },
  { view: "plugins", labelKey: "pluginsTitle", keywords: ["plugins", "chajian"], icon: <Plug size={14} /> },
];

const ASSET_ICONS: Record<string, React.ReactNode> = {
  video: <FileVideo size={14} />,
  audio: <FileAudio size={14} />,
  image: <FileImage size={14} />,
};

export function CommandPalette({
  workspace,
  projects,
  onNavigate,
  onOpenProject,
}: {
  workspace: Workspace;
  projects: ProjectWithStats[];
  onNavigate: (view: StudioView) => void;
  onOpenProject: (projectId: string) => void;
}) {
  const t = useI18n();
  const { theme, setTheme } = usePreferences();
  const [open, setOpen] = React.useState(false);
  const [input, setInput] = React.useState("");
  const [query, setQuery] = React.useState("");

  // Cmd+K / Ctrl+K 全局开关
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    // 顶栏搜索按钮通过该事件打开(它和面板不在同一组件树)。
    const onOpenEvent = () => setOpen(true);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("mosael:open-cmdk", onOpenEvent);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("mosael:open-cmdk", onOpenEvent);
    };
  }, []);

  // 250ms 防抖;关闭时清空,避免下次打开闪旧结果。
  React.useEffect(() => {
    const timer = window.setTimeout(() => setQuery(input.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [input]);
  React.useEffect(() => {
    if (!open) {
      setInput("");
      setQuery("");
    }
  }, [open]);

  const assets = useQuery({
    // Same key as the media library — same request. Two keys meant the palette warmed one
    // cache entry and the page read the other, so a deep link landed on an empty list.
    queryKey: ["assets", workspace.id],
    queryFn: () => api<Asset[]>(`/api/assets?workspace_id=${workspace.id}`),
    enabled: open && query.length > 0,
    staleTime: 30_000,
  });

  // 工作流与发布记录都有现成的深链通道(mosael:open-*),接进来就能跳。
  const workflows = useQuery({
    queryKey: ["workflows", workspace.id],
    queryFn: () => listWorkflows(workspace.id),
    enabled: open && query.length > 0,
    staleTime: 30_000,
  });
  const publishTasks = useQuery({
    queryKey: ["publish-tasks", workspace.id],
    queryFn: () => listPublishTasks(workspace.id),
    enabled: open && query.length > 0,
    staleTime: 30_000,
  });

  const q = query.toLowerCase();
  const navMatches = q
    ? NAV_ENTRIES.filter(
        (entry) =>
          t(entry.labelKey as never).toLowerCase().includes(q) ||
          entry.keywords.some((keyword) => keyword.startsWith(q)),
      )
    : NAV_ENTRIES;
  const projectMatches = q ? projects.filter((project) => project.name.toLowerCase().includes(q)).slice(0, 6) : [];
  const assetMatches = q
    ? (assets.data ?? [])
        .filter(
          (asset) =>
            asset.name.toLowerCase().includes(q) ||
            (asset.tags ?? []).some((tag) => tag.toLowerCase().includes(q)),
        )
        .slice(0, 6)
    : [];

  // 名字之外也搜说明/账号/成片名 —— 记不住标题但记得"发到哪个号"的时候,那才是他手上的线索。
  const workflowMatches = q
    ? (workflows.data ?? [])
        .filter(
          (workflow) =>
            workflow.name.toLowerCase().includes(q) || (workflow.description ?? "").toLowerCase().includes(q),
        )
        .slice(0, 6)
    : [];
  const publishMatches = q
    ? (publishTasks.data ?? [])
        .filter(
          (task) =>
            task.title.toLowerCase().includes(q) ||
            task.asset_name.toLowerCase().includes(q) ||
            task.account_name.toLowerCase().includes(q),
        )
        .slice(0, 6)
    : [];

  const run = (action: () => void) => {
    setOpen(false);
    action();
  };

  // 空态是手工判的(关掉了 cmdk 内建过滤),所以**每加一类结果都要加进这两行** ——
  // 漏掉的话「没有匹配的结果」会和结果同时显示出来(加发布记录时就这么漏过一次)。
  const searching = assets.isFetching || workflows.isFetching || publishTasks.isFetching || input.trim() !== query;
  const hasAnyResult =
    navMatches.length > 0 ||
    projectMatches.length > 0 ||
    assetMatches.length > 0 ||
    workflowMatches.length > 0 ||
    publishMatches.length > 0;

  // 关掉内建过滤后 cmdk 不再自动高亮第一项(Enter 会没有目标)— 受控高亮:
  // 结果集头名变化(=输入变化)时重置到第一项,方向键仍经 onValueChange 自由移动。
  const firstValue =
    q === ""
      ? "action-new-project"
      : navMatches.length > 0
        ? `nav-${navMatches[0].view}`
        : projectMatches.length > 0
          ? `project-${projectMatches[0].id}`
          : assetMatches.length > 0
            ? `asset-${assetMatches[0].id}`
              : "";
  const [highlighted, setHighlighted] = React.useState(firstValue);
  React.useEffect(() => {
    setHighlighted(firstValue);
  }, [firstValue]);

  return (
    // 面板自己做匹配(中文子串 + 拼音/英文关键词 + 服务端检索),item 的 value 是
    // 不可读的稳定 id — 必须关掉 cmdk 的内建按 value 过滤,否则真命中反被藏起来。
    <CommandDialog
      open={open}
      onOpenChange={setOpen}
      shouldFilter={false}
      value={highlighted}
      onValueChange={setHighlighted}
    >
      <CommandInput
        value={input}
        onValueChange={setInput}
        placeholder={t("cmdkPlaceholder")}
        autoFocus
      />
      <CommandList>
        {/* cmdk 的 <CommandEmpty> 依赖内建过滤计数,关掉过滤后永不触发 — 手工空态。
            检索请求在途时不闪空态。 */}
        {!hasAnyResult && !searching && (
          <div className="grid justify-items-center gap-1 px-3 pb-[30px] pt-[26px] text-center [&>span:last-child]:max-w-80 [&>span:last-child]:text-ui-xs [&>span:last-child]:leading-normal [&>span:last-child]:text-muted-foreground [&_strong]:text-ui-sm [&_strong]:font-semibold [&_strong]:text-foreground">
            <span className="mb-1 grid h-9 w-9 place-items-center rounded-lg bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary">
              <SearchX size={17} />
            </span>
            <strong>{t("cmdkEmpty")}</strong>
            <span>{t("cmdkEmptyHint")}</span>
          </div>
        )}

        {q === "" && (
          <>
            <CommandGroup heading={t("cmdkQuickActions")}>
              <CommandItem value="action-new-project" onSelect={() => run(() => onNavigate("home"))}>
                <FolderPlus size={14} />
                {t("createProject")}
              </CommandItem>
              <CommandItem
                value="action-toggle-theme"
                onSelect={() => run(() => setTheme(theme === "dark" ? "light" : "dark"))}
              >
                {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
                {t("cmdkToggleTheme")}
              </CommandItem>
            </CommandGroup>
            <CommandSeparator />
          </>
        )}

        {navMatches.length > 0 && (
          <CommandGroup heading={t("cmdkPages")}>
            {navMatches.map((entry) => (
              <CommandItem key={entry.view} value={`nav-${entry.view}`} onSelect={() => run(() => onNavigate(entry.view))}>
                {entry.icon}
                <Highlight text={t(entry.labelKey as never)} query={query} />
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {projectMatches.length > 0 && (
          <CommandGroup heading={t("cmdkProjects")}>
            {projectMatches.map((project) => (
              <CommandItem
                key={project.id}
                value={`project-${project.id}`}
                onSelect={() => run(() => onOpenProject(project.id))}
              >
                <Clapperboard size={14} />
                <Highlight className="min-w-0 flex-1 truncate" text={project.name} query={query} />
                <span className="text-ui-xs text-muted-foreground">
                  {t("projectStatAssets").replace("{n}", String(project.asset_count))}
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {workflowMatches.length > 0 && (
          <CommandGroup heading={t("navWorkflows")}>
            {workflowMatches.map((workflow) => (
              <CommandItem
                key={workflow.id}
                value={`workflow-${workflow.id}`}
                onSelect={() =>
                  run(() => {
                    onNavigate("workflows");
                    emitOpenEvent("mosael:open-workflow", workflow.id);
                  })
                }
              >
                <Workflow size={14} />
                <Highlight className="min-w-0 flex-1 truncate" text={workflow.name} query={query} />
                <span className="text-ui-xs tabular-nums text-muted-foreground">
                  {t("wfNodeCount").replace("{n}", String(((workflow.graph as { nodes?: unknown[] }).nodes ?? []).length))}
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {publishMatches.length > 0 && (
          <CommandGroup heading={t("publishListTitle")}>
            {publishMatches.map((task) => (
              <CommandItem
                key={task.id}
                value={`publish-${task.id}`}
                onSelect={() =>
                  run(() => {
                    onNavigate("publish");
                    emitOpenEvent("mosael:open-publish-task", task.id);
                  })
                }
              >
                <Rocket size={14} />
                <Highlight className="min-w-0 flex-1 truncate" text={task.title || task.asset_name} query={query} />
                <span className="text-ui-xs text-muted-foreground">{t(`batchStatus_${task.status}` as never)}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {assetMatches.length > 0 && (
          <CommandGroup heading={t("cmdkAssets")}>
            {assetMatches.map((asset) => (
              <CommandItem
                key={asset.id}
                value={`asset-${asset.id}`}
                onSelect={() =>
                  run(() => {
                    onNavigate("media");
                    // 素材库监听该事件后打开预览(跨页面深链的最小通道)。
                    emitOpenEvent("mosael:open-asset", asset.id);
                  })
                }
              >
                {ASSET_ICONS[asset.kind] ?? <FileVideo size={14} />}
                <Highlight className="min-w-0 flex-1 truncate" text={asset.name} query={query} />
                <span className="text-ui-xs uppercase text-muted-foreground">{asset.kind}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
      </CommandList>
    </CommandDialog>
  );
}
