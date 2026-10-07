/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 「存成技能」(ADR 0040 §7):会话设置里一个按钮。用这次对话的模型起草一份 SKILL.md,填进同一个编辑表单,
 * **人改完才保存** —— 起草本身什么都不建。保存时记成「从对话存成的」。
 */

const api = vi.hoisted(() => ({
  draftSkillFromSession: vi.fn(),
  createSkill: vi.fn(),
  getSkill: vi.fn(),
  putSkillFile: vi.fn(),
  deleteSkillFile: vi.fn(),
  updateSkill: vi.fn(),
}));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return { useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key] ?? key };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/features/agent/AutoApprovalTrace", () => ({ AutoApprovalTrace: () => null }));
vi.mock("@/features/agent/ThinkingLevelPicker", () => ({ ThinkingLevelPicker: () => null }));
vi.mock("@/features/agent/AnalysisModePicker", () => ({ AnalysisModePicker: () => null }));
vi.mock("@/features/agent/PermissionModePicker", () => ({
  PermissionModePicker: () => null,
  permissionModeOf: () => "manual",
  PERMISSION_MODE_ICON: { manual: () => null, auto: () => null, bypass: () => null },
  ACCENT: { manual: "", auto: "", bypass: "" },
}));

import { SessionSettingsMenu } from "@/features/agent/SessionSettingsMenu";

const SESSION = { id: "s-1", workspace_id: "ws-1" } as never;
const DRAFT = { name: "long-to-short", title: "长视频切竖屏", description: "把长视频切成竖屏短片", body: "1. 转写\n2. 挑段落\n" };

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.draftSkillFromSession.mockResolvedValue(DRAFT);
  api.createSkill.mockImplementation(async (_ws: string, body: { name: string }) => ({
    ref: body.name, name: body.name, title: "长视频切竖屏", description: "x", source: "workspace", source_label: "从对话存成的",
    origin: "conversation", enabled: true, editable: true, problem: "",
    license: "", compatibility: "", allowed_tools: "", unknown_fields: [], metadata: {}, body: "", files: [],
  }));
  api.getSkill.mockImplementation(async () => (api.createSkill.mock.results.at(-1)?.value));
});
afterEach(cleanup);

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SessionSettingsMenu workspaceId="ws-1" place={{ kind: "studio", id: "" }} session={SESSION} />
    </QueryClientProvider>,
  );
}

describe("存成技能", () => {
  it("起草填进表单,不自动保存;改完保存记成从对话来的", async () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "会话设置" }));
    fireEvent.click(await screen.findByRole("button", { name: /存成技能/ }));
    await waitFor(() => expect(api.draftSkillFromSession).toHaveBeenCalledWith("s-1"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.querySelector("[data-slot='skill-draft-hint']")).toBeTruthy();
    const [title, name, description, body] = within(dialog).getAllByRole("textbox") as HTMLInputElement[];
    expect([title.value, name.value, description.value, body.value]).toEqual(["长视频切竖屏", "long-to-short", "把长视频切成竖屏短片", "1. 转写\n2. 挑段落\n"]);
    expect(api.createSkill).not.toHaveBeenCalled();

    fireEvent.change(body, { target: { value: "1. 转写\n2. 挑能独立成段的几分钟\n3. 裁成 9:16" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }));
    await waitFor(() => expect(api.createSkill).toHaveBeenCalled());
    expect(api.createSkill.mock.calls[0]).toEqual(["ws-1", {
      name: "long-to-short", title: "长视频切竖屏", description: "把长视频切成竖屏短片", license: "", compatibility: "",
      body: "1. 转写\n2. 挑能独立成段的几分钟\n3. 裁成 9:16", from_conversation: true,
    }]);
  });

  it("没有会话时没有这个按钮(还没聊过,没什么可存)", async () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <SessionSettingsMenu workspaceId="ws-1" place={{ kind: "studio", id: "" }} session={null} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "会话设置" }));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(screen.queryByRole("button", { name: /存成技能/ })).toBeNull();
  });
});
