/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 剪辑页空态必须给出口。
 *
 * 真实回归:一个项目都没有时,剪辑页只渲染一句「没有项目」,**连个可点的东西都没有** ——
 * 而顶栏的项目切换器在零项目时压根不挂(AppShell 里 `projects.length > 0` 才渲染),
 * 于是用户站在剪辑页无路可走,只能自己猜要回首页。
 *
 * 这条在 jsdom 下是确定可测的:不依赖动画、不依赖网络,project=null 时的分支是纯渲染。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (k: string) => k, usePreferences: () => ({ locale: "zh-CN" }) }));

import { EditorView } from "@/features/editor/EditorView";

const workspace = { id: "w1", name: "W" } as never;

describe("剪辑页空态", () => {
  it("没有项目时给出新建入口,点击触发回调", async () => {
    const onCreateProject = vi.fn();
    const user = userEvent.setup();
    render(
      <EditorView workspace={workspace} project={null} onCreateProject={onCreateProject} creatingProject={false} />,
    );

    const button = screen.getByRole("button", { name: /createProject/ });
    await user.click(button);
    expect(onCreateProject).toHaveBeenCalledTimes(1);
  });

  it("正在新建时按钮禁用,避免连点建出多个项目", () => {
    render(
      <EditorView workspace={workspace} project={null} onCreateProject={vi.fn()} creatingProject={true} />,
    );
    expect(screen.getByRole("button", { name: /createProject/ })).toBeDisabled();
  });
});
