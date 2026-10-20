/** @vitest-environment jsdom */
/**
 * 设置 → 账户的**块顺序**、**页头**与**方位指代**。
 *
 * 维护者看完成品说:「密码不应该放在下面吧,容易引起误解」「header 怎么还是本地账号」
 * 「不如把 MosaelCloud 账号放到最上面吧」。误会的来由是顺序:此前是
 * 本地账号 → MosaelCloud 账号 → 登录密码,密码被云账号隔开,看着像云账号的密码;
 * 页头那句又只有「本地账号」,只描述了这一页的一半(这页现在有两个账号)。
 *
 * 现在的顺序:**MosaelCloud 账号**(最上)→ **本地账号**(头像、用户名、昵称、签名)
 * → **登录密码**(紧跟本地账号 —— 密码属于本地账号,归属一眼就清)。
 * 页头同时说两套账号,不再只说本地账号。
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
  it("MosaelCloud 账号在最上 → 本地账号 → 登录密码紧跟本地账号", async () => {
    h.status.mockResolvedValue({ bound: false, email: null, device_id: null, created_at: null });
    render(<AccountSection />);
    await screen.findByRole("button", { name: "登录 MosaelCloud" });

    const cloud = screen.getByText("MosaelCloud 账号", { selector: "strong" });
    const local = screen.getByText("本地账号", { selector: "strong" });
    const username = screen.getByText("用户名");
    const password = screen.getByText("登录密码", { selector: "strong" });

    //: 云账号置顶:第一块就是它。
    const firstBlock = document.querySelector('[data-slot="settings-group-content"] > [data-slot="settings-block"]');
    expect(firstBlock?.contains(cloud), "MosaelCloud 账号应是第一块").toBe(true);

    expect(before(cloud, local), "本地账号应在 MosaelCloud 账号之后").toBe(true);
    expect(before(local, username), "本地账号的资料应在本地账号标题之后").toBe(true);
    expect(before(username, password), "登录密码应在本地账号资料之后").toBe(true);
    //: 密码紧跟本地账号:云账号在本地账号之前,不再夹在本地账号和密码之间。
    expect(before(local, password), "登录密码应在本地账号之后").toBe(true);
    expect(before(cloud, password), "MosaelCloud 账号不应夹在本地账号和登录密码之间").toBe(true);
    //: 渲染出来的整页文字里也不许再有方位指代。
    expect(document.body.textContent ?? "").not.toMatch(/上面|下面|如上|上述/);
  });
});

describe("账户页的页头", () => {
  it("不只说本地账号:同时说清 MosaelCloud 账号,并点明两者独立", async () => {
    h.status.mockResolvedValue({ bound: false, email: null, device_id: null, created_at: null });
    render(<AccountSection />);
    await screen.findByRole("button", { name: "登录 MosaelCloud" });

    const description = document.querySelector('[data-slot="settings-group-description"]');
    const text = description?.textContent ?? "";
    expect(text, "页头仍要说是哪个账号").toContain("本地账号");
    expect(text, "页头要提到另一套账号").toContain("MosaelCloud 账号");
    expect(text, "页头要说清两套账号的关系").toMatch(/独立/);
  });
});

/** 这一页真正渲染到的文案键(含云账号块每一种状态)。 */
const ACCOUNT_KEYS = [
  "settingsAccount",
  "settingsAccountScope",
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
