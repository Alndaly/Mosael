/** @vitest-environment jsdom */
/**
 * 「场景中的物体」每一行除了删除,还能藏 / 显示。
 *
 * 钉三件事:点眼睛改的是**场景数据**(淡显跟着变)、它和别的编辑走同一条 `update`
 * 所以 ⌘Z 撤得回来、藏一个组时组里的行也淡下去但**孩子自己的标记不动**。
 * 视口在这里换成一个空壳 —— 要测的是列表和数据,不是 WebGL。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { messages, type MessageKey } from "@/app/messages";
import type { Scene } from "@/api/domains/scenes";

const zh = (key: MessageKey) => messages["zh-CN"][key];

vi.mock("@/app/preferences", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  usePreferences: () => ({ locale: "zh-CN", t: zh }),
  useI18n: () => zh,
}));
vi.mock("./SceneViewport", async () => {
  const React = await import("react");
  return { SceneViewport: React.forwardRef(() => <div data-testid="viewport" />) };
});
vi.mock("./SceneBlender", () => ({ SceneBlender: () => null }));
vi.mock("./SceneBlenderPull", () => ({ SceneBlenderPull: () => null }));

let scene: Scene;
vi.mock("@/api/domains/scenes", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getScene: vi.fn(async () => scene),
  listScenes: vi.fn(async () => []),
  listSceneModels: vi.fn(async () => []),
  saveScene: vi.fn(async (next: Scene) => ({ ...next, revision: next.revision + 1 })),
}));

import { SceneStudio } from "./SceneStudio";
import { initialScene, makeObject, makeShot } from "./sceneGraph";

/** 物体列表里的那一行。同名的字还出现在时间轴的行上,所以只在列表(role=tree)里找。 */
const tree = () => within(screen.getByRole("tree"));
const row = (name: string) => tree().getByText(name).closest(".scene-object-row")!;

beforeEach(() => {
  localStorage.clear();
  const content = initialScene(zh);
  const group = makeObject("group", { name: "后排" });
  const prop = makeObject("box", { name: "石像", parent_id: group.id });
  content.objects.push(group, prop);
  scene = {
    id: "s1",
    workspace_id: "w1",
    name: "展厅",
    revision: 1,
    content,
  } as Scene;
  location.hash = "#/scenes?scene=s1";
});
afterEach(() => {
  cleanup();
  location.hash = "";
});

async function open() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SceneStudio workspace={{ id: "w1" } as never} />
    </QueryClientProvider>,
  );
  await screen.findByRole("tree");
}

it("点眼睛藏起来,行淡显;⌘Z 撤回", async () => {
  await open();
  const statue = row("石像");
  expect(statue).not.toHaveAttribute("data-hidden");
  fireEvent.click(screen.getByRole("button", { name: "隐藏 石像" }));
  expect(row("石像")).toHaveAttribute("data-hidden", "self");
  expect(screen.getByRole("button", { name: "显示 石像" })).toBeInTheDocument();

  act(() => {
    fireEvent.keyDown(document.body, { key: "z", code: "KeyZ", metaKey: true });
  });
  expect(row("石像")).not.toHaveAttribute("data-hidden");
});

it("藏一个组:组里的行也淡下去,但孩子自己的眼睛仍是睁着的", async () => {
  await open();
  fireEvent.click(screen.getByRole("button", { name: "隐藏 后排" }));
  expect(row("后排")).toHaveAttribute("data-hidden", "self");
  expect(row("石像")).toHaveAttribute("data-hidden", "inherited");
  // 孩子那一位没被改:它的按钮仍是「隐藏」,不是「显示」。
  expect(screen.getByRole("button", { name: "隐藏 石像" })).toBeInTheDocument();
});

it("H 切换选中物体,⌥H 全部显示", async () => {
  await open();
  fireEvent.click(tree().getByText("石像"));
  act(() => {
    fireEvent.keyDown(document.body, { key: "h", code: "KeyH" });
  });
  expect(row("石像")).toHaveAttribute("data-hidden", "self");
  fireEvent.click(screen.getByRole("button", { name: "隐藏 后排" }));
  act(() => {
    fireEvent.keyDown(document.body, { key: "˙", code: "KeyH", altKey: true });
  });
  expect(row("石像")).not.toHaveAttribute("data-hidden");
  expect(row("后排")).not.toHaveAttribute("data-hidden");
});

it("只属于别的镜头的人偶:当前镜头里淡下去,行尾写只在哪一镜(ADR 0102)", async () => {
  const two = makeShot("镜头 2");
  scene.content.objects.push(two.camera, makeObject("figure", { name: "小满", shot_ids: [two.shot.id] }));
  scene.content.shots.push(two.shot);
  await open();
  //: 打开时停在第一个镜头:小满只属于镜头 2,淡下去,但不是「藏起来」(眼睛仍睁着)
  expect(row("小满")).toHaveAttribute("data-hidden", "off-shot");
  expect(screen.getByRole("button", { name: "隐藏 小满" })).toBeInTheDocument();
  expect(row("小满").querySelector("[data-only-in]")?.textContent).toBe("只在镜头 2");
  //: 共用的布景每个镜头都在,不标
  expect(row("石像")).not.toHaveAttribute("data-hidden");
  expect(row("石像").querySelector("[data-only-in]")).toBeNull();
});

it("在列表里选中只属于别的镜头的人偶:切到它那一镜", async () => {
  const two = makeShot("镜头 2");
  scene.content.objects.push(two.camera, makeObject("figure", { name: "小满", shot_ids: [two.shot.id] }));
  scene.content.shots.push(two.shot);
  await open();
  fireEvent.click(tree().getByText("小满"));
  expect(row("小满")).not.toHaveAttribute("data-hidden");
  expect(row("石像")).not.toHaveAttribute("data-hidden");
});
