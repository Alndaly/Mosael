/** @vitest-environment jsdom */
/**
 * 3D 场景里按 ⌘S:欠着的这一份马上存,不等自动保存那 600ms;网页版也不弹浏览器的「存储网页」
 * (见 lib/saveShortcut)。视口换成空壳,要测的是存盘,不是 WebGL。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { messages, type MessageKey } from "@/app/messages";
import type { Scene } from "@/api/domains/scenes";
import { saveScene } from "@/api/domains/scenes";
import { installSaveShortcut } from "@/lib/saveShortcut";

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
import { initialScene, makeObject } from "./sceneGraph";

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
let uninstall: () => void = () => undefined;
beforeEach(() => {
  uninstall = installSaveShortcut(window);
});
afterEach(() => {
  uninstall();
  cleanup();
  location.hash = "";
  vi.mocked(saveScene).mockClear();
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

it("藏起一个物体就按 ⌘S:马上存(不等自动保存),键被拦下", async () => {
  await open();
  fireEvent.click(screen.getByRole("button", { name: "隐藏 石像" }));
  expect(row("石像")).toHaveAttribute("data-hidden", "self");
  const event = new KeyboardEvent("keydown", { key: "s", code: "KeyS", metaKey: true, bubbles: true, cancelable: true });
  act(() => void document.body.dispatchEvent(event));
  expect(event.defaultPrevented).toBe(true);
  await waitFor(() => expect(saveScene).toHaveBeenCalledTimes(1), { timeout: 300 });
  const saved = vi.mocked(saveScene).mock.calls[0][0] as Scene;
  expect(saved.content.objects.find((one) => one.name === "石像")?.hidden).toBe(true);
});
