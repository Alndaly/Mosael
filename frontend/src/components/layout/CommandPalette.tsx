import React from "react";
import { assetKeys } from "@/api/queryKeys";
import { useQuery } from "@tanstack/react-query";
import {
  Clapperboard,
  FileAudio,
  FileImage,
  FileVideo,
  FolderPlus,
  Rocket,
  SearchX,
  Workflow,
} from "lucide-react";

import { api, listPublishTasks, listWorkflows, type Asset, type ProjectWithStats, type Workspace } from "@/api/client";
import { useIsDeploymentAdmin } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { Highlight } from "@/components/app/Highlight";
import type { StudioView } from "@/components/layout/AppShell";
import { NAV_ITEMS } from "@/components/layout/navLabels";
import { THEME_ICONS, THEME_LABEL_KEYS, nextTheme } from "@/components/layout/themeCycle";
import {
  CommandDialog,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { emitOpenEvent } from "@/lib/deepLink";
import { listenKeys } from "@/lib/shortcuts";


type PaletteItem = {
  /** cmdk 的 value:不可读的稳定 id(`nav-media`、`asset-<id>`…),受控高亮认的是它。 */
  value: string;
  onSelect: () => void;
  disabled?: boolean;
  content: React.ReactNode;
};
type PaletteGroup = { id: string; heading: string; items: PaletteItem[]; separatorAfter?: boolean };

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
  onCreateProject,
  creatingProject,
}: {
  workspace: Workspace;
  projects: ProjectWithStats[];
  onNavigate: (view: StudioView) => void;
  onOpenProject: (projectId: string) => void;
  /** 和顶栏项目切换器同一个动作:直接建一个并打开,不是跳回首页让人再点一次。 */
  onCreateProject: () => void;
  creatingProject?: boolean;
}) {
  const t = useI18n();
  const { theme, setTheme } = usePreferences();
  const isDeploymentAdmin = useIsDeploymentAdmin();
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
    const stopKeys = listenKeys(document, onKeyDown);
    window.addEventListener("mosael:open-cmdk", onOpenEvent);
    return () => {
      stopKeys();
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
    queryKey: assetKeys.list(workspace.id),
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
  // 页面清单读 navLabels 那一份。此前这里抄了一份,漏掉了笔记、3D 场景、画板、管理 —— ⌘K 跳不过去。
  // 管理页和侧栏同一条:只对部署管理员出现(**藏起来的入口不是权限**,后端各自把关)。
  const pages = NAV_ITEMS.filter((item) => item.placement !== "admin" || isDeploymentAdmin);
  const navMatches = q
    ? pages.filter(
        (entry) =>
          t(entry.labelKey).toLowerCase().includes(q) ||
          entry.keywords.some((keyword) => keyword.startsWith(q)),
      )
    : pages;
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

  const upcomingTheme = nextTheme(theme);
  const UpcomingThemeIcon = THEME_ICONS[upcomingTheme];

  // 面板里的每一组结果,**按渲染顺序**。空态、默认高亮、渲染三件事都从这一张表来:此前是三份
  // 手抄 —— 空态判断漏过发布记录(「没有匹配的结果」和结果同时出现),默认高亮漏过工作流和
  // 发布记录(只搜到它们时 Enter 没有目标)。
  const groups: PaletteGroup[] = [
    {
      id: "actions",
      heading: t("cmdkQuickActions"),
      separatorAfter: true,
      items:
        q === ""
          ? [
              {
                value: "action-new-project",
                disabled: creatingProject,
                onSelect: onCreateProject,
                content: (
                  <>
                    <FolderPlus size={14} />
                    {t("createProject")}
                  </>
                ),
              },
              // 和顶栏那个按钮同一个循环(themeCycle):浅 → 深 → 跟随系统。显示的是按下去会到哪一档。
              {
                value: "action-toggle-theme",
                onSelect: () => setTheme(upcomingTheme),
                content: (
                  <>
                    <UpcomingThemeIcon size={14} />
                    {t("cmdkToggleTheme")}
                    <span className="ml-auto text-ui-xs text-muted-foreground">{t(THEME_LABEL_KEYS[upcomingTheme])}</span>
                  </>
                ),
              },
            ]
          : [],
    },
    {
      id: "pages",
      heading: t("cmdkPages"),
      items: navMatches.map((entry) => ({
        value: `nav-${entry.view}`,
        onSelect: () => onNavigate(entry.view),
        content: (
          <>
            <entry.icon size={14} />
            <Highlight text={t(entry.labelKey)} query={query} />
          </>
        ),
      })),
    },
    {
      id: "projects",
      heading: t("cmdkProjects"),
      items: projectMatches.map((project) => ({
        value: `project-${project.id}`,
        onSelect: () => onOpenProject(project.id),
        content: (
          <>
            <Clapperboard size={14} />
            <Highlight className="min-w-0 flex-1 truncate" text={project.name} query={query} />
            <span className="text-ui-xs text-muted-foreground">
              {t("projectStatAssets").replace("{n}", String(project.asset_count))}
            </span>
          </>
        ),
      })),
    },
    {
      id: "workflows",
      heading: t("navWorkflows"),
      items: workflowMatches.map((workflow) => ({
        value: `workflow-${workflow.id}`,
        onSelect: () => {
          onNavigate("workflows");
          emitOpenEvent("mosael:open-workflow", workflow.id);
        },
        content: (
          <>
            <Workflow size={14} />
            <Highlight className="min-w-0 flex-1 truncate" text={workflow.name} query={query} />
            <span className="text-ui-xs tabular-nums text-muted-foreground">
              {t("wfNodeCount").replace("{n}", String(((workflow.graph as { nodes?: unknown[] }).nodes ?? []).length))}
            </span>
          </>
        ),
      })),
    },
    {
      id: "publish",
      heading: t("publishListTitle"),
      items: publishMatches.map((task) => ({
        value: `publish-${task.id}`,
        onSelect: () => {
          onNavigate("publish");
          emitOpenEvent("mosael:open-publish-task", task.id);
        },
        content: (
          <>
            <Rocket size={14} />
            <Highlight className="min-w-0 flex-1 truncate" text={task.title || task.asset_name} query={query} />
            <span className="text-ui-xs text-muted-foreground">{t(`batchStatus_${task.status}` as never)}</span>
          </>
        ),
      })),
    },
    {
      id: "assets",
      heading: t("cmdkAssets"),
      items: assetMatches.map((asset) => ({
        value: `asset-${asset.id}`,
        onSelect: () => {
          onNavigate("media");
          // 素材库监听该事件后打开预览(跨页面深链的最小通道)。
          emitOpenEvent("mosael:open-asset", asset.id);
        },
        content: (
          <>
            {ASSET_ICONS[asset.kind] ?? <FileVideo size={14} />}
            <Highlight className="min-w-0 flex-1 truncate" text={asset.name} query={query} />
            <span className="text-ui-xs uppercase text-muted-foreground">{asset.kind}</span>
          </>
        ),
      })),
    },
  ].filter((group) => group.items.length > 0);

  const searching = assets.isFetching || workflows.isFetching || publishTasks.isFetching || input.trim() !== query;

  // 关掉内建过滤后 cmdk 不再自动高亮第一项(Enter 会没有目标)— 受控高亮:
  // 结果集头名变化(=输入变化)时重置到第一项,方向键仍经 onValueChange 自由移动。
  const firstValue = groups[0]?.items[0]?.value ?? "";
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
        {groups.length === 0 && !searching && (
          <div className="grid justify-items-center gap-1 px-3 pb-[30px] pt-[26px] text-center [&>span:last-child]:max-w-80 [&>span:last-child]:text-ui-xs [&>span:last-child]:leading-normal [&>span:last-child]:text-muted-foreground [&_strong]:text-ui-sm [&_strong]:font-semibold [&_strong]:text-foreground">
            <span className="mb-1 grid h-9 w-9 place-items-center rounded-lg bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary">
              <SearchX size={17} />
            </span>
            <strong>{t("cmdkEmpty")}</strong>
            <span>{t("cmdkEmptyHint")}</span>
          </div>
        )}

        {groups.map((group) => (
          <React.Fragment key={group.id}>
            <CommandGroup heading={group.heading}>
              {group.items.map((item) => (
                <CommandItem key={item.value} value={item.value} disabled={item.disabled} onSelect={() => run(item.onSelect)}>
                  {item.content}
                </CommandItem>
              ))}
            </CommandGroup>
            {group.separatorAfter && <CommandSeparator />}
          </React.Fragment>
        ))}
      </CommandList>
    </CommandDialog>
  );
}
