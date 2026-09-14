/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BoardItem, GenerationOption } from "@/api/client";
import { NodeComposer } from "./NodeComposer";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({ NodeToolbar: ({ children }: { children: React.ReactNode }) => children, Position: { Bottom: "bottom" } }));
vi.mock("@tanstack/react-query", () => ({ useQuery: () => ({ data: [] }) }));
vi.mock("./PromptEditor", () => ({ PromptEditor: () => <div />, restorePromptDocument: vi.fn(), collect: () => [] }));

it("edits parameters in the settings popup, persists them after closing, and submits those values", async () => {
  HTMLElement.prototype.scrollIntoView = vi.fn();
  const onSubmit = vi.fn();
  const onFormChange = vi.fn();
  render(<NodeComposer
    item={{ id: "video", kind: "video", text: "A sunrise" } as BoardItem}
    models={[{ id: "model", provider_profile_id: "profile", profile_name: "Test", label: "Video", adapter_available: true, provider: "test", model: "a-long-video-model-name", kind: "video", capabilities: {
      parameter_keys: ["aspect_ratio", "generate_audio"], aspect_ratios: ["16:9", "9:16"], default_aspect_ratio: "16:9",
    } } as GenerationOption]}
    busy={false} workspaceId="test" onPickAsset={vi.fn()} onFormChange={onFormChange} onSubmit={onSubmit}
  />);
  expect(screen.queryByRole("combobox", { name: "wfGenAspectRatio" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "boardGenerationSettings" }));
  fireEvent.click(await screen.findByRole("combobox", { name: "wfGenAspectRatio" }));
  fireEvent.click(await screen.findByRole("option", { name: "9:16" }));
  await waitFor(() => expect(onFormChange).toHaveBeenLastCalledWith(expect.objectContaining({ parameters: expect.objectContaining({ aspect_ratio: "9:16" }) })));
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ parameters: expect.objectContaining({ aspect_ratio: "9:16" }) }));
});

it("把模型旁那枚图标画在触发器里面 —— 装饰和控件必须是同一个盒子", () => {
  // 图标曾经和触发器并排放在一个只负责 hover 底色的 span 里。于是这一格有了两个盒子:
  // 悬停高亮的是外层(左边紧贴图标、没有内边距),聚焦时的环却只圈住触发器(把图标排除在外)。
  // 同一个控件高亮出两个大小不同的方框,左右内边距还不对称。
  //
  // 断言「图标在 combobox 里面」而不是「外面没有 span」:后者换个写法就绕过去了,而前者
  // 正是那两个高亮框合成一个的充分条件 —— 内边距、hover、焦点环都由触发器这一个盒子出。
  render(<NodeComposer
    item={{ id: "video", kind: "video", text: "A sunrise" } as BoardItem}
    models={[{ id: "model", provider_profile_id: "profile", profile_name: "Test", label: "Video", adapter_available: true, provider: "test", model: "a-long-video-model-name", kind: "video", capabilities: {} } as GenerationOption]}
    busy={false} workspaceId="test" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={vi.fn()}
  />);
  const trigger = screen.getAllByRole("combobox").find((one) => one.textContent?.includes("a-long-video-model-name"));
  expect(trigger).toBeDefined();
  expect(trigger!.querySelector("svg.lucide-sparkles")).not.toBeNull();
  // 左右内边距由触发器自己出,两侧同一个值 —— 这正是「左侧边距明显不对」的那一处。
  expect(trigger!.className).toContain("px-2");
});
