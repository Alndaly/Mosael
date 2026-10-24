import type { ReactElement } from "react";
import { expect, it, vi } from "vitest";

import type { ProjectWithStats, Workspace } from "@/api/client";
import { PAGE_RENDERERS, type PageContext } from "@/app/pages";
import { HomeView } from "@/features/home/HomeView";

/**
 * 一个 tab 两个状态:没有项目 = 项目浏览器;有项目 = 编辑器。
 * 这条钉的是装配,不是编辑器内部 —— 它保证「从列表里选项目」确实会换成另一个页面。
 */
it("剪辑页:没有项目时是项目浏览器,选中项目后不是", () => {
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

  const browser = PAGE_RENDERERS.editor(base) as ReactElement;
  expect(browser.type).toBe(HomeView);

  const editor = PAGE_RENDERERS.editor({
    ...base,
    project: { id: "p", workspace_id: "w", name: "P" } as ProjectWithStats,
  }) as ReactElement;
  expect(editor.type).not.toBe(HomeView);
});
