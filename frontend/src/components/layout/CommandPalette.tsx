import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BookOpen,
  Bot,
  CalendarClock,
  Clapperboard,
  FileAudio,
  FileImage,
  FileText,
  FileVideo,
  FolderOpen,
  FolderPlus,
  Home,
  Layers,
  Moon,
  Plug,
  Rocket,
  Scissors,
  SearchX,
  Settings,
  Sun,
  Workflow,
} from "lucide-react";

import { api, type Asset, type ProjectWithStats, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n, usePreferences } from "@/app/preferences";
import type { StudioView } from "@/components/layout/AppShell";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";

type KbSearchResult = components["schemas"]["KbSearchResultOut"];

/** 页面导航项:label 走 i18n,keywords 供英文/拼音前缀匹配。 */
const NAV_ENTRIES: Array<{ view: StudioView; labelKey: string; keywords: string[]; icon: React.ReactNode }> = [
  { view: "home", labelKey: "navHome", keywords: ["home", "shouye"], icon: <Home size={14} /> },
  { view: "media", labelKey: "navMedia", keywords: ["media", "assets", "sucai"], icon: <FolderOpen size={14} /> },
  { view: "editor", labelKey: "navEditor", keywords: ["editor", "cut", "jianji"], icon: <Scissors size={14} /> },
  { view: "ai", labelKey: "navAi", keywords: ["ai", "chat", "agent"], icon: <Bot size={14} /> },
  { view: "batch", labelKey: "navBatch", keywords: ["batch", "piliang"], icon: <Layers size={14} /> },
  { view: "publish", labelKey: "navPublish", keywords: ["publish", "fabu"], icon: <Rocket size={14} /> },
  { view: "kb", labelKey: "navKb", keywords: ["kb", "knowledge", "zhishiku"], icon: <BookOpen size={14} /> },
  { view: "workflows", labelKey: "navWorkflows", keywords: ["workflow", "flow", "gongzuoliu"], icon: <Workflow size={14} /> },
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
    window.addEventListener("mibu:open-cmdk", onOpenEvent);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("mibu:open-cmdk", onOpenEvent);
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
  const kbResults = useQuery({
    queryKey: ["cmdk-kb", workspace.id, query],
    queryFn: () =>
      api<KbSearchResult[]>(`/api/kb/search?workspace_id=${workspace.id}&q=${encodeURIComponent(query)}&limit=6`),
    enabled: open && query.length > 1,
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
  const kbMatches = kbResults.data ?? [];
  // 同一文档命中多个 chunk 时只展示得分最高的一条
  const kbUnique = kbMatches.filter(
    (item, index) => kbMatches.findIndex((other) => other.document_id === item.document_id) === index,
  );

  const run = (action: () => void) => {
    setOpen(false);
    action();
  };

  const hasAnyResult = navMatches.length > 0 || projectMatches.length > 0 || assetMatches.length > 0 || kbUnique.length > 0;

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput
        value={input}
        onValueChange={setInput}
        placeholder={t("cmdkPlaceholder")}
        autoFocus
      />
      <CommandList>
        {!hasAnyResult && (
          <CommandEmpty>
            <span className="grid justify-items-center gap-1 px-3 pb-[30px] pt-[26px] text-center [&>span:last-child]:max-w-80 [&>span:last-child]:text-[11.5px] [&>span:last-child]:leading-normal [&>span:last-child]:text-muted-foreground [&_strong]:text-[12.5px] [&_strong]:font-semibold [&_strong]:text-foreground">
              <span className="mb-1 grid h-9 w-9 place-items-center rounded-lg bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary">
                <SearchX size={17} />
              </span>
              <strong>{t("cmdkEmpty")}</strong>
              <span>{t("cmdkEmptyHint")}</span>
            </span>
          </CommandEmpty>
        )}

        {q === "" && (
          <>
            <CommandGroup heading={t("cmdkQuickActions")}>
              <CommandItem value="action-new-project" onSelect={() => run(() => onNavigate("home"))}>
                <FolderPlus size={14} />
                {t("createProject")}
              </CommandItem>
              <CommandItem value="action-new-note" onSelect={() => run(() => onNavigate("kb"))}>
                <FileText size={14} />
                {t("kbNewNote")}
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
                {t(entry.labelKey as never)}
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
                <span className="min-w-0 flex-1 truncate">{project.name}</span>
                <span className="text-[11px] text-muted-foreground">
                  {t("projectStatAssets").replace("{n}", String(project.asset_count))}
                </span>
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
                    window.setTimeout(
                      () => window.dispatchEvent(new CustomEvent("mibu:open-asset", { detail: asset.id })),
                      80,
                    );
                  })
                }
              >
                {ASSET_ICONS[asset.kind] ?? <FileVideo size={14} />}
                <span className="min-w-0 flex-1 truncate">{asset.name}</span>
                <span className="text-[11px] uppercase text-muted-foreground">{asset.kind}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {kbUnique.length > 0 && (
          <CommandGroup heading={t("cmdkKb")}>
            {kbUnique.map((result) => (
              <CommandItem
                key={result.document_id}
                value={`kb-${result.document_id}`}
                onSelect={() =>
                  run(() => {
                    onNavigate("kb");
                    window.setTimeout(
                      () => window.dispatchEvent(new CustomEvent("mibu:open-kb-doc", { detail: result.document_id })),
                      80,
                    );
                  })
                }
              >
                <BookOpen size={14} />
                <span className="min-w-0 flex-1 truncate">{result.title}</span>
                <span className="max-w-[180px] truncate text-[11px] text-muted-foreground">{result.snippet}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
      </CommandList>
    </CommandDialog>
  );
}
