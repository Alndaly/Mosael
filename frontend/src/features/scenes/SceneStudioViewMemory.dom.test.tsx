/** @vitest-environment jsdom */
/**
 * 编辑器这一层:视角档和当前镜头按场景记住,**不进场景数据**。
 *
 * 视口换成空壳(WebGL 跑不起来);相机那一段见 sceneViewMemory.dom.test.ts。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
  return {
    SceneViewport: React.forwardRef((props: { shot: { id: string } }) => (
      <div data-testid="viewport" data-shot={props.shot.id} />
    )),
  };
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

import { saveScene } from "@/api/domains/scenes";
import { SceneStudio } from "./SceneStudio";
import { initialScene, makeShot } from "./sceneGraph";
import { readSceneView, writeSceneView } from "./sceneViewMemory";

beforeEach(() => {
  localStorage.clear();
  vi.mocked(saveScene).mockClear();
  const content = initialScene(zh);
  const second = makeShot("镜头 2");
  second.shot.id = "shot-2";
  content.objects.push(second.camera);
  content.shots.push(second.shot);
  scene = { id: "s1", workspace_id: "w1", name: "展厅", revision: 1, content } as Scene;
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
  await screen.findByTestId("viewport");
}
const pressed = (label: string) => screen.getByRole("button", { name: label }).getAttribute("aria-pressed");

it("第一次进来是自由视角、第一个镜头", async () => {
  await open();
  expect(pressed(zh("sceneViewFree"))).toBe("true");
  expect(screen.getByTestId("viewport").dataset.shot).toBe(scene.content.shots[0].id);
});

it("回到场景时还是上次的视角档和镜头", async () => {
  writeSceneView("w1", "s1", { mode: "observe", shotId: "shot-2" });
  await open();
  expect(pressed(zh("sceneViewOverview"))).toBe("true");
  expect(screen.getByTestId("viewport").dataset.shot).toBe("shot-2");
});

it("切视角档会被记住,但不动场景 —— 不存盘、不涨版本", async () => {
  await open();
  fireEvent.click(screen.getByRole("button", { name: zh("sceneViewCamera") }));
  expect(readSceneView("w1", "s1").mode).toBe("camera");
  expect(saveScene).not.toHaveBeenCalled();
  expect(localStorage.getItem("mosael.scene-draft:w1:s1")).toBeNull();
});

it("存着的镜头已经被删了、视角档是坏的 → 回到默认", async () => {
  localStorage.setItem("mosael:scene-view:w1:s1", JSON.stringify({ mode: "nope", shotId: "gone" }));
  await open();
  expect(pressed(zh("sceneViewFree"))).toBe("true");
  expect(screen.getByTestId("viewport").dataset.shot).toBe(scene.content.shots[0].id);
});

it("别的场景的记忆不串过来", async () => {
  writeSceneView("w1", "other", { mode: "observe", shotId: "shot-2" });
  await open();
  expect(pressed(zh("sceneViewFree"))).toBe("true");
});
