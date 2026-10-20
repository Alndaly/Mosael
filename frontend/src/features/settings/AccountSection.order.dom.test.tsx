/** @vitest-environment jsdom */
/**
 * 设置 → 账户的**块顺序**与**方位指代**。
 *
 * 维护者原话:「MosaelCloud 账号的相关这部分 UI 应该放到账号页面的上面一点位置,否则很难看到」;
 * 又说那块文案「它和上面的本地账号是两套」里的「上面」不成立 —— 它本来就位于本地账号之下,
 * 挪上来之后更不能再说方位。
 *
 * 顺序:标题「账户」/说明「本地账号」→ 本地账号身份(头像、用户名、昵称、签名)→ **MosaelCloud 账号**
 * → **登录密码**。云账号不放页面最顶:本地账号仍是这台机器的身份。
 *
 * 这一页不再用「上面 / 下面 / 如上」指位置 —— 谁在上面是会随排版和窗口变化的,而名字不会。
 */
import React from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { messages } from "@/app/messages";

const h = vi.hoisted(() => ({ status: vi.fn() }));

vi.mock("@/app/auth", () => ({
  useAuth: () => ({
    user: { id: "user-1", username: "demo", display_name: "Demo", signature: "", avatar_key: null },
    updateProfile: vi.fn(),
    changePassword: vi.fn(),
    updateAvatar: vi.fn(),
    logout: vi.fn(),
  }),
}));
vi.mock("@/app/preferences", async () => {
  const { messages: table } = await import("@/app/messages");
  return {
    useI18n: () => (key: keyof (typeof table)["zh-CN"]) => table["zh-CN"][key],
    usePreferences: () => ({ locale: "zh-CN", preferences: {}, updatePreferences: vi.fn() }),
  };
});
vi.mock("@/api/domains/cloud", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/domains/cloud")>();
  return { ...actual, getCloudBinding: h.status };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { AccountSection } from "./AccountSection";

afterEach(cleanup);

/** `a` 在文档里排在 `b` 前面。 */
function before(a: Element, b: Element): boolean {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe("账户页的块顺序", () => {
  it("身份 → 云账号 → 改密码:云账号在本地账号之后、登录密码之前", async () => {
    h.status.mockResolvedValue({ bound: false, email: null, device_id: null, created_at: null });
    render(<AccountSection />);
    await screen.findByRole("button", { name: "登录 MosaelCloud" });

    const local = screen.getByText("本地账号", { selector: '[data-slot="settings-group-description"]' });
    const username = screen.getByText("用户名");
    const cloud = screen.getByText("MosaelCloud 账号", { selector: "strong" });
    const password = screen.getByText("登录密码", { selector: "strong" });

    expect(before(local, cloud), "MosaelCloud 账号应在本地账号之后").toBe(true);
    expect(before(username, cloud), "MosaelCloud 账号应在本地账号信息之后").toBe(true);
    expect(before(cloud, password), "MosaelCloud 账号应在登录密码之前").toBe(true);
    //: 渲染出来的整页文字里也不许再有方位指代。
    expect(document.body.textContent ?? "").not.toMatch(/上面|下面|如上|上述/);
  });
});

/** 这一页真正渲染到的文案键(含云账号块每一种状态)。 */
const ACCOUNT_KEYS = [
  "settingsAccount",
  "railLocalAccount",
  "railServerAccount",
  "railSignedInWith",
  "signOut",
  "avatarChange",
  "avatarUpdated",
  "avatarUpdateFailed",
  "profileSaving",
  "profileSaved",
  "profileSaveFailed",
  "settingsUsername",
  "settingsUsernameDesc",
  "usernameChange",
  "usernameChangeConfirm",
  "usernameChanged",
  "teamUsernameShort",
  "displayName",
  "displayNameDesc",
  "signature",
  "signatureDesc",
  "signaturePlaceholder",
  "settingsPassword",
  "settingsPasswordDesc",
  "currentPassword",
  "newPassword",
  "confirmPassword",
  "updatePassword",
  "passwordMismatch",
  "passwordTooShort",
  "passwordUpdated",
  "passwordUpdateFailed",
  "cloudBindingTitle",
  "cloudBindingIntro",
  "cloudBindingOauthNote",
  "cloudBindingBind",
  "cloudBindingChecking",
  "cloudBindingBoundTo",
  "cloudBindingBoundSince",
  "cloudBindingBoundDevice",
  "cloudBindingBoundDeviceHint",
  "cloudBindingUnbind",
  "cloudBindingUnbindHint",
  "cloudBindingCodeTitle",
  "cloudBindingCodeHint",
  "cloudBindingOpen",
  "cloudBindingCopyCode",
  "cloudBindingCopied",
  "cloudBindingApproved",
  "cloudBindingCancel",
  "cloudBindingStarting",
  "cloudBindingCompleting",
  "cloudBindingWaiting",
  "cloudBindingPending",
  "cloudBindingGranted",
  "cloudBindingRemoved",
  "cloudBindingUnreachable",
  "cloudBindingNotConfigured",
  "cloudBindingExpired",
  "cloudBindingAlreadyBound",
  "cloudBindingErrorCode",
  "cloudBindingRetry",
  "cloudBindingRestart",
] as const satisfies readonly (keyof (typeof messages)["zh-CN"])[];

describe("账户页的方位指代", () => {
  it("组件里不再用「上面 / 下面 / 如上」指位置(注释也算)", () => {
    for (const file of ["AccountSection.tsx", "CloudBindingSection.tsx"]) {
      const source = readFileSync(join(import.meta.dirname, file), "utf8");
      expect(source, file).not.toMatch(/上面|下面|如上|上述/);
    }
  });

  it("这一页的文案不含方位指代(中英两份)", () => {
    const zh = messages["zh-CN"] as Record<string, string>;
    const en = messages["en-US"] as Record<string, string>;
    const offenders: string[] = [];
    for (const key of ACCOUNT_KEYS) {
      if (/上面|下面|如上|上述/.test(zh[key])) offenders.push(`zh-CN/${key}: ${zh[key]}`);
      if (/\b(above|below)\b/i.test(en[key])) offenders.push(`en-US/${key}: ${en[key]}`);
    }
    expect(offenders).toEqual([]);
  });
});
