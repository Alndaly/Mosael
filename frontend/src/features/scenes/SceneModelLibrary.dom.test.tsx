/** @vitest-environment jsdom */
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { messages, type MessageKey } from "@/app/messages";
import { SceneModelLibrary } from "./SceneModelLibrary";

/**
 * 导入的 3D 模型此前在界面上删不掉:`deleteSceneModel` 没有调用者,模型只出现在「添加」菜单里。
 * 这里钉住:能删;后端拒了(还有场景摆着)照实说原因;当前场景里摆着的那份不给删。
 */

const deleteSceneModel = vi.hoisted(() => vi.fn());
vi.mock("@/api/domains/scenes", () => ({ deleteSceneModel }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: MessageKey) => messages["zh-CN"][key] }));
afterEach(() => {
  cleanup();
  deleteSceneModel.mockReset();
});

const models = [
  { id: "chair", name: "椅子", format: "glb", size: 320_000 },
  { id: "desk", name: "书桌", format: "gltf", size: 1_200_000 },
];

function mount(inDraft: string[] = []) {
  const qc = new QueryClient();
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  render(
    <QueryClientProvider client={qc}>
      <SceneModelLibrary workspaceId="w" models={models} inDraft={new Set(inDraft)} open onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  );
  return { invalidate };
}

function deleteButton(name: string) {
  return screen.getByRole("button", { name: messages["zh-CN"].sceneModelDelete.replace("{name}", name) });
}

it("确认后删掉那一份,并刷新模型列表", async () => {
  deleteSceneModel.mockResolvedValue(undefined);
  const { invalidate } = mount();
  fireEvent.click(deleteButton("椅子"));
  fireEvent.click(screen.getByRole("button", { name: messages["zh-CN"].delete }));
  await waitFor(() => expect(deleteSceneModel).toHaveBeenCalledWith("w", "chair"));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["scene-models", "w"] }));
});

it("后端拒了(还有场景摆着):照实说原因", async () => {
  deleteSceneModel.mockRejectedValue(new Error("还有场景在用这份模型:客厅。先把它们里面的这件物体删掉。"));
  mount();
  fireEvent.click(deleteButton("书桌"));
  fireEvent.click(screen.getByRole("button", { name: messages["zh-CN"].delete }));
  expect(await screen.findByText(/还有场景在用这份模型:客厅/)).toBeTruthy();
});

it("当前场景里摆着的那份不给删", () => {
  mount(["chair"]);
  expect((deleteButton("椅子") as HTMLButtonElement).disabled).toBe(true);
  expect((deleteButton("书桌") as HTMLButtonElement).disabled).toBe(false);
  expect(screen.getByText(messages["zh-CN"].sceneModelPlacedHere)).toBeTruthy();
});
