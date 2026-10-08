import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BookOpen,
  Clapperboard,
  FileAudio,
  FileImage,
  FileVideo,
  FolderPlus,
  LayoutGrid,
  Rocket,
  SearchX,
  Settings,
  ShieldCheck,
  UsersRound,
  Workflow,
} from "lucide-react";

import {
  entityKeys,
  getEntityCatalog,
  listBoards,
  listEntities,
  listNotes,
  listPublishTasks,
  listWorkflows,
  type ProjectWithStats,
  type Workspace,
} from "@/api/client";
import { boardKeys, noteKeys } from "@/api/queryKeys";
import { useIsDeploymentAdmin } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { Highlight } from "@/components/app/Highlight";
import type { StudioView } from "@/components/layout/AppShell";
import { NAV_ITEMS } from "@/components/layout/navLabels";
import { THEME_ICONS, THEME_LABEL_KEYS, nextTheme } from "@/components/layout/themeCycle";
import { Truncate } from "@/components/ui/truncate";
import {
  CommandDialog,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { ADMIN_SETTINGS, SETTINGS_SEARCH, matchSettings } from "@/lib/settingsSearch";
import { useAssetPages } from "@/lib/assetQueries";
import { assetKindKey } from "@/lib/assetKinds";
import { emitOpenEvent, gotoAdmin, gotoSettings, openBoard, openNote, OPEN_ASSET_EVENT } from "@/lib/deepLink";
import { isCommandPaletteKey, listenKeys } from "@/lib/shortcuts";
import { leaveNativeView } from "@/lib/nativeView";


type PaletteItem = {
  /** cmdk 的 value:不可读的稳定 id(`nav-media`、`asset-<id>`…),受控高亮认的是它。 */
  value: string;
  onSelect: () => void;
  /** 选了它人还留在原处(换主题):不收起前台的原生视图。别的都是去别处的。 */
  staysHere?: boolean;
  disabled?: boolean;
  content: React.ReactNode;
};
type PaletteGroup = { id: string; heading: string; items: PaletteItem[]; separatorAfter?: boolean };

/** 素材一组摆几条(和别的几组一样多)。 */
const ASSET_MATCHES = 6;

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
      if (isCommandPaletteKey(event)) {
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

  //: 素材按名字 / 文件名 / 标签在服务端搜,只要前 6 条 —— 不为了面板里这几行把整个素材库拉回来。
  //: 跳过去之后素材页按 id 开详情,不靠这里预热它的列表。
  const assets = useAssetPages(
    { workspace_id: workspace.id, q: query, limit: ASSET_MATCHES },
    { enabled: open && query.length > 0 },
  );

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
  //: 「全局搜索」此前搜不到资产(人物 / 场景 / 道具)、笔记、画板和设置项 —— 记得名字的人得出「没有」,
  //: 其实就在那(体检 UM-14)。资产、笔记在服务端按关键字搜;画板列表本来就小,和工作流一样取回来在这儿筛。
  const entities = useQuery({
    queryKey: entityKeys.list(workspace.id, { q: query }),
    queryFn: () => listEntities(workspace.id, { q: query }),
    enabled: open && query.length > 0,
    staleTime: 30_000,
  });
  const notes = useQuery({
    queryKey: noteKeys.search(workspace.id, query),
    queryFn: () => listNotes(workspace.id, query),
    enabled: open && query.length > 0,
    staleTime: 30_000,
  });
  const boards = useQuery({
    queryKey: boardKeys.list(workspace.id),
    queryFn: () => listBoards(workspace.id),
    enabled: open && query.length > 0,
    staleTime: 30_000,
  });
  //: 种类名(人物 / 场景 / 道具)从后端的词表来,和资产页同一份(同一个 query key,打开过资产页就不再取)。
  const entityCatalog = useQuery({
    queryKey: entityKeys.catalog(),
    queryFn: getEntityCatalog,
    staleTime: Infinity,
    enabled: open && query.length > 0,
  });
  const entityKindLabel = (kind: string) => entityCatalog.data?.kinds.find((one) => one.kind === kind)?.label ?? "";

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
  const assetMatches = q ? assets.items.slice(0, ASSET_MATCHES) : [];

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

  const entityMatches = q ? (entities.data ?? []).slice(0, 6) : [];
  const noteMatches = q ? (notes.data ?? []).slice(0, 6) : [];
  const boardMatches = q ? (boards.data ?? []).filter((board) => board.name.toLowerCase().includes(q)).slice(0, 6) : [];
  //: 设置项和设置页左边那个搜索框是同一份(settingsSearch):分区里的行、只在管理页的设置都搜得到。
  //: 管理页的那些,部署管理员点了直达那个 tab;别人看得到它在哪、由谁改,但点不了。
  const settingsMatches = q ? matchSettings(SETTINGS_SEARCH, query, t).slice(0, 6) : [];
  const adminSettingMatches = q ? matchSettings(ADMIN_SETTINGS, query, t).slice(0, 4) : [];

  //: 去别处的那几项:内嵌浏览器、工作台在前台时先把它收起来再走(ADR 0051)—— 不然面板一关,网页又盖回来,
  //: 跳过去的那一页在它底下,看着像什么都没发生。先收再关面板:面板关掉时视图回到原处那一步就落了空,不闪。
  const run = (item: PaletteItem) => {
    if (!item.staysHere) void leaveNativeView();
    setOpen(false);
    item.onSelect();
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
                staysHere: true,
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
      id: "entities",
      heading: t("navEntities"),
      items: entityMatches.map((entity) => ({
        value: `entity-${entity.id}`,
        onSelect: () => {
          onNavigate("entities");
          emitOpenEvent("mosael:open-entity", entity.id);
        },
        content: (
          <>
            <UsersRound size={14} />
            <Highlight className="min-w-0 flex-1 truncate" text={entity.name} query={query} />
            <span className="text-ui-xs text-muted-foreground">{entityKindLabel(entity.kind)}</span>
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
      id: "notes",
      heading: t("navNotes"),
      items: noteMatches.map((note) => ({
        value: `note-${note.id}`,
        onSelect: () => openNote(note.id),
        content: (
          <>
            <BookOpen size={14} />
            <Highlight className="min-w-0 flex-1 truncate" text={note.title || t("cmdkUntitledNote")} query={query} />
          </>
        ),
      })),
    },
    {
      id: "boards",
      heading: t("navBoards"),
      items: boardMatches.map((board) => ({
        value: `board-${board.id}`,
        onSelect: () => openBoard(board.id),
        content: (
          <>
            <LayoutGrid size={14} />
            <Highlight className="min-w-0 flex-1 truncate" text={board.name} query={query} />
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
          emitOpenEvent(OPEN_ASSET_EVENT, asset.id);
        },
        content: (
          <>
            {ASSET_ICONS[asset.kind] ?? <FileVideo size={14} />}
            <Highlight className="min-w-0 flex-1 truncate" text={asset.name} query={query} />
            <span className="text-ui-xs text-muted-foreground">{t(assetKindKey(asset.kind))}</span>
          </>
        ),
      })),
    },
    {
      id: "settings",
      heading: t("navSettings"),
      items: [
        ...settingsMatches.map(({ entry, hit }) => ({
          value: `settings-${entry.id}`,
          onSelect: () => gotoSettings(entry.id),
          content: (
            <>
              <Settings size={14} />
              <Truncate className="min-w-0 flex-1">
                {t(entry.label)}
                {hit && <span className="text-muted-foreground"> · {t(hit)}</span>}
              </Truncate>
            </>
          ),
        })),
        ...adminSettingMatches.map(({ entry }) => ({
          value: `admin-setting-${entry.id}`,
          disabled: !isDeploymentAdmin,
          onSelect: () => gotoAdmin(entry.tab),
          content: (
            <>
              <ShieldCheck size={14} />
              <Truncate className="min-w-0 flex-1">{t(entry.label)}</Truncate>
              <span className="text-ui-xs text-muted-foreground">{isDeploymentAdmin ? t("navAdmin") : t("cmdkAdminOnly")}</span>
            </>
          ),
        })),
      ],
    },
  ].filter((group) => group.items.length > 0);

  const searching =
    assets.isFetching || workflows.isFetching || publishTasks.isFetching || entities.isFetching || notes.isFetching
    || boards.isFetching || input.trim() !== query;

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
                <CommandItem key={item.value} value={item.value} disabled={item.disabled} onSelect={() => run(item)}>
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
