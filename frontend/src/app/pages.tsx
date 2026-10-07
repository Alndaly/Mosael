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
const EntitiesView = React.lazy(() => import("@/features/entities/EntitiesView").then((m) => ({ default: m.EntitiesView })));
const EditorView = React.lazy(() => import("@/features/editor/EditorView").then((m) => ({ default: m.EditorView })));
const MediaLibraryView = React.lazy(() => import("@/features/media/MediaLibraryView").then((m) => ({ default: m.MediaLibraryView })));
//: 笔记页连同它的助手面板:笔记不认识助手(见 NotesView 的 NotesAgentPanelProps),装配放在认识两边的那一侧。
const NotesWithAgent = React.lazy(() => import("@/features/agent/NotesWithAgent").then((m) => ({ default: m.NotesWithAgent })));
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
  statistics: (ctx) => <StatisticsView workspace={ctx.workspace} />,
  media: (ctx) => <MediaLibraryView workspace={ctx.workspace} />,
  entities: (ctx) => <EntitiesView key={ctx.workspace.id} workspace={ctx.workspace} />,
  notes: (ctx) => <NotesWithAgent key={ctx.workspace.id} workspace={ctx.workspace} />,
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
  admin: (ctx) => <AdminView workspace={ctx.workspace} />,
  settings: (ctx) => <SettingsView workspace={ctx.workspace} />,
};
