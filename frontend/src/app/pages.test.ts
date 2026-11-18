import type { ReactElement } from "react";
import { expect, it, vi } from "vitest";

import type { ProjectWithStats, Workspace } from "@/api/client";
import { PAGE_RENDERERS, type PageContext } from "@/app/pages";
import { HomeView } from "@/features/home/HomeView";

/**
 * 项目浏览页和剪辑是两张不同的页面:前者是独立的空态 surface,后者只在有项目时挂编辑器。
 * 这条钉的是装配,不是编辑器内部 —— 它保证「从列表里选项目」确实会换成另一个页面。
 */
it("项目浏览页是 HomeView;剪辑页有项目时不是", () => {
  const base: PageContext = {
    workspace: { id: "w", name: "W", role: "editor" } as Workspace,
    project: null,
    projects: [],
    projectsLoad: { pending: false, error: null, retrying: false, retry: vi.fn() },
    openProject: vi.fn(),
    createProject: vi.fn(),
    creatingProject: false,
    t: (key) => key,
  };

  const browser = PAGE_RENDERERS.projects(base) as ReactElement;
  expect(browser.type).toBe(HomeView);

  const editor = PAGE_RENDERERS.editor({
    ...base,
    project: { id: "p", workspace_id: "w", name: "P" } as ProjectWithStats,
  }) as ReactElement;
  expect(editor.type).not.toBe(HomeView);
});
