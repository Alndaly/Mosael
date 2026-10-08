/** @vitest-environment jsdom */
/**
 * 邀请链接在客户端这一侧(ADR 0054):链接的两种样子、从一段文字里认出码、打开之后「待处理的那一张」。
 */
import { beforeEach, describe, expect, it } from "vitest";

import {
  captureInviteFromLocation,
  clearPendingInvite,
  codeFromInviteText,
  inviteLinkUrls,
  listenInviteDeepLinks,
  pendingInvite,
} from "./inviteLinks";

const web = { protocol: "https:", origin: "https://studio.example.com", pathname: "/" };
const desktopFile = { protocol: "file:", origin: "null", pathname: "/Applications/Mosael.app/index.html" };

beforeEach(() => sessionStorage.clear());

describe("链接的样子(D52)", () => {
  it("部署配了网页地址:网页版用它(去掉结尾的斜杠),桌面端是深链", () => {
    expect(inviteLinkUrls("Code-1234abcd", "https://team.example.com/", desktopFile, true)).toEqual({
      web: "https://team.example.com/#/join/Code-1234abcd",
      app: "mosael://open?join=Code-1234abcd",
    });
  });

  it("没配、而这个界面本身是网页版:用自己这个地址", () => {
    expect(inviteLinkUrls("Code-1234abcd", "", web, false).web).toBe("https://studio.example.com/#/join/Code-1234abcd");
  });

  it("桌面单机(没配网页地址):只有深链", () => {
    expect(inviteLinkUrls("Code-1234abcd", "", desktopFile, true).web).toBeNull();
    //: 桌面端哪怕开在 http 的开发页上,也不拿本机开发地址当网页版。
    expect(inviteLinkUrls("Code-1234abcd", "", { protocol: "http:", origin: "http://127.0.0.1:5173", pathname: "/" }, true).web)
      .toBeNull();
  });
});

describe("从一段文字里认出码", () => {
  it("裸码、网页地址、深链都认;认不出就原样", () => {
    expect(codeFromInviteText(" Code-1234abcd ")).toBe("Code-1234abcd");
    expect(codeFromInviteText("https://studio.example.com/#/join/Code-1234abcd")).toBe("Code-1234abcd");
    expect(codeFromInviteText("mosael://open?join=Code-1234abcd")).toBe("Code-1234abcd");
    expect(codeFromInviteText("给你:https://x.example/#/join/Code-1234abcd 记得点")).toBe("Code-1234abcd");
  });
});

describe("待处理的那一张", () => {
  it("启动时从地址里收起来,地址换回首页(码不留在地址栏里)", () => {
    window.history.replaceState(null, "", "/#/join/Code-1234abcd");
    captureInviteFromLocation();
    expect(pendingInvite()).toBe("Code-1234abcd");
    expect(window.location.hash).toBe("#/home");
    clearPendingInvite();
    expect(pendingInvite()).toBeNull();
  });

  it("别的地址不动;字符集不对的不收", () => {
    window.history.replaceState(null, "", "/#/workflows");
    captureInviteFromLocation();
    expect(pendingInvite()).toBeNull();
    expect(window.location.hash).toBe("#/workflows");
    window.history.replaceState(null, "", "/#/join/..%2F..%2Fx");
    captureInviteFromLocation();
    expect(pendingInvite()).toBeNull();
  });

  it("桌面端深链:登录之前也接得住", () => {
    const stop = listenInviteDeepLinks();
    window.dispatchEvent(new CustomEvent("mosael:deep-link", { detail: { view: "home", join: "Code-1234abcd" } }));
    expect(pendingInvite()).toBe("Code-1234abcd");
    stop();
  });
});
