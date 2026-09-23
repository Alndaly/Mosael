import React from "react";

import type { ProjectWithStats, Workspace } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import type { StudioView } from "@/components/layout/navLabels";
import { HomeView } from "@/features/home/HomeView";

/**
 * **页面按需加载。** 打开一次素材库,不该先解析工作流的图编辑器、笔记的富文本内核和 3D 的
 * three.js —— 它们此前全在同一个 4.2 MB 的主包里,每次启动都要解析一遍。
 *
 * 只有首屏那一页(home)是直接 import 的:它一定会被渲染,给它加一层 Suspense 只会多一次闪烁。
 */
const AdminView = React.lazy(() => import("@/features/admin/AdminView").then((m) => ({ default: m.AdminView })));
const AiStudio = React.lazy(() => import("@/features/ai-studio/AiStudio").then((m) => ({ default: m.AiStudio })));
const BoardsView = React.lazy(() => import("@/features/boards/BoardsView").then((m) => ({ default: m.BoardsView })));
const BrowserPoolView = React.lazy(() => import("@/features/browser-pool/BrowserPoolView").then((m) => ({ default: m.BrowserPoolView })));
const EditorView = React.lazy(() => import("@/features/editor/EditorView").then((m) => ({ default: m.EditorView })));
const MediaLibraryView = React.lazy(() => import("@/features/media/MediaLibraryView").then((m) => ({ default: m.MediaLibraryView })));
const NotesView = React.lazy(() => import("@/features/notes/NotesView").then((m) => ({ default: m.NotesView })));
const PluginsView = React.lazy(() => import("@/features/plugins/PluginsView").then((m) => ({ default: m.PluginsView })));
const PublishView = React.lazy(() => import("@/features/publish/PublishView").then((m) => ({ default: m.PublishView })));
const SchedulerView = React.lazy(() => import("@/features/scheduler/SchedulerView").then((m) => ({ default: m.SchedulerView })));
const SettingsView = React.lazy(() => import("@/features/settings/SettingsView").then((m) => ({ default: m.SettingsView })));
const StatisticsView = React.lazy(() => import("@/features/statistics/StatisticsView").then((m) => ({ default: m.StatisticsView })));
const WorkflowsView = React.lazy(() => import("@/features/workflows/WorkflowsView").then((m) => ({ default: m.WorkflowsView })));
const SceneStudio = React.lazy(() => import("@/features/scenes/SceneStudio").then((m) => ({ default: m.SceneStudio })));

/** 每个页面渲染时能拿到的东西。页面自己挑要用的那几样。 */
export type PageContext = {
  workspace: Workspace;
  project: ProjectWithStats | null;
  projects: ProjectWithStats[];
  openProject: (projectId: string) => void;
  createProject: () => void;
  creatingProject: boolean;
  t: (key: MessageKey) => string;
};

/**
 * 页面 id → 渲染什么。**类型是 `Record<StudioView, …>`**:在 navLabels 里声明了一个页面,
 * 这里没写它,编译就过不去 —— 而不是像此前那串 `view === "…" &&` 一样,漏了就静默地显示空白。
 *
 * 页面叫什么、在侧栏哪一组、用什么图标,在 components/layout/navLabels.ts;这里只管渲染,
 * 所以只有这一层 import 各个功能模块。
 */
export const PAGE_RENDERERS: Record<StudioView, (ctx: PageContext) => React.ReactNode> = {
  home: (ctx) => (
    <HomeView
      workspace={ctx.workspace}
      projects={ctx.projects}
      onOpenProject={ctx.openProject}
    />
  ),
  statistics: (ctx) => <StatisticsView workspace={ctx.workspace} projects={ctx.projects} onOpenProject={ctx.openProject} />,
  media: (ctx) => <MediaLibraryView workspace={ctx.workspace} />,
  notes: (ctx) => <NotesView key={ctx.workspace.id} workspace={ctx.workspace} />,
  scenes: (ctx) => <SceneStudio key={ctx.workspace.id} workspace={ctx.workspace} />,
  boards: (ctx) => <BoardsView workspace={ctx.workspace} />,
  editor: (ctx) => (
    <EditorView
      workspace={ctx.workspace}
      project={ctx.project}
      onCreateProject={ctx.createProject}
      creatingProject={ctx.creatingProject}
    />
  ),
  ai: (ctx) => <AiStudio workspace={ctx.workspace} />,
  publish: (ctx) => <PublishView workspace={ctx.workspace} />,
  workflows: (ctx) => <WorkflowsView workspace={ctx.workspace} />,
  "browser-pool": (ctx) => <BrowserPoolView workspace={ctx.workspace} />,
  scheduler: (ctx) => <SchedulerView workspace={ctx.workspace} project={ctx.project} />,
  plugins: (ctx) => <PluginsView workspaceId={ctx.workspace.id} />,
  admin: () => <AdminView />,
  settings: (ctx) => <SettingsView workspace={ctx.workspace} />,
};
