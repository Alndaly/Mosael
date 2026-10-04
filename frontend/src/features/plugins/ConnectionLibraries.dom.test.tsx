/** @vitest-environment jsdom */

/**
 * 一个连接的「模型库」「工作流库」:两颗按钮、两个窗口,两个库能互相跳。
 *
 * - 另一个库没开:叠在上面开,停到那一项;关掉它回到原来那一项;
 * - 另一个库已经开着(在下面):把上面这个关掉,让下面那个停到那一项 —— 不会越叠越多;
 * - 只认领了一个库的连接只有一颗按钮,也不给跳去另一个库的入口;
 * - 读不出来时「去检查连接设置」:关掉窗口再交给插件页。
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

type Stub = {
  focus?: { at: number } & Record<string, unknown>;
  onOpenChange: (open: boolean) => void;
  onCheckSettings?: () => void;
};

/** 两个窗口换成桩:摆出停在哪一项,露出跳去另一个库的那一下。 */
vi.mock("./ModelLibrary", () => ({
  ModelLibraryDialog: (props: Stub & { onShowWorkflow?: (path: string) => void }) => (
    <section role="dialog" aria-label="model-library" data-focus={JSON.stringify(props.focus ?? null)}>
      {props.onShowWorkflow && <button onClick={() => props.onShowWorkflow!("人像/古风.json")}>show-workflow</button>}
      <button onClick={() => props.onCheckSettings?.()}>check-settings</button>
      <button onClick={() => props.onOpenChange(false)}>close-model</button>
    </section>
  ),
}));
vi.mock("./WorkflowLibrary", () => ({
  WorkflowLibraryDialog: (props: Stub & { onShowModel?: (focus: Record<string, unknown>) => void }) => (
    <section role="dialog" aria-label="workflow-library" data-focus={JSON.stringify(props.focus ?? null)}>
      {props.onShowModel && (
        <button onClick={() => props.onShowModel!({ model: { folder: "loras", name: "a.safetensors" } })}>show-model</button>
      )}
      <button onClick={() => props.onOpenChange(false)}>close-workflow</button>
    </section>
  ),
}));

import type { PluginInstance } from "@/api/client";
import { ConnectionLibraries } from "./ConnectionLibraries";

const instance = { id: "i1", name: "ComfyUI", blocked_reason: "" } as PluginInstance;

/** 窗口从下到上的次序(后挂上的在上面)。 */
const layers = () => screen.queryAllByRole("dialog").map((one) => one.getAttribute("aria-label"));
const focusOf = (name: string) => JSON.parse(screen.getByRole("dialog", { name }).getAttribute("data-focus") ?? "null");

describe("一个连接的两个库", () => {
  it("工作流库里点用到的模型:模型库叠在上面开、停到那一项;关掉回到工作流库", () => {
    render(<ConnectionLibraries instance={instance} workspaceId="w1" models workflows />);
    fireEvent.click(screen.getByRole("button", { name: "workflowLibraryOpen" }));
    expect(layers()).toEqual(["workflow-library"]);
    fireEvent.click(screen.getByRole("button", { name: "show-model" }));
    expect(layers()).toEqual(["workflow-library", "model-library"]);
    expect(focusOf("model-library")).toMatchObject({ model: { folder: "loras", name: "a.safetensors" } });
    fireEvent.click(screen.getByRole("button", { name: "close-model" }));
    expect(layers()).toEqual(["workflow-library"]);
  });

  it("另一个库已经开着(在下面):关掉上面这个,下面那个停到那一项", () => {
    render(<ConnectionLibraries instance={instance} workspaceId="w1" models workflows />);
    fireEvent.click(screen.getByRole("button", { name: "modelLibraryOpen" }));
    fireEvent.click(screen.getByRole("button", { name: "show-workflow" }));
    expect(layers()).toEqual(["model-library", "workflow-library"]);
    expect(focusOf("workflow-library")).toMatchObject({ path: "人像/古风.json" });
    fireEvent.click(screen.getByRole("button", { name: "show-model" }));
    expect(layers(), "不越叠越多").toEqual(["model-library"]);
    expect(focusOf("model-library")).toMatchObject({ model: { folder: "loras", name: "a.safetensors" } });
  });

  it("只认领了一个库:只有一颗按钮,也不给跳去另一个库", () => {
    render(<ConnectionLibraries instance={instance} workspaceId="w1" workflows />);
    expect(screen.queryByRole("button", { name: "modelLibraryOpen" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "workflowLibraryOpen" }));
    expect(screen.queryByRole("button", { name: "show-model" })).toBeNull();
  });

  it("连接停用着:按钮点不了", () => {
    render(<ConnectionLibraries instance={{ ...instance, blocked_reason: "没授权" }} workspaceId="w1" models workflows />);
    expect((screen.getByRole("button", { name: "modelLibraryOpen" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "workflowLibraryOpen" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("去检查连接设置:窗口全关掉,再交给插件页", () => {
    const check = vi.fn();
    render(<ConnectionLibraries instance={instance} workspaceId="w1" models workflows onCheckSettings={check} />);
    fireEvent.click(screen.getByRole("button", { name: "workflowLibraryOpen" }));
    fireEvent.click(screen.getByRole("button", { name: "show-model" }));
    fireEvent.click(screen.getByRole("button", { name: "check-settings" }));
    expect(layers()).toEqual([]);
    expect(check).toHaveBeenCalledOnce();
  });
});
