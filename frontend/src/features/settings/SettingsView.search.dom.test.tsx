/** @vitest-environment jsdom */
/**
 * 设置页左边的搜索按「我要改什么」找(体检 UM-15):分区里的行、只在管理页的设置都搜得到。
 * 管理页的那些:部署管理员点了直达那个 tab;别人看到一句由谁在哪儿改,而不是「没有找到」。
 */
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { messages, type MessageKey } from "@/app/messages";

const h = vi.hoisted(() => ({ admin: false, gotoAdmin: vi.fn() }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: MessageKey) => messages["zh-CN"][key] }));
vi.mock("@/app/auth", () => ({ useIsDeploymentAdmin: () => h.admin }));
vi.mock("@/lib/deepLink", () => ({ gotoAdmin: h.gotoAdmin, useOpenRequest: () => undefined }));
vi.mock("@/features/settings/AccountSection", () => ({ AccountSection: () => null }));
vi.mock("@/features/settings/AgentMemorySection", () => ({ AgentMemorySection: () => null }));
vi.mock("@/features/settings/AgentSkillsSection", () => ({ AgentSkillsSection: () => null }));
vi.mock("@/features/settings/AgentVoiceSection", () => ({ AgentVoiceSection: () => null }));
vi.mock("@/features/settings/AppearanceSection", () => ({ AppearanceSection: () => null, BackgroundSection: () => null, CustomCssSection: () => null }));
vi.mock("@/features/settings/AutopilotRulesSection", () => ({ AutopilotRulesSection: () => null }));
vi.mock("@/features/settings/BackendSection", () => ({ BackendSection: () => null }));
vi.mock("@/features/settings/BuiltinTtsSection", () => ({ BuiltinTtsSection: () => null }));
vi.mock("@/features/settings/CapabilityProvidersSection", () => ({ CapabilityProvidersSection: () => null }));
vi.mock("@/features/settings/FeishuSection", () => ({ FeishuSection: () => null }));
vi.mock("@/features/settings/ProviderDefaultsSection", () => ({ ProviderDefaultsSection: () => null }));
vi.mock("@/features/settings/ProviderProfilesSection", () => ({ ProviderProfilesSection: () => null }));
vi.mock("@/features/settings/TeamSection", () => ({ TeamSection: () => null }));
vi.mock("@/features/settings/VoiceLibrarySection", () => ({ VoiceLibrarySection: () => null }));

import { SettingsView } from "./SettingsView";

function search(text: string) {
  const view = render(<SettingsView workspace={{ id: "w1", name: "W" } as never} />);
  fireEvent.change(screen.getByRole("textbox", { name: messages["zh-CN"].studioSettingsSearch }), { target: { value: text } });
  return view;
}

beforeEach(() => {
  h.admin = false;
  h.gotoAdmin.mockReset();
  localStorage.clear();
});

it("搜「语言」落到「外观」,并写出是里面的哪一行", () => {
  search("语言");
  const nav = screen.getByRole("navigation");
  expect(within(nav).getByRole("button", { name: /外观/ }).textContent).toContain("语言");
  expect(screen.queryByText(messages["zh-CN"].studioSettingsEmpty)).toBeNull();
});

it("搜「代理」:不是部署管理员的人看到它在管理页、由谁改", () => {
  const { container } = search("代理");
  const hits = container.querySelector("[data-settings-admin-hits]") as HTMLElement;
  expect(hits.textContent).toContain(messages["zh-CN"].proxyTitle);
  expect(hits.textContent).toContain(messages["zh-CN"].settingsSearchAdminOnly);
  expect(within(hits).queryByRole("button")).toBeNull();
});

it("部署管理员搜「镜像」,点了直达管理页的「引擎」", () => {
  h.admin = true;
  const { container } = search("镜像");
  const hits = container.querySelector("[data-settings-admin-hits]") as HTMLElement;
  fireEvent.click(within(hits).getByRole("button", { name: messages["zh-CN"].installSourceTitle }));
  expect(h.gotoAdmin).toHaveBeenCalledWith("engines");
});

it("真的哪儿都没有才说「没有找到」", () => {
  search("zzzz-nothing");
  expect(screen.getByText(messages["zh-CN"].studioSettingsEmpty)).toBeInTheDocument();
});
