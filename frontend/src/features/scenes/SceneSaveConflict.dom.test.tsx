/** @vitest-environment jsdom */
/**
 * 保存撞了 409(别处先存了一版):整份换成服务端那份、清掉撤销历史、告诉用户,之后基于新底子照常保存。
 *
 * 此前只记一句错误,之后每次自动保存都带着同一个旧修订号再撞一次 —— 这个场景从此再也存不上。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
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
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));

let served: Scene;
vi.mock("@/api/domains/scenes", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getScene: vi.fn(async () => served),
  listScenes: vi.fn(async () => []),
  listSceneModels: vi.fn(async () => []),
  saveScene: vi.fn(),
}));

import { toast } from "sonner";
import { saveScene } from "@/api/domains/scenes";
import { SceneStudio } from "./SceneStudio";
import { initialScene, makeObject } from "./sceneGraph";

const tree = () => within(screen.getByRole("tree"));

function sceneWith(name: string, revision: number): Scene {
  const content = initialScene(zh);
  content.objects.push(makeObject("box", { name }));
  return { id: "s1", workspace_id: "w1", name: "展厅", revision, content } as Scene;
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(toast.error).mockClear();
  served = sceneWith("石像", 1);
  //: 第一次保存撞上别处存的第 4 版;之后照常存。
  vi.mocked(saveScene).mockReset();
  vi.mocked(saveScene)
    .mockImplementationOnce(async () => {
      served = sceneWith("雕塑", 4);
      throw new ApiError("conflict", 409, "");
    })
    .mockImplementation(async (next: Scene) => ({ ...next, revision: next.revision + 1 }));
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

it("撞了 409:换成服务端那份并告知,撤销不会把旧内容写回去,下一次保存带新修订号", async () => {
  await open();
  fireEvent.click(screen.getByRole("button", { name: "隐藏 石像" }));

  await waitFor(() => expect(tree().getByText("雕塑")).toBeTruthy(), { timeout: 3000 });
  expect(tree().queryByText("石像")).toBeNull();
  expect(toast.error).toHaveBeenCalledWith(zh("sceneSaveConflict"), { description: zh("sceneSaveConflictDetail") });
  //: 撤销历史记的是被换掉的那份 —— 清掉了,按 ⌘Z 什么都不变。
  act(() => {
    fireEvent.keyDown(document.body, { key: "z", code: "KeyZ", metaKey: true });
  });
  expect(tree().getByText("雕塑")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "隐藏 雕塑" }));
  await waitFor(() => expect(saveScene).toHaveBeenCalledTimes(2), { timeout: 3000 });
  //: 第二次保存就是这一下编辑(雕塑藏起来了),不是把换上来的那份原样送回去;带的是新修订号。
  const second = vi.mocked(saveScene).mock.calls[1][0];
  expect(second.revision).toBe(4);
  expect(second.content.objects.find((one) => one.name === "雕塑")?.hidden).toBe(true);
});
