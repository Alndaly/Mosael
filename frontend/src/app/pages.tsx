import React from "react";

import type { ProjectWithStats, Workspace } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import type { StudioView } from "@/components/layout/navLabels";
import { LoadingState } from "@/components/layout/LoadingState";
import { AdminView } from "@/features/admin/AdminView";
import { AiStudio } from "@/features/ai-studio/AiStudio";
import { BoardsView } from "@/features/boards/BoardsView";
import { BrowserPoolView } from "@/features/browser-pool/BrowserPoolView";
import { EditorView } from "@/features/editor/EditorView";
import { HomeView } from "@/features/home/HomeView";
import { MediaLibraryView } from "@/features/media/MediaLibraryView";
import { NotesView } from "@/features/notes/NotesView";
import { PluginsView } from "@/features/plugins/PluginsView";
import { PublishView } from "@/features/publish/PublishView";
import { SchedulerView } from "@/features/scheduler/SchedulerView";
import { SettingsView } from "@/features/settings/SettingsView";
import { StatisticsView } from "@/features/statistics/StatisticsView";
import { WorkflowsView } from "@/features/workflows/WorkflowsView";

// 3D 工作台带着 three.js,首屏不该为它付代价。
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
      onCreateProject={ctx.createProject}
      creatingProject={ctx.creatingProject}
    />
  ),
  statistics: (ctx) => <StatisticsView workspace={ctx.workspace} projects={ctx.projects} onOpenProject={ctx.openProject} />,
  media: (ctx) => <MediaLibraryView workspace={ctx.workspace} />,
  notes: (ctx) => <NotesView key={ctx.workspace.id} workspace={ctx.workspace} />,
  scenes: (ctx) => (
    <React.Suspense fallback={<LoadingState label={ctx.t("scenesStudioLoading")} />}>
      <SceneStudio key={ctx.workspace.id} workspace={ctx.workspace} />
    </React.Suspense>
  ),
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
